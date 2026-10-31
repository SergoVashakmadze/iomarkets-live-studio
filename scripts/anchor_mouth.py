"""The anchor's open mouth, made once with Meta's Muse Image; the page opens and closes it with
the loudness of his voice. No model runs during an interview.

    uv run --with opencv-python-headless python scripts/anchor_mouth.py [--open EDIT.png]

1. Muse Image's edit endpoint redraws anchor.jpg with the mouth open, mid-word (or `--open`
   reuses an edit made earlier). The edit redraws the whole face, slightly moved and resized.
2. OpenCV's ECC image registration (plain optimisation, not a trained model) aligns the edit to
   the still on the upper face, and the mouth area's colour is matched to the still.
3. Only a feathered ellipse round the mouth and chin is kept, as a transparent PNG the size of
   the still: anchor-mouth.png (live 4:3 shot) and anchor-mouth-wide.png (the segment's 16:9).

The ellipse is placed by hand for this anchor (MOUTH): a new picture needs new numbers.
Needs META_API_KEY unless `--open` is given.
"""

import argparse
import base64
import os
from pathlib import Path

import cv2
import httpx
import numpy as np

ASSETS = Path(__file__).resolve().parent.parent / "src" / "studio" / "assets"
PROMPT = "Same photo, identical in every way, except his mouth is open mid-word, as if speaking"
MOUTH = ((480, 300), (85, 58))  # centre and radii in anchor.jpg (960x720), by eye
UPPER_FACE = (330, 110, 630, 330)  # x0, y0, x1, y1: eyes and nose, for the alignment
# anchor.jpg and anchor-wide.jpg are crops of one Muse Image picture (scripts/anchor_art.py):
# live crop 1707x1280 at x 106 scaled to 960x720; wide crop 1920x1080 at y 40 scaled to 1280x720.
LIVE_TO_WIDE = np.float32(
    [[1707 / 960 * 2 / 3, 0, 106 * 2 / 3], [0, 1280 / 720 * 2 / 3, -40 * 2 / 3]]
)


def edit(still: Path) -> np.ndarray:
    data = base64.b64encode(still.read_bytes()).decode()
    r = httpx.post(
        "https://api.meta.ai/v1/images/edits",
        headers={"Authorization": f"Bearer {os.environ['META_API_KEY']}"},
        json={
            "model": "muse-image-1.0",
            "images": [{"image_url": f"data:image/jpeg;base64,{data}"}],
            "prompt": PROMPT,
        },
        timeout=180,
    )
    r.raise_for_status()
    raw = np.frombuffer(base64.b64decode(r.json()["data"][0]["b64_json"]), np.uint8)
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


def mouth_layer(base: np.ndarray, opened: np.ndarray) -> np.ndarray:
    h, w = base.shape[:2]
    opened = cv2.resize(opened, (w, h), interpolation=cv2.INTER_AREA)
    g0 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g1 = cv2.cvtColor(opened, cv2.COLOR_BGR2GRAY).astype(np.float32)
    x0, y0, x1, y1 = UPPER_FACE
    roi = np.zeros((h, w), np.uint8)
    roi[y0:y1, x0:x1] = 255
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    _, warp = cv2.findTransformECC(g0, g1, warp, cv2.MOTION_AFFINE, criteria, roi, 5)
    aligned = cv2.warpAffine(opened, warp, (w, h), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
    mask = np.zeros((h, w), np.float32)
    cv2.ellipse(mask, *MOUTH, 0, 0, 360, 1, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), 14)
    inside = mask > 0.5
    out = aligned.astype(np.float32)
    for c in range(3):  # the edit's light differs a little: match the still's
        a, b = out[..., c][inside], base[..., c][inside].astype(np.float32)
        out[..., c] = (out[..., c] - a.mean()) * (b.std() / a.std()) + b.mean()
    rgba = np.dstack([np.clip(out, 0, 255), mask * 255]).astype(np.uint8)
    rgba[mask < 1 / 255] = 0  # nothing outside the mouth: a small PNG
    return rgba


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", type=Path, help="an open-mouth edit made earlier")
    args = ap.parse_args()
    still = ASSETS / "anchor.jpg"
    base = cv2.imread(str(still))
    opened = cv2.imread(str(args.open)) if args.open else edit(still)
    live = mouth_layer(base, opened)
    cv2.imwrite(str(ASSETS / "anchor-mouth.png"), live)
    wide = cv2.warpAffine(live, LIVE_TO_WIDE, (1280, 720), flags=cv2.INTER_LINEAR)
    cv2.imwrite(str(ASSETS / "anchor-mouth-wide.png"), wide)
    for name in ("anchor-mouth.png", "anchor-mouth-wide.png"):
        print(f"{name}: {(ASSETS / name).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
