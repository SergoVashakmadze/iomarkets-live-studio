"""The segment room: each guest answer, cut out of its background while the interview goes on.

The page records the guest's camera and mic continuously, restarting the recorder at each turn
boundary, and uploads each answer as WebM with the offset where the guest began speaking. Each
answer goes through `cut_out_guest` (SAM 3.1) in the background, at most two at a time, and the
page is told when it is ready. At the end the producer joins the answers into one segment.

Guest media is kept no longer than the work needs: the raw upload is deleted as soon as its
cutout is done (or fails), SAM's copy is deleted by `segment()`, and the cut-out clips are
deleted `KEEP_AFTER_END_S` after the interview ends, which leaves time to download them.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import secrets
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from studio.cutout import cut_out_guest, join_clips
from studio.live import Send
from studio.meta.responses import ResponsesClient

KEEP_AFTER_END_S = 30 * 60
MAX_CLIP_BYTES = 60_000_000  # about two minutes of 720p WebM
MAX_CONCURRENT = 2
MEDIA_NAME = re.compile(r"^(turn-[0-9]{1,4}|segment)\.mp4$")

ROOMS: dict[str, SegmentRoom] = {}


@dataclass
class SegmentRoom:
    client: ResponsesClient
    send: Send
    key: str = field(default_factory=lambda: secrets.token_urlsafe(18))
    dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="studio-")))
    clips: dict[int, Path] = field(default_factory=dict)
    _slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(MAX_CONCURRENT))
    _jobs: set[asyncio.Task] = field(default_factory=set)

    def __post_init__(self) -> None:
        ROOMS[self.key] = self

    def media_path(self, name: str) -> Path | None:
        if not MEDIA_NAME.fullmatch(name):
            return None
        path = self.dir / name
        return path if path.is_file() else None

    def add_answer(self, turn: int, webm: bytes, start_s: float) -> None:
        raw = self.dir / f"raw-{turn}.webm"
        raw.write_bytes(webm)
        task = asyncio.create_task(self._cut(turn, raw, start_s))
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def _cut(self, turn: int, raw: Path, start_s: float) -> None:
        out = self.dir / f"turn-{turn}.mp4"
        try:
            async with self._slots:
                await self._safe_send({"type": "cutout_started", "turn": turn})
                report = await cut_out_guest(
                    self.client, raw, out, workdir=self.dir, start_s=start_s
                )
        except Exception as e:
            await self._safe_send({"type": "error", "message": f"cutout, turn {turn}: {e}"})
            return
        finally:
            raw.unlink(missing_ok=True)
        self.clips[turn] = out
        await self._safe_send(
            {
                "type": "cutout",
                "turn": turn,
                "file": out.name,
                "guest_frames": report.guest_frames,
                "frames": report.frames,
                "seconds": round(report.upload_s + report.sam_s + report.composite_s, 1),
            }
        )

    async def build_segment(self) -> str:
        if not self.clips:
            raise ValueError("no cut-out answers yet")
        out = self.dir / "segment.mp4"
        await join_clips([self.clips[t] for t in sorted(self.clips)], out)
        return out.name

    async def _safe_send(self, msg: dict) -> None:
        with contextlib.suppress(Exception):  # the page has gone; clips are kept until cleanup
            await self.send(msg)

    @property
    def busy(self) -> int:
        return len(self._jobs)

    async def drain(self, timeout: float = 600) -> None:
        """Let answers already uploaded finish: the last answer matters as much as the first."""
        if self._jobs:
            await asyncio.wait(list(self._jobs), timeout=timeout)

    def close(self) -> None:
        """Interview over: stop what is left, and delete everything after a grace period."""
        for task in list(self._jobs):
            task.cancel()
        for raw in self.dir.glob("raw-*.webm"):
            raw.unlink(missing_ok=True)
        loop = asyncio.get_running_loop()
        loop.call_later(KEEP_AFTER_END_S, self.discard)

    def discard(self) -> None:
        ROOMS.pop(self.key, None)
        shutil.rmtree(self.dir, ignore_errors=True)
