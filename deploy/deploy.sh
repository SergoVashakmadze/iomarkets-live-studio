#!/usr/bin/env bash
# Deploy the live studio to Modal for judges. Run from anywhere:
#
#   bash deploy/deploy.sh [path/to/.env] [daily budget in USD]
#
# The .env must hold META_API_KEY (and FIREWORKS_API_KEY for the open-weights editor). Values
# are copied into the Modal secret `iomarkets-studio` without being printed. A new STUDIO_TOKEN
# is generated; the judges' link (URL + token) is written to a private file, not the screen.
# Re-running redeploys and rotates the token (see docs/SECRETS.md for overlap if judges have
# the old link already).
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."
ENV_FILE="${1:-.env}"
BUDGET="${2:-10}"
MODAL=(uv run --no-project --with "modal==1.6.1" modal)
OUT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/iomarkets-studio"
LINK_FILE="$OUT_DIR/judges-link.txt"

grep -q '^META_API_KEY=.' "$ENV_FILE" 2>/dev/null \
  || { echo "No META_API_KEY in $ENV_FILE. Pass the .env that holds it." >&2; exit 1; }

echo "1/4 Modal login"
"${MODAL[@]}" token info >/dev/null 2>&1 || "${MODAL[@]}" token new

echo "2/4 Secret iomarkets-studio (values not shown)"
mkdir -p "$OUT_DIR"
TMP="$(mktemp -d)"
trap 'find "$TMP" -type f -exec shred -u {} + 2>/dev/null; rm -rf "$TMP"' EXIT
TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
{
  grep -E '^(META_API_KEY|FIREWORKS_API_KEY)=' "$ENV_FILE"
  echo "STUDIO_TOKEN=$TOKEN"
  echo "STUDIO_DAILY_BUDGET_USD=$BUDGET"
} > "$TMP/secret.env"
"${MODAL[@]}" secret create iomarkets-studio --from-dotenv "$TMP/secret.env" --force >/dev/null

echo "3/4 Deploy (first build takes a few minutes)"
"${MODAL[@]}" deploy deploy/modal_app.py | tee "$TMP/deploy.log"
URL="$(grep -oE 'https://[a-zA-Z0-9.-]+\.modal\.run' "$TMP/deploy.log" | tail -1)"
[ -n "$URL" ] || { echo "No URL in the deploy output; see above." >&2; exit 1; }
echo "$URL/?token=$TOKEN" > "$LINK_FILE"

echo "4/4 Check (a cold start can take a minute)"
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 180 "$URL/?token=$TOKEN" || true)"
budget="$(curl -sS --max-time 60 "$URL/api/budget?token=$TOKEN" || true)"
echo "Page: HTTP $code   Budget: $budget"
echo "Judges' link saved to $LINK_FILE (keep it private; it carries the token)."
