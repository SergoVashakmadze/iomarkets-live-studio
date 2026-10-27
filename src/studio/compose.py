"""Packaging the segment: question cards, lower thirds, one MP4.

The anchor has no picture in this entry, so each answer is preceded by a card: the question on
the studio background, labelled as the AI anchor, with the anchor's voice. Each answer carries a
lower third with the guest's name and role for its first seconds. Everything is joined with
ffmpeg's concat filter, which scales, resamples and re-times every part, so cards and answers
from any camera join cleanly.

Text reaches drawtext through files (`textfile=`, `expansion=none`), never through the filter
string, so a guest's name or a question cannot break or inject into the filter graph.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from studio.cutout import FPS, STUDIO_BACKGROUND, _run

LABEL = "IoMarkets.tv  |  AI anchor"
CAPTION_SECONDS = 6
SILENT_CARD_SECONDS = 3.5
FONT = "DejaVu Sans"


async def media_info(path: Path) -> tuple[int, int, float, bool]:
    """(width, height, duration s, has audio)."""
    out = await _run(
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
        "-show_entries", "format=duration", "-of", "json", str(path),
    )  # fmt: skip
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return (
        int(video.get("width", 0)),
        int(video.get("height", 0)),
        float(data.get("format", {}).get("duration", 0) or 0),
        has_audio,
    )


def _text(path: Path, text: str) -> str:
    """Write `text` for drawtext and return the path to quote in the filter."""
    if any(c in str(path) for c in "':\\"):
        raise ValueError(f"work path not safe inside a filter: {path}")
    path.write_text(text)
    return str(path)


async def question_card(
    question: str, mp3: Path | None, out: Path, width: int, height: int, workdir: Path
) -> None:
    duration = (await media_info(mp3))[2] + 0.6 if mp3 else SILENT_CARD_SECONDS
    # One drawtext per line: this ffmpeg draws a newline in a textfile as a missing glyph.
    lines = textwrap.wrap(question, width=36)[:6]
    label = _text(workdir / f"{out.stem}.label.txt", LABEL)
    audio = (
        ["-i", str(mp3)]
        if mp3
        else ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration}"]
    )
    size = height // 18
    step = size * 4 // 3
    top = (height - step * len(lines)) // 2
    drawn = []
    for i, line in enumerate(lines):
        path = _text(workdir / f"{out.stem}.q{i}.txt", line)
        drawn.append(
            f"drawtext=font='{FONT}':textfile='{path}':expansion=none:fontcolor=white:"
            f"fontsize={size}:x=(w-text_w)/2:y={top + i * step}"
        )
    drawn.append(
        f"drawtext=font='{FONT}':textfile='{label}':expansion=none:fontcolor=0x9fb3c8:"
        f"fontsize={height // 32}:x={width // 20}:y={height // 14}"
    )
    graph = ",".join(drawn)
    await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={STUDIO_BACKGROUND}:s={width}x{height}:r={FPS}:d={duration}",
        *audio, "-vf", graph, "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", f"{duration:.2f}", str(out),
    )  # fmt: skip


async def captioned_answer(clip: Path, out: Path, name: str, role: str, workdir: Path) -> None:
    width, height, duration, has_audio = await media_info(clip)
    on = f"enable='between(t,0,{CAPTION_SECONDS})'"
    filters = [
        f"drawbox=x=0:y=ih*0.76:w=iw:h=ih*0.15:color=black@0.55:t=fill:{on}",
    ]
    if name:
        n = _text(workdir / f"{out.stem}.name.txt", name)
        filters.append(
            f"drawtext=font='{FONT}':textfile='{n}':expansion=none:fontcolor=white:"
            f"fontsize={height // 20}:x={width // 20}:y=h*0.785:{on}"
        )
    if role:
        r = _text(workdir / f"{out.stem}.role.txt", role)
        filters.append(
            f"drawtext=font='{FONT}':textfile='{r}':expansion=none:fontcolor=0xd0d8e0:"
            f"fontsize={height // 32}:x={width // 20}:y=h*0.855:{on}"
        )
    inputs, amap = ["-i", str(clip)], "0:a"
    if not has_audio:  # concat needs an audio track in every part
        inputs += ["-f", "lavfi", "-t", f"{duration:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        amap = "1:a"
    await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
        "-vf", ",".join(filters), "-map", "0:v", "-map", amap,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(out),
    )  # fmt: skip


async def join(parts: list[Path], out: Path, width: int, height: int) -> None:
    """Concatenate parts of any size and audio layout into one MP4 at width x height."""
    inputs, graph = [], []
    for i, part in enumerate(parts):
        inputs += ["-i", str(part)]
        graph.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS}[v{i}];"
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]"
        )
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(parts)))
    graph.append(f"{pairs}concat=n={len(parts)}:v=1:a=1[v][a]")
    await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
        "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out),
    )  # fmt: skip
