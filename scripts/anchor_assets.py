"""Build the anchor's studio assets from the IoMarkets.tv newsroom's pre-existing media.

    uv run python scripts/anchor_assets.py [--newsroom PATH]

The anchor (Teresa, a HeyGen-sourced avatar) and the IoMarkets TV studio background predate the
hackathon and are not open source, so they stay out of this public repo: this script writes them
to src/studio/assets/, which git ignores (NEW_WORK.md, "Pre-existing"). They carry their own names, so they never
overwrite the Muse Image set and anchor (studio.jpg, anchor.jpg) that ship in the repo: the page
and compose.py use Teresa's files when present, and the Muse Image ones otherwise. Without them the studio
falls back to the drawn backdrop and shows no anchor picture.

Outputs:
- teresa-studio.jpg   the studio background, 1920x1080
- teresa.png          the anchor's loop, first frame, with transparency, cropped, 720 high: her
                      still when no lip-synced clip is playing
- teresa-wide.png     that frame on the studio background, 1280x720: her still in the
                      segment when there is no lip-sync server (lipsync/server.py)
"""

import argparse
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "studio" / "assets"
DEFAULT_NEWSROOM = ROOT.parent / "iomarkets.tv-newsroom"
H = 720  # the anchor's height in the live assets
# The live medium shot, in the 1920x1080 composite: x, y, w, h. The page (index.html, SHOT) and
# lipsync/server.py (SHOTS["live"]) use the same numbers, so the lip-synced clips and her still
# line up to the pixel.
SHOT = (420, 230, 1080, 810)


def ff(*args: str) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True
    ).stdout


def person_box(mask: Path) -> tuple[int, int, int, int]:
    """(x, y, w, h) around every frame of the mask, with a margin, in even pixels."""
    w, h = 480, 270  # analyse at a quarter of 1920x1080
    raw = ff("-i", str(mask), "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "pipe:1")
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w)
    on = (frames > 128).any(axis=0)
    ys, xs = np.nonzero(on)
    x0, x1 = max(0, xs.min() - 8) * 4, min(w, xs.max() + 9) * 4
    y0, y1 = max(0, ys.min() - 8) * 4, min(h, ys.max() + 1) * 4
    return x0 // 2 * 2, y0 // 2 * 2, (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--newsroom", type=Path, default=DEFAULT_NEWSROOM)
    src = ap.parse_args().newsroom / "services" / "broadcast" / "assets"
    loop, mask = src / "avatars" / "teresa_loop.mp4", src / "avatars" / "teresa_loop_mask.mp4"
    studio = src / "studio_background_iomarkets_tv.png"
    OUT.mkdir(exist_ok=True)

    ff("-i", str(studio), "-vf", "scale=1920:1080", "-q:v", "3", str(OUT / "teresa-studio.jpg"))
    x, y, w, h = person_box(mask)
    crop = f"crop={w}:{h}:{x}:{y},scale=-2:{H}"
    keyed = f"[0:v]{crop}[c];[1:v]{crop},format=gray[m];[c][m]alphamerge"
    ff("-i", str(loop), "-i", str(mask), "-filter_complex",
       keyed + ",format=rgba", "-frames:v", "1", str(OUT / "teresa.png"))  # fmt: skip
    # The full frame for MuseTalk: the anchor where the loop has her, over the studio's desk,
    # 24 px lower so the loop's bottom edge (y 1068) falls off the frame.
    ff("-i", str(studio), "-i", str(loop), "-i", str(mask), "-filter_complex",
       "[2:v]format=gray[m];[1:v][m]alphamerge[a];[0:v]scale=1920:1080[bg];"
       "[bg][a]overlay=0:24,scale=1280:720", "-frames:v", "1",
       str(OUT / "teresa-wide.png"))  # fmt: skip
    for name in ("teresa-studio.jpg", "teresa.png", "teresa-wide.png"):
        print(f"{name}: {(OUT / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
