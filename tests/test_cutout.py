from __future__ import annotations

import json
import shutil
import subprocess

import httpx
import numpy as np
import pytest
from conftest import FIXTURES
from meta_sam_parser import (
    CompletedOutcome,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    video_segmentation_format,
)

from studio.cutout import (
    MAX_HOLD,
    ClipInfo,
    Placed,
    Segmentation,
    _resize_nearest,
    composite,
    mattes,
    normalise,
    parse_segmentation,
    segment,
    split_masks,
)
from studio.meta.responses import MetaAPIError, ResponsesClient

# The first five frames SAM 3.1 returned for a 1280x720 clip of one person (2026-10-27).
SAM_TEXT = (FIXTURES / "sam_person_5frames_2026-10-27.txt").read_text()
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def test_parses_recorded_sam_output():
    seg = parse_segmentation(SAM_TEXT, 1280, 720)
    assert sorted(seg.frames) == [0, 1, 2, 3, 4]
    assert seg.guest_id() == "0"
    first = seg.frames[0]["0"]
    assert (first.left, first.top) == (435, 193)
    assert first.raster.shape == (519, 414)  # the half-open bounds match the raster exactly
    assert set(np.unique(first.raster)) <= {0, 1}
    assert 0.3 < first.raster.mean() < 0.9  # a person fills much of their own box


def test_split_matches_meta_parser():
    """Our single-decode split must agree with Meta's own parser, mask for mask."""
    parser = video_segmentation_format().create_parser()
    parser.push(SAM_TEXT, emit=False)
    records = [
        r
        for r in parser.finish(CompletedOutcome()).result.records
        if isinstance(r, SegmentationMaskRecord)
    ]
    ours = parse_segmentation(SAM_TEXT, 1280, 720)
    assert len(records) == len(split_masks(SAM_TEXT)) == 5
    for rec in records:
        placed = ours.frames[rec.frame.frame_index][rec.object_id]
        b = rec.bounds
        assert (placed.left, placed.top) == (b.left, b.top)
        assert placed.raster.shape == (b.bottom - b.top, b.right - b.left)
        theirs = np.frombuffer(decode_mask_to_raster(rec.mask), dtype=np.uint8)
        assert np.array_equal(placed.raster.ravel(), theirs)


def test_malformed_records_are_skipped():
    text = "<0f>1<|box;x1=0;y1=0|><|mask;x=0;y=0;data=2,2,!abc|>\nnot a frame\n<1f>"
    assert split_masks(text) == []


def test_matte_places_mask_in_frame():
    seg = parse_segmentation(SAM_TEXT, 1280, 720)
    matte = np.frombuffer(next(mattes(seg, 1, "0")), dtype=np.uint8).reshape(720, 1280)
    assert matte[:193].max() == 0 and matte[:, :435].max() == 0  # nothing outside the box
    assert matte[193:711, 435:848].max() == 255


def _seg(frames: dict[int, dict[str, Placed]]) -> Segmentation:
    return Segmentation(8, 6, frames)


def _one(left=0, top=0, h=2, w=2) -> Placed:
    return Placed(np.ones((h, w), dtype=np.uint8), left, top)


