# Deploying the live studio for judges (Modal)

The app is one FastAPI process with ffmpeg; Meta's models are all hosted, so no GPU is needed.
`deploy/modal_app.py` runs it on Modal as a single container that scales to zero.

## What it costs

| | Rate | Per judge session (10 min interview) |
|---|---|---|
| Modal compute: 4 cores + 4 GiB, while serving and for 20 min after | $0.0472/core-h, $0.008/GiB-h (Modal Starter: $30/month free) | ~$0.13, so about 230 sessions a month inside the free allowance |
| Meta Model API (our credit) | published Standard rates | ~$1.30: SAM ~$0.80, fact-checks ~$0.30, brief ~$0.16, ASR $0.03 |

Meta is the real cost. The app meters it (`studio/ledger.py`) and refuses new work once a
day's spend reaches `STUDIO_DAILY_BUDGET_USD`; the Meta console's spend limit is the backstop.
$10 a day is about 7 full sessions; raise it for the judging window if needed.

## Deploying (operator, about 5 minutes)

```sh
bash deploy/deploy.sh ../iomarkets.tv-newsroom/.env 10
```

The first argument is the `.env` holding `META_API_KEY` (and `FIREWORKS_API_KEY`); the second
is the daily Meta budget in USD. The script:

1. logs in to Modal if needed (`modal token new` opens a browser: the one manual step);
2. creates the Modal secret `iomarkets-studio` from those two keys, a newly generated
   `STUDIO_TOKEN` and the budget; nothing is printed, and the temporary file is shredded;
3. deploys `deploy/modal_app.py` (Modal 1.6.1, pinned);
4. checks the page and `/api/budget`, and writes the judges' link (URL with the token) to
   `~/.config/iomarkets-studio/judges-link.txt`, mode 600.

To ship new code without touching the secret or the judges' link:
`uv run --no-project --with modal==1.6.1 modal deploy deploy/modal_app.py`.

Re-running `deploy.sh` redeploys and rotates the token. Once judges have a link, rotate with overlap
instead (`docs/SECRETS.md`).

## The anchor's lip-sync on a Modal GPU

`lipsync/server.py` runs as the class `Lipsync` on an **L4 GPU** in the same app, with MuseTalk's
own pinned stack (Python 3.10, torch 2.0.1/CUDA 11.8, mmcv 2.0.1) at commit `0a89dec`. The
studio calls it directly (`STUDIO_LIPSYNC=modal`). Modal needs a payment method on the
workspace before it runs GPU functions.

Once, to fill the private Volume `iomarkets-lipsync` (the anchor's media and the face-parsing
weights are uploaded; MuseTalk's other weights are fetched from Hugging Face on Modal):

```sh
bash deploy/lipsync_setup.sh ../iomarkets.tv-newsroom ~/musetalk-local/MuseTalk
```

### No surprise bills

| Guard | What it stops |
|---|---|
| No public URL: the GPU is a class only this app can call | strangers, crawlers or a leaked link starting the GPU |
| The page wakes it only with the token (`index`, test `test_only_the_token_holder_wakes_the_lip_sync_gpu`) | a page load by anyone else costing GPU time |
| `max_containers=1` | two GPUs billing at once |
| `scaledown_window` 5 minutes | an idle GPU running on |
| `timeout` 10 minutes per render | a stuck render running on |
| `warm.sh on HOURS` (default 3, at most 72) ends by itself: `cool_down` checks every 15 minutes | a forgotten "keep warm" |
| The studio's Meta spend cap (`STUDIO_DAILY_BUDGET_USD`, $10 a day) | runaway Meta API spend |

What it costs: the L4 is about $0.80 an hour while it runs, plus a little CPU and memory. An
interview keeps it up for its length plus five minutes: about $0.20 for a 10-minute interview.
`warm.sh on 3` is about $2.40. `cool_down` is a few CPU-seconds four times an hour (cents a
month). Modal's Starter plan includes $30 of usage a month, which covers testing and judging at
these rates. **Set a workspace budget in Modal's settings as the backstop** (the operator, in the
dashboard): it caps everything, whatever happens in code.

```sh
bash deploy/warm.sh on 3   # before a testing session; off by itself after three hours
bash deploy/warm.sh off
```

Without the GPU (not yet up, or none), interviews still work: the anchor is shown still.

## Limits that shaped the setup

- **One container** (`max_containers=1`): answer uploads go to the container holding the
  interview's socket, and its state is in memory.
- **WebSocket messages are capped at 2 MiB** on Modal, so a chart frame is capped at 1.4 MB of
  JPEG (base64 grows it by a third). A 720p frame is 150-300 KB.
- **Cold start**: the first request after 20 idle minutes waits for the container to start.
- **Dependencies** are installed from `deploy/requirements.txt`, exported from `uv.lock`;
  CI fails if the two drift. Regenerate with
  `uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -q > deploy/requirements.txt`.
