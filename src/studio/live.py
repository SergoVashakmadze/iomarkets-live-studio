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
  late or fails. With `lipsync` set, each sentence is lip-synced (MuseTalk) before it is sent,
  and its clip travels with its audio; a sentence that fails to render goes out as audio only.
  A barge-in or a new line cancels the line still being rendered.
- With a `greeting` (a fixed line, voiced and lip-synced ahead of time), the anchor speaks the
  moment the interview starts; her opening question is written and rendered meanwhile and held
  until the greeting ends, so the guest never waits in silence or speaks first.
- In a cold start (`researcher` set), Live Scout researches what the guest has said after
  each turn, one search at a time; its findings reach the anchor with the guest's next words
  and the Devil's Advocate checks against them.
- The Devil's Advocate passes the anchor contradictions and, for claims that matter but cannot
  be verified, a challenge to put: at most three notes wait at once.
- Every guest turn with a figure in it, and every chart the guest holds up, goes to the fact
  desk in the background; the anchor never waits for it. A contradicted figure becomes a note
  the anchor sees with the guest's next words.

Everything sent to the page is a JSON message with a `type`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import tempfile
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

from studio.agents.anchor import Anchor
from studio.agents.factcheck import HAS_FIGURE, ChartReading, Check
from studio.agents.live_scout import LiveResearch
from studio.asr import Event, GuestPartial, GuestPaused, GuestStarted, GuestTurn
from studio.tts import sentences

Send = Callable[[dict[str, Any]], Awaitable[None]]
Voice = Callable[[str], Awaitable[bytes]]
# (mp3, line id, sentence) -> the name of the lip-synced clip in the room's media, or None
Lipsync = Callable[[bytes, int, int], Awaitable[str | None]]
Researcher = Callable[[str, str], Awaitable[LiveResearch]]
MAX_NOTES = 3
TRANSCRIPT_LINES = 16  # what Live Scout reads: the latest exchanges


class Desk(Protocol):
    async def check(self, said: str) -> list[Check]: ...
    async def read_chart(self, jpeg: bytes) -> ChartReading: ...


def _short_start(parts: list[str], words: int = 9) -> list[str]:
    """Split a long first sentence at its first comma, so its lip-sync renders quickly.

    The anchor is silent until the first clip is ready, and MuseTalk takes about 1.2x the
    clip's length (measured 2026-10-30), so the first clip is what the guest waits for.
    """
    first = parts[0]
    if len(first.split()) <= words:
        return parts
    head, sep, tail = first.partition(", ")
    if not sep or len(head.split()) < 3 or not tail:
        return parts
    return [head + ",", tail, *parts[1:]]


RENDER_RATIO = 1.3  # lip-sync seconds per second of speech (measured 2026-11-01 on L40S and H100)
MAX_BUFFER_S = 8.0  # the longest the first clip is held back


async def _mp3_seconds(mp3: bytes) -> float | None:
    """The length of an MP3 in seconds, or None if ffprobe cannot tell.

    From a file: ffprobe reports N/A for an MP3 on a pipe (checked 2026-11-01)."""
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3)
            path = f.name
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 10)
        except BaseException:
            proc.kill()
            raise
        return float(out.decode().strip())
    except Exception:
        return None
    finally:
        if path:
            with contextlib.suppress(OSError):
                os.unlink(path)


def buffer_seconds(durations: list[float], ratio: float = RENDER_RATIO) -> float:
    """How long after its first clip is ready a line must wait to play without a break.

    Clip i is ready ratio * (the speech of parts 1..i) after the first, and plays after the
    speech of parts 0..i-1; the wait is the worst shortfall, never negative or beyond the cap."""
    worst = 0.0
    for i in range(1, len(durations)):
        worst = max(worst, ratio * sum(durations[1 : i + 1]) - sum(durations[:i]))
    return min(worst, MAX_BUFFER_S)


@dataclass
class Greeting:
    """The anchor's first words, made before the interview: text, voice, clip, length."""

    text: str
    mp3: bytes
    video: str | None  # the lip-synced clip's name in the room's media, if there is one
    seconds: float


