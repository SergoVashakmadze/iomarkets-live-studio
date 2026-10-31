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
import wave

MODEL = "facebook/mms-tts-eng"
DEFAULT_VOICE = "meta-mms-tts-eng"  # also the greeting cache's key
SEED = 7  # one take of the voice's rhythm, the same every run
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_lock = asyncio.Lock()
_model = None


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip())]
    return [p for p in parts if p]


def _load():
    global _model
    if _model is None:
        import torch
        from transformers import AutoTokenizer, VitsModel

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        _model = (AutoTokenizer.from_pretrained(MODEL), VitsModel.from_pretrained(MODEL).eval())
    return _model


def _speak(text: str) -> bytes:
    """One sentence to 16-bit mono WAV bytes."""
    import numpy as np
    import torch

    tok, model = _load()
    torch.manual_seed(SEED)
    with torch.inference_mode():
        audio = model(**tok(text, return_tensors="pt")).waveform[0].numpy()
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


async def synthesize(text: str, voice: str | None = None, timeout: float = 30.0) -> bytes:
    """One sentence to MP3 bytes. `voice` is accepted for the old interface; MMS has one."""

    async def run() -> bytes:
        async with _lock:
            wav = await asyncio.to_thread(_speak, text)
        return await _mp3(wav)

    return await asyncio.wait_for(run(), timeout)


async def warm() -> None:
    """Load the model ahead of the first line (a few seconds, once)."""
    await asyncio.to_thread(_load)
