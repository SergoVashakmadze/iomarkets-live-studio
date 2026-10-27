"""Live Scout: research done during a cold-start interview, from what the guest has said.

In a cold start the anchor knows nothing in advance. After each guest turn, Live Scout reads
the conversation so far, searches the web for the people, organisations and claims the guest
mentioned, and returns who the guest seems to be, the facts it could confirm, and angles for
follow-up questions. The anchor gets it with the guest's next words; the Devil's Advocate checks
against it. It runs in the background, one search at a time; the anchor never waits for it.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from studio.agents.loop import run_agent
from studio.agents.policy import GUARDRAILS
from studio.meta.responses import ResponsesClient, strict_object

_STR = {"type": "string"}
_LIST = {"type": "array", "items": _STR}

SCHEMA = strict_object({"who": _STR, "facts": _LIST, "angles": _LIST})

INSTRUCTIONS = (
    """\
You are Scout, working live during an IoMarkets.tv interview that began cold: nobody
researched the guest in advance. Below is the conversation so far and what is already known.

Search the web for the people, organisations, products, places and claims the guest has
mentioned. Then return:
- who: one line on who the guest appears to be (say "unclear" rather than guess);
- facts: up to five short facts you could confirm that bear on what they said, each ending
  with its source in brackets; nothing you could not confirm;
- angles: up to three follow-up angles the anchor could take, grounded in what the guest said.

"""
    + GUARDRAILS
)


class LiveResearch(BaseModel):
    who: str
    facts: list[str]
    angles: list[str]

    def as_text(self) -> str:
        facts = "\n".join(f"- {f}" for f in self.facts) or "- none confirmed yet"
        angles = "\n".join(f"- {a}" for a in self.angles) or "- none yet"
        return f"Guest: {self.who}\nConfirmed:\n{facts}\nAngles:\n{angles}"


async def research(client: ResponsesClient, transcript: str, known: str) -> LiveResearch:
    result = await run_agent(
        client,
        "factcheck",
        f"WHAT IS KNOWN\n{known or 'nothing yet'}\n\nTHE CONVERSATION SO FAR\n{transcript}",
        instructions=INSTRUCTIONS,
        web_search=True,
        schema=("live_research", SCHEMA),
    )
    found = LiveResearch.model_validate(json.loads(result.text))
    return LiveResearch(who=found.who, facts=found.facts[:5], angles=found.angles[:3])
