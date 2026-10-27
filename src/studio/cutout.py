"""Guest cutout: SAM 3.1 finds the guest in their answer clip; ffmpeg puts them in the studio.

1. ffmpeg normalises the clip: SAM takes MP4/MOV with H.264 only (a browser records WebM), and
   25 fps at no more than 720p keeps the frame count, which is what SAM bills, down.
2. The clip goes to the Files API with a one-hour expiry and is deleted as soon as SAM has
   answered: guest video is kept no longer than the work needs.
3. SAM 3.1 segments "person" across the clip. Each output line is one frame; each mask is
   box-local (its raster covers the object's box, not the frame) and decoded with Meta's
   `meta-sam-parser`. Its full parser decodes every mask once to validate it and again to
   rasterise it, in pure Python: ~0.76 s a frame, 227 s for a 12 s clip. So lines are split
   here, to the grammar that parser documents, and each mask is decoded once with its
   `decode_mask_to_raster`, across a process pool, while SAM is still streaming.
4. The guest is the object with the most mask area across the clip. Their masks are pasted into
   full-frame mattes, a frame SAM skipped reuses the last matte, and ffmpeg feathers the matte
   and lays the guest over the studio background.

Measured 2026-10-27, 720p, 12 s WebM clip (300 frames, $0.06): normalise <1 s, upload 2.7 s,
SAM streamed and decoded alongside 21.1 s, composite 0.8 s; 25 s in all, against 251 s with
Meta's full parser in one process. SAM runs at about 1.6x real time, so a cut-out answer is
ready about twice its own length after the guest stops: not live picture, but in time to build
the segment while the interview carries on.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from meta_sam_parser import SegmentationMask, decode_mask_to_raster

from studio.meta.responses import ResponsesClient

SAM_MODEL = "sam-3.1"
FPS = 25
MAX_HEIGHT = 720
COST_PER_FRAME = 0.20 / 1000  # Standard mode, 50-frame minimum per request
STUDIO_BACKGROUND = "0x0d1b2a"
MAX_HOLD = 3  # frames a missing mask is held for


@dataclass(frozen=True)
class ClipInfo:
    width: int
    height: int
    frames: int


@dataclass
class Placed:
    """One decoded mask and where it sits in the frame."""

    raster: np.ndarray  # (h, w) uint8, 0 or 1
    left: int
    top: int


@dataclass
class Segmentation:
    width: int
    height: int
    frames: dict[int, dict[str, Placed]] = field(default_factory=dict)

    def guest_id(self) -> str | None:
        area: dict[str, int] = defaultdict(int)
        for objects in self.frames.values():
            for oid, placed in objects.items():
                area[oid] += int(placed.raster.sum())
        return max(area, key=area.__getitem__) if area else None


@dataclass
class CutoutReport:
    frames: int
    guest_frames: int
    upload_s: float
    sam_s: float
    composite_s: float

    @property
    def cost_usd(self) -> float:
        return max(self.frames, 50) * COST_PER_FRAME


# The record grammar documented in meta_sam_parser/_segmentation.py: a frame header ``<Nf>``,
# then records of an object id and ``<|name;fields|>`` tokens in any order. Payloads never
# contain ``|`` or ``;``.
_HEADER = re.compile(r"<([0-9]+)f(?:;[^>]*)?>")
_RECORD = re.compile(r",?([0-9]+)((?:<\|[A-Za-z][A-Za-z0-9_.-]*(?:;[^|]*)?\|>)+)")
_TOKEN = re.compile(r"<\|([A-Za-z][A-Za-z0-9_.-]*)(?:;([^|]*))?\|>")
_MASK_DATA = re.compile(r"([0-9]+),([0-9]+),([!~])([^|]+)")

# (frame, object id, left, top, box height, box width, mask height, mask width, encoding, payload)
RawMask = tuple[int, str, int, int, int, int, int, int, str, str]
Decoded = tuple[int, str, int, int, int, int, bytes]


def _fields(body: str | None) -> dict[str, str]:
    out = {}
    for part in (body or "").split(";"):
        key, _, value = part.strip().partition("=")
        out.setdefault(key.strip(), value.strip())
    return out


def split_masks(text: str) -> list[RawMask]:
    """Every well-formed (frame, object) mask in SAM's output, still encoded."""
    masks = []
    for line in text.splitlines():
        header = _HEADER.match(line)
        if not header:
            continue
        frame = int(header.group(1))
        for rec in _RECORD.finditer(line, header.end()):
            tokens = {name: _fields(body) for name, body in _TOKEN.findall(rec.group(2))}
            box, mask = tokens.get("box"), tokens.get("mask")
            data = _MASK_DATA.fullmatch(mask.get("data", "")) if mask else None
            if not box or not data:
                continue
            try:
                x1, y1, x2, y2 = (int(box[k]) for k in ("x1", "y1", "x2", "y2"))
            except (KeyError, ValueError):
                continue
            encoding = "one_bit" if data.group(3) == "!" else "lossless"
            masks.append(
                (frame, rec.group(1), x1, y1, y2 - y1 + 1, x2 - x1 + 1,
                 int(data.group(1)), int(data.group(2)), encoding,
                 data.group(3) + data.group(4))  # the parser keeps the marker in the payload
            )  # fmt: skip
    return masks


