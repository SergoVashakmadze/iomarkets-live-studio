# Submission form answers (Cerebral Valley, Meta Global AI Developer Hackathon)

Paste-ready. Check each against the live form; the EIN is typed by the operator, never stored here.

- **Track:** Startup. **Company:** IOMARKETS LLC (Wyoming; US EIN, letter dated 2 Oct 2025). The
  organiser (Adam Blumenfeld, 1 Nov 2026) confirmed the track changes no rule and suggested Startup.
- **Project name:** IoMarkets Live Studio
- **One line:** A live interview studio for any topic: a guest talks to an AI anchor in real time,
  Meta's models listen, fact-check and cut the guest into the studio, and a broadcast-ready segment
  is ready when the call ends.
- **Problem statement:** Build for Your World.
- **Code:** https://github.com/SergoVashakmadze/iomarkets-live-studio (MIT)
- **Try it:** the judges' link (token in the Modal secret `iomarkets-studio`; rotate after judging)
- **Video:** unlisted YouTube link, 3:00 at most; **opens with the disclosure line** (`docs/VIDEO.md`):
  Teresa is a pre-existing HeyGen library avatar and the IoMarkets TV studio background is
  pre-existing; MuseTalk is open source (MIT); everything else, and every call to a Meta model, was
  built this week.
- **Meta models used:** Muse Spark 1.3 (Responses API, web search, image input, strict JSON), Muse
  Voice Transcribe (realtime ENDPOINTING), SAM 3.1 (hosted), Muse Image, Muse Spark Open (open
  weights, via Fireworks: bonus), FastSpeech 2 and MMS-TTS (anchor voice, run by the studio).
- **Open source outside Meta:** MuseTalk (MIT) for lip-sync, allowed in writing by an organiser.
- **Write-up:** `docs/WRITEUP.md` (by judging criterion). **What was built when:** `NEW_WORK.md`.
- **Bonuses to name:** open-weights model (Muse Spark Open on Fireworks); creative (Muse Image);
  Most Viral: post a 45-60 s cut on X.
- **Meta credits:** each participant, including startup entrants, must claim the $150 credit
  individually by Wed 4 Nov, 9:00 PM Eastern.
- **Do before submitting:** testers' recordings in (due Mon 2 Nov, 8 pm UK), video recorded, video
  link in the form, the README/`docs/VIDEO.md`/title card updated for Teresa.

## The form's fields (as seen 1 Nov 2026) and drafted answers

Opinion and rating fields are the operator's to confirm; they are drafted from this project's logs.

- **Team Name:** IoMarkets
- **Which track:** Startup (company: IOMARKETS LLC; EIN typed by the operator)
- **Problem statement:** Build for Your World
- **Most Viral X post link:** leave empty until the 45-60 s cut is posted
- **Public GitHub Repository:** https://github.com/SergoVashakmadze/iomarkets-live-studio
- **3-Minute Demo Video:** the unlisted YouTube link, after recording (opens with the disclosure line)
- **Project Description:** IoMarkets Live Studio is a live interview studio for any topic. A guest
  talks to an AI anchor in real time; Meta's models listen, research the guest beforehand,
  fact-check every figure they say or show while they talk, cut them out of their room with SAM 3.1
  and place them in the studio, and package a broadcast-ready segment before the call ends. One
  person can run what normally needs a presenter, researcher, fact-checker and editor, so local
  newsrooms, niche channels, schools and solo creators publish more interviews with the claims
  checked. The anchor is labelled AI everywhere, guests consent first, and raw recordings are
  deleted after processing.
- **Describe your use of Meta products:** Muse Spark 1.3 (Responses API) is the anchor's replies,
  Scout's web-search research, the fact-checker's strict-JSON verdicts with sources, and chart
  reading from the camera (image input). Muse Voice Transcribe (realtime ENDPOINTING) hears the guest
  and drives turn-taking and barge-in. SAM 3.1 (hosted) cuts the guest out of each answer. Muse Spark
  Open (open weights, on Fireworks) edits the research into the anchor's brief. Meta's FastSpeech 2
  is the anchor's voice, with MMS-TTS as fallback. Muse Image made the fallback anchor and set. One
  open-source non-Meta model, MuseTalk (MIT), lip-syncs the anchor, allowed in writing by an organiser.
- **Why Meta's models are important:** Voice in, web-grounded checking, vision and segmentation had
  to work together inside one conversation's latency. Muse Spark gives the anchor's line 1.3-2.1 s
  after the guest stops, fact-checks a spoken figure with sources in 6-8 s and reads a chart in
  under 5 s; SAM 3.1 gives a guest cut-out with no green screen at 1.6x real time; open weights
  (Muse Spark Open) let part of the pipeline run on a model that never sees the guest.
- **Feedback on partner technologies (Fireworks, Modal, Baseten):** Modal: one-file deploys and
  scale-to-zero worked well; surprises were that a GPU class with no `cpu=` gets about 0.125 of a
  core, a secret change needs new containers, and WebSocket messages are capped at 2 MiB. Fireworks:
  Muse Spark Open worked as the brief editor. Baseten: not used.
- **Likelihood to build with Meta Model API / opinion:** Very likely / Very favorable (as in the
  application; confirm).
- **Biggest obstacle:** Latency. Chaining turns with `previous_response_id` cost ~10 s a call versus
  1-2 s resending the history; `meta-sam-parser` decoded each mask in ~0.76 s of pure Python until
  decoded once in a process pool (a 12 s clip from 251 s to 25 s); and lip-sync renders at about real
  time, so the anchor's first words take 8-11 s.
- **Compared with other models / what matters most / hardest to switch / what would stop
  production use:** the operator's own judgement. This project ran no side-by-side benchmark, so say
  only what was observed (the figures above) and leave comparisons to experience.
