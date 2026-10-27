"""Turn-taking for a live interview, independent of the transport.

The ASR decides when the guest starts and stops; this decides what the anchor does about it:

- The guest finishes a turn: the anchor writes a reply to everything the guest has said since
  its last line.
- The guest starts while the anchor is speaking: barge-in. Playback stops at once, and the
  anchor's next line knows it was interrupted.
- The guest starts again while a reply is still being written: that reply is dropped, so the
  anchor never answers half a thought. The guest's words stay pending and the next reply
  covers all of them.
- Each anchor line is sent as text at once, then as audio sentence by sentence (`voice`), so
  playback starts on the first sentence. The page uses the browser's own voice if audio is
  late or fails.
- Every guest turn with a figure in it, and every chart the guest holds up, goes to the fact
  desk in the background; the anchor never waits for it. A contradicted figure becomes a note
  the anchor sees with the guest's next words.

Everything sent to the page is a JSON message with a `type`.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol

from studio.agents.anchor import Anchor
from studio.agents.factcheck import ChartReading, Check
from studio.asr import Event, GuestPartial, GuestPaused, GuestStarted, GuestTurn
from studio.tts import sentences

Send = Callable[[dict[str, Any]], Awaitable[None]]
Voice = Callable[[str], Awaitable[bytes]]


class Desk(Protocol):
    async def check(self, said: str) -> list[Check]: ...
    async def read_chart(self, jpeg: bytes) -> ChartReading: ...


class LiveSession:
    def __init__(
        self, anchor: Anchor, send: Send, desk: Desk | None = None, voice: Voice | None = None
    ):
        self.anchor = anchor
        self.desk = desk
        self.voice = voice
        self._line_id = 0
        self.last_line: str | None = None
        # The anchor line each guest turn was answering, for the segment's question cards.
        self.question_for_turn: dict[int, str] = {}
        self.notes: list[str] = []
        self._background: set[asyncio.Task] = set()
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
                if self.last_line and turn_id not in self.question_for_turn:
                    self.question_for_turn[turn_id] = self.last_line
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
                    if self.desk:
                        self._spawn(self._check(text, turn=turn_id))

    async def on_frame(self, jpeg: bytes) -> None:
        """A camera frame the producer flagged: read any chart in it, then check its figures."""
        if self.desk:
            self._spawn(self._read_chart(jpeg))

    async def close(self) -> None:
        self._cancel_reply()
        for task in list(self._background):
            task.cancel()

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _read_chart(self, jpeg: bytes) -> None:
        assert self.desk is not None
        await self.send({"type": "chart_reading_started"})
        try:
            chart = await self.desk.read_chart(jpeg)
        except Exception as e:
            await self.send({"type": "error", "message": f"chart: {e}"})
            return
        await self.send({"type": "chart", **chart.model_dump()})
        if chart.legible and chart.figures:
            await self._check(chart.as_claims(), turn=None)

    async def _check(self, said: str, *, turn: int | None) -> None:
        assert self.desk is not None
        try:
            checks = await self.desk.check(said)
        except Exception as e:
            await self.send({"type": "error", "message": f"fact-check: {e}"})
            return
        if not checks:
            return
        for c in checks:
            if c.verdict == "contradicted":
                self.notes.append(
                    f"the guest's {c.claim!r} looks wrong: sources give {c.correct_value}. "
                    f"{c.explanation}"
                )
        await self.send(
            {"type": "fact_check", "turn": turn, "checks": [c.model_dump() for c in checks]}
        )

    def _cancel_reply(self) -> None:
        if self._reply and not self._reply.done():
            self._reply.cancel()

    def _start_reply(self, opening: bool = False) -> None:
        self._cancel_reply()
        self._reply = asyncio.create_task(self._write_reply(opening))

    async def _write_reply(self, opening: bool) -> None:
        taken, noted = len(self.pending), len(self.notes)
        try:
            await self.send({"type": "anchor_thinking"})
            if opening:
                line = await self.anchor.opening()
            else:
                line = await self.anchor.reply(
                    " ".join(self.pending[:taken]),
                    interrupted=self.interrupted,
                    notes=self.notes[:noted],
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.send({"type": "error", "message": f"anchor: {e}"})
            return
        del self.pending[:taken]
        if not opening:
            del self.notes[:noted]
        self.interrupted = False
        self._line_id += 1
        self.last_line = line
        await self.send({"type": "anchor_line", "id": self._line_id, "text": line})
        if self.voice:
            self._spawn(self._speak(self._line_id, line))

    async def _speak(self, line_id: int, line: str) -> None:
        """Audio for one line, in order, one message per sentence."""
        assert self.voice is not None
        parts = sentences(line) or [line]
        jobs = [asyncio.create_task(self.voice(p)) for p in parts]
        try:
            for i, job in enumerate(jobs):
                mp3 = await job
                await self.send(
                    {
                        "type": "anchor_audio",
                        "id": line_id,
                        "part": i,
                        "last": i == len(jobs) - 1,
                        "mp3": base64.b64encode(mp3).decode(),
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.send({"type": "anchor_audio_failed", "id": line_id})
        finally:
            for job in jobs:
                job.cancel()
