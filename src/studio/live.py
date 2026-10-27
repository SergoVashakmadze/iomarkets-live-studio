"""Turn-taking for a live interview, independent of the transport.

The ASR decides when the guest starts and stops; this decides what the anchor does about it:

- The guest finishes a turn: the anchor writes a reply to everything the guest has said since
  its last line.
- The guest starts while the anchor is speaking: barge-in. Playback stops at once, and the
  anchor's next line knows it was interrupted.
- The guest starts again while a reply is still being written: that reply is dropped, so the
  anchor never answers half a thought. The guest's words stay pending and the next reply
  covers all of them.

Everything sent to the page is a JSON message with a `type`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from studio.agents.anchor import Anchor
from studio.asr import Event, GuestPartial, GuestPaused, GuestStarted, GuestTurn

Send = Callable[[dict[str, Any]], Awaitable[None]]


class LiveSession:
    def __init__(self, anchor: Anchor, send: Send):
        self.anchor = anchor
        self._send = send
        self._lock = asyncio.Lock()
        self.anchor_speaking = False
        self.pending: list[str] = []
        self.interrupted = False
        self._reply: asyncio.Task | None = None

    async def send(self, msg: dict[str, Any]) -> None:
        async with self._lock:
            await self._send(msg)

    def set_anchor_speaking(self, speaking: bool) -> None:
        """The page reports when playback of an anchor line starts and ends."""
        self.anchor_speaking = speaking

    async def open(self) -> None:
        self._start_reply(opening=True)

    async def on_event(self, event: Event) -> None:
        match event:
            case GuestStarted(turn_id, barge_in):
                if barge_in:
                    self.interrupted = True
                    self.anchor_speaking = False
                    await self.send({"type": "stop_anchor"})
                self._cancel_reply()
                await self.send({"type": "guest_started", "turn": turn_id, "barge_in": barge_in})
            case GuestPartial(turn_id, text):
                await self.send({"type": "guest_partial", "turn": turn_id, "text": text})
            case GuestPaused(turn_id):
                await self.send({"type": "guest_paused", "turn": turn_id})
            case GuestTurn(turn_id, text, _):
                await self.send({"type": "guest_turn", "turn": turn_id, "text": text})
                if text:
                    self.pending.append(text)
                    self._start_reply()

    async def close(self) -> None:
        self._cancel_reply()

    def _cancel_reply(self) -> None:
        if self._reply and not self._reply.done():
            self._reply.cancel()

    def _start_reply(self, opening: bool = False) -> None:
        self._cancel_reply()
        self._reply = asyncio.create_task(self._write_reply(opening))

    async def _write_reply(self, opening: bool) -> None:
        taken = len(self.pending)
        try:
            await self.send({"type": "anchor_thinking"})
            if opening:
                line = await self.anchor.opening()
            else:
                line = await self.anchor.reply(
                    " ".join(self.pending[:taken]), interrupted=self.interrupted
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.send({"type": "error", "message": f"anchor: {e}"})
            return
        del self.pending[:taken]
        self.interrupted = False
        await self.send({"type": "anchor_line", "text": line})
