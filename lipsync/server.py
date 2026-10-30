"""The anchor's lip-sync: MuseTalk v1.5 over her moving loop, so head and body move as she talks.

Runs in a MuseTalk checkout's environment (MuseTalk is MIT, github.com/TMElyralab/MuseTalk),
with that checkout as the working directory, since its models load from ./models:

    cd ~/musetalk-local/MuseTalk
    ~/musetalk-local/venv/bin/python "<this repo>/lipsync/server.py"

Like MuseTalk's own realtime_inference.py, the anchor is prepared once from a video: every frame
of her loop (played forwards, then backwards, so it never jumps) gets its face crop, latents and
blend mask, cached on disk. Unlike it, each frame is first composed into the studio (the loop
keyed by its mask over the studio background), and a cursor carries the loop's position from
one sentence to the next, so her movement flows on instead of restarting each sentence.

Two shots, prepared at their own resolution so her face is never upscaled more than needed:
    live   the 4:3 medium shot in the page's anchor box (960x720 out)
    wide   the full studio, 16:9, for the packaged segment (1280x720 out)

API (localhost, one render at a time):
    POST /speak   multipart: audio (MP3/WAV), shot (live | wide), start (optional: the loop
                  position to start from; 0 is her still) -> MP4, picture and sound, with
                  the position where it ended in the X-Cursor header
    GET  /health  -> {"status": "ok", "shots": [...], "cursor": n}
"""

from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import json
import os
import pickle
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import torch

# MuseTalk's checkpoints predate PyTorch 2.6's weights_only=True default.
_load = torch.load
torch.load = lambda *a, **kw: _load(*a, **{"weights_only": False, **kw})

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.getcwd())
from musetalk.utils.audio_processor import AudioProcessor  # noqa: E402
from musetalk.utils.blending import get_image_blending, get_image_prepare_material  # noqa: E402
from musetalk.utils.face_parsing import FaceParsing  # noqa: E402
from musetalk.utils.preprocessing import get_landmark_and_bbox  # noqa: E402
from musetalk.utils.utils import datagen, load_all_model  # noqa: E402
from transformers import WhisperModel  # noqa: E402

FPS = 25
BATCH = 20  # one batch shape: every new shape pays a CUDA warm-up of ~15 s
EXTRA_MARGIN = 10  # v1.5 jaw margin, as realtime_inference.py
# Where each shot sits in the 1920x1080 studio composite (x, y, w, h), and its output size.
# "live" must match SHOT in scripts/anchor_assets.py and the page.
SHOTS = {"live": ((420, 230, 1080, 810), (960, 720)), "wide": ((0, 0, 1920, 1080), (1280, 720))}
Y_OFFSET = 24  # the loop's bottom edge (y 1068) pushed off the frame, as anchor_assets.py

ROOT = Path(__file__).resolve().parent.parent
NEWSROOM = ROOT.parent / "iomarkets.tv-newsroom" / "services" / "broadcast" / "assets"


def read_video(path: Path, gray: bool = False) -> list[np.ndarray]:
    cap, frames = cv2.VideoCapture(str(path)), []
    while True:
        ok, frame = cap.read()
        if not ok:
            return frames
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if gray else frame)


def studio_frames(loop: Path, mask: Path, studio: Path) -> list[np.ndarray]:
    """Each loop frame keyed by its mask over the studio, 1920x1080, BGR."""
    bg = cv2.resize(cv2.imread(str(studio)), (1920, 1080)).astype(np.float32)
    out = []
    for frame, matte in zip(read_video(loop), read_video(mask, gray=True), strict=True):
        a = np.zeros((1080, 1920), np.float32)
        a[Y_OFFSET:] = matte[: 1080 - Y_OFFSET] / 255.0
        fg = np.zeros_like(bg)
        fg[Y_OFFSET:] = frame[: 1080 - Y_OFFSET]
        out.append((fg * a[..., None] + bg * (1 - a[..., None])).astype(np.uint8))
    return out


