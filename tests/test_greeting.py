from __future__ import annotations

import shutil
import subprocess

import pytest

from studio import compose, greeting

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _mp3(path):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=d=1", str(path)], check=True)  # fmt: skip
    return path.read_bytes()


@needs_ffmpeg
async def test_the_greeting_is_made_once_then_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_CACHE", str(tmp_path))
    calls = {"voice": 0, "lipsync": 0}
    tone = _mp3(tmp_path / "tone.mp3")

    async def voice(text):
        calls["voice"] += 1
        return tone

    async def fake_lipsync(mp3, out, shot="wide", start=None):
        assert (shot, start) == ("live", 0)  # from her still, in the live shot
        calls["lipsync"] += 1
        out.write_bytes(b"mp4")
        return 31

    monkeypatch.setattr(compose, "lipsync", fake_lipsync)
    first = await greeting.prepare(voice, synced=True)
    again = await greeting.prepare(voice, synced=True)
    assert calls == {"voice": 1, "lipsync": 1}
    assert again.clip == first.clip and again.cursor == 31 and 0.9 < again.seconds < 1.2
    assert (await greeting.prepare(voice, synced=False)).clip is None
