#!/usr/bin/env bash
# Fill the private Modal Volume `iomarkets-lipsync` for the anchor's lip-sync (once), in your own
# Modal workspace:
#
#   bash deploy/lipsync_setup.sh
#
# Uploads Teresa's pre-existing media from lipsync/anchor/ (in this repo), then fetches MuseTalk's
# public weights on Modal itself (~4 GB, no upload): from Hugging Face, plus face-parse-bisent's
# weights from a pinned, SHA-256-checked copy (deploy/modal_app.py, fetch_models).
set -euo pipefail
cd "$(dirname "$0")/.."
MODAL=(uv run --no-project --with "modal==1.6.1" modal)

"${MODAL[@]}" volume create iomarkets-lipsync 2>/dev/null || true
for f in lipsync/anchor/teresa_loop.mp4 lipsync/anchor/teresa_loop_mask.mp4 \
         lipsync/anchor/studio_background_iomarkets_tv.png; do
  "${MODAL[@]}" volume put --force iomarkets-lipsync "$f" "/media/$(basename "$f")"
done
"${MODAL[@]}" run deploy/modal_app.py::fetch_models
"${MODAL[@]}" volume ls iomarkets-lipsync /models
