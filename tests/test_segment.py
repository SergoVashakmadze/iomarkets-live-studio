from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio import segment as segment_mod
from studio.cutout import CutoutReport
from studio.segment import ROOMS, SegmentRoom
from studio.server import create_app

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make_clip(path: Path, seconds: float = 1.0, colour: str = "red") -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:r=25:d={seconds}",
         "-f", "lavfi", "-i", f"sine=d={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )  # fmt: skip


class Cutter:
    """Stands in for cut_out_guest: records the call and writes a placeholder clip."""

    def __init__(self, delay: float = 0.0, fail: bool = False, real_clip: bool = False):
        self.delay, self.fail, self.real_clip = delay, fail, real_clip
        self.calls: list[dict] = []

    async def __call__(self, client, src, out, *, workdir, start_s=0.0, background=None):
        self.calls.append({"src": Path(src), "start_s": start_s, "src_existed": Path(src).exists()})
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("SAM said no")
        if self.real_clip:
            _make_clip(Path(out))
        else:
            Path(out).write_bytes(b"mp4")
        return CutoutReport(frames=25, guest_frames=24, upload_s=1, sam_s=2, composite_s=0.5)


@pytest.fixture
def cutter(monkeypatch):
    c = Cutter()
    monkeypatch.setattr(segment_mod, "cut_out_guest", c)
    return c


def _room() -> tuple[SegmentRoom, list[dict]]:
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    return SegmentRoom(client=None, send=send), sent


async def test_answer_is_cut_and_raw_upload_deleted(cutter):
    room, sent = _room()
    try:
        room.add_answer(3, b"webm bytes", 2.5)
        await room.drain()
        [call] = cutter.calls
        assert call["src_existed"] and call["start_s"] == 2.5
        assert not call["src"].exists()  # raw WebM gone once cut
        assert [m["type"] for m in sent] == ["cutout_started", "cutout"]
        assert sent[-1] == {
            "type": "cutout", "turn": 3, "file": "turn-3.mp4",
            "guest_frames": 24, "frames": 25, "seconds": 3.5,
        }  # fmt: skip
        assert room.media_path("turn-3.mp4") is not None
    finally:
        room.discard()


async def test_failed_cutout_reports_and_still_deletes_raw(monkeypatch):
    c = Cutter(fail=True)
    monkeypatch.setattr(segment_mod, "cut_out_guest", c)
    room, sent = _room()
    try:
        room.add_answer(0, b"x", 0)
        await room.drain()
        assert sent[-1]["type"] == "error" and "SAM said no" in sent[-1]["message"]
        assert not c.calls[0]["src"].exists()
        assert room.clips == {}
    finally:
        room.discard()


async def test_last_answer_survives_the_end_of_the_interview(monkeypatch):
    c = Cutter(delay=0.05)
    monkeypatch.setattr(segment_mod, "cut_out_guest", c)
    room, sent = _room()
    room.add_answer(7, b"x", 0)
    await room.drain()  # what the server does before closing the room
    room.close()
    assert sent[-1]["type"] == "cutout"
    room.discard()
    assert not room.dir.exists() and room.key not in ROOMS


async def test_media_names_are_whitelisted(cutter):
    room, _ = _room()
    try:
        (room.dir / "raw-1.webm").write_bytes(b"x")
        (room.dir / "turn-1.mp4").write_bytes(b"x")
        assert room.media_path("turn-1.mp4") is not None
        for name in ["raw-1.webm", "../turn-1.mp4", "turn-1.mp4/../x", "segment.mp4", "x.mp4"]:
            assert room.media_path(name) is None
    finally:
        room.discard()


def _duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return float(out)


@needs_ffmpeg
async def test_segment_joins_answers_in_turn_order(monkeypatch):
    monkeypatch.setattr(segment_mod, "cut_out_guest", Cutter(real_clip=True))
    room, _ = _room()
    try:
        for turn in (2, 0):
            room.add_answer(turn, b"x", 0)
        await room.drain()
        out = room.media_path(await room.build_segment("Jane Doe", "CFO, Example plc"))
        assert 1.9 < _duration(out) < 2.3  # two 1 s answers, no questions known
    finally:
        room.discard()


@needs_ffmpeg
async def test_segment_has_a_card_per_new_question(monkeypatch):
    monkeypatch.setattr(segment_mod, "cut_out_guest", Cutter(real_clip=True))
    room, _ = _room()
    room.questions.update({0: "Welcome. How is it going?", 1: "Welcome. How is it going?",
                           2: "And next year?"})  # fmt: skip
    try:
        for turn in (0, 1, 2):
            room.add_answer(turn, b"x", 0)
        await room.drain()
        out = room.media_path(await room.build_segment("Jane Doe", "CFO"))
        # Two silent cards (the repeated question gets none) of 3.5 s, three 1 s answers.
        assert 9.6 < _duration(out) < 10.4
    finally:
        room.discard()


async def test_segment_needs_an_answer():
    room, _ = _room()
    try:
        with pytest.raises(ValueError):
            await room.build_segment()
    finally:
        room.discard()


def test_answer_and_media_endpoints(cutter, monkeypatch):
    monkeypatch.delenv("STUDIO_TOKEN", raising=False)
    app = create_app(editor_factory=lambda: None)
    with TestClient(app) as http:
        room, _ = _room()
        try:
            assert http.post(f"/api/answers/{room.key}/1?start=1.5", content=b"webm").json() == {
                "status": "accepted"
            }
            assert http.post(f"/api/answers/{room.key}/1", content=b"").status_code == 400
            assert http.post("/api/answers/nope/1", content=b"x").status_code == 404
            assert http.post(f"/api/answers/{room.key}/1?start=-1", content=b"x").status_code == 422
            assert http.get(f"/media/{room.key}/raw-1.webm").status_code == 404
            monkeypatch.setenv("STUDIO_TOKEN", "t")
            assert http.post(f"/api/answers/{room.key}/2", content=b"x").status_code == 403
            assert http.post(f"/api/segment/{room.key}").status_code == 403
        finally:
            room.discard()
