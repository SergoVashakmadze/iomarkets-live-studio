"""The live studio on Modal, for judges. See docs/DEPLOY.md.

    uvx modal deploy deploy/modal_app.py      # from the repo root

One container, scaled to zero when idle: an interview's answer uploads must reach the
container holding its socket, and one is plenty for judging. Secrets come from the Modal
secret `iomarkets-studio`; the spend ledger lives on a Volume so the daily cap survives
restarts (Modal writes Volume changes back when the container stops).

The anchor is a Muse Image still voiced by Meta's MMS-TTS on this container's CPU: no GPU.
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

    from studio.server import create_app

    return create_app()
