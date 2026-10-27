# Secrets and rotation

Every secret this repo reads, by name, and how to rotate it without downtime. Values never go
in the repo, the chat or a form field: generate a new value into a `umask 077` file, paste it
where it belongs, then `shred -u` the file.

| Name | What it is | Where it lives | Two live at once? |
|---|---|---|---|
| `META_API_KEY` | Meta Model API key (named `iomarkets-hackathon` in the console): Muse Spark, Voice Transcribe, SAM 3.1, Files | `.env` locally; the host's secret store when deployed | Yes: a project can hold several keys |
| `FIREWORKS_API_KEY` | Fireworks key for Muse Spark Open (Scout's editor). Optional | same | Yes |
| `STUDIO_TOKEN` | Shared token the page passes as `?token=`; the app checks it itself | same | Yes, via `STUDIO_TOKEN_PREV` |
| `STUDIO_TOKEN_PREV` | The previous `STUDIO_TOKEN`, accepted only during a rotation | same | n/a |

`META_API_BASE_URL` and `META_MODEL` are configuration, not secrets.

## Rotating a provider key (`META_API_KEY`, `FIREWORKS_API_KEY`)

1. Create a second key in the provider console (Meta: dev.meta.ai → project → API keys;
   Fireworks: account → API keys). Write it to a `umask 077` file.
2. Paste it into `.env` (or the host's secret store) in place of the old value; restart the app.
3. Check one real request: `uv run studio brief "<any listed company>"` for Meta, and the
   output line ends "Built with Muse Spark Open" for Fireworks.
4. Revoke the old key in the console. `shred -u` the file.

## Rotating `STUDIO_TOKEN` (the app verifies it, so it overlaps in code)

1. Generate: `umask 077; python3 -c "import secrets; print(secrets.token_urlsafe(32))" > token.txt`.
2. Set `STUDIO_TOKEN_PREV` to the current token and `STUDIO_TOKEN` to the new one; restart.
   Both now work.
3. Give producers the new link (`…/?token=<new>`); check it loads and a brief runs.
4. Once nobody uses the old link (a token has no expiry, so this is a judgement call: the end of
   the day's sessions), delete `STUDIO_TOKEN_PREV` and restart. `shred -u token.txt`.
