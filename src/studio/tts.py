"""The anchor's voice: Meta's MMS text-to-speech (`facebook/mms-tts-eng`), run in this process.

The organisers' answer of 2026-10-31: every model the studio calls at runtime must be Meta's,
and Microsoft's Edge voice is not, so the anchor speaks with Meta's own open-weights MMS model
(VITS, CC-BY-NC-4.0), on the CPU. Measured 2026-10-31 on the workstation: 0.3-0.8 s per sentence
on the CPU, 0.03 s on the GPU; MMS has one English voice, a man's.

Only the anchor's own lines are spoken: never anything the guest said, and nothing leaves the
machine. Lines are split into sentences, so the page starts playing the first while the rest
are made. Sentences are voiced one at a time, in order (an asyncio lock is first come, first
served), so the first sentence is always ready first.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import threading
import wave

from studio.speech_text import phrases, to_speech

MODEL = "facebook/mms-tts-eng"
DEFAULT_VOICE = "meta-mms-tts-eng-v2"  # also the greeting cache's key: v2 = calmer, rewritten text
SEED = 7  # one take of the voice's rhythm, the same every run
# Calmer than MMS's defaults (0.667, 0.8, 1.0): steadier, slightly slower, easier to follow.
# Measured 2026-10-31 on eight anchor questions with Whisper as the listener (offline, not in
# the studio): with speech_text's rewriting, word errors fell from 0.22 to 0.17, and the
# questions with figures went from garbled ("riven you trepled in fist") to word-perfect.
NOISE_SCALE, NOISE_SCALE_DURATION, SPEAKING_RATE = 0.4, 0.6, 0.92
PHRASE_PAUSE_S, SENTENCE_TAIL_S = 0.18, 0.12
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_lock = asyncio.Lock()
_model = None
_load_lock = threading.Lock()  # two first calls at once load it once


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip())]
    return [p for p in parts if p]


def _load():
    global _model
    with _load_lock:
        if _model is not None:
            return _model
        import torch
        from transformers import AutoTokenizer, VitsModel

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        model = VitsModel.from_pretrained(MODEL).eval()
        model.noise_scale, model.noise_scale_duration = NOISE_SCALE, NOISE_SCALE_DURATION
        model.speaking_rate = SPEAKING_RATE
        _model = (AutoTokenizer.from_pretrained(MODEL), model)
    return _model


def _speak(text: str) -> bytes:
    """One sentence to 16-bit mono WAV bytes: rewritten for the ear (speech_text), each phrase
    voiced alone with a short pause between, then brought to a steady level."""
    import numpy as np
    import torch

    tok, model = _load()
    rate = model.config.sampling_rate
    chunks = []
    for i, phrase in enumerate(phrases(text) or [text]):
        if i:
            chunks.append(np.zeros(int(rate * PHRASE_PAUSE_S), np.float32))
        torch.manual_seed(SEED)
        with torch.inference_mode():
            chunks.append(model(**tok(phrase, return_tensors="pt")).waveform[0].numpy())
    chunks.append(np.zeros(int(rate * SENTENCE_TAIL_S), np.float32))
    audio = np.concatenate(chunks)
    audio *= 0.89 / max(float(np.abs(audio).max()), 1e-3)  # peak at -1 dB, every sentence alike
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(model.config.sampling_rate)
        w.writeframes(pcm)
    return out.getvalue()


async def _mp3(wav: bytes) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-v", "error", "-f", "wav", "-i", "pipe:0",
        "-c:a", "libmp3lame", "-b:a", "96k", "-f", "mp3", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
    )  # fmt: skip
    data, _ = await proc.communicate(wav)
    if proc.returncode != 0 or not data:
        raise RuntimeError("ffmpeg could not encode the voice")
    return data


# The anchor's main voice since Oct 31 (late): Meta's FastSpeech 2 on LJSpeech, a native US
# English speaker, in its own service (voice/server.py): STUDIO_TTS_URL locally, or the Modal
# class Voice with STUDIO_TTS=modal. MMS, above, is only the fallback when that is not set or
# fails: the operator found it robotic and not native.
NATIVE_VOICE = "meta-fastspeech2-ljspeech-v2"  # v2: IoMarkets as in IoT
APP, VOICE_CLS = "iomarkets-live-studio", "Voice"


def _native() -> str:
    """ "url", "modal" or "" (no native voice configured: MMS)."""
    if os.environ.get("STUDIO_TTS_URL"):
        return "url"
    return "modal" if os.environ.get("STUDIO_TTS") == "modal" else ""


def voice_name() -> str:
    """Which voice speaks now; the greeting's cache key."""
    return NATIVE_VOICE if _native() else DEFAULT_VOICE


async def _native_wav(text: str, timeout: float) -> bytes:
    spoken = to_speech(text, keep_brand=True)
    if _native() == "url":
        import httpx

        url = os.environ["STUDIO_TTS_URL"].rstrip("/") + "/speak"
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json={"text": spoken})
            r.raise_for_status()
            return r.content
    import modal

    voice = modal.Cls.from_name(APP, VOICE_CLS)()
    return await voice.speak.remote.aio(spoken)


async def synthesize(text: str, voice: str | None = None, timeout: float = 30.0) -> bytes:
    """One sentence to MP3 bytes: the native voice if configured, else (or if it fails) MMS.
    `voice` is accepted for the old interface."""

    async def run() -> bytes:
        if _native():
            try:
                return await _mp3(await _native_wav(text, timeout))
            except Exception as e:  # never leave the anchor silent: fall back to MMS
                print(f"[voice] native voice failed, MMS instead: {e!r}", flush=True)
        async with _lock:
            wav = await asyncio.to_thread(_speak, text)
        return await _mp3(wav)

    return await asyncio.wait_for(run(), timeout)


async def warm() -> None:
    """Load the model ahead of the first line (a few seconds, once)."""
    await asyncio.to_thread(_load)
