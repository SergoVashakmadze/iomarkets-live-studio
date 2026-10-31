# IoMarkets Live Studio

An entry to the **Meta Global AI Developer Hackathon** (building Oct 26 (12:24 PM ET) – Nov 4, 2026), problem
statement *Build for Your World*.

A live interview studio for any topic (business news first: IoMarkets.tv): a guest talks to an
AI anchor in real time, Meta models
listen, check the facts and cut the guest out of their background, and the result is a
broadcast-ready segment.

**Status:** being built during the hackathon. Building opened when the Oct 26 kickoff ended (12:24 PM ET); see
[`NEW_WORK.md`](NEW_WORK.md) for the two scaffold commits made earlier that morning.

## What was built during the hackathon

See [`NEW_WORK.md`](NEW_WORK.md). It lists every feature built in the event window and, separately,
every pre-existing, open-source or hosted piece it builds on.

## Try it

```sh
uv sync
cp .env.example .env   # add META_API_KEY (and FIREWORKS_API_KEY for the open-weights editor)
uv run studio brief "Eliud Kipchoge, marathon runner"   # any guest, any topic
uv run studio listen --keyword Vodafone   # live transcription from the microphone
uv run studio serve                       # the studio page at http://127.0.0.1:8000
# On the page: attach links and a deck for the brief, or press Cold start to improvise.
uv run studio cutout answer.webm out.mp4  # cut the guest into the studio with SAM 3.1
uv run pytest          # no key needed: tests replay recorded responses
```

## Demo

[`docs/DEMO.md`](docs/DEMO.md): choosing the guest, the run sheet, and the consent form.
[`docs/VIDEO.md`](docs/VIDEO.md): the 3-minute video, shot by shot.
[`docs/WRITEUP.md`](docs/WRITEUP.md): the submission write-up, by judging criterion.

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
  **Built with Muse Spark Open.** Meta's MMS-TTS, run by the studio on the CPU, is the anchor's
  voice (since Oct 31).
- **Made with Muse Image:** the anchor's picture and the studio set (`scripts/anchor_art.py`).

## The anchor

Every model the studio calls at runtime is Meta's. The anchor, "Adrian Hale", is fictional: his
picture was made with Muse Image, and his voice is MMS-TTS. He is shown still: the rules allow
only Meta models at runtime, and Meta has no lip-sync model yet. MuseTalk lip-sync, built Oct 30,
was removed on Oct 31.

## Licence

MIT. See [`LICENSE`](LICENSE).