def _sums(seg: Segmentation, n: int, oid="0") -> list[int]:
    return [sum(m) // 255 for m in mattes(seg, n, oid)]


def test_skipped_frames_hold_then_clear():
    seg = _seg({0: {"0": _one()}})
    assert _sums(seg, MAX_HOLD + 3) == [4] * (MAX_HOLD + 1) + [0, 0]


def test_frame_with_other_objects_only_is_empty():
    seg = _seg({0: {"0": _one()}, 1: {"7": _one()}})
    assert _sums(seg, 2) == [4, 0]


def test_mask_overhanging_the_frame_is_clipped():
    seg = _seg({0: {"0": _one(left=6, top=-1, h=3, w=4)}})
    matte = np.frombuffer(next(mattes(seg, 1, "0")), dtype=np.uint8).reshape(6, 8)
    assert matte.sum() // 255 == 4  # 2 rows x 2 columns survive
    assert matte[0:2, 6:8].min() == 255


def test_guest_is_the_largest_object():
    seg = _seg({0: {"1": _one(h=1, w=1), "2": _one(h=3, w=3)}, 1: {"1": _one(h=2, w=2)}})
    assert seg.guest_id() == "2"
    assert _seg({}).guest_id() is None


def test_resize_nearest():
    a = np.array([[1, 0], [0, 1]], dtype=np.uint8)
    assert _resize_nearest(a, 4, 4).tolist() == [
        [1, 1, 0, 0],
        [1, 1, 0, 0],
        [0, 0, 1, 1],
        [0, 0, 1, 1],
    ]


def _sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class FakeMeta:
    """Files API plus a streamed SAM response that splits lines across deltas."""

    def __init__(self, sam_status: int = 200, fail_midway: bool = False):
        self.sam_status = sam_status
        self.fail_midway = fail_midway
        self.calls: list[str] = []
        self.sam_body: dict | None = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(f"{req.method} {req.url.path}")
        if req.url.path == "/v1/files":
            assert b'name="expires_after[seconds]"' in req.content
            return httpx.Response(200, json={"id": "file-1", "status": "uploaded"})
        if req.url.path == "/v1/responses":
            self.sam_body = json.loads(req.content)
            if self.sam_status != 200:
                return httpx.Response(self.sam_status, json={"error": {"message": "nope"}})
            deltas = [SAM_TEXT[i : i + 300] for i in range(0, len(SAM_TEXT), 300)]
            events = [{"type": "response.output_text.delta", "delta": d} for d in deltas]
            if self.fail_midway:
                events = events[:2] + [
                    {"type": "response.failed", "response": {"error": {"message": "boom"}}}
                ]
            else:
                events.append({"type": "response.completed", "response": {"id": "r"}})
            return httpx.Response(
                200, content=_sse(*events), headers={"content-type": "text/event-stream"}
            )
        if req.method == "DELETE":
            return httpx.Response(200, json={"id": "file-1", "deleted": True})
        raise AssertionError(req.url)


INFO = ClipInfo(1280, 720, 5)


async def test_segment_streams_decodes_and_deletes(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"not really a video")
    fake = FakeMeta()
    async with ResponsesClient(api_key="k", transport=httpx.MockTransport(fake)) as client:
        seg, _, _ = await segment(client, clip, INFO, workers=2, lines_per_task=2)
    assert sorted(seg.frames) == [0, 1, 2, 3, 4]
    expected = parse_segmentation(SAM_TEXT, 1280, 720)
    for f in seg.frames:
        assert np.array_equal(seg.frames[f]["0"].raster, expected.frames[f]["0"].raster)
    assert fake.calls == ["POST /v1/files", "POST /v1/responses", "DELETE /v1/files/file-1"]
    assert fake.sam_body["stream"] is True
    assert fake.sam_body["input"][0]["content"] == [
        {"type": "input_text", "text": "person"},
        {"type": "input_video", "file_id": "file-1"},
    ]
    assert fake.sam_body["metadata"] == {"mask_encoding": "one_bit"}
    assert "reasoning" not in fake.sam_body


@pytest.mark.parametrize("fake", [FakeMeta(sam_status=400), FakeMeta(fail_midway=True)])
async def test_upload_is_deleted_even_when_sam_fails(tmp_path, fake):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    async with ResponsesClient(api_key="k", transport=httpx.MockTransport(fake)) as client:
        with pytest.raises(MetaAPIError):
            await segment(client, clip, INFO, workers=1)
    assert fake.calls[-1] == "DELETE /v1/files/file-1"


@needs_ffmpeg
async def test_normalise_webm_and_composite(tmp_path):
    src = tmp_path / "guest.webm"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1",
         "-c:v", "libvpx-vp9", "-b:v", "200k", str(src)],
        check=True,
    )  # fmt: skip
    clip = tmp_path / "n.mp4"
    info = await normalise(src, clip)
    assert info == ClipInfo(320, 240, 25)
    seg = Segmentation(320, 240, {i: {"0": _one(10, 10, 100, 80)} for i in range(25)})
    out = tmp_path / "out.mp4"
    assert await composite(clip, seg, info, out) == 25
    frame = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(out), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    img = np.frombuffer(frame, dtype=np.uint8).reshape(240, 320, 3)
    background = img[200, 300]  # outside the mask: the plain studio colour 0x0d1b2a
    assert abs(int(background[0]) - 0x0D) < 8 and abs(int(background[2]) - 0x2A) < 8
    assert not np.array_equal(img[50, 50], background)  # inside the mask: the guest
