"""Assemble the 3-minute demo video from one take's files and the cards.

    uv run python scripts/video_cards.py
    uv run python scripts/assemble_video.py TAKE_DIR

TAKE_DIR holds what the page gave the tester after the interview: `programme.webm` (the
programme as it went out live), `segment.mp4` (Build segment) and `interview.srt`. The excerpts
below are from Alex Kandelaki's take of 2 Nov 2026. Each is a continuous stretch of the live
programme, never spliced inside, so nothing looks faster than it was. Captions are burned in
(many judges watch muted) and each shot carries a label naming the Meta model at work.

If video/voiceover/ holds a WAV per card (scripts/voiceover.py), each card is held on its last
frame for as long as its line, which is spoken over it; the interview keeps its own sound.

Writes video/iomarkets-live-studio-demo.mp4 (1920x1080, 30 fps, H.264, AAC).
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "video" / "cards"
OUT = ROOT / "video" / "iomarkets-live-studio-demo.mp4"
VOICEOVER = ROOT / "video" / "voiceover"
VO_LEAD, VO_TAIL = 0.4, 0.6  # seconds of quiet card before and after the line
FONT = "DejaVu Sans"

# (source, start s, end s, label). Times are in the take's programme / segment.
SHOTS = [
    ("card", "01-title", None, None),
    ("card", "02-problem", None, None),
    (
        "programme",
        13.5,
        26.0,
        "Live. Muse Spark writes her lines, Meta FastSpeech 2 voices them, MuseTalk lip-syncs",
    ),
    ("programme", 28.0, 39.0, "Muse Voice Transcribe hears the guest as he speaks"),
    (
        "programme",
        78.0,
        101.0,
        "She reacts as he finishes, while Muse Spark writes a follow-up on what he said",
    ),
    ("programme", 213.0, 241.8, "Each follow-up builds on his last answer"),
    (
        "programme",
        350.0,
        376.4,
        "Figures from Muse Spark's web research, raised live in the conversation",
    ),
    (
        "segment",
        0.0,
        22.0,
        "After the call: SAM 3.1 cut him into the studio, in one click",
    ),
    ("card", "03-how", None, None),
    ("card", "04-new-work", None, None),
    ("card", "05-end", None, None),
]

ENCODE = [
    "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
]  # fmt: skip


def ts(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    def sec(s: str) -> float:
        h, m, rest = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))

    cues = []
    for block in re.split(r"\n\s*\n", path.read_text().strip()):
        lines = block.strip().splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            a, b = (sec(x.strip()) for x in lines[1].split("-->"))
            cues.append((a, b, " ".join(lines[2:])))
    return cues


def chunked(cues, words: int = 11):
    """Long cues (a guest answer is one 60 s cue) split into short ones, timed by word count.
    The page gives each anchor line a fixed 6 s; she speaks about 3 words a second, so her cue
    lasts that long instead (a 33-word question ran 11 s), up to the next cue."""
    out = []
    for k, (a, b, text) in enumerate(cues):
        who, _, said = text.partition(": ")
        ws = said.split()
        if who.startswith("ANCHOR"):
            b = a + max(1.2, len(ws) / 3.0)
            if k + 1 < len(cues):
                b = min(b, cues[k + 1][0] - 0.1)
        n = max(1, -(-len(ws) // words))
        step = (b - a) / n
        for i in range(n):
            part = " ".join(ws[i * words : (i + 1) * words])
            out.append((a + i * step, a + (i + 1) * step, f"{who}: {part}" if i == 0 else part))
    return out


def window_srt(cues, start: float, end: float, path: Path) -> None:
    blocks = []
    for a, b, text in cues:
        if b <= start or a >= end:
            continue
        a, b = max(a, start) - start, min(b, end) - start
        blocks.append(f"{len(blocks) + 1}\n{ts(a)} --> {ts(b)}\n{text}\n")
    path.write_text("\n".join(blocks))


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return float(out.stdout)


def run(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def main(take: Path) -> None:
    cues = chunked(parse_srt(take / "interview.srt"))
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        parts = []
        for i, (kind, a, b, label) in enumerate(SHOTS):
            part = work / f"{i:02}.mp4"
            if kind == "card":
                card, vo = CARDS / f"{a}.mp4", VOICEOVER / f"{a}.wav"
                if vo.exists():
                    hold = max(0.0, VO_LEAD + duration(vo) + VO_TAIL - duration(card))
                    vf = f"scale=1920:1080,setsar=1,tpad=stop_mode=clone:stop_duration={hold:.2f}"
                    run(["-i", str(card), "-i", str(vo), "-map", "0:v", "-map", "1:a", "-vf", vf,
                         "-af", f"adelay={int(VO_LEAD * 1000)}:all=1,apad,aresample=48000,"
                                "loudnorm=I=-16:TP=-1.5",
                         "-shortest", *ENCODE, str(part)])  # fmt: skip
                else:
                    run(["-i", str(card), "-vf", "scale=1920:1080,setsar=1",
                         "-af", "aresample=48000", *ENCODE, str(part)])  # fmt: skip
            else:
                src = take / ("programme.webm" if kind == "programme" else "segment.mp4")
                dur = b - a
                (work / f"{i:02}.txt").write_text(label)
                vf = "scale=1920:1080,setsar=1"
                if kind == "programme":  # the segment has its own captions
                    window_srt(cues, a, b, work / f"{i:02}.srt")
                    vf += (
                        f",subtitles={work / f'{i:02}.srt'}:force_style='FontName={FONT},"
                        "FontSize=11,BorderStyle=3,Outline=2,Shadow=0,BackColour=&H60000000,"
                        "MarginV=21'"
                    )
                # Top centre on the programme; top right on the segment, clear of its header.
                at = "x=w-text_w-48:y=40" if kind == "segment" else "x=(w-text_w)/2:y=128"
                vf += (
                    f",drawtext=font='{FONT}':textfile='{work / f'{i:02}.txt'}':expansion=none:"
                    f"fontcolor=white:fontsize=34:{at}:"
                    "box=1:boxcolor=0x0b1a2e@0.85:boxborderw=16"
                )
                af = f"afade=t=in:d=0.3,afade=t=out:st={dur - 0.4:.2f}:d=0.4,loudnorm=I=-16:TP=-1.5"
                run(["-ss", f"{a}", "-t", f"{dur}", "-i", str(src),
                     "-vf", vf, "-af", af, *ENCODE, str(part)])  # fmt: skip
            parts.append(part)
            print(f"{part.name}: {kind} {a}", flush=True)
        listing = work / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
             "-movflags", "+faststart", str(OUT)])  # fmt: skip
    print(OUT)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
