"""Packaging the segment: question cards, lower thirds, one MP4.

Each answer is preceded by the AI anchor asking the question in the IoMarkets TV studio, with
the question in a strap. The anchor is lip-synced by the studio's MuseTalk server
(`lipsync/server.py`, `STUDIO_LIPSYNC_URL`, default http://127.0.0.1:8766), which moves her
whole loop as she talks; without it she is shown still.
Each answer carries a lower third with the guest's name and role for its first seconds.
Everything is joined with ffmpeg's concat filter, which scales, resamples and re-times every
part, so cards and answers from any camera join cleanly.

Text reaches drawtext through files (`textfile=`, `expansion=none`), never through the filter
string, so a guest's name or a question cannot break or inject into the filter graph.
"""

from __future__ import annotations

import asyncio
import json
import os
import textwrap
from pathlib import Path

import httpx

from studio import ledger
from studio.cutout import BACKDROP, FPS, STUDIO_BACKGROUND, _run

LABEL = "IoMarkets.tv  |  AI anchor"
AI_NOTE = "AI-generated anchor: synthetic image and voice"
ANCHOR_NAME = "Alexandra Morgan  |  AI anchor"
ASSETS = Path(__file__).parent / "assets"
STUDIO = ASSETS / "studio.jpg"  # pre-existing, built by scripts/anchor_assets.py
ANCHOR_STUDIO = ASSETS / "anchor-studio.png"  # her still in the wide shot, without lip-sync
LIPSYNC_TIMEOUT_S = 300
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


def lipsync_url() -> str:
    return os.environ.get("STUDIO_LIPSYNC_URL", "http://127.0.0.1:8766").rstrip("/")


# On Modal (STUDIO_LIPSYNC=modal) the lip-sync is the private class Lipsync in deploy/modal_app.py,
# called directly: it has no URL, so nothing else can start the GPU.
APP, LIPSYNC_CLS, STATE = "iomarkets-live-studio", "Lipsync", "iomarkets-lipsync-state"


def _on_modal() -> bool:
    return os.environ.get("STUDIO_LIPSYNC") == "modal"


async def lipsync_wake() -> None:
    """Start the GPU ahead of an interview (Modal only; a no-op call, then it idles 5 min)."""
    if _on_modal() and ledger.gpu_allowed():
        import modal

        await modal.Cls.from_name(APP, LIPSYNC_CLS)().ping.spawn.aio()


async def lipsync_up() -> bool:
    """Whether lip-sync is ready now. On Modal this reads a flag and never starts the GPU, and
    once today's GPU cap is spent the answer is no: the anchor is shown still."""
    if _on_modal():
        import modal

        if not ledger.gpu_allowed():
            return False
        try:
            state = modal.Dict.from_name(STATE, create_if_missing=True)
            return bool(await state.get.aio("up", False))
        except Exception:
            return False
    if not lipsync_url():
        return False
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            return (await client.get(f"{lipsync_url()}/health")).status_code == 200
    except httpx.HTTPError:
        return False


async def lipsync(mp3: Path, out: Path, shot: str = "wide", start: int | None = None) -> int | None:
    """The anchor saying `mp3` in `shot` (live: 4:3, wide: 16:9), picture and sound, written to
    `out`. Returns where her loop ended (the next clip's `start`), or None if there is no
    lip-sync server or it fails. `start` sets where her loop begins (0: her still); by default
    it carries on from the server's last clip."""
    if _on_modal():
        import modal

        if not ledger.gpu_allowed():
            return None
        t = asyncio.get_running_loop().time()
        try:
            speaker = modal.Cls.from_name(APP, LIPSYNC_CLS)()
            data, cursor = await asyncio.wait_for(
                speaker.speak.remote.aio(mp3.read_bytes(), shot, start), LIPSYNC_TIMEOUT_S
            )
        except Exception:
            return None
        finally:
            ledger.charge("gpu", ledger.gpu_seconds(asyncio.get_running_loop().time() - t))
        out.write_bytes(data)
        return cursor
    url = lipsync_url()
    if not url:
        return None
    files = {"audio": (mp3.name, mp3.read_bytes(), "audio/mpeg")}
    # On Modal the lip-sync server is public and checks the studio's own token.
    headers = {"X-Studio-Token": t} if (t := os.environ.get("STUDIO_TOKEN")) else {}
    try:
        timeout = httpx.Timeout(LIPSYNC_TIMEOUT_S, connect=2)
        async with httpx.AsyncClient(timeout=timeout) as client:
            data = {"shot": shot} | ({} if start is None else {"start": str(start)})
            r = await client.post(f"{url}/speak", files=files, data=data, headers=headers)
            r.raise_for_status()
    except httpx.HTTPError:
        return None
    out.write_bytes(r.content)
    return int(r.headers.get("x-cursor", 0))


def _studio_input() -> list[str]:
    still = STUDIO if STUDIO.exists() else BACKDROP
    return ["-loop", "1", "-framerate", str(FPS), "-i", str(still)]


