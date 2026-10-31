"""Before an interview: which words would the anchor's voice have to guess?

    ~/.cache/iomarkets-voice/bin/python voice/check.py "Ada Okonkwo, CEO of Zentrafin"
    ~/.cache/iomarkets-voice/bin/python voice/check.py --file brief.txt

Prints each word that is in neither the lexicon nor the CMU Pronouncing Dictionary and cannot be
built from parts of it (UK spelling, a known stem plus an ending, two known words), with the
sounds the voice would guess. Add the right sounds for each to LEXICON in voice/server.py (ARPAbet,
as CMUdict writes them), redeploy, and the anchor says them correctly.
"""

import argparse
import re
import sys
from pathlib import Path

# speech_text from the studio, then this folder first: src/studio has a server.py of its own.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "studio"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
from speech_text import to_speech  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--file", type=Path)
    args = ap.parse_args()
    text = args.file.read_text() if args.file else args.text
    phonemes = server.Phonemizer()
    spoken = to_speech(text, keep_brand=True)
    guessed = {}
    for word in re.findall(r"[A-Za-z][A-Za-z'\-]*", spoken):
        for part in word.lower().strip("'").removesuffix("'s").split("-"):
            if part and len(part) > 1 and phonemes.derive(part) is None and part not in guessed:
                guessed[part] = " ".join(server.spell(part))
    if not guessed:
        print("Every word is known: nothing to check.")
        return
    print(f"{len(guessed)} word(s) the voice would guess; add the right sounds to LEXICON:")
    for word, sounds in guessed.items():
        print(f'    "{word}": "{sounds}",')


if __name__ == "__main__":
    main()
