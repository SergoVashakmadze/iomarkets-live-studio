# IoMarkets Live Studio

An entry to the **Meta Global AI Developer Hackathon** (Oct 27 – Nov 4, 2026), problem
statement *Build for Your World*.

A live business-news interview studio: a guest talks to an AI anchor in real time, Meta models
listen, check the facts and cut the guest out of their background, and the result is a
broadcast-ready segment.

**Status:** being built during the hackathon. Nothing here predates Oct 27, 2026.

## What was built during the hackathon

See [`NEW_WORK.md`](NEW_WORK.md). It lists every feature built in the event window and, separately,
every pre-existing service this repo calls but does not contain.

## Try it

```sh
uv sync
cp .env.example .env   # add your META_API_KEY
uv run studio brief "Margherita Della Valle, CEO of Vodafone"
uv run studio listen --keyword Vodafone   # live transcription from the microphone
uv run studio serve                       # the studio page at http://127.0.0.1:8000
uv run pytest          # no key needed: tests replay recorded responses
```

## Meta models used

- **In use:** Muse Spark 1.3 on the Responses API, with built-in web search (Scout, since Oct 27);
  Muse Voice Transcribe, realtime ENDPOINTING mode (live guest speech, since Oct 27);
  Muse Spark 1.3 as the live Anchor (since Oct 27).
- **Planned:** SAM 3.1 (guest cutout) and Muse Spark Open (one agent on open weights).

## Licence

MIT. See [`LICENSE`](LICENSE).
