from __future__ import annotations

import asyncio
import json

import pytest
from conftest import load_recording
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from studio import asr
from studio.asr import (
    FRAME_BYTES,
    AsrError,
    GuestListener,
    GuestPartial,
    GuestPaused,
    GuestStarted,
    GuestTurn,
    Pacer,
    TurnTracker,
)

# A live run (2026-10-27) of a 16 s, two-turn synthetic clip; the handshake frame is first.
RECORDING = [f["msg"] for f in load_recording("asr_two_turns_2026-10-27.json")]
SERVER_EVENTS = RECORDING[1:]


def _events(tracker: TurnTracker, messages: list[dict]) -> list:
    return [e for m in messages if (e := tracker.feed(m)) is not None]


def test_recorded_session_gives_two_turns():
    events = _events(TurnTracker(), SERVER_EVENTS)
    turns = [e for e in events if isinstance(e, GuestTurn)]
    assert [t.turn_id for t in turns] == [0, 1]
    assert turns[0].text.endswith("by 5.4% last year.")
    assert turns[1].text.startswith("Sorry, can I jump in there")
    assert [type(e) for e in events if not isinstance(e, GuestPartial)] == [
        GuestStarted,
        GuestPaused,
        GuestTurn,
        GuestStarted,
        GuestPaused,
        GuestTurn,
    ]


def test_end_of_stream_empty_transcript_is_ignored():
    events = _events(TurnTracker(), SERVER_EVENTS)
    assert all(e.text for e in events if isinstance(e, GuestPartial))
    assert isinstance(events[-1], GuestTurn)


def test_speech_start_while_anchor_speaks_is_barge_in():
    speaking = {"now": False}
    tracker = TurnTracker(anchor_speaking=lambda: speaking["now"])
    assert tracker.feed({"type": "speechStart", "turnId": 0}) == GuestStarted(0, barge_in=False)
    speaking["now"] = True
    assert tracker.feed({"type": "speechStart", "turnId": 1}) == GuestStarted(1, barge_in=True)


def test_overlapping_turns_are_keyed_by_turn_id():
    t = TurnTracker()
    t.feed({"type": "speechStart", "turnId": 3})
    t.feed({"type": "transcript", "transcript": "first one", "final": False})
    t.feed({"type": "speechStart", "turnId": 4})
    assert t.feed({"type": "transcript", "transcript": "second", "final": False}) == GuestPartial(
        4, "second"
    )
    # Turn 3 completes late, with no final text: falls back to its own last partial.
    assert t.feed({"type": "speechComplete", "turnId": 3, "transcript": ""}) == GuestTurn(
        3, "first one", 0
    )
    done = t.feed(
        {"type": "speechComplete", "turnId": 4, "transcript": "Second.", "audioProcessedMs": 9}
    )
    assert done == GuestTurn(4, "Second.", 9)


def test_error_event_raises():
    with pytest.raises(AsrError, match="bad audio"):
        TurnTracker().feed({"type": "error", "message": "bad audio", "errorType": "x"})


def test_unknown_events_are_ignored():
    t = TurnTracker()
    assert t.feed({"type": "audioProgress", "audioProcessedMs": 80}) is None
    assert t.feed({"type": "speaker", "label": "A"}) is None
    assert t.feed({"type": "somethingNew"}) is None


def test_handshake_fields():
    h = asr.handshake("k", ["Vodafone"], ["English"])
    assert h["authorization"] == {"accessToken": "Bearer k"}
    assert h["mode"] == "ENDPOINTING" and h["audioEncoding"] == "PCM_24KHZ"
    assert h["model"] == "muse-voice-transcribe-1.0"
    assert h["keywords"] == ["Vodafone"] and h["languageBias"] == ["English"]
    assert "keywords" not in asr.handshake("k")


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_pacer_sends_a_file_at_real_time_with_a_small_lead():
    clock = FakeClock()
    p = Pacer(clock=clock)
    p.push(bytes(FRAME_BYTES * 100))  # 8 s of audio at once
    assert len(p.frames()) == 5  # 400 ms lead at t=0
    clock.t = 1.0
    assert len(p.frames()) == 13  # up to one frame past the 1.4 s target
    assert p.sent_ms == 1440


def test_pacer_fills_silence_only_when_starved():
    clock = FakeClock()
    p = Pacer(clock=clock)
    assert p.frames() == []
    clock.t = 0.1
    assert p.frames() == []  # within the 200 ms grace
    clock.t = 0.3
    [frame] = p.frames()
    assert frame == bytes(FRAME_BYTES)


def test_pacer_pads_a_partial_frame_into_silence():
    clock = FakeClock()
    p = Pacer(clock=clock)
    p.frames()
    p.push(b"\x01\x00" * 10)
    clock.t = 0.5
    [frame] = p.frames()
    assert frame.startswith(b"\x01\x00" * 10) and len(frame) == FRAME_BYTES


class FakeSocket:
    """Plays server frames back once the client has sent endStream."""

    def __init__(self, reply: dict, events: list[dict], close: Close | None = None):
        self.reply = json.dumps(reply)
        self.events = [json.dumps(e) for e in events]
        self.close_frame = close
        self.sent: list[str | bytes] = []
        self.ended = asyncio.Event()
        self.closed = False

    async def send(self, data):
        self.sent.append(data)
        if isinstance(data, str) and json.loads(data).get("type") == "endStream":
            self.ended.set()

    async def recv(self):
        return self.reply

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        await self.ended.wait()
        for e in self.events:
            yield e
        if self.close_frame:
            raise ConnectionClosedError(self.close_frame, None)
        return


def _connector(sock: FakeSocket):
    async def connect(url, **kw):
        sock.url = url
        return sock

    return connect


@pytest.fixture
def fast(monkeypatch):
    real_sleep = asyncio.sleep
    monkeypatch.setattr("studio.asr.asyncio.sleep", lambda _s: real_sleep(0))


async def test_listener_session_end_to_end(fast):
    sock = FakeSocket({"sessionId": "s1"}, SERVER_EVENTS)
    async with GuestListener("k", connect=_connector(sock)) as listener:
        assert listener.session_id == "s1"
        listener.pacer = Pacer(lead_ms=10**9)  # no real-time wait in tests
        listener.push(bytes(FRAME_BYTES * 3 + 10))
        listener.finish()
        events = [e async for e in listener.events()]

    assert json.loads(sock.sent[0])["authorization"]["accessToken"] == "Bearer k"
    audio = [s for s in sock.sent if isinstance(s, bytes)]
    assert len(audio) == 4 and all(len(a) == FRAME_BYTES for a in audio)
    assert json.loads(sock.sent[-1]) == {"type": "endStream"}
    assert sum(isinstance(e, GuestTurn) for e in events) == 2
    assert sock.closed


async def test_refused_handshake_raises():
    sock = FakeSocket({"type": "error", "message": "invalid key", "sessionId": ""}, [])
    with pytest.raises(AsrError, match="invalid key"):
        async with GuestListener("k", connect=_connector(sock)):
            pass
    assert sock.closed


async def test_policy_close_raises_with_code(fast):
    sock = FakeSocket({"sessionId": "s"}, [], close=Close(1008, "ingress below real time"))
    async with GuestListener("k", connect=_connector(sock)) as listener:
        listener.finish()
        with pytest.raises(AsrError) as e:
            [_ async for _ in listener.events()]
    assert e.value.code == 1008
