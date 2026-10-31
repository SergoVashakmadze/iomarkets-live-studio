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


def _fake_wav(text: str) -> bytes:
    import io
    import wave

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * 1600 * max(1, len(text) // 10))
    return out.getvalue()


async def test_synthesize_gives_mp3_in_call_order(monkeypatch):
    """Meta's MMS-TTS is stubbed (no model download in tests); the WAV goes out as MP3."""
    spoken: list[str] = []

    def speak(text):
        spoken.append(text)
        return _fake_wav(text)

    monkeypatch.setattr(tts, "_speak", speak)
    out = await asyncio.gather(synthesize("First."), synthesize("Second, longer sentence."))
    assert spoken == ["First.", "Second, longer sentence."]
    assert all(o[:3] == b"ID3" or o[:2] in (b"\xff\xfb", b"\xff\xf3") for o in out)


async def test_synthesize_failure_raises(monkeypatch):
    def broken(text):
        raise RuntimeError("model missing")

    monkeypatch.setattr(tts, "_speak", broken)
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


async def test_native_voice_first_then_mms_if_it_fails(monkeypatch):
    """With STUDIO_TTS_URL set the native voice speaks; if it fails, MMS does, never silence."""
    calls: list[str] = []

    async def native(text, timeout):
        calls.append(text)
        return _fake_wav(text)

    monkeypatch.setenv("STUDIO_TTS_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(tts, "_native_wav", native)
    monkeypatch.setattr(tts, "_speak", lambda text: (_ for _ in ()).throw(AssertionError("MMS")))
    assert (await synthesize("Hello.")) and calls == ["Hello."]
    assert tts.voice_name() == tts.NATIVE_VOICE

    async def broken(text, timeout):
        raise RuntimeError("down")

    spoken: list[str] = []
    monkeypatch.setattr(tts, "_native_wav", broken)
    monkeypatch.setattr(tts, "_speak", lambda text: spoken.append(text) or _fake_wav(text))
    assert await synthesize("Hello again.") and spoken == ["Hello again."]

    monkeypatch.delenv("STUDIO_TTS_URL")
    assert tts.voice_name() == tts.DEFAULT_VOICE
