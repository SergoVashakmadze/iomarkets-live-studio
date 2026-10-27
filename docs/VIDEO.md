# The demo video (3:00)

Judging: Impact 30, **Use of Meta tooling 25**, **Demo 25**, Technical depth 20. The rules
also say the demo may show only work built during the event, so every shot here is of this
repo. The video carries three jobs: show a real interview working end to end, make each Meta
model visible at the moment it works, and say plainly what was built when.

## What you need

- One full interview recorded with a real guest (`docs/DEMO.md`: guest, chart, consent).
- The cards: `uv run python scripts/video_cards.py` writes `video/cards/*.mp4` (1920x1080).
- The interview's captions: **Transcript (.srt)** on the page after the interview.
- The packaged segment: **Build segment**, then download `segment.mp4`.
- A screen recorder (OBS: 1920x1080, 30 fps, desktop audio plus the guest's mic), and an editor
  (Kdenlive, DaVinci Resolve or similar).

## Recording the screen

- Chrome full screen, page zoom so the **Meta models strip** and the fact-check panel are both
  visible above the fold (about 110 % on a 1080p screen). The strip is the visual proof of
  "use of Meta tooling": each badge lights while its model is working.
- Start recording before **Prepare brief**, and keep it running through **Build segment**.
- Do one full rehearsal take first. Use the best take; never splice two takes into one
  "live" sequence.

## Storyboard

| Time | Shot | On screen | Voice-over (operator) | Scores |
|---|---|---|---|---|
| 0:00-0:06 | `01-title` card | | "IoMarkets Live Studio: a live business interview with an AI anchor." | |
| 0:06-0:16 | `02-problem` card | | "A live interview takes a presenter, a researcher, a fact-checker and an editor. Small newsrooms go without. This does all four, live, on Meta's models." | Impact |
| 0:16-0:34 | Screen: type the guest, paste a link, drop their deck, **Prepare brief** | Badges light; brief appears with PRESSURE POINTS | "Scout reads the guest's deck and links with Muse Spark and searches the web; the Devil's Advocate lists the claims to test, each with a question." | Meta tooling, Impact |
| 0:34-1:00 | Screen: tick consent, **Go live**; anchor opens; guest answers | Voice Transcribe badge on while the guest talks; live transcript; anchor line | "The guest speaks; Muse Voice Transcribe hears every word as it is said, and the anchor, on Muse Spark, answers in about two seconds." | Demo |
| 1:00-1:12 | Screen: the guest **interrupts** the anchor | Anchor audio stops; "Guest · interrupted" | "And they can interrupt, like a real interview." | Demo |
| 1:12-1:45 | Screen: guest holds up the chart, **Show chart** | Vision badge; chart read; Fact-Check badge; **CONTRADICTED** with source; then the anchor raises it | "Muse Spark reads the chart off the camera. Fact-Check checks every figure against the web: this one is wrong, and the anchor says so, politely, with the source." | Meta tooling, Impact |
| 1:45-2:00 | Screen: the guest replies; **End interview** | SAM badge counts; "cut-outs done" | "Each answer has already been cut out of the guest's room by SAM 3.1 while the interview went on." | Technical |
| 2:00-2:20 | `segment.mp4` (best 20 s) | Question card, guest in the studio, lower third | "One click packages the programme: the anchor's questions, the guest's answers, cut into the studio." | Demo |
| 2:20-2:40 | `03-how` card | | "Six Meta model roles, measured live: replies in two seconds, barge-in in a third of a second, fact-checks in seven." | Technical |
| 2:40-2:54 | `04-new-work` card | | "Everything shown was written during the hackathon. The anchor is AI, and it says so." | Rules |
| 2:54-3:00 | `05-end` card | | "IoMarkets Live Studio. The code is open." | |

Waiting time (Scout's 20-40 s, the last cut-outs) may be **sped up**, labelled on screen
("4x"). Never cut so that something looks faster than it was without saying so.

## Captions and labels

- Import `interview.srt` as subtitles for the screen-recorded interview; shift it to the moment
  you pressed Go live. Burn them in: many judges watch muted.
- Keep the page's own "AI system ... synthetic voice" footer visible in at least one shot, and
  the `04-new-work` card's "The anchor is AI" line (EU AI Act Art. 50 disclosure).
- If a guest's figure is wrong on purpose (the chart), say so in the voice-over or a caption.

## Export

1920x1080, 30 fps, H.264, AAC, under 3:00. Upload unlisted to YouTube for the submission, and
post a 45-60 s cut (the barge-in and the CONTRADICTED moment) to X for the Most Viral prize.
