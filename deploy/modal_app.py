"""The live studio on Modal, for judges. See docs/DEPLOY.md.

    uvx modal deploy deploy/modal_app.py      # from the repo root

One container, scaled to zero when idle: an interview's answer uploads must reach the
container holding its socket, and one is plenty for judging. Secrets come from the Modal
secret `iomarkets-studio`; the spend ledger lives on a Volume so the daily cap survives
restarts (Modal writes Volume changes back when the container stops).

The anchor's lip-sync (lipsync/server.py) runs beside it on an L4 GPU, scaled to zero when idle.
The studio's page load wakes it; until it answers, interviews show the anchor still. Keep it warm
for a testing session or the judging window with `deploy/warm.sh on` (and `off` after). Its
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

    os.environ.setdefault("STUDIO_LIPSYNC_URL", lipsync.get_web_url())
    return create_app()


@app.function(
    image=lipsync_image,
    gpu="L4",
    secrets=[modal.Secret.from_name("iomarkets-studio")],  # STUDIO_TOKEN guards /speak
    volumes={"/vol": lipsync_volume},
    max_containers=1,  # one anchor, one loop position
    scaledown_window=10 * 60,
    timeout=24 * 60 * 60,
)
@modal.concurrent(max_inputs=4)  # /health while a render runs; renders queue in the server
@modal.web_server(8766, startup_timeout=15 * 60)  # first start prepares the anchor (~2 min)
def lipsync():
    import subprocess

    subprocess.Popen(
        ["python", "/root/lipsync/server.py", "--host", "0.0.0.0", "--port", "8766",
         "--loop", "/vol/media/teresa_loop.mp4", "--mask", "/vol/media/teresa_loop_mask.mp4",
         "--studio", "/vol/media/studio_background_iomarkets_tv.png", "--cache", "/vol/cache"],
        cwd="/musetalk",
    )  # fmt: skip


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
