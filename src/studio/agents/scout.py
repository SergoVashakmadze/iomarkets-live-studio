"""Scout: writes the pre-interview brief on a guest and their company.

Runs before the guest joins and sees no guest data, which is why it is the agent planned for
Muse Spark Open later in the week.
"""

from __future__ import annotations

from studio.agents.loop import AgentResult, run_agent
from studio.meta.responses import ResponsesClient
from studio.tools.market import market_quote

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