class LiveSession:
    def __init__(
        self,
        anchor: Anchor,
        send: Send,
        desk: Desk | None = None,
        voice: Voice | None = None,
        researcher: Researcher | None = None,
        lipsync: Lipsync | None = None,
        greeting: Greeting | None = None,
    ):
        self.anchor = anchor
        self.desk = desk
        self.voice = voice
        self.researcher = researcher
        self.lipsync = lipsync
        self.greeting = greeting
        self.last_heard = asyncio.get_event_loop().time()  # the guest's last sound: idle end
        self._hold_until = 0.0  # the opening waits for the greeting to finish
        self._speaking: asyncio.Task | None = None
        self.transcript: list[str] = []
        self.research_text = ""
        self._researching = False
        self._research_again = False
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
        if g := self.greeting:
            self._line_id += 1
            self.transcript.append(f"Anchor: {g.text}")
            self.anchor.said(g.text)
            await self.send({"type": "anchor_line", "id": self._line_id, "text": g.text})
            msg = {
                "type": "anchor_audio",
                "id": self._line_id,
                "part": 0,
                "last": True,
                "mp3": base64.b64encode(g.mp3).decode(),
            }
            if self.lipsync:
                msg["video"] = g.video
            await self.send(msg)
            # Allow the page a moment to load the clip before it starts.
            self._hold_until = asyncio.get_running_loop().time() + g.seconds + 0.4
        self._start_reply(opening=True)

    async def on_event(self, event: Event) -> None:
        if isinstance(event, (GuestStarted, GuestPartial, GuestTurn)):
            self.last_heard = asyncio.get_running_loop().time()
        match event:
            case GuestStarted(turn_id, barge_in):
                if self.last_line and turn_id not in self.question_for_turn:
                    self.question_for_turn[turn_id] = self.last_line
                if barge_in:
                    self.interrupted = True
                    self.anchor_speaking = False
                    self._stop_speaking()
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
                    self.transcript.append(f"Guest: {text}")
                    self.pending.append(text)
                    self._start_reply()
                    if self.desk:
                        self._spawn(self._check(text, turn=turn_id))
                    if self.researcher:
                        self._kick_research()

    async def on_frame(self, jpeg: bytes) -> None:
        """A camera frame the producer flagged: read any chart in it, then check its figures."""
        if self.desk:
            self._spawn(self._read_chart(jpeg))

    async def drain(self, timeout: float = 30) -> None:
        """At the end: let fact checks and research already running finish, so the guest's
        last answer is checked too. Measured on Modal 2026-10-27: a check could still be in
        flight several seconds after the interview ended, and was being cancelled."""
        if self._background:
            await asyncio.wait(list(self._background), timeout=timeout)

    async def close(self) -> None:
        self._cancel_reply()
        self._stop_speaking()
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
        started = bool(HAS_FIGURE.search(said))
        if started:  # the page lights its Fact-Check badge until the matching fact_check
            await self.send({"type": "fact_check_started", "turn": turn})
        try:
            checks = await self.desk.check(said)
        except Exception as e:
            await self.send({"type": "error", "message": f"fact-check: {e}"})
            return
        if not checks:
            if started:
                await self.send({"type": "fact_check", "turn": turn, "checks": []})
            return
        for c in checks:
            if c.verdict == "contradicted":
                ask = f" You could ask: {c.challenge}" if c.challenge else ""
                self.notes.append(
                    f"the guest's {c.claim!r} looks wrong: sources give {c.correct_value}. "
                    f"{c.explanation}{ask}"
                )
            elif c.verdict == "unverifiable" and c.challenge and len(self.notes) < MAX_NOTES:
                self.notes.append(
                    f"the guest's {c.claim!r} cannot be verified yet. You could ask: {c.challenge}"
                )
        del self.notes[:-MAX_NOTES]
        await self.send(
            {"type": "fact_check", "turn": turn, "checks": [c.model_dump() for c in checks]}
        )

    def _kick_research(self) -> None:
        """One Live Scout search at a time; turns that arrive meanwhile trigger one more."""
        if self._researching:
            self._research_again = True
            return
        self._researching = True
        self._spawn(self._research())

    async def _research(self) -> None:
        assert self.researcher is not None
        try:
            while True:
                self._research_again = False
                await self.send({"type": "research_started"})
                talk = "\n".join(self.transcript[-TRANSCRIPT_LINES:])
                try:
                    found = await self.researcher(talk, self.research_text)
                except Exception as e:
                    await self.send({"type": "error", "message": f"research: {e}"})
                    return
                self.research_text = found.as_text()
                learn = getattr(self.desk, "learn", None)
                if learn:
                    learn(self.research_text)
                await self.send({"type": "research", **found.model_dump()})
                if not self._research_again:
                    return
        finally:
            self._researching = False

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
                    research=self.research_text,
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
        self.transcript.append(f"Anchor: {line}")
        hold = self._hold_until if opening else 0.0
        if self.voice:
            self._stop_speaking()
            self._speaking = asyncio.create_task(self._speak(self._line_id, line, hold))
        else:
            await self._wait_until(hold)
            await self.send({"type": "anchor_line", "id": self._line_id, "text": line})

    @staticmethod
    async def _wait_until(t: float) -> None:
        delay = t - asyncio.get_running_loop().time()
        if delay > 0:
            await asyncio.sleep(delay)

    def _stop_speaking(self) -> None:
        """Drop the line being voiced: its audio, and above all its lip-sync renders."""
        if self._speaking and not self._speaking.done():
            self._speaking.cancel()
        self._speaking = None

    async def _buffer(self, jobs: list[asyncio.Task], loop: asyncio.AbstractEventLoop) -> None:
        """Hold the first clip back so the others, still rendering, stay ahead of its playback."""
        t_ready = loop.time()
        try:
            mp3s = await asyncio.gather(*jobs)
        except Exception:
            return  # a voice failed: _speak's own error path handles it
        lengths = await asyncio.gather(*(_mp3_seconds(m) for m in mp3s))
        if any(x is None for x in lengths):
            print("[speak] could not measure the speech: no hold", flush=True)
            return
        wait = buffer_seconds([x for x in lengths if x is not None]) - (loop.time() - t_ready)
        print(
            f"[speak] speech {[round(x, 1) for x in lengths if x]}s, holding {max(wait, 0):.1f}s",
            flush=True,
        )
        if wait > 0:
            await asyncio.sleep(wait)

    async def _speak(self, line_id: int, line: str, hold: float = 0.0) -> None:
        """The line's text, then its audio in order, one message per sentence. With `hold`, the
        sentences are voiced (and rendered) at once but the line goes out only at that time.

        Lip-sync renders at about 1.2x the speech's length and one sentence after another, so a
        line that starts the moment its first clip is ready runs dry mid-sentence. The first clip
        is therefore held back just long enough for the rest to keep ahead of playback."""
        assert self.voice is not None
        # A long first sentence is split at its first comma, so her first words come sooner: the
        # voice takes ~1 s for a short phrase, ~2 s for a long sentence (Modal, Oct 31).
        parts = _short_start(sentences(line) or [line])
        jobs = [asyncio.create_task(self.voice(p)) for p in parts]
        announced = False
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        ready: asyncio.Queue = asyncio.Queue()  # (part, message), or the exception that stopped it

        async def render() -> None:
            try:
                for i, job in enumerate(jobs):
                    mp3 = await job
                    t_voice = loop.time() - t0
                    msg = {
                        "type": "anchor_audio",
                        "id": line_id,
                        "part": i,
                        "last": i == len(jobs) - 1,
                        "mp3": base64.b64encode(mp3).decode(),
                    }
                    if self.lipsync:
                        t_sync = loop.time()
                        try:
                            msg["video"] = await self.lipsync(mp3, line_id, i)
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            msg["video"] = None  # this sentence goes out as audio only
                        # One line per sentence in the logs (Modal's too), to see where time goes.
                        print(
                            f"[speak] line {line_id} part {i}: voiced at {t_voice:.1f}s, "
                            f"lip-sync {loop.time() - t_sync:.1f}s, "
                            f"out at {loop.time() - t0:.1f}s, "
                            f"clip {'yes' if msg['video'] else 'no'}",
                            flush=True,
                        )
                    await ready.put((i, msg))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await ready.put(e)

        renderer = asyncio.create_task(render())
        try:
            if not hold:
                await self.send({"type": "anchor_line", "id": line_id, "text": line})
                announced = True
            for _ in jobs:
                item = await ready.get()
                if isinstance(item, Exception):
                    raise item
                i, msg = item
                if i == 0 and self.lipsync and msg.get("video") and len(jobs) > 1:
                    await self._buffer(jobs, loop)
                if not announced:  # the greeting has finished: on air
                    await self._wait_until(hold)
                    await self.send({"type": "anchor_line", "id": line_id, "text": line})
                    announced = True
                await self.send(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not announced:  # the page needs the text to fall back to its own voice
                await self._wait_until(hold)
                await self.send({"type": "anchor_line", "id": line_id, "text": line})
            await self.send({"type": "anchor_audio_failed", "id": line_id})
        finally:
            renderer.cancel()
            for job in jobs:
                job.cancel()
