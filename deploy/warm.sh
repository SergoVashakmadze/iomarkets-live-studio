#!/usr/bin/env bash
# Keep the anchor's lip-sync GPU running (on) or let it scale to zero when idle (off):
#
#   bash deploy/warm.sh on     # before a testing session or for the judging window
#   bash deploy/warm.sh off    # after: an idle L4 costs about $0.80 an hour
#
# Takes effect at once and lasts until the next deploy, which resets it to off.
set -euo pipefail
case "${1:-}" in on) N=1 ;; off) N=0 ;; *) echo "usage: $0 on|off" >&2; exit 2 ;; esac
uv run --no-project --with "modal==1.6.1" python - "$N" <<'PY'
import sys
import modal
fn = modal.Function.from_name("iomarkets-live-studio", "lipsync")
fn.update_autoscaler(min_containers=int(sys.argv[1]))
print("lip-sync GPU:", "kept warm" if sys.argv[1] == "1" else "scales to zero when idle")
PY
