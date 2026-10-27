"""The Devil's Advocate: tests what the guest claims, before air and as the interview runs.

- `pressure_points`: before air, reads the brief and the guest's own materials (deck, site,
  profile) and lists the claims most worth testing, each with why it is doubtful and a question
  that tests it. They become the brief's PRESSURE POINTS section, so the anchor's questions
  come from the material rather than from nowhere.
- `check`: a guest turn, or a chart's figures, is checked with web search and `market_quote`:
  supported, contradicted or unverifiable, with the correct value, a source, and a challenge
  question when one is worth asking (10 s per claim on 2026-10-27). The live session passes
  contradictions and challenges to the anchor as notes: that is how the two coordinate.
- `read_chart`: a camera frame of a chart the guest holds up goes to Muse Spark as an image;
  the figures come back as strict JSON (2.2 s on 2026-10-27, tilted and noisy frame).

Only turns with something checkable in them are checked: pleasantries cost nothing.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Literal

from pydantic import BaseModel

from studio.agents.loop import run_agent
from studio.agents.policy import GUARDRAILS
from studio.meta.responses import ResponsesClient, strict_object
from studio.tools.market import market_quote

# Something checkable: a digit, a number word a speech recogniser might spell out, or a claim
# of rank or record ("the first", "the largest").
HAS_FIGURE = re.compile(
    r"\d|\b(percent|per cent|million|billion|trillion|half|double|triple|quarter"
    r"|first|largest|biggest|smallest|fastest|oldest|youngest|most|least|record|only"
    r"|leader|leading|unique|proven|guarantee[sd]?|best)\b",
    re.I,
)


class Figure(BaseModel):
    label: str
    value: float
    unit: str
    period: str


class ChartReading(BaseModel):
    legible: bool
    title: str
    source: str
    figures: list[Figure]

    def as_claims(self) -> str:
        lines = [f"{f.label}: {f.value:g} {f.unit} ({f.period})".strip() for f in self.figures]
        src = f" Source shown: {self.source}." if self.source else ""
        return f'Chart "{self.title}".{src} ' + "; ".join(lines)


class Check(BaseModel):
    claim: str
    verdict: Literal["supported", "contradicted", "unverifiable"]
    correct_value: str
    explanation: str
    source_url: str
    challenge: str = ""  # a question for the anchor to put to the guest, "" if none


class Checks(BaseModel):
    checks: list[Check]


class PressurePoint(BaseModel):
    claim: str
    doubt: str
    question: str


class PressurePoints(BaseModel):
    points: list[PressurePoint]


def format_points(points: list[PressurePoint]) -> str:
    if not points:
        return ""
    lines = [f"- {p.claim}: {p.doubt}\n  Ask: {p.question}" for p in points]
    return "PRESSURE POINTS (Devil's Advocate):\n" + "\n".join(lines)


_STR = {"type": "string"}

CHART_SCHEMA = strict_object(
    {
        "legible": {"type": "boolean"},
        "title": _STR,
        "source": _STR,
        "figures": {
            "type": "array",
            "items": strict_object(
                {"label": _STR, "value": {"type": "number"}, "unit": _STR, "period": _STR}
            ),
        },
    }
)

CHECKS_SCHEMA = strict_object(
    {
        "checks": {
            "type": "array",
            "items": strict_object(
                {
                    "claim": _STR,
                    "verdict": {
                        "type": "string",
                        "enum": ["supported", "contradicted", "unverifiable"],
                    },
                    "correct_value": _STR,
                    "explanation": _STR,
                    "source_url": _STR,
                    "challenge": _STR,
                }
            ),
        }
    }
)

POINTS_SCHEMA = strict_object(
    {
        "points": {
            "type": "array",
            "items": strict_object({"claim": _STR, "doubt": _STR, "question": _STR}),
        }
    }
)

CHART_INSTRUCTIONS = """\
The image is a frame from a live interview camera. If the guest is holding up a chart, slide
or table, read it. Report only what is printed: never estimate a value from a bar's height
when no number is printed. Give each figure its label, value, unit (%, GBP bn, EUR m, ...) and
period if shown, else "". Title and source are the printed text, else "". If there is no
legible chart, set legible to false and figures to [].
"""

CHECK_INSTRUCTIONS = """\
You are the Devil's Advocate in a live IoMarkets.tv interview, on any topic: the colleague who
checks what the guest claims and tells the anchor what to push on. Find the specific,
checkable claims in what the guest said or showed (figures, dates, records, rankings, "the
first", "the leader", "proven") and check each one: first against the brief below (including
its PRESSURE POINTS), then with web search, and with market_quote for a share price. Skip
opinions and pleasantries.

