"""Scout: writes the pre-interview brief on a guest and their topic, in two stages.

1. Research, on Muse Spark 1.3 (Meta's Model API): web search and `market_quote`, giving a
   dated, sourced draft.
2. Editing, on Muse Spark Open (Meta's open weights, served by Fireworks): tighten the draft
   into the anchor's brief, vary the questions, strip anything outside the guardrails (`policy`),
   and keep every caution. The editor adds no facts, and runs only on public research: it
   never sees the guest's voice, face or words, so no guest data goes to a second host.

If the editor is unavailable, fails, or drops a section, the research draft is used as is and
the result says so.

Materials: links and files the producer attaches (a LinkedIn profile, a company site, a pitch
deck) go to the research stage and to the Devil's Advocate, whose PRESSURE POINTS are appended
to the brief. When the guest's own files are attached, the editor is skipped: a brief built
from private material is not sent to a second host.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from studio.agents.factcheck import PressurePoint, format_points, pressure_points
from studio.agents.loop import AgentResult, run_agent
from studio.agents.policy import GUARDRAILS
from studio.meta.open_weights import ATTRIBUTION
from studio.meta.responses import ResponsesClient
from studio.tools.market import market_quote

log = logging.getLogger(__name__)

SECTIONS = ("GUEST:", "CONTEXT:", "RECENT:", "FACTS:", "QUESTIONS:", "CAUTION:")

INSTRUCTIONS = (
    """\
You are Scout, the researcher for IoMarkets.tv, a channel of live interviews on any topic:
business, science, sport, culture, technology, a guest's own work. Write the brief an anchor
reads before a live interview with the guest named below, on their topic (if one is given) or
on what they are known for.

Search the web for recent, reputable sources. If the guest leads or speaks for a listed
company, call market_quote for its ticker rather than taking a price from a search result.

Write plain text with these sections, each a few short lines:
GUEST: who they are and their role.
CONTEXT: their organisation, field or body of work: what it is and why it matters now.
RECENT: the two to four most newsworthy developments of the last six months, each dated.
FACTS: figures, dates and claims the guest is likely to cite, each with its source and date.
QUESTIONS: four open questions, each a different style (explain, challenge, forward-looking,
personal). Never the same opening twice.
CAUTION: anything unconfirmed, disputed or out of date.

These rules are for you; follow them, but do not restate them in the brief:
"""
    + GUARDRAILS
)


MATERIALS_NOTE = """
The producer attached the guest's materials below (links, documents, slides). Read them first.
Ground CONTEXT, FACTS and QUESTIONS in them, and treat what they say as the guest's claims:
check them on the web and note in CAUTION anything you cannot confirm.
"""


async def write_brief(
    client: ResponsesClient, subject: str, materials: list[dict[str, Any]] = ()
) -> AgentResult:
    ask = f"Brief me for an interview with: {subject}"
    prompt: str | list[dict[str, Any]] = ask
    if materials:
        content = [{"type": "input_text", "text": ask + "\n" + MATERIALS_NOTE}, *materials]
        prompt = [{"role": "user", "content": content}]
    return await run_agent(
        client,
        "scout",
        prompt,
        instructions=INSTRUCTIONS,
        tools=[market_quote],
        web_search=True,
    )


EDITOR_INSTRUCTIONS = """\
You are the Scout editor at IoMarkets.tv. Below is a researcher's draft brief for a live
interview. Edit it into the brief the anchor reads in the minute before going on air.

Keep the six sections and their headings exactly: GUEST:, CONTEXT:, RECENT:, FACTS:,
QUESTIONS:, CAUTION:. Plain text, no markdown.

- The anchor reads this in the minute before air: under 350 words in all. GUEST and CONTEXT
  two lines each; RECENT at most three items, one dated line each; FACTS at most six, each
  "fact or figure - what it is - source, date"; CAUTION at most four short items.
- Choose what the guest is most likely to talk about and drop the rest; never shorten a figure,
  date or source you keep.
- Add no fact, figure or source that is not in the draft. If something is unclear, move it to
  CAUTION rather than resolving it.
- QUESTIONS: exactly four, one each of explain, challenge, forward-looking and personal, each
  opening differently, each one sentence the anchor can say aloud.
- Remove anything political or about war, and anything that reads as medical, legal or
  financial advice (diagnoses, treatments, buy or sell, price targets).
- Keep every CAUTION item about the facts; drop any that only restate editorial rules.
- The word limit is firm: cut the weakest RECENT and FACTS items first.
"""


@dataclass
class Brief:
    text: str
    research: AgentResult
    edited_by: str | None  # ATTRIBUTION when Muse Spark Open edited it, else None
    pressure: list[PressurePoint] = field(default_factory=list)
    editor_note: str | None = None  # why the editor did not run, when it was skipped


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


async def _points(
    client: ResponsesClient, draft: str, materials: list[dict[str, Any]]
) -> list[PressurePoint]:
    try:
        return await pressure_points(client, draft, materials)
    except Exception as e:
        log.warning("Devil's Advocate pressure points failed: %s", e)
        return []


async def prepare_brief(
    client: ResponsesClient,
    subject: str,
    editor: ResponsesClient | None = None,
    materials: list[dict[str, Any]] = (),
    private: bool = False,
) -> Brief:
    """Research, then the editor and the Devil's Advocate side by side.

    `private` is true when the guest's own files are among the materials: then the editor
    (on Fireworks) is skipped, and the draft is used as written.
    """
    research = await write_brief(client, subject, materials)
    use_editor = editor is not None and not private
    edited, points = await asyncio.gather(
        edit_brief(editor, research.text) if use_editor else _none(),
        _points(client, research.text, materials),
    )
    text = edited or research.text
    if points:
        text += "\n\n" + format_points(points)
    note = None if use_editor or editor is None else "skipped: the guest's files stay with Meta"
    return Brief(text, research, ATTRIBUTION if edited else None, points, note)


async def _none() -> None:
    return None
