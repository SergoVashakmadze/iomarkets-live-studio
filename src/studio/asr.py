"""Live guest speech over Muse Voice Transcribe (`wss://api.meta.ai/v1/asr/realtime`).

Protocol (Meta docs, read 2026-10-27):

- The key goes in the first JSON frame (`authorization.accessToken`, with `Bearer `), within
  10 s; the HTTP header is ignored. The server answers `{"sessionId": ...}`, the only frame
  without a `type`. Keywords and language bias are fixed for the session.
- Audio is binary frames of signed 16-bit little-endian mono PCM at 24 kHz, sent at about real
  time: no more than 5 s ahead, and never starved, or the server closes with 1008. Silence is
  sent while the guest is quiet.
- In ENDPOINTING mode each turn is `speechStart`, partial `transcript`s (no `turnId`; they belong
  to the latest `speechStart`), `speechEnd`, then `speechComplete` with the final text, which
  can differ from the last partial. Turns can overlap, so state is keyed by `turnId`.
- `{"type": "endStream"}` ends input; results keep coming until the server closes with 1000.

`speechStart` is the barge-in signal: if the anchor is speaking when it arrives, the caller
stops playback.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from studio import ledger

ASR_URL = "wss://api.meta.ai/v1/asr/realtime"
ASR_MODEL = "muse-voice-transcribe-1.0"
SAMPLE_RATE = 24_000
BYTES_PER_MS = SAMPLE_RATE * 2 // 1000  # s16le mono
FRAME_MS = 80
FRAME_BYTES = FRAME_MS * BYTES_PER_MS  # 3840, the docs' example frame


class AsrError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, error_type: str | None = None):
        super().__init__(message)
        self.code = code
        self.error_type = error_type


# Events the studio acts on.


@dataclass(frozen=True)
class GuestStarted:
    turn_id: int
    barge_in: bool  # the anchor was speaking: stop its playback


@dataclass(frozen=True)
class GuestPartial:
    turn_id: int
    text: str


@dataclass(frozen=True)
class GuestPaused:
    """`speechEnd`: the guest stopped; final text follows in GuestTurn."""

    turn_id: int


@dataclass(frozen=True)
class GuestTurn:
    turn_id: int
    text: str
    audio_ms: int


Event = GuestStarted | GuestPartial | GuestPaused | GuestTurn


@dataclass
class TurnTracker:
    """Turns server messages into studio events. Pure, so it is tested without a socket.

    `anchor_speaking` is asked at each `speechStart`; the live loop wires it to playback.
    """

    anchor_speaking: Callable[[], bool] = lambda: False
    partials: dict[int, str] = field(default_factory=dict)
    _latest: int | None = None

    def feed(self, msg: dict[str, Any]) -> Event | None:
        kind = msg.get("type")
        if kind == "speechStart":
            turn = int(msg["turnId"])
            self._latest = turn
            self.partials[turn] = ""
            return GuestStarted(turn, barge_in=self.anchor_speaking())
        if kind == "transcript":
            # After the last turn completes, the server still sends one empty `final`
            # transcript for the end of the stream (measured 2026-10-27): no open turn, ignored.
            if self._latest is None:
                return None
            text = msg.get("transcript") or ""
            if not text or text == self.partials.get(self._latest):
                return None
            self.partials[self._latest] = text
            return GuestPartial(self._latest, text)
        if kind == "speechEnd":
            return GuestPaused(int(msg["turnId"]))
        if kind == "speechComplete":
            turn = int(msg["turnId"])
            last = self.partials.pop(turn, "")
            if turn == self._latest:
                self._latest = None
            text = (msg.get("transcript") or last).strip()
            return GuestTurn(turn, text, int(msg.get("audioProcessedMs", 0)))
        if kind == "error":
            raise AsrError(msg.get("message", "ASR error"), error_type=msg.get("errorType"))
        return None  # audioProgress, speaker and anything new


@dataclass
class Pacer:
    """Decides what to send each tick so audio stays close to real time.

    Live sources arrive at real time but in uneven bursts; files arrive all at once. Either
    way: send buffered audio while we are less than `lead_ms` ahead of the wall clock, and send
    silence once we fall `starve_ms` behind with nothing buffered.
    """

    lead_ms: int = 400
    starve_ms: int = 200
    clock: Callable[[], float] = time.monotonic
    buffer: bytearray = field(default_factory=bytearray)
    sent_ms: float = 0.0
    _t0: float | None = None

    def push(self, pcm: bytes) -> None:
        self.buffer += pcm

    def frames(self) -> list[bytes]:
        now = self.clock()
        if self._t0 is None:
            self._t0 = now
        wall_ms = (now - self._t0) * 1000
        out = []
        while len(self.buffer) >= FRAME_BYTES and self.sent_ms < wall_ms + self.lead_ms:
            out.append(bytes(self.buffer[:FRAME_BYTES]))
            del self.buffer[:FRAME_BYTES]
            self.sent_ms += FRAME_MS
        if not out and self.sent_ms < wall_ms - self.starve_ms:
            out.append(bytes(self.buffer) + bytes(FRAME_BYTES - len(self.buffer)))
            self.buffer.clear()
            self.sent_ms += FRAME_MS
        return out


def handshake(api_key: str, keywords: list[str] = (), language: list[str] = ()) -> dict:
    msg: dict[str, Any] = {
        "authorization": {"accessToken": f"Bearer {api_key}"},
        "audioEncoding": "PCM_24KHZ",
        "model": ASR_MODEL,
        "mode": "ENDPOINTING",
        "partialMode": "CUMULATIVE",
        "emitAudioProgress": False,
    }
    if keywords:
        msg["keywords"] = list(keywords)
    if language:
        msg["languageBias"] = list(language)
    return msg


class GuestListener:
    """One realtime ASR session. At most 60 minutes, which covers an interview.

    Connecting and the handshake took 1.9 s on 2026-10-27, so open the session before the guest
    is due to speak. Measured on the same run: `speechStart` 0.2-0.4 s after the guest starts,
    and the final text 0.3-0.7 s after they stop.

    Use as `async with GuestListener(...) as asr:`, feed PCM with `push()`, iterate `events()`,
    and call `finish()` when the guest is done; iteration ends once the server has sent
    everything.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        keywords: list[str] = (),
        language: list[str] = ("English",),
        anchor_speaking: Callable[[], bool] = lambda: False,
        url: str = ASR_URL,
        connect: Callable[..., Any] = websockets.connect,
    ):
        key = api_key or os.environ.get("META_API_KEY")
        if not key:
            raise RuntimeError("META_API_KEY is not set (see .env.example)")
        self._hello = handshake(key, keywords, language)
        self._url = url
        self._connect = connect
        self.tracker = TurnTracker(anchor_speaking)
        self.pacer = Pacer()
        self.session_id: str | None = None
        self._ws: ClientConnection | None = None
        self._sender: asyncio.Task | None = None
        self._finishing = False

    async def __aenter__(self) -> GuestListener:
        self._ws = await self._connect(self._url, max_size=2**20)
        await self._ws.send(json.dumps(self._hello))
        reply = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=10))
        if "sessionId" not in reply or reply.get("type") == "error":
            await self._ws.close()
            raise AsrError(reply.get("message", f"handshake refused: {reply}"))
        self.session_id = reply["sessionId"]
        self._sender = asyncio.create_task(self._send_loop())
        return self

    async def __aexit__(self, *exc: object) -> None:
        ledger.charge("asr", ledger.asr_cost(self.pacer.sent_ms / 1000))
        if self._sender:
            self._sender.cancel()
        if self._ws:
            await self._ws.close()

    def push(self, pcm: bytes) -> None:
        self.pacer.push(pcm)

    def finish(self) -> None:
        """No more audio: flush what is buffered, then send endStream."""
        self._finishing = True

    async def _send_loop(self) -> None:
        assert self._ws is not None
        while True:
            for frame in self.pacer.frames():
                await self._ws.send(frame)
            if self._finishing and len(self.pacer.buffer) < FRAME_BYTES:
                if self.pacer.buffer:
                    pad = FRAME_BYTES - len(self.pacer.buffer)
                    await self._ws.send(bytes(self.pacer.buffer) + bytes(pad))
                await self._ws.send(json.dumps({"type": "endStream"}))
                return
            await asyncio.sleep(FRAME_MS / 4000)

    async def events(self) -> AsyncIterator[Event]:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                event = self.tracker.feed(json.loads(raw))
                if event is not None:
                    yield event
        except websockets.ConnectionClosedError as e:
            code = e.rcvd.code if e.rcvd else None
            reason = e.rcvd.reason if e.rcvd else str(e)
            raise AsrError(f"ASR closed {code}: {reason}", code=code) from e
        if self._sender and self._sender.done() and self._sender.exception():
            raise self._sender.exception()
