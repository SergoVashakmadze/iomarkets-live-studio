#!/usr/bin/env bash
# Fill the private Modal Volume `iomarkets-lipsync` for the anchor's lip-sync (once):
#
#   bash deploy/lipsync_setup.sh [path/to/iomarkets.tv-newsroom] [path/to/MuseTalk]
#
# Uploads the anchor's pre-existing media (not in this repo) and face-parse-bisent's weights
# (published on Google Drive, so taken from the workstation's MuseTalk install), then fetches
# MuseTalk's other public weights from Hugging Face on Modal itself (~4 GB, no upload).
set -euo pipefail
cd "$(dirname "$0")/.."
NEWSROOM="${1:-../iomarkets.tv-newsroom}"
MUSETALK="${2:-$HOME/musetalk-local/MuseTalk}"
MODAL=(uv run --no-project --with "modal==1.6.1" modal)
A="$NEWSROOM/services/broadcast/assets"

"${MODAL[@]}" volume create iomarkets-lipsync 2>/dev/null || true
for f in "$A/avatars/teresa_loop.mp4" "$A/avatars/teresa_loop_mask.mp4" \
         "$A/studio_background_iomarkets_tv.png"; do
  "${MODAL[@]}" volume put --force iomarkets-lipsync "$f" "/media/$(basename "$f")"
done
"${MODAL[@]}" volume put --force iomarkets-lipsync \
  "$MUSETALK/models/face-parse-bisent/79999_iter.pth" /models/face-parse-bisent/79999_iter.pth
"${MODAL[@]}" run deploy/modal_app.py::fetch_models
"${MODAL[@]}" volume ls iomarkets-lipsync /models