For each claim: "supported" if reputable sources match it (allow rounding), "contradicted" if
they give a clearly different figure for the same thing and period, else "unverifiable".
correct_value is the sourced figure ("" if none). explanation is one plain sentence a
producer can read at a glance. source_url is the best single source ("" if none).
challenge is one short, fair question the anchor could ask next to test the claim (for a
contradicted claim, or an unverifiable one that matters, especially one from the guest's own
materials); "" for a supported claim.

Speech recognition may have garbled words; judge the figure the guest evidently meant. If
there is nothing checkable, return no checks.

THE BRIEF
"""


async def read_chart(client: ResponsesClient, jpeg: bytes) -> ChartReading:
    image = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    resp = await client.create(
        "vision",
        [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Read the chart in this frame."},
                    {"type": "input_image", "image_url": image},
                ],
            }
        ],
        instructions=CHART_INSTRUCTIONS,
        schema=("chart_reading", CHART_SCHEMA),
    )
    return ChartReading.model_validate(json.loads(resp.text))


POINTS_INSTRUCTIONS = """\
You are the Devil's Advocate preparing an IoMarkets.tv interview. Below are the anchor's brief
and, when the producer supplied them, the guest's own materials (pitch deck, website, profile,
notes). Treat everything in the materials as the guest's claims, not as facts.

List the three to five claims most worth testing on air: numbers that look high, firsts and
superlatives, results without a source, gaps between the materials and what you find on the
web. For each: the claim as the guest makes it, why it is doubtful in one sentence (cite what
you found), and one fair, specific question that tests it. Use web search. If nothing is
doubtful, return the claims a sceptical viewer would most want evidenced.

"""


async def pressure_points(
    client: ResponsesClient, brief: str, materials: list[dict] = ()
) -> list[PressurePoint]:
    result = await run_agent(
        client,
        "factcheck",
        [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": f"THE BRIEF\n{brief}"}, *materials],
            }
        ],
        instructions=POINTS_INSTRUCTIONS + GUARDRAILS,
        tools=[market_quote],
        web_search=True,
        schema=("pressure_points", POINTS_SCHEMA),
    )
    return PressurePoints.model_validate(json.loads(result.text)).points[:5]


async def check(client: ResponsesClient, said: str, brief: str) -> list[Check]:
    if not HAS_FIGURE.search(said):
        return []
    result = await run_agent(
        client,
        "factcheck",
        f"The guest said or showed: {said}",
        instructions=CHECK_INSTRUCTIONS + brief,
        tools=[market_quote],
        web_search=True,
        schema=("fact_checks", CHECKS_SCHEMA),
    )
    return Checks.model_validate(json.loads(result.text)).checks


class FactDesk:
    """What the live session calls: checks and chart reads against one interview's brief."""

    def __init__(self, client: ResponsesClient, brief: str):
        self.client = client
        self.brief = brief
        self.research = ""  # cold start: what the live researcher has found so far

    def learn(self, research: str) -> None:
        self.research = research

    async def check(self, said: str) -> list[Check]:
        brief = self.brief + (f"\n\nLIVE RESEARCH\n{self.research}" if self.research else "")
        return await check(self.client, said, brief)

    async def read_chart(self, jpeg: bytes) -> ChartReading:
        return await read_chart(self.client, jpeg)
