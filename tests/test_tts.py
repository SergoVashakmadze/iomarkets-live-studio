from __future__ import annotations

import asyncio
import base64

import pytest

from studio import tts
from studio.asr import GuestTurn
from studio.live import LiveSession
from studio.tts import sentences, synthesize


def test_sentences():
    assert sentences("That was strong. But why now? Tell us!") == [
        "That was strong.",
        "But why now?",
        "Tell us!",
    ]
    assert sentences("No full stop") == ["No full stop"]
    assert sentences("  ") == []
    assert sentences("It grew 5.4% in FY26. Why?") == ["It grew 5.4% in FY26.", "Why?"]


class FakeCommunicate:
    calls: list[tuple[str, str]] = []

    def __init__(self, text, voice):
        FakeCommunicate.calls.append((text, voice))
        self.text = text

    async def stream(self):
        yield {"type": "WordBoundary"}
        yield {"type": "audio", "data": b"mp3:"}
        yield {"type": "audio", "data": self.text.encode()}


async def test_synthesize_collects_audio(monkeypatch):
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.delenv("STUDIO_VOICE", raising=False)
    assert await synthesize("Hello.") == b"mp3:Hello."
    assert FakeCommunicate.calls[-1] == ("Hello.", "en-GB-RyanNeural")


async def test_synthesize_with_no_audio_fails(monkeypatch):
    class Silent(FakeCommunicate):
        async def stream(self):
            yield {"type": "WordBoundary"}

    monkeypatch.setattr(tts.edge_tts, "Communicate", Silent)
    with pytest.raises(RuntimeError):
        await synthesize("Hello.")


class Anchor:
    async def opening(self):
        return "Welcome. First question?"

    async def reply(self, said, *, interrupted=False, notes=(), research=""):
        return "Thanks. Next?"


def _session(voice):
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    return LiveSession(Anchor(), send, None, voice), sent


async def _settle(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


async def test_line_text_first_then_audio_in_sentence_order():
    async def voice(text):
        await asyncio.sleep(0.02 if text.startswith("Welcome") else 0)  # 2nd finishes first
        return text.encode()

    s, sent = _session(voice)
    await s.open()
    await asyncio.sleep(0.05)
    kinds = [m["type"] for m in sent]
    assert kinds == ["anchor_thinking", "anchor_line", "anchor_audio", "anchor_audio"]
    line, a0, a1 = sent[1], sent[2], sent[3]
    assert line["id"] == a0["id"] == a1["id"] == 1
    assert (a0["part"], a0["last"], base64.b64decode(a0["mp3"])) == (0, False, b"Welcome.")
    assert (a1["part"], a1["last"], base64.b64decode(a1["mp3"])) == (1, True, b"First question?")


async def test_voice_failure_tells_the_page_to_fall_back():
    async def voice(text):
        raise RuntimeError("403")

    s, sent = _session(voice)
    await s.on_event(GuestTurn(0, "Hello.", 0))
    await _settle()
    assert sent[-1] == {"type": "anchor_audio_failed", "id": 1}


async def test_no_voice_sends_text_only():
    s, sent = _session(None)
    await s.open()
    await _settle()
    assert [m["type"] for m in sent] == ["anchor_thinking", "anchor_line"]
