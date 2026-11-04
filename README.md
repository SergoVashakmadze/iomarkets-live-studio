# IoMarkets Live Studio

An entry to the **Meta Global AI Developer Hackathon** (building Oct 26 (12:24 PM ET) – Nov 4, 2026), problem
statement *Build for Your World*.

A live interview studio for any topic (business news first: IoMarkets.tv): a guest talks to an
AI anchor in real time, Meta models
listen, check the facts and cut the guest out of their background, and the result is a
broadcast-ready segment.

**Status:** submitted on 2 Nov 2026. Demo video: <https://youtu.be/0N31qRkWRH4>. There is no
hosted link. The studio runs on the API keys of whoever runs it, so judges run it themselves (below).

## What was built during the hackathon

See [`NEW_WORK.md`](NEW_WORK.md). It lists every feature built in the event window and, separately,
every pre-existing, open-source or hosted piece it builds on.

## Run it on your own keys (judges)

Nothing here uses the author's credits. The hosted copy is switched off, and the code never ships a
key: every Meta call is billed to the `META_API_KEY` in **your** `.env`. Three levels, cheapest first.

### 1. No key, no cost: the test suite (2 minutes)

```sh
git clone https://github.com/SergoVashakmadze/iomarkets-live-studio && cd iomarkets-live-studio
uv sync               # Python 3.12; uv installs it if missing (https://docs.astral.sh/uv/)
uv run pytest         # 158 tests, offline: they replay recorded Meta responses
```

The tests drive the live loop end to end (`tests/test_server.py`, `tests/test_live.py`): the guest's
speech arrives, the anchor answers, the guest talks over her, a figure is fact-checked. Others cover
the brief, the SAM 3.1 cut-out and the packaged segment. Meta's responses are replayed from
recordings of this repo's own calls (`tests/fixtures/`) or stubbed in the test. `uv run studio serve`
also works with no key: the page opens, and pressing Prepare brief or Go live says that a key is
needed.

### 2. Your own Meta key: the full studio on your laptop (10 minutes)

You need ffmpeg (`apt install ffmpeg` / `brew install ffmpeg`), Chrome, a webcam and a microphone.

1. Get a Meta Model API key: <https://dev.meta.ai>, then your project, then **API keys**. The studio
   calls Muse Spark 1.3, Muse Voice Transcribe and SAM 3.1 with it.
2. `cp .env.example .env`, and paste the key after `META_API_KEY=`. `.env` is git-ignored.
3. Optional: `FIREWORKS_API_KEY=` (your own Fireworks key) turns on the Muse Spark Open editor for
   the brief. Without it the brief is used unedited and everything else works.
4. Run it:

   ```sh
   uv run studio serve        # open http://127.0.0.1:8000 in Chrome
   ```

   Type a guest (for example `Eliud Kipchoge, marathon runner`), press **Prepare brief** (about 30 s,
   web-searched and cited), then **Go live** and allow camera and microphone. **Cold start** skips the
   brief, and research then runs during the interview. Talk to the anchor. Hold a chart up to the
   camera and press **Show chart** to have it read and fact-checked. **End interview**, then
   **Build segment**, packages the broadcast segment with the guest cut out into the studio.

5. Without the browser: `uv run studio brief "Eliud Kipchoge, marathon runner"`,
   `uv run studio listen --keyword Kipchoge` (live transcription from the microphone), and
   `uv run studio cutout answer.webm out.mp4` (SAM 3.1 cuts the guest out of a clip).

**What it costs you:** about $1.30 of Meta usage for a 10-minute interview (SAM about $0.80,
fact-checks $0.30, brief $0.16, transcription $0.03), at Meta's published rates. The studio meters
its own spend and refuses new briefs and interviews once a UTC day reaches
`STUDIO_DAILY_BUDGET_USD` (default $10, set in `.env`). The page's top bar shows today's spend against that cap. Nothing runs
on a GPU locally.

**What looks different from the video.** Two things in the video are pre-existing media that are
not in this repo, because they are not ours to redistribute: Teresa (a HeyGen library avatar) and
the IoMarkets TV studio background. A local run shows the fallback anchor, "Alexandra Morgan", and
her set, both made with Muse Image during the event (`scripts/anchor_art.py`). She is shown still,
because MuseTalk lip-sync needs a GPU service (level 3). The voice is Meta's MMS-TTS on your CPU.
For the FastSpeech 2 voice heard in the video, run `voice/server.py` as its docstring says (its own
Python 3.10 environment) and start the studio with `STUDIO_TTS_URL=http://127.0.0.1:8767`.

**A guest on another machine.** Camera and microphone need HTTPS everywhere except localhost. Set a
`STUDIO_TOKEN` in `.env` (any long random string), run `cloudflared tunnel --url
http://127.0.0.1:8000` (cloudflared 2026.10.2 or later), and send the guest
`https://<tunnel>/?token=<STUDIO_TOKEN>`.

### 3. Your own Modal account: the hosted studio, with lip-sync

`docs/DEPLOY.md` deploys the same app to Modal: `bash deploy/deploy.sh path/to/your.env 10`, where
the `.env` holds your keys and `10` is your daily Meta budget in USD. It runs in your Modal
workspace, on your keys, and prints your own private link. Lip-sync of Teresa also needs her
pre-existing media on a Modal Volume (`deploy/lipsync_setup.sh`), which the repo does not hold, so
for judging levels 1 and 2 are the practical routes and the video shows the lip-synced version.

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
- **Open source, not Meta:** MuseTalk v1.5 (MIT) lip-syncs the anchor, allowed in writing by an
  organiser (`docs/ORGANISER_RULES.md`).

## The anchor

The anchor is an AI presenter and the page labels her as one. In the video and the hosted studio
she is "Teresa". Two parts of her are **pre-existing, not built this week**: her picture is an avatar
made earlier with HeyGen, and the studio background she sits in was made earlier too. Her voice is
Meta's FastSpeech 2 (`voice/server.py`, with MMS-TTS as the fallback). Her lip-sync is **MuseTalk**
v1.5 (open source, MIT) on one Modal GPU (`lipsync/server.py`, `deploy/modal_app.py`). An organiser
confirmed in writing that both are allowed (`docs/ORGANISER_RULES.md`). When Teresa's image files are
absent, as in a fresh clone, the page shows the Muse Image anchor "Alexandra Morgan" instead. When
the lip-sync service is down, the anchor is shown still, and the text and voice carry on.

## Licence

MIT. See [`LICENSE`](LICENSE).