def _decode(chunk: list[RawMask]) -> list[Decoded]:
    """Runs in a worker process: decode each mask to a box-sized 0/1 raster."""
    out = []
    for frame, oid, left, top, box_h, box_w, h, w, encoding, payload in chunk:
        raw = decode_mask_to_raster(SegmentationMask(encoding, payload, w, h))
        raster = _resize_nearest(np.frombuffer(raw, dtype=np.uint8).reshape(h, w), box_h, box_w)
        out.append((frame, oid, left, top, box_h, box_w, raster.tobytes()))
    return out


def _assemble(decoded: list[Decoded], width: int, height: int) -> Segmentation:
    seg = Segmentation(width, height)
    for frame, oid, left, top, h, w, raster in decoded:
        arr = np.frombuffer(raster, dtype=np.uint8).reshape(h, w)
        seg.frames.setdefault(frame, {})[oid] = Placed(arr, left, top)
    return seg


def parse_segmentation(text: str, width: int, height: int) -> Segmentation:
    """Decode a complete output in this process. `segment()` decodes in parallel as it streams."""
    return _assemble(_decode(split_masks(text)), width, height)


def _resize_nearest(a: np.ndarray, h: int, w: int) -> np.ndarray:
    if a.shape == (h, w):
        return a
    rows = (np.arange(h) * a.shape[0] // h).clip(0, a.shape[0] - 1)
    cols = (np.arange(w) * a.shape[1] // w).clip(0, a.shape[1] - 1)
    return a[rows[:, None], cols]


def mattes(seg: Segmentation, frames: int, oid: str | None) -> Iterator[bytes]:
    """One full-frame 8-bit matte per frame (255 = guest).

    SAM writes no line for a frame with nothing in it, and may also skip frames. So a missing
    frame holds the last matte for up to MAX_HOLD frames (a skip), then goes empty (the guest
    has left the shot).
    """
    empty = np.zeros((seg.height, seg.width), dtype=np.uint8)
    last, missing = empty, 0
    for i in range(frames):
        placed = seg.frames.get(i, {}).get(oid) if oid is not None else None
        if placed is None:
            missing += 1
            if i in seg.frames or missing > MAX_HOLD:
                last = empty
            yield last.tobytes()
            continue
        missing = 0
        last = np.zeros_like(empty)
        if placed is not None:
            r = placed.raster
            top, left = max(placed.top, 0), max(placed.left, 0)
            bottom = min(placed.top + r.shape[0], seg.height)
            right = min(placed.left + r.shape[1], seg.width)
            if bottom > top and right > left:
                last[top:bottom, left:right] = (
                    r[
                        top - placed.top : bottom - placed.top,
                        left - placed.left : right - placed.left,
                    ]
                    * 255
                )
        yield last.tobytes()


async def _run(*cmd: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {err.decode()[-500:]}")
    return out


async def normalise(src: str | Path, dst: str | Path) -> ClipInfo:
    """Any clip (WebM included) to H.264 MP4, 25 fps, at most 720p, with +faststart."""
    await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-vf", f"fps={FPS},scale=-2:'min({MAX_HEIGHT},ih)'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst),
    )  # fmt: skip
    return await probe(dst)


async def probe(path: str | Path) -> ClipInfo:
    out = await _run(
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
        "-show_entries", "stream=width,height,nb_read_packets", "-of", "json", str(path),
    )  # fmt: skip
    s = json.loads(out)["streams"][0]
    return ClipInfo(int(s["width"]), int(s["height"]), int(s["nb_read_packets"]))


def _sam_body(file_id: str, prompt: str) -> dict:
    return {
        "model": SAM_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_video", "file_id": file_id},
                ],
            }
        ],
        "metadata": {"mask_encoding": "one_bit"},
    }


