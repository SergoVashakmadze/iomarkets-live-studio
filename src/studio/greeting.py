"""The anchor's greeting: the same words every interview, so voiced and lip-synced once and kept.

Lip-syncing a sentence takes about 1.2x its length on the workstation GPU, and the anchor's
opening question takes a few seconds to write: without this, the guest sat in silence for
6-8 s after going live, and often spoke first. The greeting plays at once, from disk, while
the opening question is written and rendered behind it (live.LiveSession, `greeting`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from studio import compose
from studio.tts import DEFAULT_VOICE

GREETING = "Welcome to IoMarkets TV. I'm Adrian Hale, and we're live."
_lock = asyncio.Lock()


@dataclass
class Prepared:
    mp3: Path
    seconds: float
    clip: Path | None = None  # lip-synced, in the live shot, starting from her still
    cursor: int | None = None  # where her loop ends: the opening question carries on from here


def cache_dir() -> Path:
    default = Path.home() / ".cache" / "iomarkets-studio"
    path = Path(os.environ.get("STUDIO_CACHE", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


async def prepare(voice: Callable[[str], Awaitable[bytes]], synced: bool) -> Prepared:
    """The greeting's voice, and its lip-synced clip when `synced`: made once, then from disk."""
    name = os.environ.get("STUDIO_VOICE") or DEFAULT_VOICE
    key = hashlib.sha1(f"{GREETING}|{name}".encode()).hexdigest()[:12]
    async with _lock:  # the page's warm-up and a first interview may ask at once
        mp3 = cache_dir() / f"greeting-{key}.mp3"
        if not mp3.exists():
            data = await voice(GREETING)
            mp3.with_suffix(".tmp").write_bytes(data)
            mp3.with_suffix(".tmp").rename(mp3)
        done = Prepared(mp3, (await compose.media_info(mp3))[2])
        if not synced:
            return done
        clip, meta = mp3.with_suffix(".live.mp4"), mp3.with_suffix(".live.json")
        if not (clip.exists() and meta.exists()):
            cursor = await compose.lipsync(mp3, clip, "live", start=0)
            if cursor is None:
                return done
            meta.write_text(json.dumps({"cursor": cursor}))
        done.clip, done.cursor = clip, json.loads(meta.read_text())["cursor"]
        return done
