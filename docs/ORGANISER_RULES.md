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

Asked back on Oct 31: whether MuseTalk (MIT, self-hosted) may lip-sync the anchor, given the
Oct 27 answer that non-Meta models may be used alongside Meta's. Until answered, lip-sync is off.

## Where the repo stands

| Rule | Status |
|---|---|
| Public standalone repo, event work only | Public. `src/` calls no IoMarkets.tv code or backend (PR #21 corrected a stale claim that it did). |
| Window opens Oct 26, 12:24 PM ET | Docs corrected in PR #21. |
| No pre-kickoff history | **Settled 2026-10-30.** `a4ac558` (09:32 ET) and `08bc541` (12:16 ET) predate kickoff: scaffold only, no code, disclosed in `NEW_WORK.md`. Asked on Discord; the organiser replied "Nah thats fine, as long as it was on Oct 26". History left as is. |
| Open source, disclosed | **Settled 2026-10-31** (Discord answer): HeyGen avatar, studio set and Edge TTS replaced by a Muse Image anchor and set and Meta's MMS-TTS; lip-sync (MuseTalk) off. Earlier note: **Open:** the anchor voice is Microsoft's Edge TTS service (closed; client library LGPL-3.0). Option: swap to Kokoro-82M (Apache-2.0). Waiting on the organisers. **Open (2026-10-30):** the on-screen anchor is a HeyGen library avatar (Teresa), pre-existing and not open source; disclosed in `NEW_WORK.md` and on the video's title card, kept out of the repo. The owner chose it knowing the risk; worth asking the organisers. MuseTalk, which lip-syncs it, is MIT. |
| Video opens with the disclosure | Title card and first voice-over line (`docs/VIDEO.md`, `scripts/video_cards.py`). |
| Track | **Owner's call:** Startup only if Rainmaker Partners Ltd is registered with a tax ID; otherwise Indie. |
| Meta models central | Six Meta model roles (README, "Meta models used"). |
