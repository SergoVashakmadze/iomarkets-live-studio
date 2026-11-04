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

**The anchor is Teresa, in the IoMarkets TV studio, as in the video.** Both are pre-existing
IoMarkets.tv media, declared as such (`NEW_WORK.md`, and the video's opening line) and allowed in
writing by an organiser (`docs/ORGANISER_RULES.md`). They are in the repo, so a plain clone shows
them. Her voice is Meta's MMS-TTS on your CPU. For the FastSpeech 2 voice heard in the video, run
`voice/server.py` as its docstring says (its own Python 3.10 environment) and start the studio
with `STUDIO_TTS_URL=http://127.0.0.1:8767`.

> **Lip-sync needs a GPU or a Modal account.** Teresa's lip movement is rendered by MuseTalk
> (open source, MIT), which needs an NVIDIA GPU. On an ordinary laptop she speaks every line with
> voice and text but **without moving her lips**. To see the lip-sync, either:
> - **your own NVIDIA GPU**: set up a MuseTalk checkout, run
>   `lipsync/server.py` in it as its docstring says (it reads Teresa's media from
>   `lipsync/anchor/`), and start the studio with `STUDIO_LIPSYNC_URL=http://127.0.0.1:8766`; or
> - **your own Modal account** (level 3 below), which runs it on an L40S GPU for you.

**A guest on another machine.** Camera and microphone need HTTPS everywhere except localhost. Set a
`STUDIO_TOKEN` in `.env` (any long random string), run `cloudflared tunnel --url
http://127.0.0.1:8000` (cloudflared 2026.10.2 or later), and send the guest
`https://<tunnel>/?token=<STUDIO_TOKEN>`.

### 3. Your own Modal account: the hosted studio, with lip-sync

`docs/DEPLOY.md` deploys the same app, lip-sync included, to your Modal workspace on your keys:

```sh
uv run --no-project --with modal==1.6.1 modal token new   # once: log in to your Modal account
bash deploy/lipsync_setup.sh             # once: Teresa's media and MuseTalk's public weights
bash deploy/deploy.sh path/to/your.env 10   # your keys; 10 = your daily Meta budget in USD
```

It prints the path of a private file holding your link (URL with its token). Open it in Chrome; the
first interview waits about two minutes while the GPU starts. Cost on your Modal bill: about
$2.45 an hour while the L40S is up (it stops five idle minutes after an interview), plus about
$0.13 of CPU a session; Meta usage is as in level 2. The studio caps GPU spend at
`STUDIO_GPU_DAILY_BUDGET_USD` (default $5 a day), then shows Teresa still.

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
confirmed in writing that both are allowed (`docs/ORGANISER_RULES.md`). Her pictures and lip-sync
media are in the repo (`src/studio/assets/teresa*`, `lipsync/anchor/`). The Muse Image anchor
"Alexandra Morgan" remains as the fallback if they are removed. Without a GPU, or when the
lip-sync service is down, Teresa is shown still, and the text and voice carry on.

## Licence

MIT. See [`LICENSE`](LICENSE).
