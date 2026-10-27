# Demo: guest, run sheet and consent

The demo video shows one real interview, start to finish, with a real person as the guest.
Everything on screen must be built during the hackathon (`NEW_WORK.md`).

## The guest

- **A real adult who agrees in writing** to their face and voice appearing in a public video
  (consent form below). Not under 18: the Muse Spark Open licence excludes minors.
- **Someone who can talk with authority about a listed company's published results**: a
  founder, an analyst, an accountant, an investor-relations or finance person, a business
  journalist. Fact-Check needs public figures to check, so the topic is a listed company's
  latest results, not the guest's private business.
- **Not political, not war, not medical** (the hackathon's exclusions), and nothing that sounds
  like advice to buy or sell. The anchor is told to avoid both; the guest should too.
- Not speaking about their own employer's unpublished numbers.

A good shape: *"An analyst on Vodafone's FY26 results"*, or any FTSE/S&P company that has just
reported. Pick one with a recent results release so the brief and the checks have material.

## The chart (shows Fact-Check)

Print one chart, A4 landscape, matte paper, large type (values printed on the bars), with the
company's real figures **and one figure deliberately wrong**. The fact-check panel flags it with
the correct value and a source; that is the moment the video should catch. Say so on screen:
"the guest misquotes one figure on purpose to show the fact-check." Never present a staged
error as a real one.

## Setup

- Chrome on a laptop, page at `http://127.0.0.1:8000` (`uv run studio serve`) or the deployed
  link. Allow camera and microphone.
- **The guest wears headphones.** The anchor's voice must not reach the microphone, or it counts
  as the guest talking.
- Head and shoulders, centred, facing a window or a lamp. Any background: SAM cuts it out.
- Quiet room. Phone on silent.
- Screen recording (OBS or similar) of the whole page, with system audio, for the video.

## Run sheet (about 10 minutes)

| When | Who | What |
|---|---|---|
| −15 min | operator | Prepare the brief (guest name, company). Read it; edit if anything looks off. |
| −10 min | operator + guest | Sign the consent form. Headphones on. Tick the consent box on the page. |
| −2 min | operator | Start the screen recording. |
| 0:00 | guest | Go live. The anchor opens; the guest answers. |
| ~1:00 | guest | Interrupt the anchor once, mid-sentence (shows barge-in). |
| ~2:30 | guest | Hold up the chart; operator presses **Show chart**. Keep it still for 2 seconds. |
| ~3:30 | guest | Cite one real figure out loud (the fact-check marks it supported). |
| ~4:00 | anchor | Raises the wrong chart figure politely; the guest responds. |
| 6:00-8:00 | operator | **End interview**. Wait for "cut-outs done", then **Build segment**. |
| after | operator | Download the segment; stop the screen recording. |

Answers cut out while the interview runs; the last ones finish within about a minute of the end.
The daily spend cap ($10 by default) covers several rehearsals; one full run costs about $1.30.

## Consent form

> **IoMarkets.tv: consent to record and publish (hackathon demo)**
>
> I, ______________________, agree that on ____ / ____ / 2026 Rainmaker Partners Ltd may:
>
> 1. Record my voice and video during a demonstration interview with an AI anchor.
> 2. Process the recording with Meta's AI models (speech recognition, video segmentation and
>    language models) under Meta's Standard terms, which are not the Contributor programme that
>    trains on content. Public research about my company, but not my voice, face or words, may
>    also be processed by Fireworks AI.
> 3. Cut me out of my background and place me in a virtual studio.
> 4. Publish the resulting video, my name and my role, as part of a hackathon entry (Devpost,
>    YouTube, X and the IoMarkets.tv website), with on-screen notice that the anchor is
>    AI-generated.
>
> I understand that the anchor is an AI system, that raw recordings are deleted once the
> cut-out is made, and that I can withdraw this consent before publication by writing to
> ______________________. After publication, the video can be taken down on request but copies
> made by others cannot be recalled.
>
> I am 18 or over. Nothing I say is investment advice.
>
> Signed: ______________________ Date: __________
>
> For Rainmaker Partners Ltd: ______________________ Date: __________
