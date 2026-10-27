from __future__ import annotations

import asyncio

from studio.agents.factcheck import ChartReading, Check, Figure
from studio.asr import GuestPartial, GuestPaused, GuestStarted, GuestTurn
from studio.live import LiveSession


class FakeAnchor:
    """Answers after `delay` seconds; records what it was asked."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.asked: list[tuple[str, bool]] = []
        self.started: list[str] = []
        self.notes_seen: list[list[str]] = []

    async def opening(self) -> str:
        self.started.append("opening")
        await asyncio.sleep(self.delay)
        return "Welcome."

    async def reply(
        self, guest_said: str, *, interrupted: bool = False, notes=(), research=""
    ) -> str:
        self.started.append(guest_said)
        await asyncio.sleep(self.delay)
        self.asked.append((guest_said, interrupted))
        self.notes_seen.append(list(notes))
        return f"re: {guest_said}"


def _session(anchor: FakeAnchor, desk=None) -> tuple[LiveSession, list[dict]]:
    sent: list[dict] = []

    async def send(msg: dict) -> None:
        sent.append(msg)

    return LiveSession(anchor, send, desk), sent


WRONG = Check(
    claim="FY26 growth 9.1%",
    verdict="contradicted",
    correct_value="5.4%",
    explanation="FY26 results give 5.4%.",
    source_url="https://example.com/results",
)


class FakeDesk:
    def __init__(self, checks=(), chart=None, delay: float = 0.0):
        self.checks, self.chart, self.delay = list(checks), chart, delay
        self.checked: list[str] = []

    async def check(self, said: str):
        """The first call returns `checks`; later ones find nothing."""
        self.checked.append(said)
        await asyncio.sleep(self.delay)
        found, self.checks = self.checks, []
        return found

    async def read_chart(self, jpeg: bytes):
        return self.chart


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
        async def reply(self, guest_said, *, interrupted=False, notes=(), research=""):
            raise RuntimeError("budget spent")

    s, sent = _session(Broken())
    await s.on_event(GuestTurn(0, "Hello.", 0))
    await _settle()
    assert any(m["type"] == "error" and "budget spent" in m["message"] for m in sent)
    assert s.pending == ["Hello."]


async def test_contradicted_figure_reaches_the_next_anchor_reply():
    anchor, desk = FakeAnchor(), FakeDesk([WRONG])
    s, sent = _session(anchor, desk)
    await s.on_event(GuestTurn(0, "We grew 9.1% in FY26.", 0))
    await _settle()
    [fc] = [m for m in sent if m["type"] == "fact_check"]
    assert fc["turn"] == 0 and fc["checks"][0]["verdict"] == "contradicted"
    assert anchor.notes_seen == [[]]  # the first reply did not wait for the check
    await s.on_event(GuestTurn(1, "And margins held up.", 0))
    await _settle()
    assert "5.4%" in anchor.notes_seen[1][0]
    assert s.notes == []  # used once


async def test_fact_check_never_delays_the_anchor():
    anchor, desk = FakeAnchor(), FakeDesk([WRONG], delay=1.0)
    s, sent = _session(anchor, desk)
    await s.on_event(GuestTurn(0, "We grew 9.1%.", 0))
    await _settle()
    assert _lines(sent) == ["re: We grew 9.1%."]
    await s.close()  # the slow check is cancelled with the session


async def test_chart_frame_is_read_then_checked():
    chart = ChartReading(
        legible=True,
        title="Organic growth",
        source="company results",
        figures=[Figure(label="FY26", value=9.1, unit="%", period="FY26")],
    )
    desk = FakeDesk([WRONG], chart=chart)
    s, sent = _session(FakeAnchor(), desk)
    await s.on_frame(b"\xff\xd8jpeg")
    await _settle()
    types = [m["type"] for m in sent]
    assert types == ["chart_reading_started", "chart", "fact_check_started", "fact_check"]
    assert desk.checked == [
        'Chart "Organic growth". Source shown: company results. FY26: 9.1 % (FY26)'
    ]


async def test_illegible_chart_is_not_checked():
    chart = ChartReading(legible=False, title="", source="", figures=[])
    desk = FakeDesk(chart=chart)
    s, sent = _session(FakeAnchor(), desk)
    await s.on_frame(b"\xff\xd8")
    await _settle()
    assert desk.checked == [] and sent[-1]["type"] == "chart"


async def test_check_with_nothing_found_still_closes_the_badge():
    s, sent = _session(FakeAnchor(), FakeDesk([]))
    await s.on_event(GuestTurn(0, "We grew 5%.", 0))
    await s.on_event(GuestTurn(1, "Thanks for having me.", 0))  # no figure: no check messages
    await _settle()
    checks = [m for m in sent if m["type"].startswith("fact_check")]
    assert checks == [
        {"type": "fact_check_started", "turn": 0},
        {"type": "fact_check", "turn": 0, "checks": []},
    ]
