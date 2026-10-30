"""The live studio on Modal, for judges. See docs/DEPLOY.md.

    uvx modal deploy deploy/modal_app.py      # from the repo root

One container, scaled to zero when idle: an interview's answer uploads must reach the
container holding its socket, and one is plenty for judging. Secrets come from the Modal
secret `iomarkets-studio`; the spend ledger lives on a Volume so the daily cap survives
restarts (Modal writes Volume changes back when the container stops).

The anchor's lip-sync (lipsync/server.py) runs beside it on an L4 GPU, as a class with no public
URL, scaled to zero after five idle minutes, one container at most. Opening the studio page with
the token wakes it; until it is up, interviews show the anchor still. `deploy/warm.sh on HOURS`
keeps it running for a testing session or judging, and switches itself off when the hours are
up (`cool_down`). Its
models and the anchor's media live on the private Volume `iomarkets-lipsync`, filled once by
`deploy/lipsync_setup.sh`; none of them is in this repo.
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "fonts-dejavu-core")  # drawtext in the segment needs a font
    .pip_install_from_requirements(str(ROOT / "deploy" / "requirements.txt"))
    .env({"STUDIO_LEDGER": "/data/ledger.json"})
    .add_local_dir(str(ROOT / "src" / "studio"), remote_path="/root/studio")
)

# MuseTalk's own pinned stack (its README: Python 3.10, torch 2.0.1 on CUDA 11.8, mmcv 2.0.1),
# at the commit the workstation runs. The workstation needed source builds for its Blackwell
# GPU; an L4 takes the published wheels.
MUSETALK_COMMIT = "0a89dec"
lipsync_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.0.1",
        "torchvision==0.15.2",
        "torchaudio==2.0.2",
        index_url="https://download.pytorch.org/whl/cu118",
    )
    .pip_install(
        "diffusers==0.30.2",
        "accelerate==0.28.0",
        "numpy==1.23.5",
        "opencv-python-headless==4.9.0.80",
        "soundfile==0.12.1",
        "transformers==4.39.2",
        "huggingface_hub==0.30.2",
        "librosa==0.11.0",
        "einops==0.8.1",
        "omegaconf==2.3.0",
        "ffmpeg-python==0.2.0",
        "mmengine==0.10.4",
    )
    .pip_install(
        "mmcv==2.0.1",
        find_links="https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html",
    )
    .pip_install("mmdet==3.1.0", "mmpose==1.1.0")
    .run_commands(
        "git clone https://github.com/TMElyralab/MuseTalk.git /musetalk",
        f"cd /musetalk && git checkout {MUSETALK_COMMIT}",
        "ln -s /vol/models /musetalk/models",
    )
    .add_local_file(str(ROOT / "lipsync" / "server.py"), remote_path="/root/lipsync/server.py")
)
lipsync_volume = modal.Volume.from_name("iomarkets-lipsync", create_if_missing=True)

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

    os.environ.setdefault("STUDIO_LIPSYNC", "modal")  # compose.lipsync calls Lipsync.speak
    return create_app()


# Shared state that costs nothing to read and never starts a GPU: whether the lip-sync container
# is up ("up"), and until when warm.sh asked to keep it warm ("warm_until", epoch seconds).
lipsync_state = modal.Dict.from_name("iomarkets-lipsync-state", create_if_missing=True)


@app.cls(
    image=lipsync_image,
    gpu="L4",
    volumes={"/vol": lipsync_volume},
    max_containers=1,  # one anchor, one loop position, and never two GPUs billing at once
    scaledown_window=5 * 60,  # idle five minutes, then off
    timeout=10 * 60,  # per render; a stuck one cannot run up a bill
    startup_timeout=15 * 60,  # the first start prepares the anchor (~2 min)
)
class Lipsync:
    """lipsync/server.py on an L4, reachable only from this app: it has no public URL, so
    nothing outside the studio can start (and bill) the GPU."""

    @modal.enter()
    def load(self) -> None:
        import os
        import sys

        os.chdir("/musetalk")  # MuseTalk loads its models from ./models
        sys.path.insert(0, "/root/lipsync")
        import server

        self.studio = server.Studio(
            server.Models(),
            Path("/vol/media/teresa_loop.mp4"),
            Path("/vol/media/teresa_loop_mask.mp4"),
            Path("/vol/media/studio_background_iomarkets_tv.png"),
            Path("/vol/cache"),
        )
        lipsync_volume.commit()  # keep the prepared anchor for the next cold start
        lipsync_state["up"] = True

    @modal.exit()
    def down(self) -> None:
        lipsync_state["up"] = False

    @modal.method()
    def speak(self, audio: bytes, shot: str, start: int | None) -> tuple[bytes, int]:
        """The anchor saying `audio` in `shot`: MP4 bytes and where her loop ended."""
        import subprocess
        import tempfile

        if start is not None:
            self.studio.cursor = start
        with tempfile.TemporaryDirectory() as tmp:
            wav, mp4 = Path(tmp) / "a.wav", Path(tmp) / "out.mp4"
            to_wav = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", "pipe:0"]
            subprocess.run([*to_wav, "-ac", "1", "-ar", "16000", str(wav)], input=audio, check=True)
            result = self.studio.speak(shot, wav, mp4)
            return mp4.read_bytes(), result["cursor"]

    @modal.method()
    def ping(self) -> None:
        """Wake the GPU ahead of an interview (the studio page does, for token holders only)."""


@app.function(schedule=modal.Period(minutes=15), timeout=60)
def cool_down() -> None:
    """Turn 'keep warm' off when its time is up, so a forgotten `warm.sh on` cannot run on.
    A tiny CPU job, four times an hour."""
    import time

    if lipsync_state.get("warm_until", 0) and time.time() > lipsync_state["warm_until"]:
        Lipsync().update_autoscaler(min_containers=0)
        lipsync_state["warm_until"] = 0


@app.function(image=lipsync_image, volumes={"/vol": lipsync_volume}, timeout=60 * 60)
def fetch_models():
    """MuseTalk's public weights onto the Volume, from the sources its download_weights.sh uses
    (face-parse-bisent's 79999_iter.pth is on Google Drive: deploy/lipsync_setup.sh uploads it)."""
    import subprocess

    from huggingface_hub import hf_hub_download

    m = "/vol/models"
    for repo, name, sub in [
        ("TMElyralab/MuseTalk", "musetalkV15/musetalk.json", ""),
        ("TMElyralab/MuseTalk", "musetalkV15/unet.pth", ""),
        ("stabilityai/sd-vae-ft-mse", "config.json", "sd-vae"),
        ("stabilityai/sd-vae-ft-mse", "diffusion_pytorch_model.bin", "sd-vae"),
        ("openai/whisper-tiny", "config.json", "whisper"),
        ("openai/whisper-tiny", "pytorch_model.bin", "whisper"),
        ("openai/whisper-tiny", "preprocessor_config.json", "whisper"),
        ("yzd-v/DWPose", "dw-ll_ucoco_384.pth", "dwpose"),
    ]:
        hf_hub_download(repo, name, local_dir=f"{m}/{sub}" if sub else m)
    subprocess.run(
        ["curl", "-sSfL", "https://download.pytorch.org/models/resnet18-5c106cde.pth",
         "--create-dirs", "-o", f"{m}/face-parse-bisent/resnet18-5c106cde.pth"],
        check=True,
    )  # fmt: skip
    lipsync_volume.commit()
