#!/usr/bin/env bash
# Keep the anchor's lip-sync GPU running for a while, or let it go now:
#
#   bash deploy/warm.sh on [HOURS]   # default 3; switches itself off after (cool_down, every 15 min)
#   bash deploy/warm.sh off
#
# An L40S kept warm costs about $1.95 an hour. Without `on`, it runs only while interviews use it
# and five idle minutes after. A redeploy also resets it to off.
set -euo pipefail
case "${1:-}" in on|off) ;; *) echo "usage: $0 on [HOURS] | off" >&2; exit 2 ;; esac
uv run --no-project --with "modal==1.6.1" python - "$1" "${2:-3}" <<'PY'
import sys, time
import modal
mode, hours = sys.argv[1], float(sys.argv[2])
if mode == "on" and not 0 < hours <= 72:
    sys.exit("HOURS must be between 0 and 72")
state = modal.Dict.from_name("iomarkets-lipsync-state", create_if_missing=True)
gpu = modal.Cls.from_name("iomarkets-live-studio", "Lipsync")()
if mode == "on":
    state["warm_until"] = time.time() + hours * 3600
    gpu.update_autoscaler(min_containers=1)
    print(f"lip-sync GPU kept warm for {hours:g} h (about ${1.95 * hours:.2f}), then off by itself")
else:
    state["warm_until"] = 0
    gpu.update_autoscaler(min_containers=0)
    print("lip-sync GPU: off when idle (five minutes)")
PY
