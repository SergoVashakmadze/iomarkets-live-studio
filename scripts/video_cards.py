"""Render the demo video's cards (1920x1080, silent MP4) into video/cards/.

    uv run python scripts/video_cards.py

Edit the text below, not the video: the cards stay consistent with the studio's own look.
Numbers on the cards are the ones measured and recorded in NEW_WORK.md.
"""

import asyncio
import tempfile
from pathlib import Path

from studio.compose import text_card

WHITE, MUTED, ACCENT, RED = "white", "0x9fb3c8", "0x6aa8ff", "0xff6b6b"
OUT = Path(__file__).resolve().parent.parent / "video" / "cards"

CARDS = {
    "01-title": (
        [
            ("IoMarkets Live Studio", 12, WHITE),
            ("A live interview on any topic, with an AI anchor", 26, MUTED),
            ("that listens, fact-checks and produces the segment as it happens", 26, MUTED),
            ("", 40, WHITE),
            ("Built on Meta's models  |  Meta Global AI Developer Hackathon 2026", 34, ACCENT),
            ("", 30, WHITE),
            # The video must open with this disclosure (docs/ORGANISER_RULES.md).
            (
                "Pre-existing: Meta's models, open-source MuseTalk, and the anchor Teresa",
                34,
                WHITE,
            ),
            (
                "(a HeyGen avatar) with her studio. New this week: the studio software.",
                34,
                WHITE,
            ),
        ],
        7,
    ),
    "02-problem": (
        [
            ("Live interviews are expensive", 16, WHITE),
            ("A presenter, a researcher, a fact-checker and an editor", 28, MUTED),
            ("for every guest. Small newsrooms go without.", 28, MUTED),
        ],
        5,
    ),
    "03-how": (
        [
            ("How it works", 16, WHITE),
            ("Muse Voice Transcribe  -  hears the guest live; they can interrupt", 34, MUTED),
            ("Muse Spark 1.3  -  the anchor, chart reading, fact-check with web search", 34, MUTED),
            ("SAM 3.1  -  cuts the guest out of their room, answer by answer", 34, MUTED),
            ("Muse Spark Open  -  edits the research brief on open weights", 34, MUTED),
            ("", 40, WHITE),
            ("Anchor replies in 1.3-2.1 s  |  barge-in detected in 0.2-0.4 s", 34, ACCENT),
            ("Fact-check 6-8 s  |  a 12 s answer cut out in about 25 s", 34, ACCENT),
        ],
        8,
    ),
    "04-new-work": (
        [
            ("Built during the hackathon", 16, WHITE),
            (
                "All the code shown was written from the Oct 26 kickoff, in a new public repo.",
                32,
                MUTED,
            ),
            ("IoMarkets.tv had an earlier studio on other providers;", 32, MUTED),
            ("this is a ground-up rebuild on Meta's stack. See NEW_WORK.md.", 32, MUTED),
            ("", 40, WHITE),
            ("The anchor is AI. Its voice is synthetic.", 30, RED),
        ],
        6,
    ),
    "05-end": (
        [
            ("IoMarkets Live Studio", 14, WHITE),
            ("github.com/SergoVashakmadze/iomarkets-live-studio", 30, ACCENT),
            ("", 40, WHITE),
            ("Built with Muse Spark Open", 34, MUTED),
            ("Journalism on any topic. Not medical, legal or financial advice.", 36, MUTED),
        ],
        5,
    ),
}


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        for name, (lines, seconds) in CARDS.items():
            await text_card(lines, OUT / f"{name}.mp4", Path(work), seconds=seconds)
            print(OUT / f"{name}.mp4")


if __name__ == "__main__":
    asyncio.run(main())
