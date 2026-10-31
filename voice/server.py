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

# Said our way. Keys are lower case; values are ARPAbet with stress, as in CMUdict.
LEXICON = {
    "iomarkets": "AY2 OW0 M AA1 R K IH0 T S",  # operator's pick, Oct 31: one word, no gap
    "tv": "T IY1 V IY1",
    "muse": "M Y UW1 Z",
    "llama": "L AA1 M AH0",
    "meta": "M EH1 T AH0",
    "fintech": "F IH1 N T EH2 K",
    "esg": "IY1 EH1 S JH IY1",
}

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

    def word(self, w: str) -> list[str]:
        w = w.lower().strip("'")
        if not w:
            return []
        if w in LEXICON:
            return LEXICON[w].split()
        if w in self.cmu:
            return self.cmu[w][0]
        if w.endswith("'s") and w[:-2] in self.cmu:  # possessives
            return self.cmu[w[:-2]][0] + ["Z"]
        if "-" in w:
            return [p for part in w.split("-") for p in self.word(part)]
        return spell(w)

    def __call__(self, text: str) -> list[str]:
        out: list[str] = []
        for tok in re.findall(r"[A-Za-z][A-Za-z'\-]*|[,;:]", text):
            if tok in ",;:":
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
        self.generator = task.build_generator(models, cfg)
        self.phonemes = Phonemizer()

    def speak(self, text: str) -> bytes:
        """One sentence to 16-bit mono WAV bytes at 22.05 kHz, peaking at -1 dB."""
        import numpy as np

        phones = self.phonemes(text)
        if not phones:
            raise ValueError("nothing to say")
        tokens = self.task.src_dict.encode_line(
            " ".join(phones), add_if_not_exist=False, append_eos=True
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
            wav, rate = self.hub.get_prediction(self.task, self.model, self.generator, sample)
        audio = wav.numpy().astype(np.float32)
        audio = np.concatenate([audio, np.zeros(int(rate * 0.12), np.float32)])  # breath after
        audio *= 0.89 / max(float(np.abs(audio).max()), 1e-3)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        return out.getvalue()


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
