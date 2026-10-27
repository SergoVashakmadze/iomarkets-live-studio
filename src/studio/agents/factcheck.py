"""Fact-Check and chart reading: the figures a guest says or shows, checked as the interview runs.

- `read_chart`: a camera frame of a chart the guest holds up goes to Muse Spark as an image;
  the figures come back as strict JSON (2.2 s on 2026-10-27, tilted and noisy frame).
- `check`: a guest turn, or a chart's figures, goes to Fact-Check with web search and
  `market_quote`; each checkable figure comes back as supported, contradicted or unverifiable,
  with the correct value and a source (10 s per claim on 2026-10-27).

Only turns that contain a figure are checked: opinions and pleasantries cost nothing.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Literal

from pydantic import BaseModel

from studio.agents.loop import run_agent
from studio.meta.responses import ResponsesClient, strict_object
from studio.tools.market import market_quote

# Something checkable: a digit, a number word a speech recogniser might spell out, or a claim
# of rank or record ("the first", "the largest").
HAS_FIGURE = re.compile(
    r"\d|\b(percent|per cent|million|billion|trillion|half|double|triple|quarter"
    r"|first|largest|biggest|smallest|fastest|oldest|youngest|most|least|record|only)\b",
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


class Checks(BaseModel):
    checks: list[Check]


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
                }
            ),
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
You are Fact-Check for a live IoMarkets.tv interview, on any topic. Find the specific,
checkable claims in what the guest said or showed (figures, dates, records, rankings, "the
first" or "the largest", named results) and check each one: first against the brief below,
then with web search, and with market_quote for a share price. Skip opinions, forecasts and
vague statements.

For each figure: "supported" if reputable sources match it (allow rounding), "contradicted" if
they give a clearly different figure for the same thing and period, else "unverifiable".
correct_value is the sourced figure ("" if none). explanation is one plain sentence a
producer can read at a glance. source_url is the best single source ("" if none).

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

    async def check(self, said: str) -> list[Check]:
        return await check(self.client, said, self.brief)

    async def read_chart(self, jpeg: bytes) -> ChartReading:
        return await read_chart(self.client, jpeg)
