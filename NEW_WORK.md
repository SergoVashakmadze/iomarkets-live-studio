# New work vs pre-existing

**Disclosure.** IoMarkets.tv had a prior interview studio built on other providers, before this
hackathon. This entry is a ground-up rebuild on Meta's stack: every line of code in this repo was
written Oct 27 – Nov 4, 2026. No code was copied from the prior version. Where ideas or prompt
wording carry over, the entry below says so. The demo video labels on screen which parts are new
and which are pre-existing.

The hackathon rules require that judges can tell what was built during the event. This file is
the record. Every entry links to the commits that built it.

## Built during the hackathon (Oct 27 – Nov 4, 2026)

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