async def segment(
    client: ResponsesClient,
    clip: str | Path,
    info: ClipInfo,
    prompt: str = "person",
    *,
    workers: int | None = None,
    lines_per_task: int = 4,
) -> tuple[Segmentation, float, float]:
    """Upload, stream SAM 3.1, and decode frames while SAM is still producing them.

    Returns (segmentation, upload s, SAM-plus-decode s). The upload is deleted whatever happens.
    """
    t0 = time.monotonic()
    file_id = await client.upload_file(str(clip))
    t1 = time.monotonic()
    loop = asyncio.get_running_loop()
    workers = workers or os.cpu_count() or 1
    tasks: list[asyncio.Future] = []
    buffer, pending = "", []
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:

            def submit(lines: list[str]) -> None:
                masks = split_masks("\n".join(lines))
                if masks:
                    tasks.append(loop.run_in_executor(pool, _decode, masks))

            async for delta in client.stream_text(_sam_body(file_id, prompt), timeout=900):
                buffer += delta
                *done, buffer = buffer.split("\n")
                pending += done
                if len(pending) >= lines_per_task:
                    submit(pending)
                    pending = []
            submit([*pending, buffer])
            parts = await asyncio.gather(*tasks)
    finally:
        await client.delete_file(file_id)
    seg = _assemble([d for part in parts for d in part], info.width, info.height)
    return seg, t1 - t0, time.monotonic() - t1


async def composite(
    clip: str | Path,
    seg: Segmentation,
    info: ClipInfo,
    out: str | Path,
    background: str | Path | None = None,
) -> int:
    """Lay the guest over the background; returns how many frames had the guest in them."""
    oid = seg.guest_id()
    w, h = info.width, info.height
    bg = (
        ["-loop", "1", "-i", str(background)]
        if background
        else ["-f", "lavfi", "-i", f"color=c={STUDIO_BACKGROUND}:s={w}x{h}:r={FPS}"]
    )
    graph = (
        "[1:v]erosion,gblur=sigma=1.5[m];[0:v][m]alphamerge[fg];"  # shrink 1 px: no fringe
        f"[2:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[bg];"
        "[bg][fg]overlay=shortest=1:format=auto,format=yuv420p[v]"
    )
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(clip),
        "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "pipe:0",
        *bg,
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "copy",
        "-movflags", "+faststart", str(out),
        stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    assert proc.stdin is not None
    guest_frames = 0
    try:
        for i, matte in enumerate(mattes(seg, info.frames, oid)):
            guest_frames += oid is not None and oid in seg.frames.get(i, {})
            proc.stdin.write(matte)
            await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    proc.stdin.close()
    err = await proc.stderr.read() if proc.stderr else b""
    if await proc.wait():
        raise RuntimeError(f"ffmpeg composite failed: {err.decode()[-500:]}")
    return guest_frames


async def cut_out_guest(
    client: ResponsesClient,
    src: str | Path,
    out: str | Path,
    *,
    workdir: str | Path,
    background: str | Path | None = None,
) -> CutoutReport:
    clip = Path(workdir) / "normalised.mp4"
    info = await normalise(src, clip)
    try:
        seg, upload_s, sam_s = await segment(client, clip, info)
        t = time.monotonic()
        guest_frames = await composite(clip, seg, info, out, background)
        return CutoutReport(info.frames, guest_frames, upload_s, sam_s, time.monotonic() - t)
    finally:
        clip.unlink(missing_ok=True)
