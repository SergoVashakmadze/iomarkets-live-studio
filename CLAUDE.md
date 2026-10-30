# iomarkets-live-studio: working notes

Entry to the Meta Global AI Developer Hackathon (building opened Oct 26, 12:24 PM ET, at the end of the kickoff; ends Nov 4, 2026). The build plan lives in
the private repo `iomarkets.tv-newsroom`, `docs/HACKATHON_PLAN_2026-10-26_meta.md` §9. Every line of
code here must be written in the event window and recorded in `NEW_WORK.md`.

## Cloudflare Tunnel and TLS: the eMudhra certificate compromise (2026-10-19)

Eight eMudhra (emSign) intermediate certificates have publicly recoverable private keys, so anyone
can mint certificates with them that impersonate any site. Browsers block them; other software
only stops trusting them once it is updated. Cloudflare's write-up:
<https://blog.cloudflare.com/emudhra-certificate-compromise/>.

1. **cloudflared must be 2026.10.2 or later** before you start any tunnel, including a quick tunnel
   (`cloudflared tunnel --url …`) for a demo URL, a webhook, or the guest's HTTPS camera and mic
   page. Check with `cloudflared --version`. On 2026-10-26 the laptop and the VPS tunnel
   (`api.iomarkets.tv`) were both upgraded to 2026.10.4. With Docker, pin
   `cloudflare/cloudflared:2026.10.3` or newer; restarting an old container keeps the old binary.
   If `cloudflared update` fails (it did on 10-26), download `cloudflared-linux-amd64` from the
   GitHub releases page.
2. **Never get past a TLS error by turning verification off.** No `noTLSVerify` in a tunnel
   config, no `verify=False` in httpx, no `NODE_TLS_REJECT_UNAUTHORIZED=0`, no `curl -k`. A
   certificate error now means the other side has an emSign chain. Replace that certificate.
3. **Python trust store:** when adding `certifi`, or anything that pulls it in (httpx, requests),
   resolve to the newest release; `certifi>=2026.10.23` carries fewer emSign roots than 2026.10.19. Never
   hand-add emSign roots or intermediates to any trust store.

Background and the VPS upgrade steps: `iomarkets.tv-newsroom`,
`docs/HANDOVER_2026-10-26_cloudflared-emudhra.md`.
