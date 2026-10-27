"""The anchor's voice: Microsoft Edge text-to-speech (Meta has no speech model).

Only the anchor's own lines are sent: never anything the guest said. Lines are split into
sentences and synthesised in parallel, so the page can start playing the first sentence while
the rest are still being made. Measured 2026-10-27, a 25-word line: en-GB-RyanNeural first
audio 0.9 s, whole line 1.7 s; en-GB-SoniaNeural 3.6 s and 6.6 s, so Ryan is the default.

edge-tts verifies TLS with certifi (>=2026.10.23 here) and must be 7.3.1 or later: older
releases get HTTP 403.
"""

from __future__ import annotations

import asyncio
import os
import re

import edge_tts

DEFAULT_VOICE = "en-GB-RyanNeural"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip())]
    return [p for p in parts if p]


async def synthesize(text: str, voice: str | None = None, timeout: float = 10.0) -> bytes:
    """One sentence to MP3 bytes."""
    voice = voice or os.environ.get("STUDIO_VOICE") or DEFAULT_VOICE

    async def run() -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        if not audio:
            raise RuntimeError("no audio returned")
        return bytes(audio)

    return await asyncio.wait_for(run(), timeout)
