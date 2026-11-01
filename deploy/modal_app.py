"""The live studio on Modal, for judges. See docs/DEPLOY.md.

    uvx modal deploy deploy/modal_app.py      # from the repo root

One container, scaled to zero when idle: an interview's answer uploads must reach the
container holding its socket, and one is plenty for judging. Secrets come from the Modal
secret `iomarkets-studio`; the spend ledger lives on a Volume so the daily cap survives
restarts (Modal writes Volume changes back when the container stops).

The anchor (Teresa, a pre-existing HeyGen library avatar, disclosed in the demo video as the
organisers' Nov 1 ruling requires) is lip-synced by MuseTalk (MIT, open source) on an L40S GPU,
as a class with no public URL, scaled to zero after five idle minutes, one container at most.
Opening the studio page with the token wakes it; until it is up, interviews show the anchor still.
`deploy/warm.sh on HOURS` keeps it running for a testing session or judging, and switches itself
off when the hours are up (`cool_down`). Its models and the anchor's media live on the private
Volume `iomarkets-lipsync`, filled once by `deploy/lipsync_setup.sh`; none of them is in this repo.
Her voice is Meta's FastSpeech 2 (LJSpeech, a native US speaker) in the CPU class `Voice` below
(voice/server.py, Python 3.10 for fairseq); MMS-TTS on the web container's CPU is the fallback.
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent

# Teresa's page pictures are git-ignored (scripts/anchor_assets.py builds them), so a deploy from a
# fresh checkout would quietly show the Muse Image anchor instead. It did on Nov 1, mid-testing.
TERESA = ("teresa-studio.jpg", "teresa.png", "teresa-wide.png")
if modal.is_local():
    missing = [n for n in TERESA if not (ROOT / "src" / "studio" / "assets" / n).is_file()]
    if missing:
        raise SystemExit(
            f"Missing {', '.join(missing)} in src/studio/assets/: run "
            "`uv run python scripts/anchor_assets.py` first, or the studio shows the wrong anchor."
        )

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

# MuseTalk's own pinned stack (its README: Python 3.10, torch 2.0.1 on CUDA 11.8, mmcv 2.0.1),
# at the commit the workstation runs. The workstation needed source builds for its Blackwell
# GPU; an L40S takes the published wheels.
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
    # MuseTalk's face detector downloads its weights (86 MB) through torch.hub on first use:
    # keep them on the Volume, or every cold start fetches them again (~7 s).
    .env({"TORCH_HOME": "/vol/torch"})
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

    os.environ.setdefault("STUDIO_TTS", "modal")  # the Voice class below; MMS if it fails
    os.environ.setdefault("STUDIO_LIPSYNC", "modal")  # compose.lipsync calls Lipsync.speak
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


# Shared state that costs nothing to read and never starts a GPU: whether the lip-sync container
# is up ("up"), and until when warm.sh asked to keep it warm ("warm_until", epoch seconds).
lipsync_state = modal.Dict.from_name("iomarkets-lipsync-state", create_if_missing=True)


@app.cls(
    image=lipsync_image,
    # Measured 2026-10-30, 4.3 s of speech, once warm: L4 8.7 s (2.0x real time), L40S 4.8 s
    # (1.1x, as the workstation's RTX 5060 Ti). An L40S keeps the anchor's pauses short.
    gpu="L40S",
    # Per frame the CPU resizes and blends the face (cv2) and libx264 encodes the clip. With no
    # cpu= Modal gave this class ~0.125 of a core, so renders took ~1.2x real time and an H100
    # gained nothing (2026-11-01). 8 cores is about $0.40 an hour more.
    cpu=8.0,
    memory=16384,
    volumes={"/vol": lipsync_volume},
    max_containers=1,  # one anchor, one loop position, and never two GPUs billing at once
    scaledown_window=5 * 60,  # idle five minutes, then off
    timeout=10 * 60,  # per render; a stuck one cannot run up a bill
    startup_timeout=15 * 60,  # the first start prepares the anchor (~2 min)
)
class Lipsync:
    """lipsync/server.py on an L40S, reachable only from this app: it has no public URL, so
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
    import urllib.request

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
    resnet = Path(f"{m}/face-parse-bisent/resnet18-5c106cde.pth")
    if not resnet.exists():  # the image has no curl; urllib verifies TLS as curl would
        url = "https://download.pytorch.org/models/resnet18-5c106cde.pth"
        urllib.request.urlretrieve(url, resnet)
    lipsync_volume.commit()
