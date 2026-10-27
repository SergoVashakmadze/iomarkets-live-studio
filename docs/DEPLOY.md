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

## One-time setup (operator)

1. Log in to Modal: `uvx modal token new` (opens a browser).
2. Make a studio token for the judges' link, without it passing through chat:
   `umask 077; python3 -c "import secrets; print(secrets.token_urlsafe(32))" > studio-token.txt`
3. Create the secret in the Modal dashboard (Secrets → Create → Custom), named
   `iomarkets-studio`, with keys `META_API_KEY`, `FIREWORKS_API_KEY`, `STUDIO_TOKEN` (the
   contents of `studio-token.txt`) and `STUDIO_DAILY_BUDGET_USD` (e.g. `10`). Pasting there keeps
   the values out of shell history; never put them on a command line.
4. Deploy from the repo root: `uvx modal deploy deploy/modal_app.py`. Modal prints the URL
   (`https://<workspace>--iomarkets-live-studio-web.modal.run`).
5. The judges' link is `<URL>/?token=<contents of studio-token.txt>`. Then `shred -u studio-token.txt`
   once the link is saved where you submit it.

Rotation of every value above: `docs/SECRETS.md`.

## Limits that shaped the setup

- **One container** (`max_containers=1`): answer uploads go to the container holding the
  interview's socket, and its state is in memory.
- **WebSocket messages are capped at 2 MiB** on Modal, so a chart frame is capped at 1.4 MB of
  JPEG (base64 grows it by a third). A 720p frame is 150-300 KB.
- **Cold start**: the first request after 20 idle minutes waits for the container to start.
- **Dependencies** are installed from `deploy/requirements.txt`, exported from `uv.lock`;
  CI fails if the two drift. Regenerate with
  `uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -q > deploy/requirements.txt`.
