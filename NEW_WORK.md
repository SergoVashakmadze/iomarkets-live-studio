# New work vs pre-existing

**Disclosure.** IoMarkets.tv had a prior interview studio built on other providers, before this
hackathon. This entry is a ground-up rebuild on Meta's stack: every line of code in this repo was
written Oct 27 – Nov 4, 2026. No code was copied from the prior version. Where ideas or prompt
wording carry over, the entry below says so. The demo video labels on screen which parts are new
and which are pre-existing.

The hackathon rules require that judges can tell what was built during the event. This file is
the record. Every entry links to the commits that built it.

## Built during the hackathon (Oct 27 – Nov 4, 2026)

### Oct 27: the packaged segment

- `src/studio/compose.py`: Build segment now makes a programme, not a reel of answers. Each
  answer follows a card with the question it answered (studio background, labelled "AI
  anchor", in the anchor's voice) and carries a lower third with the guest's name and role.
  Parts are joined with ffmpeg's concat filter (any size or audio layout). Text reaches drawtext
  only through files, so names and questions cannot inject into the filter graph.
- `live.py` records which anchor line each guest turn answered.
- Measured live: a 41 s segment (two cards, two answers) built in 7 s.

### Oct 27: the anchor's voice

- `src/studio/tts.py` + `live.py` + page: each anchor line is sent as text at once, then as
  audio sentence by sentence (Microsoft Edge TTS, parallel synthesis); the page plays sentences
  in order as they arrive, stops at once on barge-in, ignores audio for a stopped line, and
  uses the browser's own voice if audio is 3 s late or fails. Only the anchor's own lines are
  sent to Edge TTS, never the guest's words. `STUDIO_VOICE=browser` turns it off.
- Measured live: audio for a line's first sentence 1.8-2.1 s after its text.

### Oct 27: deployment for judges (Modal)

- `deploy/modal_app.py`, `deploy/requirements.txt` (exported from `uv.lock`, checked in CI),
  `docs/DEPLOY.md`: one container with ffmpeg, scaled to zero, secrets from a Modal secret,
  the spend ledger on a Volume. Chart frames capped at 1.4 MB for Modal's 2 MiB WebSocket limit.

### Oct 27: spend ledger and daily cap

- `src/studio/ledger.py`: every Meta call is metered from the usage the API reports (tokens,
  cached tokens, web searches, SAM frames, seconds of audio), priced at Meta's published
  Standard rates, and written to a small ledger. New briefs, interviews and answers are
  refused once today's spend reaches `STUDIO_DAILY_BUDGET_USD` (default $10);
  `GET /api/budget` shows it. Interviews stop at 15 minutes and 12 cut-out answers.
- Why: judges use the live product on our Meta credit, and a full interview costs about $1.30.

### Oct 27: the segment, built while the interview runs

- `src/studio/segment.py` + page: the page records the guest's camera and mic, restarting at
  each turn boundary, and uploads each answer with the offset where the guest began (so the
  first word is kept). Each answer is cut out with SAM 3.1 in the background, two at a time;
  at the end the session drains the cut-outs before closing, and **Build segment** joins the
  answers in turn order into one MP4.
- A consent checkbox gates Go live. Raw uploads are deleted when their cut-out is done; cut
  clips are deleted 30 minutes after the interview ends. Media URLs need the interview's
  unguessable key (and the token when set); only server-made file names are served.
- Measured live: two answers (12 s and 4 s) cut out in 29 s and 22 s, concurrently, while the
  interview carried on; the 16 s segment was ready 17 s after the interview ended.
- Also: `secret rotation` (`docs/SECRETS.md`, `STUDIO_TOKEN_PREV`).

### Oct 27: Scout's editor on Muse Spark Open (open weights)

- `src/studio/meta/open_weights.py`: Muse Spark Open served by Fireworks, over the same
  Responses client. Measured: built-in web search is accepted there but never runs.
- `src/studio/agents/scout.py`: Scout in two stages. Research stays on Muse Spark 1.3 (web
  search, `market_quote`); the editor on Muse Spark Open turns the draft into the anchor's
  brief, adds no facts, and falls back to the draft if it fails or drops a section. It sees
  only public research, never guest media or words.
- "Built with Muse Spark Open" is shown in the page footer and the README (Muse Model License).

### Oct 27: vision fact-check

- `src/studio/agents/factcheck.py`: chart reading (a camera frame to Muse Spark as an image,
  figures back as strict JSON) and Fact-Check (web search plus `market_quote`, a strict verdict
  per figure: supported, contradicted or unverifiable, with the sourced value and a link).
  Only turns containing a figure are checked.
- `live.py`: checks run in the background and never delay the anchor; a contradicted figure
  becomes a note the anchor raises, politely, with the guest's next words.
- Page: camera preview, Show chart (sends one JPEG frame), and a fact-check panel.
- Measured live: chart read 4.8 s after the frame; a spoken figure checked 6-8 s after the
  guest's turn; anchor replies unchanged at 1.3-1.8 s. On a test chart with a planted error
  it flagged the wrong figures and gave the annual report's values with links.

### Oct 27: guest cutout (SAM 3.1)

- `src/studio/cutout.py` + `studio cutout IN OUT [--background IMG]`: normalise any clip
  (WebM included) to H.264 MP4, upload it with a one-hour expiry, stream SAM 3.1 ("person"),
  delete the upload, pick the guest (most mask area), build full-frame mattes from box-local
  masks, and composite the guest over the studio background with ffmpeg.
- Masks are decoded with Meta's `meta-sam-parser` (a dependency, not vendored). Its full parser
  decodes each mask twice in pure Python (~0.76 s a frame); lines are split here to the grammar
  it documents and each mask decoded once, in a process pool, while SAM is still streaming.
  A test checks every mask against Meta's parser.
- Measured: a 12 s clip goes from 251 s to 25 s end to end (SAM itself 1.6x real time); $0.06.
- Test footage was one of IoMarkets.tv's synthetic anchors over a generated background, never
  a real guest; no footage is in the repo.

### Oct 27: the live studio (page, socket, Anchor, barge-in)

- `src/studio/server.py` + `src/studio/web/index.html` (`studio serve`): one page to prepare a
  brief and run a live interview. The guest's mic is resampled to 24 kHz PCM in an
  AudioWorklet and streamed over `/ws/live`; `STUDIO_TOKEN` guards every request when set.
- `src/studio/agents/anchor.py`: the Anchor on Muse Spark, one short spoken line per turn.
- `src/studio/live.py`: turn-taking. A guest turn gets a reply; speaking over the anchor stops
  its playback (barge-in) and the next line knows it was interrupted; a guest who resumes
  before the reply is ready gets one reply to everything they said.
- Measured live end to end: the anchor's line arrives 1.3-2.1 s after the guest stops;
  playback stops 0.7 s after the guest starts over it. Chaining on `previous_response_id`
  took ~10 s a turn against 1-2 s with the history resent, so the Anchor resends it.
- The anchor's voice is the browser's speech synthesis for now, and the page discloses that
  the anchor is AI and its voice synthetic.

### Oct 27: live guest speech (Muse Voice Transcribe)

- `src/studio/asr.py`: realtime ASR session in ENDPOINTING mode: handshake with guest
  keywords, a pacer that holds audio to real time and fills gaps with silence, `endStream` to
  finish. A turn tracker keyed by `turnId` turns server messages into guest-started (flagged as
  a barge-in when the anchor is speaking), partial, paused and final-turn events.
- `studio listen [--file F] [--keyword K]`: the microphone or a file, transcribed turn by turn.
- Measured live: `speechStart` 0.2-0.4 s after the guest starts, final text 0.3-0.7 s after
  they stop; connect plus handshake 1.9 s, so the session opens before the guest speaks.
- Tests replay the recorded session (`tests/fixtures/asr_two_turns_2026-10-27.json`; the audio
  was synthesised with ffmpeg's flite, no real voice).

### Oct 27: Responses client, tool loop, Scout brief

- `src/studio/meta/responses.py`: client for Meta's Responses API. Each call names a role with
  its own `reasoning.effort` and `max_output_tokens`; an empty answer (budget spent on
  reasoning) raises instead of returning blank; 429/500/503 retry with `Retry-After`. Progress
  messages (`phase: "commentary"`) are kept out of the answer text.
- `src/studio/agents/loop.py`: tool loop on `previous_response_id`, pydantic-validated
  arguments (Meta's `strict` is off), bad calls returned to the model as errors, turn cap.
  Built-in `web_search` with `include: ["web_search_call.results"]`, the only way sources come
  back (measured: Spark adds no `url_citation` annotations).
- `src/studio/tools/market.py`: `market_quote(ticker)` function tool.
- `src/studio/agents/scout.py` + `studio brief "<guest, company>"` CLI: a pre-interview brief
  with the web pages it consulted.
- Tests replay a live recording (`tests/fixtures/scout_amd_2026-10-27.json`), so CI needs no key.

Commits: see the `feat/day1-responses-agent-loop` PR.

## Pre-existing, called but not contained here

These are parts of IoMarkets.tv, a pre-launch product of Rainmaker Partners Ltd, built before the
event. This repo calls them over HTTP; their code is not in this repo, and the demo does not
present them as hackathon work.

- The interview show backend (Scout, Anchor, Fact-Check, grader, approval gate) and its API.
- The anchor lip-sync render (MuseTalk).
- Text-to-speech (Edge TTS, Kokoro-82M fallback).
