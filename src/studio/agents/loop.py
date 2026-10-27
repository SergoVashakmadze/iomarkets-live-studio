"""The tool loop every agent runs on.

Meta's Responses API leaves three things to the caller: `tool_choice` is `auto` only, parallel
calls are on, and `strict` is off, so arguments may not match the schema. So here every argument
is validated with pydantic before a tool runs, a bad call goes back to the model as an error it
can correct, and the number of turns is capped. Turns chain on `previous_response_id`, so the
model's reasoning carries over and the history is never resent.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from studio.meta.responses import Citation, Response, ResponsesClient

WEB_SEARCH: dict[str, Any] = {"type": "web_search"}
# Without this, web search returns no sources at all (see Response).
WEB_SEARCH_INCLUDE = ["web_search_call.results"]


@dataclass
class FunctionTool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[BaseModel], Awaitable[Any]]

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.args.model_json_schema(),
        }


@dataclass
class ToolRun:
    name: str
    arguments: str
    output: Any
    ok: bool


@dataclass
class AgentResult:
    text: str
    response: Response
    turns: int
    tool_runs: list[ToolRun] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    commentary: list[str] = field(default_factory=list)


class TurnLimitError(RuntimeError):
    pass


async def run_agent(
    client: ResponsesClient,
    role: str,
    input: str | list[dict[str, Any]],
    *,
    instructions: str,
    tools: list[FunctionTool] = (),
    web_search: bool = False,
    max_turns: int = 6,
) -> AgentResult:
    by_name = {t.name: t for t in tools}
    specs = [t.spec() for t in tools] + ([WEB_SEARCH] if web_search else [])
    runs: list[ToolRun] = []
    cites: dict[str, Citation] = {}
    searches: list[str] = []
    commentary: list[str] = []
    previous: str | None = None
    next_input = input

    for turn in range(1, max_turns + 1):
        resp = await client.create(
            role,
            next_input,
            instructions=instructions,
            tools=specs or None,
            previous_response_id=previous,
            include=WEB_SEARCH_INCLUDE if web_search else None,
        )
        for c in resp.citations:
            cites.setdefault(c.url, c)
        searches += resp.searches
        commentary += resp.commentary
        if not resp.function_calls:
            return AgentResult(
                resp.text, resp, turn, runs, list(cites.values()), searches, commentary
            )

        outputs = []
        for call in resp.function_calls:
            run = await _run_tool(by_name, call.name, call.arguments)
            runs.append(run)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(run.output, default=str),
                }
            )
        previous, next_input = resp.id, outputs

    raise TurnLimitError(f"{role}: no final answer after {max_turns} turns")


async def _run_tool(by_name: dict[str, FunctionTool], name: str, arguments: str) -> ToolRun:
    tool = by_name.get(name)
    if tool is None:
        return ToolRun(name, arguments, {"error": f"unknown tool {name!r}"}, False)
    try:
        args = tool.args.model_validate_json(arguments or "{}")
    except ValidationError as e:
        errors = e.errors(include_url=False, include_context=False)
        return ToolRun(name, arguments, {"error": "invalid arguments", "details": errors}, False)
    try:
        return ToolRun(name, arguments, await tool.run(args), True)
    except Exception as e:  # a failed tool is reported to the model, not raised
        return ToolRun(name, arguments, {"error": f"{type(e).__name__}: {e}"}, False)
