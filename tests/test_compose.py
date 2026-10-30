from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from studio import compose
from studio.asr import GuestStarted
from studio.live import LiveSession

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _clip(path: Path, size="320x240", audio=True, seconds=1) -> Path:
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
           "-i", f"color=c=red:s={size}:r=30:d={seconds}"]  # fmt: skip
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=d={seconds}:sample_rate=44100", "-c:a", "aac"]
    subprocess.run([*cmd, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)],
                   check=True)  # fmt: skip
    return path


@needs_ffmpeg
async def test_silent_card_and_caption_on_a_clip_without_audio(tmp_path):
    card = tmp_path / "card.mp4"
    await compose.question_card("What changed? Tell us 5% more: 'quoted'", None, card, 320, 240,
                                tmp_path)  # fmt: skip
    w, h, d, audio = await compose.media_info(card)
    assert (w, h, audio) == (320, 240, True) and 3.3 < d < 3.7
    answer = tmp_path / "answer.mp4"
    await compose.captioned_answer(_clip(tmp_path / "in.mp4", audio=False), answer,
                                   "Jane: O'Doe", "CFO, Example plc", tmp_path)  # fmt: skip
    assert (await compose.media_info(answer))[3] is True  # silent track added for concat


@needs_ffmpeg
async def test_question_card_lip_synced_or_not(tmp_path, monkeypatch):
    mp3 = tmp_path / "q.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=f=220:d=2", str(mp3)], check=True)  # fmt: skip
    # No MuseTalk server: the card still renders, from the loop, the studio or a plain colour.
    monkeypatch.setenv("STUDIO_MUSETALK_URL", "http://127.0.0.1:9")
    card = tmp_path / "card.mp4"
    await compose.question_card("Is the margin sustainable?", mp3, card, 640, 360, tmp_path)
    w, h, d, audio = await compose.media_info(card)
    assert (w, h, audio) == (640, 360, True) and 2.4 < d < 2.8

    # With one: its lip-synced video is the picture, and the question's own audio is kept.
    async def fake_lipsync(mp3_path, out):
        _clip(out, size="1280x720", audio=False, seconds=3)
        return True

    monkeypatch.setattr(compose, "lipsync", fake_lipsync)
    await compose.question_card("And next year?", mp3, card, 640, 360, tmp_path)
    w, h, d, audio = await compose.media_info(card)
    assert (w, h, audio) == (640, 360, True) and 2.4 < d < 2.8


async def test_lipsync_is_skipped_without_a_server(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_MUSETALK_URL", "")
    mp3 = tmp_path / "q.mp3"
    mp3.write_bytes(b"x")
    assert await compose.lipsync(mp3, tmp_path / "out.mp4") is False


@needs_ffmpeg
async def test_join_mixes_sizes_and_audio_layouts(tmp_path):
    a = _clip(tmp_path / "a.mp4", size="320x240")
    b = _clip(tmp_path / "b.mp4", size="640x360")
    out = tmp_path / "out.mp4"
    await compose.join([a, b], out, 320, 240)
    w, h, d, audio = await compose.media_info(out)
    assert (w, h, audio) == (320, 240, True) and 1.9 < d < 2.2


def test_unsafe_work_paths_are_refused(tmp_path):
    with pytest.raises(ValueError):
        compose._text(tmp_path / "a:b.txt", "x")


class _Anchor:
    async def opening(self):
        return "Welcome. First question?"

    async def reply(self, said, *, interrupted=False, notes=(), research=""):
        return "Second question?"


async def test_session_records_the_question_each_turn_answers():
    async def send(_):
        pass

    s = LiveSession(_Anchor(), send)
    await s.on_event(GuestStarted(0, barge_in=False))  # before any anchor line
    assert s.question_for_turn == {}
    await s.open()
    await s._reply
    await s.on_event(GuestStarted(1, barge_in=False))
    await s.on_event(GuestStarted(1, barge_in=False))  # repeated start keeps the first
    assert s.question_for_turn == {1: "Welcome. First question?"}


@needs_ffmpeg
async def test_text_card(tmp_path):
    out = tmp_path / "title.mp4"
    lines = [("Title: it's here", 12, "white"), ("", 40, "white"), ("sub", 30, "0x9fb3c8")]
    await compose.text_card(lines, out, tmp_path, width=640, height=360, seconds=1.5)
    w, h, d, audio = await compose.media_info(out)
    assert (w, h, audio) == (640, 360, True) and 1.4 < d < 1.6
