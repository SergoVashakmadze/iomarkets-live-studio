"""Voice-over for the demo video's cards, spoken by Kokoro-82M (open source, Apache-2.0).

Kokoro is not a dependency of this repo; it runs from the IoMarkets newsroom checkout, which
has it installed and the model cached:

    ln -sfn "$(PY -c 'import espeakng_loader as e; print(e.get_data_path())')" /tmp/espeak-ng-data
    ESPEAK_DATA_PATH=/tmp/espeak-ng-data PY scripts/voiceover.py video/voiceover

where PY is ../iomarkets.tv-newsroom/services/broadcast/.venv/bin/python (it has the spaCy
model misaki needs). espeak cannot open its data under a path with a space ("New Projects"),
hence the link.

Writes one WAV per card (01-title.wav, ...). The narrator is a male voice so it is never
mistaken for the anchor, whose voice is Meta's FastSpeech 2. The video credits the narration
on its end card. `assemble_video.py` lengthens each card to fit its line.
"""

from __future__ import annotations

import sys
from pathlib import Path

VOICE, SPEED = "am_fenrir", 1.12
SAMPLE_RATE = 24000

# Written as said: numbers in words, "IoMarkets" respelled as the newsroom does.
LINES = {
    "01-title": (
        "Eye-oh Markets Live Studio. Pre-existing: Meta's models, open-source libraries, and "
        "the anchor's look, a HeyGen library avatar called Teresa. Built this week: all of the "
        "studio software."
    ),
    "02-problem": (
        "A live interview takes a presenter, a researcher, a fact-checker and an editor. Small "
        "newsrooms go without. This studio does all four, live, on Meta's models. Here is a "
        "real interview, as it went out."
    ),
    "03-how": (
        "Muse Voice Transcribe hears the guest live. Muse Spark one point three is the anchor "
        "and the fact-checker, with web search. Sam three point one cuts the guest into the "
        "studio, and Muse Spark Open edits the brief on open weights."
    ),
    "04-new-work": (
        "Everything shown was written during the hackathon. The anchor is AI, and it says so."
    ),
    "05-end": "Eye-oh Markets Live Studio. The code is open.",
}


def main(out: Path) -> None:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    out.mkdir(parents=True, exist_ok=True)
    pipe = KPipeline(lang_code=VOICE[0], repo_id="hexgrad/Kokoro-82M")
    for name, text in LINES.items():
        audio = [np.asarray(a) for _, _, a in pipe(text, voice=VOICE, speed=SPEED)]
        sf.write(out / f"{name}.wav", np.concatenate(audio), SAMPLE_RATE)
        print(out / f"{name}.wav", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
