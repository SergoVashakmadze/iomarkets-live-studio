# IoMarkets Live Studio

An entry to the **Meta Global AI Developer Hackathon** (Oct 27 – Nov 4, 2026), problem
statement *Build for Your World*.

A live interview studio for any topic (business news first: IoMarkets.tv): a guest talks to an
AI anchor in real time, Meta models
listen, check the facts and cut the guest out of their background, and the result is a
broadcast-ready segment.

**Status:** being built during the hackathon. Nothing here predates Oct 27, 2026.

## What was built during the hackathon

See [`NEW_WORK.md`](NEW_WORK.md). It lists every feature built in the event window and, separately,
every pre-existing service this repo calls but does not contain.

## Try it

```sh
uv sync
cp .env.example .env   # add META_API_KEY (and FIREWORKS_API_KEY for the open-weights editor)
uv run studio brief "Eliud Kipchoge, marathon runner"   # any guest, any topic
uv run studio listen --keyword Vodafone   # live transcription from the microphone
uv run studio serve                       # the studio page at http://127.0.0.1:8000
uv run studio cutout answer.webm out.mp4  # cut the guest into the studio with SAM 3.1
uv run pytest          # no key needed: tests replay recorded responses
```

## Demo

[`docs/DEMO.md`](docs/DEMO.md): choosing the guest, the run sheet, and the consent form.
[`docs/VIDEO.md`](docs/VIDEO.md): the 3-minute video, shot by shot.

## Deploying

See [`docs/DEPLOY.md`](docs/DEPLOY.md) (Modal, one container, about $0.13 of compute per judge
session; Meta usage, about $1.30 a session, is metered and capped per day).

## Secrets

See [`docs/SECRETS.md`](docs/SECRETS.md): every secret by name and how to rotate each one
without downtime.

## Meta models used

- **In use:** Muse Spark 1.3 on the Responses API, with built-in web search (Scout, since Oct 27);
  Muse Voice Transcribe, realtime ENDPOINTING mode (live guest speech, since Oct 27);
  Muse Spark 1.3 as the live Anchor (since Oct 27); SAM 3.1, hosted, for the guest cutout,
  decoded with Meta's `meta-sam-parser` (SAM License) (since Oct 27); Muse Spark 1.3 with image
  input and strict JSON for chart reading, and with web search for Fact-Check (since Oct 27).
- **Open weights:** Muse Spark Open, served by Fireworks, edits Scout's brief (since Oct 27).
  **Built with Muse Spark Open.**

## Not Meta

The anchor's voice is Microsoft Edge text-to-speech (Meta has no speech-synthesis model); it
only ever receives the anchor's own lines.

## Licence

MIT. See [`LICENSE`](LICENSE).
