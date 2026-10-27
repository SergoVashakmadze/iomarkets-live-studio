from __future__ import annotations

import json

import httpx
import pytest
from conftest import Replay, load_recording
from pydantic import BaseModel

from studio.agents import scout
from studio.agents.loop import FunctionTool, TurnLimitError, run_agent
from studio.meta.responses import ResponsesClient

RECORDING = load_recording("scout_amd_2026-10-27.json")


def _client(replay: Replay) -> ResponsesClient:
    return ResponsesClient(api_key="k", transport=replay.transport())


def _call(name: str, arguments: str, call_id: str = "call_1", rid: str = "r1") -> httpx.Response:
    item = {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}
    return httpx.Response(200, json={"id": rid, "status": "completed", "output": [item]})


def _answer(text: str = "done", rid: str = "r2") -> httpx.Response:
    message = {"type": "message", "content": [{"type": "output_text", "text": text}]}
    return httpx.Response(200, json={"id": rid, "status": "completed", "output": [message]})


class EchoArgs(BaseModel):
    n: int


async def _echo(args: EchoArgs) -> dict:
    return {"n": args.n * 2}


ECHO = FunctionTool("echo", "doubles n", EchoArgs, _echo)


async def test_replays_recorded_scout_brief(monkeypatch):
    quotes = []

    async def fake_quote(ticker: str) -> dict:
        quotes.append(ticker)
        return {"ticker": ticker, "price": 531.28}

    monkeypatch.setattr("studio.tools.market.fetch_quote", fake_quote)
    replay = Replay([httpx.Response(200, json=e["response"]) for e in RECORDING])

    async with _client(replay) as client:
        result = await scout.write_brief(client, "Lisa Su, CEO of AMD")

    assert quotes == ["AMD"]
    assert result.turns == 2
    assert result.text.startswith("GUEST:")
    assert [r.name for r in result.tool_runs] == ["market_quote"]
    assert result.citations and result.searches and result.commentary

    first, second = replay.bodies()
    assert {"type": "web_search"} in first["tools"]
    assert first["include"] == ["web_search_call.results"]
    assert second["previous_response_id"] == RECORDING[0]["response"]["id"]
    [output] = second["input"]
    recorded_call = next(
        i for i in RECORDING[0]["response"]["output"] if i["type"] == "function_call"
    )
    assert output["type"] == "function_call_output"
    assert output["call_id"] == recorded_call["call_id"]
    assert json.loads(output["output"])["price"] == 531.28


async def test_invalid_arguments_go_back_to_the_model():
    replay = Replay([_call("echo", '{"n": "lots"}'), _answer()])
    async with _client(replay) as client:
        result = await run_agent(client, "producer", "go", instructions="x", tools=[ECHO])
    [run] = result.tool_runs
    assert not run.ok
    sent = json.loads(replay.bodies()[1]["input"][0]["output"])
    assert sent["error"] == "invalid arguments"


async def test_unknown_tool_and_failing_tool_are_reported_not_raised():
    async def boom(_args):
        raise ValueError("feed down")

    broken = FunctionTool("broken", "always fails", EchoArgs, boom)
    replay = Replay([_call("nope", "{}"), _call("broken", '{"n": 1}', rid="r2"), _answer(rid="r3")])
    async with _client(replay) as client:
        result = await run_agent(client, "producer", "go", instructions="x", tools=[broken])
    assert [r.ok for r in result.tool_runs] == [False, False]
    assert "unknown tool" in result.tool_runs[0].output["error"]
    assert "feed down" in result.tool_runs[1].output["error"]
    assert result.text == "done"


async def test_valid_call_runs_the_tool():
    replay = Replay([_call("echo", '{"n": 21}'), _answer()])
    async with _client(replay) as client:
        result = await run_agent(client, "producer", "go", instructions="x", tools=[ECHO])
    assert result.tool_runs[0].output == {"n": 42}
    assert "include" not in replay.bodies()[0]


async def test_turn_cap():
    replay = Replay([_call("echo", '{"n": 1}', rid=f"r{i}") for i in range(3)])
    async with _client(replay) as client:
        with pytest.raises(TurnLimitError):
            await run_agent(client, "producer", "go", instructions="x", tools=[ECHO], max_turns=3)
