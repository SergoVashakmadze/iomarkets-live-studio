"""The anchor's picture and the studio set, made with Meta's Muse Image (`muse-image-1.0`).

    uv run python scripts/anchor_art.py [--out DIR]

Made on 2026-10-31, during the event, to replace the pre-existing HeyGen avatar and studio set
(the organisers: everything built on must be open source or self-made). The anchor is a fictional
person. Muse Image draws a new face each call, so this writes candidates to `--out` (default
media/art/); the ones the studio uses were chosen by eye and cropped into src/studio/assets/:

- anchor.jpg       960x720, the live 4:3 shot:  crop=1707:1280:106:0, scale=960:720
- anchor-wide.jpg  1280x720, the segment's wide shot: crop=1920:1080:0:40, scale=1280:720
- studio.jpg       1920x1080, the empty set behind the guest: crop=1920:1080:0:100

Needs META_API_KEY. Each picture is one Muse Image call.
"""

import argparse
import base64
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
URL = "https://api.meta.ai/v1/images/generations"

ANCHOR = (
    "Photorealistic broadcast still: a fictional male television news anchor in his early "
    "forties, short neat dark hair, light stubble, tailored charcoal suit, white shirt, no tie, "
    "seated at a glossy anchor desk, facing the camera, warm composed expression, mouth closed, "
    "head and shoulders and desk in frame, centred. Behind him a modern TV news studio in deep "
    "red and charcoal with soft bokeh screens and warm key lighting. Shot on a broadcast camera, "
    "4K, sharp focus on the face, no text, no logos, no watermark."
)
STUDIO = (
    "Photorealistic empty modern television news studio set, deep red and charcoal colour "
    "scheme, large curved backdrop with softly glowing abstract city-skyline screens, warm studio "
    "lighting, shallow depth of field, wide shot at seated eye level, nobody in frame, no text, "
    "no logos, no watermark."
)


def make(name: str, prompt: str, out: Path) -> Path:
    r = httpx.post(
        URL,
        headers={"Authorization": f"Bearer {os.environ['META_API_KEY']}"},
        json={"model": "muse-image-1.0", "prompt": prompt, "n": 1, "size": "1536x1024"},
        timeout=180,
    )
    r.raise_for_status()
    webp = out / f"{name}.webp"
    webp.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
    png = webp.with_suffix(".png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(webp), str(png)], check=True)
    return png


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "media" / "art")
    ap.add_argument("--anchors", type=int, default=4)
    ap.add_argument("--studios", type=int, default=2)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = [(f"anchor-{i}", ANCHOR) for i in range(args.anchors)]
    jobs += [(f"studio-{i}", STUDIO) for i in range(args.studios)]
    with ThreadPoolExecutor(6) as pool:
        for path in pool.map(lambda j: make(*j, args.out), jobs):
            print(path)


if __name__ == "__main__":
    main()
