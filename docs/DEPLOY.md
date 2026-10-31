# Deploying the live studio for judges (Modal)

The app is one FastAPI process with ffmpeg; Meta's models are all hosted, so no GPU is needed.
`deploy/modal_app.py` runs it on Modal as a single container that scales to zero.

## What it costs

| | Rate | Per judge session (10 min interview) |
|---|---|---|
| Modal compute: 4 cores + 4 GiB, while serving and for 20 min after | $0.0472/core-h, $0.008/GiB-h (this workspace's Starter plan includes $1/month) | ~$0.13, so about 7 sessions a month inside the $1 allowance |
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

**Off since 2026-10-31** (the anchor is a Muse Image still; see `docs/ORGANISER_RULES.md`).
Nothing below runs unless the secret sets `STUDIO_LIPSYNC=modal`.

`lipsync/server.py` runs as the class `Lipsync` on an **L40S GPU** in the same app, with MuseTalk's
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
| GPU spend is metered (render time at $2.10/hour, plus 5 idle minutes per interview) and capped at $5 a day (`STUDIO_GPU_DAILY_BUDGET_USD`); past it the anchor is shown still and page loads stop waking the GPU | a busy day of testing running up the GPU |
| The daily total (`STUDIO_DAILY_BUDGET_USD`, $10: Meta and GPU together) refuses new briefs and interviews once spent | runaway spend of any kind |
| An interview ends by itself after 3 minutes with no one speaking (`IDLE_END_S`), and after 15 minutes in any case | a forgotten tab keeping the microphone, transcription and GPU busy |

Measured 2026-10-30, 4.3 s of speech once warm: L4 8.7 s (2.0x real time), **L40S 4.8 s
(1.1x)**, as fast as the workstation, so the L40S it is. A cold start with everything cached took
46 s; the very first start ever (image, models, preparing the anchor) took 11 minutes, once.

What it costs: the L40S is about $1.95 an hour while it runs, plus a little CPU and memory. An
interview keeps it up for its length plus five minutes: about $0.50 for a 10-minute interview.
`warm.sh on 3` is about $5.85. `cool_down` is a few CPU-seconds four times an hour (cents a
month). This workspace's Starter plan includes **$1.00** of compute a month (Modal's billing
page, 2026-10-30; not $30 as an earlier version of this guide said), with a usage limit of $1
until a payment method is added: without a card nothing can be charged. After adding one, **set
the usage limit** (Settings, Usage & billing, Usage limit) as the backstop: it caps everything,
whatever happens in code.

```sh
bash deploy/warm.sh on 3   # before a testing session (~$5.85); off by itself after three hours
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
