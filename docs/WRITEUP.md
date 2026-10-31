# IoMarkets Live Studio: submission write-up (draft)

*Indie track, "Build for Your World". Every figure below was measured on the live APIs during
the build and is recorded in `NEW_WORK.md`.*

## In one line

A live interview studio for any topic: a guest talks to an AI anchor in real time; Meta's
models listen, fact-check what the guest says and shows, cut the guest out of their room, and
package a broadcast-ready segment before the guest has left the call.

## The problem (Impact)

A live interview needs a presenter, a researcher, a fact-checker and an editor for every guest.
Local newsrooms, niche channels, schools, clubs and solo creators cannot staff that, so they
publish fewer interviews, check fewer claims, and spend hours editing the ones they do.
IoMarkets Live Studio does all four jobs during the interview itself:

- **Research before air.** Scout writes a one-minute brief on any guest and topic, with dated
  facts, sources, four questions in different styles, and cautions about what is unconfirmed.
- **A real conversation.** The anchor answers in about two seconds and can be interrupted
  mid-sentence, like a person.
- **Fact-checking live.** Every figure, date or record the guest says, or shows on a chart held
  up to the camera, is checked against the web while they talk. A wrong figure reaches the
  anchor, who raises it politely, with the source, on the next turn. Opinions are left alone.
- **The edit is done when the interview ends.** Each answer is cut out of the guest's room as
  the interview goes on; one click joins them into a programme with question cards and lower
  thirds.

It is built for honest journalism: the anchor is labelled as AI everywhere, guardrails keep it
out of politics and war and away from medical, legal or financial advice, the guest's consent
is required before going live, and raw recordings are deleted as soon as they are processed.

## Use of Meta tooling

| Meta model | Role in the studio | Measured |
|---|---|---|
| **Muse Voice Transcribe** (realtime, ENDPOINTING) | Hears the guest live; turn detection drives turn-taking; speech start while the anchor talks is the barge-in signal | barge-in signal 0.2-0.4 s after the guest starts; final text 0.3-0.7 s after they stop |
| **Muse Spark 1.3**, Responses API | The anchor's spoken replies | 1.3-2.1 s from the guest stopping to the anchor's line |
| **Muse Spark 1.3** + built-in **web search** + function tools | Scout's research; Fact-Check's verdicts as strict JSON with sources | a spoken figure checked in 6-8 s |
| **Muse Spark 1.3**, image input + strict JSON | Reads a chart held up to the camera | 2.2 s for the model; 4.8 s frame to figures |
| **SAM 3.1**, hosted, Files API + streaming | Cuts the guest out of each answer | runs at 1.6x real time; a 12 s answer cut out in about 25 s |
| **Muse Spark Open** (open weights, via Fireworks) | Edits Scout's research into the anchor's brief; sees only public research, never the guest | Built with Muse Spark Open |
| **MMS-TTS** (open weights, run by the studio) | The anchor's voice | 0.3-0.8 s a sentence on the CPU |
| **Muse Image** | The anchor's picture and the studio set, made once | |

The page shows a strip of these model roles that light up as each one works, so a viewer can
see the stack in action.

## Technical depth

- **Latency engineering.** Chaining turns on `previous_response_id` cost about 10 s a call; the
  same call with the history resent took 1-2 s (prompt cache). The anchor resends its history;
  reasoning carry-over stays in the tool loop, where it matters.
- **SAM at speed.** Meta's `meta-sam-parser` decodes each mask twice in pure Python (about
  0.76 s a frame). The studio splits SAM's output to the grammar that library documents and
  decodes each mask once, across a process pool, while SAM is still streaming: a 12 s clip went
  from 251 s to 25 s end to end. A test checks every mask against Meta's own parser.
- **Turn-taking.** A guest who resumes before the anchor's reply is ready gets one reply to
  everything they said; a barge-in stops playback at once and the anchor's next line knows it
  was interrupted; fact-checks never hold the anchor up.
- **Voice.** Each line is synthesised sentence by sentence in parallel, so playback starts on the
  first sentence; the page falls back to the browser's voice if audio is late.
- **Safety and cost.** Every Meta call is metered from the API's own usage report at Meta's
  published prices; a daily cap refuses new work once spent. Secrets rotate without downtime.
  Text reaches ffmpeg's drawtext only through files, never the filter graph.
- **Tested.** About 100 tests replay recorded live responses (no key needed), plus real ffmpeg
  runs; CI on every change.

## What was built during the hackathon

Everything in this repository, written from 27 October to 4 November 2026: see `NEW_WORK.md`
for each piece and its commits. IoMarkets.tv had an earlier interview studio on other
providers; this is a ground-up rebuild on Meta's stack, and no code was copied from it. The
anchor's picture and the studio set were made with Muse Image during the event, and his voice
is Meta's MMS-TTS: every model the studio calls is Meta's.

## Try it

- Live: *(judges' link, after deployment)*
- Code: <https://github.com/SergoVashakmadze/iomarkets-live-studio> (MIT)
- Video: *(link, after recording)*
