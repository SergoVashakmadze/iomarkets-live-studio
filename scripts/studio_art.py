"""Draw the fallback studio backdrop and render it to src/studio/assets/backdrop.jpg.

    uv run python scripts/studio_art.py

Drawn here as SVG during the hackathon and rendered by headless Chrome. The studio uses it only
when the IoMarkets TV studio background (scripts/anchor_assets.py) is not on this machine.
"""

# ruff: noqa: E501  (SVG markup reads better unwrapped)

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "studio" / "assets"
W, H = 1920, 1080


def backdrop() -> str:
    """A night-time markets studio: blue wall panels, a lit skyline, a ticker of candles."""
    rnd = random.Random(26)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        "<defs>",
        '<linearGradient id="wall" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#020814"/><stop offset=".55" stop-color="#0a2547"/>'
        '<stop offset="1" stop-color="#03101f"/></linearGradient>',
        '<radialGradient id="glow" cx=".5" cy=".62" r=".6">'
        '<stop offset="0" stop-color="#1f6fd1" stop-opacity=".55"/>'
        '<stop offset="1" stop-color="#1f6fd1" stop-opacity="0"/></radialGradient>',
        '<linearGradient id="panel" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#2d7ff0" stop-opacity="0"/>'
        '<stop offset=".5" stop-color="#2d7ff0" stop-opacity=".22"/>'
        '<stop offset="1" stop-color="#2d7ff0" stop-opacity="0"/></linearGradient>',
        '<linearGradient id="floor" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#0b1d36"/><stop offset="1" stop-color="#01050b"/></linearGradient>',
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="url(#wall)"/>',
        f'<rect width="{W}" height="{H}" fill="url(#glow)"/>',
    ]
    # Vertical light panels on the studio wall.
    for x in range(60, W, 240):
        parts.append(f'<rect x="{x}" y="40" width="120" height="760" fill="url(#panel)"/>')
        parts.append(
            f'<rect x="{x + 59}" y="40" width="2" height="760" fill="#5aa9ff" opacity=".18"/>'
        )
    # Skyline: towers with lit windows.
    x = 0
    while x < W:
        bw = rnd.randint(50, 130)
        bh = rnd.randint(120, 380)
        top = 820 - bh
        parts.append(f'<rect x="{x}" y="{top}" width="{bw}" height="{bh}" fill="#061427"/>')
        for wy in range(top + 14, 812, 18):
            for wx in range(x + 8, x + bw - 8, 14):
                if rnd.random() < 0.28:
                    c = "#ffb547" if rnd.random() < 0.25 else "#8cc4ff"
                    o = rnd.uniform(0.25, 0.75)
                    parts.append(
                        f'<rect x="{wx}" y="{wy}" width="6" height="8" fill="{c}" opacity="{o:.2f}"/>'
                    )
        x += bw + rnd.randint(4, 18)
    # A market line across the wall, with candles under it.
    pts, y = [], 330.0
    for cx in range(80, W - 60, 46):
        o = y
        y = max(200.0, min(460.0, y + rnd.uniform(-34, 30)))
        hi, lo = min(o, y) - rnd.uniform(6, 22), max(o, y) + rnd.uniform(6, 22)
        up = y < o
        col = "#3ccf7e" if up else "#ff5b5b"
        parts.append(
            f'<line x1="{cx}" y1="{hi:.0f}" x2="{cx}" y2="{lo:.0f}" stroke="{col}" stroke-width="2" opacity=".35"/>'
        )
        parts.append(
            f'<rect x="{cx - 8}" y="{min(o, y):.0f}" width="16" height="{max(3, abs(o - y)):.0f}" '
            f'fill="{col}" opacity=".35"/>'
        )
        pts.append(f"{cx},{y:.0f}")
    parts.append(
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="#ffa028" stroke-width="3" opacity=".55"/>'
    )
    # Desk-height horizon, floor and the wordmark.
    parts += [
        f'<rect x="0" y="820" width="{W}" height="{H - 820}" fill="url(#floor)"/>',
        f'<rect x="0" y="818" width="{W}" height="4" fill="#ffa028" opacity=".9"/>',
        f'<rect x="0" y="826" width="{W}" height="1" fill="#5aa9ff" opacity=".6"/>',
        '<text x="960" y="150" text-anchor="middle" font-family="Inter, Helvetica, Arial, sans-serif" '
        'font-weight="800" font-size="120" letter-spacing="28" fill="#ffffff" opacity=".07">IOMARKETS.TV</text>',
        "</svg>",
    ]
    return "\n".join(parts)


def render(svg: str, out: Path, w: int, h: int, work: Path) -> None:
    src = work / f"{out.stem}.svg"
    src.write_text(svg)
    png = work / f"{out.stem}.png"
    subprocess.run(
        [
            shutil.which("google-chrome") or "chromium", "--headless=new", "--disable-gpu",
            "--hide-scrollbars", f"--window-size={w},{h}", "--default-background-color=00000000",
            f"--screenshot={png}", src.as_uri(),
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    if out.suffix == ".jpg":
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(png), "-q:v", "3", str(out)], check=True
        )
    else:
        shutil.copy(png, out)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        render(backdrop(), OUT / "backdrop.jpg", W, H, work)
    print(f"backdrop.jpg: {(OUT / 'backdrop.jpg').stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