async def question_card(
    question: str, mp3: Path | None, out: Path, width: int, height: int, workdir: Path
) -> None:
    """The AI anchor asking `question` in the studio, with the question in a strap."""
    duration = (await media_info(mp3))[2] + 0.6 if mp3 else SILENT_CARD_SECONDS
    fit = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    synced = workdir / f"{out.stem}.lipsync.mp4"
    if mp3 and await lipsync(mp3, synced) is not None:
        inputs = ["-i", str(synced)]
        picture = f"[0:v]{fit},setsar=1,fps={FPS}[p]"
    elif ANCHOR_STUDIO.exists():  # no lip-sync: the anchor still, not a mouth out of time
        inputs = ["-loop", "1", "-framerate", str(FPS), "-i", str(ANCHOR_STUDIO)]
        picture = f"[0:v]{fit},setsar=1[p]"
    elif STUDIO.exists() or BACKDROP.exists():
        inputs = _studio_input()
        picture = f"[0:v]{fit},setsar=1[p]"
    else:
        inputs = ["-f", "lavfi", "-i", f"color=c={STUDIO_BACKGROUND}:s={width}x{height}:r={FPS}"]
        picture = "[0:v]null[p]"
    audio_at = inputs.count("-i")  # the audio input follows the picture inputs
    audio = (
        ["-i", str(mp3)]
        if mp3
        else ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration}"]
    )
    # The question strap across the bottom, one drawtext per line: this ffmpeg draws a newline
    # in a textfile as a missing glyph.
    lines = textwrap.wrap(question, width=58)[:3]
    size = height // 26
    step = size * 4 // 3
    top = int(height * 0.94) - step * len(lines)
    left = width // 16
    box_y = top - step // 2 - height // 24
    box_h = int(height * 0.97) - box_y
    name = _text(workdir / f"{out.stem}.name.txt", ANCHOR_NAME)
    label = _text(workdir / f"{out.stem}.label.txt", LABEL)
    note = _text(workdir / f"{out.stem}.note.txt", AI_NOTE)
    drawn = [
        f"drawbox=x={left - width // 60}:y={box_y}:w={width - 2 * left + width // 30}:h={box_h}:"
        "color=0x05080d@0.82:t=fill",
        f"drawbox=x={left - width // 60}:y={box_y}:w=6:h={box_h}:color=0xffa028:t=fill",
        f"drawtext=font='{FONT}':textfile='{name}':expansion=none:fontcolor=0xffb547:"
        f"fontsize={height // 36}:x={left}:y={box_y + height // 70}",
    ]
    for i, line in enumerate(lines):
        path = _text(workdir / f"{out.stem}.q{i}.txt", line)
        drawn.append(
            f"drawtext=font='{FONT}':textfile='{path}':expansion=none:fontcolor=white:"
            f"fontsize={size}:x={left}:y={top + i * step}"
        )
    drawn += [
        f"drawtext=font='{FONT}':textfile='{label}':expansion=none:fontcolor=white:"
        f"fontsize={height // 30}:x={width // 20}:y={height // 16}:box=1:boxcolor=0x05080d@0.7:"
        "boxborderw=8",
        f"drawtext=font='{FONT}':textfile='{note}':expansion=none:fontcolor=0xd0d8e0:"
        f"fontsize={height // 44}:x={width // 20}:y={height // 16 + height // 18}:box=1:"
        "boxcolor=0x05080d@0.7:boxborderw=6",
    ]
    graph = f"{picture};[p]{','.join(drawn)},format=yuv420p[v]"
    await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, *audio,
        "-filter_complex", graph, "-map", "[v]", "-map", f"{audio_at}:a", "-r", str(FPS),
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


async def text_card(
    lines: list[tuple[str, int, str]],
    out: Path,
    workdir: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    seconds: float = 5.0,
) -> None:
    """A silent card of centred lines, each (text, size as a fraction 1/n of height, colour).

    Used for the demo video's title, how-it-works and end cards (scripts/video_cards.py).
    """
    sizes = [height // n for _, n, _ in lines]
    gap = height // 60
    total = sum(sizes) + gap * (len(lines) - 1)
    y = (height - total) // 2
    drawn = []
    for i, ((text, _, colour), size) in enumerate(zip(lines, sizes, strict=True)):
        if text:
            path = _text(workdir / f"{out.stem}.l{i}.txt", text)
            drawn.append(
                f"drawtext=font='{FONT}':textfile='{path}':expansion=none:fontcolor={colour}:"
                f"fontsize={size}:x=(w-text_w)/2:y={y}"
            )
        y += size + gap
    await _run(
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={STUDIO_BACKGROUND}:s={width}x{height}:r={FPS}:d={seconds}",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}",
        "-vf", ",".join(drawn) or "null", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-t", f"{seconds:.2f}", str(out),
    )  # fmt: skip
