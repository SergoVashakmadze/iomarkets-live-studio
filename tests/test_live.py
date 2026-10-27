from __future__ import annotations

import asyncio

from studio.asr import GuestPartial, GuestPaused, GuestStarted, GuestTurn
from studio.live import LiveSession


class FakeAnchor:
    """Answers after `delay` seconds; records what it was asked."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.asked: list[tuple[str, bool]] = []
        self.started: list[str] = []

    async def opening(self) -> str:
        self.started.append("opening")
        await asyncio.sleep(self.delay)
        return "Welcome."

    async def reply(self, guest_said: str, *, interrupted: bool = False) -> str:
        self.started.append(guest_said)
        await asyncio.sleep(self.delay)
        self.asked.append((guest_said, interrupted))
        return f"re: {guest_said}"


def _session(anchor: FakeAnchor) -> tuple[LiveSession, list[dict]]:
    sent: list[dict] = []

    async def send(msg: dict) -> None:
        sent.append(msg)

    return LiveSession(anchor, send), sent


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _lines(sent: list[dict]) -> list[str]:
    return [m["text"] for m in sent if m["type"] == "anchor_line"]


async def test_opening_then_reply_per_turn():
    anchor = FakeAnchor()
    s, sent = _session(anchor)
    await s.open()
    await _settle()
    await s.on_event(GuestStarted(0, barge_in=False))
    await s.on_event(GuestPartial(0, "we grew"))
    await s.on_event(GuestPaused(0))
    await s.on_event(GuestTurn(0, "We grew five percent.", 4000))
    await _settle()
    assert _lines(sent) == ["Welcome.", "re: We grew five percent."]
    assert anchor.asked == [("We grew five percent.", False)]
    assert [m["type"] for m in sent if m["type"].startswith("guest")] == [
        "guest_started",
        "guest_partial",
        "guest_paused",
        "guest_turn",
    ]


async def test_barge_in_stops_playback_and_marks_next_reply():
    anchor = FakeAnchor()
    s, sent = _session(anchor)
    s.set_anchor_speaking(True)
    await s.on_event(GuestStarted(1, barge_in=True))
    assert {"type": "stop_anchor"} in sent
    assert not s.anchor_speaking
    await s.on_event(GuestTurn(1, "Sorry, can I jump in?", 0))
    await _settle()
    assert anchor.asked == [("Sorry, can I jump in?", True)]
    await s.on_event(GuestTurn(2, "And another thing.", 0))
    await _settle()
    assert anchor.asked[-1] == ("And another thing.", False)


async def test_guest_resuming_drops_the_unsent_reply_and_merges_turns():
    anchor = FakeAnchor(delay=0.05)
    s, sent = _session(anchor)
    await s.on_event(GuestTurn(0, "Revenue was up.", 0))
    await _settle()
    assert anchor.started == ["Revenue was up."]
    await s.on_event(GuestStarted(1, barge_in=False))  # still talking: drop that reply
    await s.on_event(GuestTurn(1, "Mostly in Germany.", 0))
    await asyncio.sleep(0.1)
    assert anchor.asked == [("Revenue was up. Mostly in Germany.", False)]
    assert _lines(sent) == ["re: Revenue was up. Mostly in Germany."]
    assert s.pending == []


async def test_empty_turn_gets_no_reply():
    anchor = FakeAnchor()
    s, sent = _session(anchor)
    await s.on_event(GuestTurn(0, "", 0))
    await _settle()
    assert anchor.started == []


async def test_anchor_failure_is_reported_and_keeps_pending():
    class Broken(FakeAnchor):
        async def reply(self, guest_said, *, interrupted=False):
            raise RuntimeError("budget spent")

    s, sent = _session(Broken())
    await s.on_event(GuestTurn(0, "Hello.", 0))
    await _settle()
    assert any(m["type"] == "error" and "budget spent" in m["message"] for m in sent)
    assert s.pending == ["Hello."]
