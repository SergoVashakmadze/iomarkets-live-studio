# Organiser rulings (Discord, 2026-10-27)

What the organisers said about this entry, and where the repo stands against each point.

## The answers

From Cerebral Valley, confirmed by Adam Blumenfeld ("p accurate"):

- Starting fresh is preferred. Building on existing work is allowed only if the submitted repo
  is a standalone public extract holding only work done during the event. No pre-hackathon code
  or git history; rewrite pre-kickoff scaffolding instead of copying it in.
- Building opened when the Oct 26 kickoff ended (hacking announced 12:24 PM ET). Anything
  written before then counts as pre-existing.
- Open-source dependencies and pre-existing public datasets are fine if labelled. The video
  must open with one line stating what was pre-existing and what was built this week.
- Track is chosen in the submission form. Startup needs an incorporated company with an EIN or
  the national equivalent; otherwise Indie.
- Non-Meta models may be used alongside Meta's, but Meta's must be a real part of the project.
  **Superseded Oct 31:** every model called at runtime must be Meta's (below).

Adam added: everything you build off of must be open source and clearly disclosed.

## Answer to our three questions (Discord, 2026-10-31)

The reply (it deferred the track question to the organisers, so it may not be an organiser's
own ruling):

1. A pre-existing HeyGen avatar is not open source: replace it with an open-source or self-made
   asset, or leave it out. **Done:** the anchor is a Muse Image picture made Oct 31.
2. Every model called at runtime must be Meta's, so Edge TTS goes (Kokoro would not be allowed
   either); a built-in OS or browser voice, or Meta's MMS-TTS run ourselves, is fine. **Done:**
   MMS-TTS; the page's fallback uses only on-device voices.
3. Track: ask in the questions channel whether a UK company number and UTR count; Indie is fine
   if unsure. **Registered as Indie.**

Follow-up answer, Oct 31: "every model your project calls at runtime must be a Meta model",
which replaced the Oct 27 guidance that non-Meta models could run alongside Meta's. MuseTalk is
not Meta's, so it cannot lip-sync the anchor, even self-hosted. **Done:** MuseTalk removed; the
anchor is a still. The track question was again deferred to the organisers: **Indie** unless
they say otherwise.

## Final answers (Discord, 2026-11-01, `questions` > "Startup Track: Use of Pre-existing Code as a Foundation")

The first reply below came from the Cerebral Valley bot (Oct 31, 21:18), which had deferred the
track question to the organisers. The operator asked Adam Blumenfeld (organiser) the Startup-track
question on Nov 1 at 09:43, and again as three numbered questions at 09:48. His answers:

> **Adam Blumenfeld, 09:44:** Yes using MuseTalk is fine. Especially since it's open source.
>
> **Adam Blumenfeld, 09:51:** #1 and #2 both fine. For #2 just make sure you disclose it as you
> are presenting it in your demo video. For #3 it doesn't make a difference for #1 or #2. I would
> suggest as you have an EIN submitting as Startup as there will be a smaller pool (so easier to win)

The three questions (09:48), for context:

1. Runtime models: the Oct 31 answer said every model called at runtime must be Meta's. Does the
   open-source exception now apply, so MuseTalk (MIT) can lip-sync the anchor, self-hosted,
   alongside Meta's models? **Answer: fine.**
2. Avatar: the original anchor was a pre-existing HeyGen library avatar (not open source). Allowed
   if clearly disclosed, or must it be open source or made during the event? **Answer: fine, but
   disclose it in the demo video.**
3. Track: does the answer to 1 and 2 differ between Indie and Startup (US LLC with an EIN, currently
   registered as Indie)? **Answer: no difference. He suggests Startup.**

What this changes:

- **MuseTalk may run at runtime** (it is open source), so the Oct 31 "Meta models only" reading is
  relaxed for open-source models. Not asked, so not assumed: closed services such as Edge TTS. The
  anchor's voice stays Meta's FastSpeech 2.
- **The pre-existing HeyGen avatar (Teresa) may be used**, provided the demo video discloses it
  (title card and opening line, `docs/VIDEO.md`). The avatar's media stay out of this repo.
- **Track:** Startup is allowed with the operator's US LLC and EIN; the choice is made in the
  submission form. Rules 1 and 2 are the same on both tracks.

## Where the repo stands

| Rule | Status |
|---|---|
| Public standalone repo, event work only | Public. `src/` calls no IoMarkets.tv code or backend (PR #21 corrected a stale claim that it did). |
| Window opens Oct 26, 12:24 PM ET | Docs corrected in PR #21. |
| No pre-kickoff history | **Settled 2026-10-30.** `a4ac558` (09:32 ET) and `08bc541` (12:16 ET) predate kickoff: scaffold only, no code, disclosed in `NEW_WORK.md`. Asked on Discord; the organiser replied "Nah thats fine, as long as it was on Oct 26". History left as is. |
| Open source, disclosed | **Settled 2026-10-31** (Discord answer): HeyGen avatar, studio set and Edge TTS replaced by a Muse Image anchor and set and Meta's MMS-TTS; lip-sync (MuseTalk) off. Earlier note: **Open:** the anchor voice is Microsoft's Edge TTS service (closed; client library LGPL-3.0). Option: swap to Kokoro-82M (Apache-2.0). Waiting on the organisers. **Open (2026-10-30):** the on-screen anchor is a HeyGen library avatar (Teresa), pre-existing and not open source; disclosed in `NEW_WORK.md` and on the video's title card, kept out of the repo. The owner chose it knowing the risk; worth asking the organisers. MuseTalk, which lip-syncs it, is MIT. |
| Video opens with the disclosure | Title card and first voice-over line (`docs/VIDEO.md`, `scripts/video_cards.py`). |
| Track | **Settled 2026-11-01:** the organiser says the track does not change the model or avatar rules, and suggests Startup for the smaller pool. Operator's US LLC has an EIN, so Startup is available; set in the submission form. |
| Meta models central | Six Meta model roles (README, "Meta models used"). |
