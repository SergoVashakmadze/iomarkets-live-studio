"""The anchor's voice: Meta's FastSpeech 2 (fairseq S^2), trained on LJSpeech, one native US
English speaker, with its HiFi-GAN vocoder. `facebook/fastspeech2-en-ljspeech`, on the CPU.

Runs in its own Python 3.10 environment, because fairseq 0.12 does not install on 3.12:

    uv venv --python 3.10 ~/.cache/iomarkets-voice && \\
      uv pip install --python ~/.cache/iomarkets-voice/bin/python -r voice/requirements.txt \\
      --extra-index-url https://download.pytorch.org/whl/cpu
    ~/.cache/iomarkets-voice/bin/python voice/server.py            # :8767
    STUDIO_TTS_URL=http://127.0.0.1:8767 uv run studio serve

On Modal it is the class `Voice` (deploy/modal_app.py), called with `STUDIO_TTS=modal`.

The model reads phonemes. The model card's own phonemizer (g2p_en) runs two small non-Meta
models (a part-of-speech tagger and a neural guesser for unknown words), and the organisers allow
only Meta models at runtime, so words become phonemes here by plain lookup: LEXICON first (the
brand, said as one word, "eye-oh-MAR-kits"), then the CMU Pronouncing Dictionary (data, BSD),
then spelling rules for words neither knows. Commas become the model's own short pause, `sp`.

The studio sends text already written for the ear (src/studio/speech_text.py: numbers, money,
acronyms as words). Measured 2026-10-31 on the workstation CPU: 0.2-0.3 s per second of speech.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

MODEL = "facebook/fastspeech2-en-ljspeech"
RATE = 22050

# Delivery for business TV: FastSpeech 2 predicts each sound's length, pitch and energy; these
# scale its predictions. Duration 0.86 (14 % quicker), pitch range x1.7 and lifted +0.45 (in the
# model's normalised units), energy x1.4: "very energetic", the operator's pick of four by ear
# (Oct 31). Whisper still follows it, with the odd slip on a word.
# Pace 0.92, not 0.86: at 0.86 short words blurred ("what went wrong" heard as "but went
# wrong"); the pitch and energy of "very energetic" stay.
DURATION, PITCH_RANGE, PITCH_LIFT, ENERGY = 0.92, 1.7, 0.45, 1.4

# Said our way. Keys are lower case; values are ARPAbet with stress, as in CMUdict.
LEXICON = {
    "iomarkets": "AY1 OW2 M AA1 R K AH0 T S",  # "Io" as in IoT, then "markets" (operator, by ear)
    "tv": "T IY1 V IY1",
    "muse": "M Y UW1 Z",
    "llama": "L AA1 M AH0",
    "meta": "M EH1 T AH0",
    "fintech": "F IH1 N T EH2 K",
    "esg": "IY1 EH1 S JH IY1",
    # Business and tech words CMUdict lacks (checked against it, Oct 31).
    "nvidia": "EH0 N V IH1 D IY0 AH0",
    "openai": "OW1 P AH0 N AY1",
    "fintechs": "F IH1 N T EH2 K S",
    "crypto": "K R IH1 P T OW0",
    "stablecoin": "S T EY1 B AH0 L K OY2 N",
    "stablecoins": "S T EY1 B AH0 L K OY2 N Z",
    "blockchain": "B L AA1 K CH EY2 N",
    "tokenisation": "T OW2 K AH0 N AH0 Z EY1 SH AH0 N",
    "tokenization": "T OW2 K AH0 N AH0 Z EY1 SH AH0 N",
    "ebitda": "IY1 B IH0 T D AA2",
    "saas": "S AE1 S",
    "agentic": "EY0 JH EH1 N T IH0 K",
    "gigawatt": "G IH1 G AH0 W AA2 T",
    "gigawatts": "G IH1 G AH0 W AA2 T S",
    "hackathon": "HH AE1 K AH0 TH AA2 N",
    "linkedin": "L IH1 NG K T IH1 N",
    "broadcom": "B R AO1 D K AA2 M",
    "anthropic": "AE2 N TH R AA1 P IH0 K",
    "fca": "EH1 F S IY1 EY1",
    "datacenter": "D EY1 T AH0 S EH2 N T ER0",
    "onchain": "AA1 N CH EY1 N",
    "neobank": "N IY1 OW0 B AE2 NG K",
    "proptech": "P R AA1 P T EH2 K",
    "regtech": "R EH1 JH T EH2 K",
    "insurtech": "IH0 N SH ER1 T EH2 K",
    "labour": "L EY1 B ER0",  # CMUdict has "lay-bower"
    # Letter names: speech_text spells acronyms with these ("FCA" -> "eff see ay").
    "ay": "EY1",
    "bee": "B IY1",
    "see": "S IY1",
    "dee": "D IY1",
    "ee": "IY1",
    "eff": "EH1 F",
    "jee": "JH IY1",
    "aitch": "EY1 CH",
    "eye": "AY1",
    "jay": "JH EY1",
    "kay": "K EY1",
    "el": "EH1 L",
    "em": "EH1 M",
    "en": "EH1 N",
    "oh": "OW1",
    "pee": "P IY1",
    "cue": "K Y UW1",
    "ar": "AA1 R",
    "ess": "EH1 S",
    "tee": "T IY1",
    "you": "Y UW1",
    "vee": "V IY1",
    "ex": "EH1 K S",
    "why": "W AY1",
    "zed": "Z EH1 D",
    "labours": "L EY1 B ER0 Z",
}

# UK spellings, rewritten to the US forms CMUdict holds, most specific first ("authorised" ->
# "authorized", "organisation" -> "organization", "colour" -> "color", "centre" -> "center").
_UK_US = [
    (r"isation(s?)$", r"ization\1"), (r"ise(s|d|r|rs)?$", r"ize\1"), (r"ising$", r"izing"),
    (r"yse(s|d)?$", r"yze\1"), (r"ysing$", r"yzing"), (r"our(s|ed|ing|ite|ites|able)?$", r"or\1"),
    (r"tre(s)?$", r"ter\1"), (r"ence$", r"ense"), (r"lled$", r"led"), (r"lling$", r"ling"),
    (r"ogue(s)?$", r"og\1"), (r"^programme(s?)$", r"program\1"), (r"^cheque(s?)$", r"check\1"),
    (r"^grey$", r"gray"), (r"^tyre(s?)$", r"tire\1"), (r"^aluminium$", r"aluminum"),
]  # fmt: skip
# Endings: a known stem plus these sounds ("refinancings" is not in CMUdict, "refinancing" is).
_SUFFIXES = [
    ("ization", "AH0 Z EY1 SH AH0 N"), ("izations", "AH0 Z EY1 SH AH0 N Z"),
    ("ness", "N AH0 S"), ("ments", "M AH0 N T S"), ("ment", "M AH0 N T"), ("ings", "IH0 NG Z"),
    ("ing", "IH0 NG"), ("ers", "ER0 Z"), ("er", "ER0"), ("ly", "L IY0"), ("ed", "D"),
    ("es", "Z"), ("s", "Z"), ("able", "AH0 B AH0 L"), ("al", "AH0 L"), ("ist", "IH0 S T"),
    ("ists", "IH0 S T S"), ("ism", "IH0 Z AH0 M"), ("ity", "AH0 T IY0"),
]  # fmt: skip
_PREFIXES = [
    ("re", "R IY0"), ("un", "AH0 N"), ("pre", "P R IY0"), ("non", "N AA1 N"), ("co", "K OW0"),
    ("multi", "M AH1 L T IY0"), ("over", "OW1 V ER0"), ("under", "AH1 N D ER0"),
    ("cross", "K R AO1 S"), ("cyber", "S AY1 B ER0"), ("de", "D IY0"), ("mis", "M IH0 S"),
]  # fmt: skip

# Spelling rules for words in neither LEXICON nor CMUdict (mostly names): longest match first.
_RULES = [
    ("tion", "SH AH0 N"), ("sion", "ZH AH0 N"), ("ough", "AH1 F"), ("augh", "AO1"),
    ("igh", "AY1"), ("tch", "CH"), ("sch", "SH"), ("dge", "JH"),
    ("ch", "CH"), ("sh", "SH"), ("th", "TH"), ("ph", "F"), ("wh", "W"), ("ck", "K"),
    ("ng", "NG"), ("qu", "K W"), ("kn", "N"), ("gh", "G"), ("ee", "IY1"), ("ea", "IY1"),
    ("oo", "UW1"), ("ou", "AW1"), ("ow", "OW1"), ("oi", "OY1"), ("oy", "OY1"), ("ai", "EY1"),
    ("ay", "EY1"), ("au", "AO1"), ("aw", "AO1"), ("ie", "IY1"), ("ei", "EY1"), ("ey", "IY0"),
    ("ue", "UW1"), ("ui", "UW1"), ("er", "ER0"), ("ar", "AA1 R"), ("or", "AO1 R"), ("ir", "ER1"),
    ("ur", "ER1"), ("a", "AE1"), ("e", "EH1"), ("i", "IH1"), ("o", "AA1"), ("u", "AH1"),
    ("y", "IY0"), ("b", "B"), ("c", "K"), ("d", "D"), ("f", "F"), ("g", "G"), ("h", "HH"),
    ("j", "JH"), ("k", "K"), ("l", "L"), ("m", "M"), ("n", "N"), ("p", "P"), ("r", "R"),
    ("s", "S"), ("t", "T"), ("v", "V"), ("w", "W"), ("x", "K S"), ("z", "Z"),
]  # fmt: skip
_VOWEL = re.compile(r"[AEIOU]")


def spell(word: str) -> list[str]:
    """Phonemes for an unknown word by rule: the first vowel stressed, the rest reduced."""
    out, i = [], 0
    while i < len(word):
        for g, p in _RULES:
            if word.startswith(g, i):
                out += p.split()
                i += len(g)
                break
        else:
            i += 1  # not a letter we know: skip it
    if word.endswith("e") and len(out) > 2 and out[-1] == "EH1":
        out.pop()  # a silent final e
    seen = False
    for k, ph in enumerate(out):
        if _VOWEL.match(ph):
            if seen:
                out[k] = "AH0" if ph[:-1] in ("AE", "EH", "AH", "AA") else ph[:-1] + "0"
            seen = True
    return out


class Phonemizer:
    def __init__(self) -> None:
        from nltk.corpus import cmudict

        self.cmu = cmudict.dict()
        self.unknown: set[str] = set()

    def word(self, w: str) -> list[str]:
        w = w.lower().strip("'")
        if not w:
            return []
        if w in LEXICON:
            return LEXICON[w].split()
        if w in self.cmu:
            return self.cmu[w][0]
        if w.endswith("'s") and len(w) > 3:  # possessives: "labour's", "nvidia's"
            return self.word(w[:-2]) + ["Z"]
        if "-" in w:
            return [p for part in w.split("-") for p in self.word(part)]
        return self.derive(w) or self._unknown(w)

    def _lookup(self, w: str) -> list[str] | None:
        if w in LEXICON:
            return LEXICON[w].split()
        if w in self.cmu:
            return self.cmu[w][0]
        for pat, rep in _UK_US:
            us = re.sub(pat, rep, w)
            if us != w and us in self.cmu:
                return self.cmu[us][0]
        return None

    def derive(self, w: str, depth: int = 0) -> list[str] | None:
        """A word CMUdict lacks, from parts it has: UK spelling, an ending on a known stem
        (also with a dropped or doubled letter), a prefix on a known word, or two known words."""
        if (found := self._lookup(w)) is not None:
            return found
        if depth > 1:
            return None
        for suf, ph in _SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                stem = w[: -len(suf)]
                for cand in (
                    stem,
                    stem + "e",
                    stem[:-1] if len(stem) > 3 and stem[-1] == stem[-2] else None,
                ):
                    if cand and (base := self.derive(cand, depth + 1)) is not None:
                        return base + ph.split()
        for pre, ph in _PREFIXES:
            if (
                w.startswith(pre)
                and len(w) - len(pre) >= 4
                and (base := self.derive(w[len(pre) :], depth + 1)) is not None
            ):
                return ph.split() + base
        for i in range(3, len(w) - 2):  # a compound of two known words: "stable" + "coin"
            a, b = self._lookup(w[:i]), self._lookup(w[i:])
            if a is not None and b is not None:
                return a + b
        return None

    def _unknown(self, w: str) -> list[str]:
        """Spelled by rule, and logged once, so the lexicon can grow from real interviews."""
        if w not in self.unknown:
            self.unknown.add(w)
            print(f"[voice] unknown word, spelled by rule: {w}", file=sys.stderr, flush=True)
        return spell(w)

    def __call__(self, text: str) -> list[str]:
        out: list[str] = []
        for tok in re.findall(r"[A-Za-z][A-Za-z'\-]*|[,;:.!?]", text):
            if tok in ",;:.!?":
                if out and out[-1] != "sp":
                    out.append("sp")
            else:
                out += self.word(tok)
        while out and out[-1] == "sp":
            out.pop()
        return out


class Voice:
    def __init__(self) -> None:
        import torch

        load = torch.load
        # fairseq 0.12's checkpoints predate torch's weights_only default; they are Meta's own,
        # fetched from Meta's Hugging Face organisation.
        torch.load = lambda *a, **k: load(*a, **{**k, "weights_only": False})
        from fairseq.checkpoint_utils import load_model_ensemble_and_task_from_hf_hub
        from fairseq.models.text_to_speech.hub_interface import TTSHubInterface

        torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))
        models, cfg, task = load_model_ensemble_and_task_from_hf_hub(
            MODEL, arg_overrides={"vocoder": "hifigan", "fp16": False, "cpu": True}
        )
        TTSHubInterface.update_cfg_with_data_cfg(cfg, task.data_cfg)
        self.torch, self.hub, self.task, self.model = torch, TTSHubInterface, task, models[0]
        self._energetic(self.model.encoder.var_adaptor)
        self.generator = task.build_generator(models, cfg)
        self.phonemes = Phonemizer()

    def _energetic(self, va) -> None:
        """Apply DURATION, PITCH_RANGE, PITCH_LIFT and ENERGY to every sentence. fairseq's
        variance adaptor takes the three factors but its generator never passes them, and has
        no lift, so its two methods are wrapped here."""
        import types

        torch, forward, pitch = self.torch, va.forward, va.get_pitch_emb

        def lifted(adaptor, x, tgt=None, factor=1.0):
            out, emb = pitch(x, tgt, factor)
            if tgt is None:
                out = out + PITCH_LIFT
                emb = adaptor.embed_pitch(torch.bucketize(out, adaptor.pitch_bins.to(x.device)))
            return out, emb

        def styled(x, mask, durations=None, pitches=None, energies=None, *_, **__):
            return forward(x, mask, durations, pitches, energies, DURATION, PITCH_RANGE, ENERGY)

        va.get_pitch_emb = types.MethodType(lifted, va)
        va.forward = styled

    def speak(self, text: str) -> bytes:
        """One sentence to 16-bit mono WAV bytes at 22.05 kHz, peaking at -1 dB."""
        import numpy as np

        phones = self.phonemes(text)
        if not phones:
            raise ValueError("nothing to say")
        audio = self.speak_phonemes(" ".join(phones))
        rate = RATE
        audio = np.concatenate([audio, np.zeros(int(rate * 0.12), np.float32)])  # breath after
        audio *= 0.89 / max(float(np.abs(audio).max()), 1e-3)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        return out.getvalue()

    def speak_phonemes(self, phones: str):
        """ARPAbet (space-separated, `sp` for a pause) to float32 audio at RATE."""
        import numpy as np

        tokens = self.task.src_dict.encode_line(
            phones, add_if_not_exist=False, append_eos=True
        ).long()
        sample = {
            "net_input": {
                "src_tokens": tokens.view(1, -1),
                "src_lengths": self.torch.tensor([tokens.numel()]),
                "prev_output_tokens": None,
            },
            "target_lengths": None,
            "speaker": None,
        }
        with self.torch.inference_mode():
            wav, _ = self.hub.get_prediction(self.task, self.model, self.generator, sample)
        return wav.numpy().astype(np.float32)


def serve(voice: Voice, host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            ok = self.path == "/health"
            self.send_response(200 if ok else 404)
            self.end_headers()

        def do_POST(self) -> None:
            if self.path != "/speak":
                self.send_response(404)
                self.end_headers()
                return
            try:
                text = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                data = voice.speak(str(text["text"]))
            except Exception as e:
                body = json.dumps({"error": f"{type(e).__name__}: {e}"}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    print(f"[voice] ready on {host}:{port}", file=sys.stderr, flush=True)
    HTTPServer((host, port), Handler).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8767)
    args = ap.parse_args()
    serve(Voice(), args.host, args.port)


if __name__ == "__main__":
    main()
