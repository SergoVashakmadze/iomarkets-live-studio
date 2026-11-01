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
  **Built with Muse Spark Open.** Meta's FastSpeech 2 and MMS-TTS, run by the studio on the CPU, are the
  anchor's voice and its fallback (since Oct 31).
- **Made with Muse Image:** the fallback anchor picture and set (`scripts/anchor_art.py`).

## The anchor

Every Meta model the studio calls at runtime is listed above. The anchor, "Teresa", is an AI presenter and is
labelled as one on the page. Two parts of her are **pre-existing, not built this week**: her picture is an avatar
made earlier with HeyGen, and so is the studio background she sits in. Her voice is Meta's FastSpeech 2
(`voice/server.py`, MMS-TTS as fallback). Her lip-sync is **MuseTalk** v1.5 (open source, MIT), running on one
Modal GPU (`lipsync/server.py`, `deploy/modal_app.py`); an organiser confirmed in writing that both are allowed
(`docs/ORGANISER_RULES.md`). If the lip-sync service is down, the page falls back to a still Teresa and the
text and voice carry on. The earlier still anchor "Alexandra Morgan" (Muse Image) remains as the fallback
picture when Teresa's image files are absent.

The first words take about 8-11 s after the guest stops: the lip-sync renders at roughly real time, so
the studio voices and renders the reply in short pieces and holds the first clip until the rest will not
run dry. After that there are no gaps. Faster options are in `docs/HANDOVER_2026-11-01.md`.

## Licence

MIT. See [`LICENSE`](LICENSE).
