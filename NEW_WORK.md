# New work vs pre-existing

**Disclosure.** IoMarkets.tv had a prior interview studio built on other providers, before this
hackathon. This entry is a ground-up rebuild on Meta's stack: every line of code in this repo was
written Oct 27 – Nov 4, 2026. No code was copied from the prior version. Where ideas or prompt
wording carry over, the entry below says so. The demo video labels on screen which parts are new
and which are pre-existing.

The hackathon rules require that judges can tell what was built during the event. This file is
the record. Every entry links to the commits that built it.

## Built during the hackathon (Oct 27 – Nov 4, 2026)

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
