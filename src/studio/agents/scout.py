"""Scout: writes the pre-interview brief on a guest and their company, in two stages.

1. Research, on Muse Spark 1.3 (Meta's Model API): web search and `market_quote`, giving a
   dated, sourced draft.
2. Editing, on Muse Spark Open (Meta's open weights, served by Fireworks): tighten the draft
   into the anchor's brief, vary the questions, strip anything that reads as investment advice,
   and keep every caution. The editor adds no facts, and runs only on public research: it
   never sees the guest's voice, face or words, so no guest data goes to a second host.

If the editor is unavailable, fails, or drops a section, the research draft is used as is and
the result says so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from studio.agents.loop import AgentResult, run_agent
from studio.meta.open_weights import ATTRIBUTION
from studio.meta.responses import ResponsesClient
from studio.tools.market import market_quote

log = logging.getLogger(__name__)

SECTIONS = ("GUEST:", "COMPANY:", "RECENT:", "NUMBERS:", "QUESTIONS:", "CAUTION:")

INSTRUCTIONS = """\
You are Scout, the researcher for IoMarkets.tv, a business-news channel. Write the brief an
anchor reads before a live interview.

Search the web for recent, reputable reporting. If the company is listed, call market_quote
for its ticker and use that price rather than one from a search result.

Write plain text with these sections, each a few short lines:
GUEST: who they are and their role.
COMPANY: what it does, size, listed or private.
RECENT: the two to four most newsworthy developments of the last six months, each dated.
NUMBERS: figures the guest is likely to cite, each with its source and date.
QUESTIONS: four open questions, each a different style (explain, challenge, forward-looking,
personal). Never the same opening twice.
CAUTION: anything unconfirmed, disputed or out of date.

This is journalism, not investment advice: no buy, sell or price-target language. Leave out
politics. If you cannot confirm something, say so instead of guessing.
"""


async def write_brief(client: ResponsesClient, subject: str) -> AgentResult:
    return await run_agent(
        client,
        "scout",
        f"Brief me for an interview with: {subject}",
        instructions=INSTRUCTIONS,
        tools=[market_quote],
        web_search=True,
    )


EDITOR_INSTRUCTIONS = """\
You are the Scout editor at IoMarkets.tv. Below is a researcher's draft brief for a live
business interview. Edit it into the brief the anchor reads in the minute before going on air.

Keep the six sections and their headings exactly: GUEST:, COMPANY:, RECENT:, NUMBERS:,
QUESTIONS:, CAUTION:. Plain text, no markdown.

- The anchor reads this in the minute before air: under 350 words in all. GUEST and COMPANY
  two lines each; RECENT at most three items, one dated line each; NUMBERS at most six, each
  "figure - what it is - source, date"; CAUTION at most four short items.
- Choose what the guest is most likely to talk about and drop the rest; never shorten a figure,
  date or source you keep.
- Add no fact, figure or source that is not in the draft. If something is unclear, move it to
  CAUTION rather than resolving it.
- QUESTIONS: exactly four, one each of explain, challenge, forward-looking and personal, each
  opening differently, each one sentence the anchor can say aloud.
- Remove anything that reads as investment advice (buy, sell, price targets, "undervalued")
  and anything political.
- Keep every CAUTION item.
"""


@dataclass
class Brief:
    text: str
    research: AgentResult
    edited_by: str | None  # ATTRIBUTION when Muse Spark Open edited it, else None


async def edit_brief(editor: ResponsesClient, draft: str) -> str | None:
    """The draft edited on Muse Spark Open, or None if that failed or lost a section."""
    try:
        resp = await editor.create("editor", draft, instructions=EDITOR_INSTRUCTIONS)
    except Exception as e:
        log.warning("Scout editor failed, using the research draft: %s", e)
        return None
    missing = [h for h in SECTIONS if h not in resp.text]
    if missing:
        log.warning("Scout editor dropped %s, using the research draft", ", ".join(missing))
        return None
    return resp.text


async def prepare_brief(
    client: ResponsesClient, subject: str, editor: ResponsesClient | None = None
) -> Brief:
    research = await write_brief(client, subject)
    edited = await edit_brief(editor, research.text) if editor else None
    return Brief(edited or research.text, research, ATTRIBUTION if edited else None)
