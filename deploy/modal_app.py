"""The live studio on Modal, for judges. See docs/DEPLOY.md.

    uvx modal deploy deploy/modal_app.py      # from the repo root

One container, scaled to zero when idle: an interview's answer uploads must reach the
container holding its socket, and one is plenty for judging. Secrets come from the Modal
secret `iomarkets-studio`; the spend ledger lives on a Volume so the daily cap survives
restarts (Modal writes Volume changes back when the container stops).

The anchor is a Muse Image still. Her voice is Meta's FastSpeech 2 (LJSpeech, a native US
speaker) in the CPU class `Voice` below (voice/server.py, Python 3.10 for fairseq); MMS-TTS on the
web container's CPU is the fallback. No GPU.
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "fonts-dejavu-core")  # drawtext in the segment needs a font
    # CPU torch first: requirements.txt pins torch==...+cpu, which only that index serves.
    .pip_install("torch==2.15.0", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install_from_requirements(str(ROOT / "deploy" / "requirements.txt"))
    # The anchor's voice, Meta's MMS-TTS: baked into the image, so a cold start never downloads it.
    .run_commands(
        'python -c "from transformers import AutoTokenizer, VitsModel; '
        "AutoTokenizer.from_pretrained('facebook/mms-tts-eng'); "
        "VitsModel.from_pretrained('facebook/mms-tts-eng')\""
    )
    .env({"STUDIO_LEDGER": "/data/ledger.json"})
    .add_local_dir(str(ROOT / "src" / "studio"), remote_path="/root/studio")
)

# The voice service's own image: fairseq 0.12 needs Python 3.10. The model, its vocoder and the
# CMU Pronouncing Dictionary are fetched at build time, so a cold start downloads nothing.
voice_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("libsndfile1", "build-essential")  # fairseq 0.12.2 builds from source
    # uv, not pip: pip refuses omegaconf 2.0.6 (fairseq's pin) over its old metadata.
    .uv_pip_install(
        requirements=[str(ROOT / "voice" / "requirements.txt")],
        extra_index_url="https://download.pytorch.org/whl/cpu",
        extra_options="--index-strategy unsafe-best-match",
    )
    .run_commands(
        "python -c \"import nltk; nltk.download('cmudict', download_dir='/usr/share/nltk_data')\""
    )
    .add_local_file(
        str(ROOT / "voice" / "server.py"), remote_path="/root/voice_server.py", copy=True
    )
    .run_commands("cd /root && python -c 'import voice_server; voice_server.Voice()'")
)

app = modal.App("iomarkets-live-studio")
ledger_volume = modal.Volume.from_name("iomarkets-studio-ledger", create_if_missing=True)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("iomarkets-studio")],
    volumes={"/data": ledger_volume},
    cpu=4.0,
    memory=4096,
    max_containers=1,
    scaledown_window=20 * 60,
    timeout=60 * 60,
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web():
    import os

    from studio.server import create_app

    os.environ.setdefault("STUDIO_TTS", "modal")  # the Voice class below; MMS if it fails
    return create_app()


@app.cls(
    image=voice_image,
    cpu=8.0,  # 4 cores: 1.8-2.3 s a sentence; the anchor's first words wait on this
    memory=4096,
    max_containers=2,
    scaledown_window=20 * 60,  # as the web container: warm for the whole session
    timeout=60,
)
class Voice:
    """The anchor's voice, Meta's FastSpeech 2: text (already written for the ear) to WAV.
    No public URL: only the studio calls it."""

    @modal.enter()
    def load(self) -> None:
        import voice_server

        self.voice = voice_server.Voice()

    @modal.method()
    def speak(self, text: str) -> bytes:
        return self.voice.speak(text)