class Anchor:
    def __init__(self, models: Models, frames: list[np.ndarray], cache: Path) -> None:
        if (cache / "anchor.pkl").exists():
            self.__dict__.update(pickle.loads((cache / "anchor.pkl").read_bytes()))
            return
        cache.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, f in enumerate(frames):
            p = cache / f"{i:05d}.png"
            cv2.imwrite(str(p), f)
            paths.append(str(p))
        coords, imgs = get_landmark_and_bbox(paths, 0)
        last = next(c for c in coords if c != (0.0, 0.0, 0.0, 0.0))
        boxes, latents = [], []
        for c, img in zip(coords, imgs, strict=True):
            x1, y1, x2, y2 = last = c if c != (0.0, 0.0, 0.0, 0.0) else last  # no face: reuse
            y2 = min(y2 + EXTRA_MARGIN, img.shape[0])
            crop = cv2.resize(img[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
            boxes.append((x1, y1, x2, y2))
            latents.append(models.vae.get_latents_for_unet(crop).cpu())
        blends = [
            get_image_prepare_material(img, list(box), fp=models.fp, mode="jaw")
            for img, box in zip(imgs, boxes, strict=True)
        ]
        # Kept once; at() plays them forwards then backwards, so the cycle never jumps.
        self.frames, self.boxes, self.latents, self.blends = imgs, boxes, latents, blends
        for p in paths:
            Path(p).unlink()
        (cache / "anchor.pkl").write_bytes(pickle.dumps(self.__dict__))

    @property
    def cycle(self) -> int:
        return 2 * len(self.frames)

    def at(self, k: int) -> int:
        """The frame shown at step k of the forwards-then-backwards cycle."""
        j = k % self.cycle
        return j if j < len(self.frames) else self.cycle - 1 - j


class Models:
    def __init__(self) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.vae, self.unet, self.pe = load_all_model(
            unet_model_path="./models/musetalkV15/unet.pth",
            vae_type="sd-vae",
            unet_config="./models/musetalkV15/musetalk.json",
            device=self.device,
        )
        self.pe = self.pe.half().to(self.device)
        self.vae.vae = self.vae.vae.half().to(self.device)
        self.unet.model = self.unet.model.half().to(self.device)
        self.dtype = self.unet.model.dtype
        self.timesteps = torch.tensor([0], device=self.device)
        self.audio = AudioProcessor(feature_extractor_path="./models/whisper")
        self.whisper = WhisperModel.from_pretrained("./models/whisper")
        self.whisper = self.whisper.to(device=self.device, dtype=self.dtype).eval()
        self.whisper.requires_grad_(False)
        self.fp = FaceParsing(left_cheek_width=90, right_cheek_width=90)


class Studio:
    def __init__(self, models: Models, loop: Path, mask: Path, studio: Path, cache: Path) -> None:
        self.models = models
        key = hashlib.sha1(b"".join(p.read_bytes()[:1_000_000] for p in (loop, mask, studio)))
        cache = cache / key.hexdigest()[:16]
        full = None
        self.anchors: dict[str, Anchor] = {}
        for name, ((x, y, w, h), _) in SHOTS.items():
            if not (cache / name / "anchor.pkl").exists() and full is None:
                full = studio_frames(loop, mask, studio)
            frames = [f[y : y + h, x : x + w].copy() for f in full] if full else []
            t = time.time()
            self.anchors[name] = Anchor(models, frames, cache / name)
            print(f"[lipsync] {name}: {self.anchors[name].cycle} frames in the cycle, ready "
                  f"in {time.time() - t:.1f}s", file=sys.stderr)  # fmt: skip
        self.cursor = 0  # where the loop is: the next sentence carries on from here
        self.lock = threading.Lock()

    @torch.no_grad()
    def speak(self, shot: str, audio: Path, out: Path) -> dict:
        m, av = self.models, self.anchors[shot]
        size = SHOTS[shot][1]
        with self.lock:
            t0 = time.time()
            feats, length = m.audio.get_audio_feature(str(audio), weight_dtype=m.dtype)
            chunks = m.audio.get_whisper_chunk(
                feats, m.device, m.dtype, m.whisper, length,
                fps=FPS, audio_padding_length_left=2, audio_padding_length_right=2,
            )  # fmt: skip
            n_cycle = av.cycle
            start = self.cursor % n_cycle
            # datagen cycles its list from index 0: hand it the cycle starting at the cursor.
            latents = [av.latents[av.at(start + j)] for j in range(n_cycle)]
            h, w = av.frames[0].shape[:2]
            enc = subprocess.Popen(
                ["ffmpeg", "-y", "-v", "error",
                 "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(FPS),
                 "-i", "pipe:0", "-i", str(audio), "-vf", f"scale={size[0]}:{size[1]}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)],
                stdin=subprocess.PIPE,
            )  # fmt: skip
            i = start
            for whisper_batch, latent_batch in datagen(chunks, latents, BATCH):
                n = latent_batch.shape[0]
                if n < BATCH:  # pad the last batch: one batch shape, one warm-up
                    pad = BATCH - n
                    whisper_batch = torch.cat([whisper_batch, whisper_batch[-1:].repeat(pad, 1, 1)])
                    latent_batch = torch.cat([latent_batch, latent_batch[-1:].repeat(pad, 1, 1, 1)])
                feats_b = m.pe(whisper_batch.to(m.device))
                latent_batch = latent_batch.to(device=m.device, dtype=m.dtype)
                pred = m.unet.model(latent_batch, m.timesteps, encoder_hidden_states=feats_b).sample
                faces = m.vae.decode_latents(pred.to(dtype=m.vae.vae.dtype))[:n]
                for face in faces:
                    k = av.at(i)
                    x1, y1, x2, y2 = av.boxes[k]
                    face = cv2.resize(face.astype(np.uint8), (x2 - x1, y2 - y1))
                    mask, box = av.blends[k]
                    frame = get_image_blending(av.frames[k].copy(), face, av.boxes[k], mask, box)
                    enc.stdin.write(frame.tobytes())
                    i += 1
            enc.stdin.close()
            if enc.wait() != 0:
                raise RuntimeError("ffmpeg failed encoding the clip")
            self.cursor = i % n_cycle
            return {
                "frames": i - start,
                "seconds": round(time.time() - t0, 2),
                "cursor": self.cursor,
            }


def serve(studio: Studio, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(200, {"status": "ok", "shots": list(studio.anchors),
                                 "cursor": studio.cursor})  # fmt: skip
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/speak":
                return self._json(404, {"error": "not found"})
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            msg = email.message_from_bytes(
                f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body,
                policy=email.policy.HTTP,
            )
            parts = {
                p.get_param("name", header="content-disposition"): p.get_payload(decode=True)
                for p in msg.iter_parts()
            }
            shot = (parts.get("shot") or b"live").decode()
            if parts.get("start"):  # carry on from a clip played earlier (or 0: her still)
                studio.cursor = int(parts["start"])
            if not parts.get("audio") or shot not in studio.anchors:
                return self._json(400, {"error": "need audio, and shot live or wide"})
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    wav, mp4 = Path(tmp) / "a.wav", Path(tmp) / "out.mp4"
                    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", "pipe:0",
                                    "-ac", "1", "-ar", "16000", str(wav)],
                                   input=parts["audio"], check=True)  # fmt: skip
                    result = studio.speak(shot, wav, mp4)
                    data = mp4.read_bytes()
            except Exception as e:
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            print(f"[lipsync] {shot}: {result}", file=sys.stderr)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("X-Cursor", str(result["cursor"]))  # where the next clip can start
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    print(f"[lipsync] ready on 127.0.0.1:{port}", file=sys.stderr)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--loop", type=Path, default=NEWSROOM / "avatars" / "teresa_loop.mp4")
    ap.add_argument("--mask", type=Path, default=NEWSROOM / "avatars" / "teresa_loop_mask.mp4")
    ap.add_argument("--studio", type=Path, default=NEWSROOM / "studio_background_iomarkets_tv.png")
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "iomarkets-lipsync")
    args = ap.parse_args()
    t = time.time()
    models = Models()
    studio = Studio(models, args.loop, args.mask, args.studio, args.cache)
    # Warm up: the first render pays CUDA's start-up, so the first guest does not.
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "silence.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                        "-t", "1", str(wav)], check=True)  # fmt: skip
        for shot in studio.anchors:
            studio.speak(shot, wav, Path(tmp) / f"{shot}.mp4")
    studio.cursor = 0
    print(f"[lipsync] models, anchor and warm-up in {time.time() - t:.0f}s", file=sys.stderr)
    serve(studio, args.port)


if __name__ == "__main__":
    main()
