from __future__ import annotations

import httpx
import pytest
from conftest import Replay, load_recording

from studio.meta.responses import (
    ROLE_BUDGETS,
    EmptyOutputError,
    MetaAPIError,
    Response,
    ResponsesClient,
)

RECORDING = load_recording("scout_amd_2026-10-27.json")


def _client(replay: Replay) -> ResponsesClient:
    return ResponsesClient(api_key="test-key", transport=replay.transport())


def _ok(text: str = "hello", rid: str = "resp_1") -> httpx.Response:
    message = {"type": "message", "content": [{"type": "output_text", "text": text}]}
    return httpx.Response(200, json={"id": rid, "status": "completed", "output": [message]})


def test_parse_recorded_tool_turn():
    r = Response.parse(RECORDING[0]["response"])
    assert r.text == ""
    assert [c.name for c in r.function_calls] == ["market_quote"]
    assert r.function_calls[0].arguments == '{"ticker":"AMD"}'
    assert r.commentary, "the recorded first turn narrates its progress"
    assert len(r.searches) == 3


def test_parse_recorded_answer_keeps_commentary_out_of_text():
    r = Response.parse(RECORDING[1]["response"])
    assert r.text.startswith("GUEST:")
    for line in r.commentary:
        assert line not in r.text
    assert r.citations and all(c.url.startswith("http") for c in r.citations)
    assert len({c.url for c in r.citations}) == len(r.citations)


def test_parse_inline_url_citations():
    body = {
        "id": "r",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Revenue rose.",
                        "annotations": [
                            {"type": "url_citation", "url": "https://a.example", "title": "A"},
                            {"type": "url_citation", "url": "https://a.example", "title": "A"},
                        ],
                    }
                ],
            }
        ],
    }
    cites = Response.parse(body).citations
    assert [(c.url, c.title) for c in cites] == [("https://a.example", "A")]


async def test_request_carries_role_budget_and_auth():
    replay = Replay([_ok()])
    async with _client(replay) as client:
        r = await client.create("anchor", "hi", instructions="be brief", previous_response_id="p")
    assert r.text == "hello"
    body = replay.bodies()[0]
    budget = ROLE_BUDGETS["anchor"]
    assert body["reasoning"] == {"effort": budget.effort}
    assert body["max_output_tokens"] == budget.max_output_tokens
    assert body["previous_response_id"] == "p"
    assert body["model"] == "muse-spark-1.3"
    assert replay.requests[0].headers["authorization"] == "Bearer test-key"
    assert replay.requests[0].url.path == "/v1/responses"


async def test_spent_budget_is_an_error_not_an_empty_reply():
    spent = {
        "id": "r",
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "reasoning", "summary": []}],
    }
    async with _client(Replay([httpx.Response(200, json=spent)])) as client:
        with pytest.raises(EmptyOutputError, match="max_output_tokens"):
            await client.create("anchor", "hi")


async def test_empty_allowed_when_asked():
    body = {"id": "r", "status": "completed", "output": []}
    async with _client(Replay([httpx.Response(200, json=body)])) as client:
        r = await client.create("anchor", "hi", allow_empty=True)
    assert r.text == ""


async def test_retries_429_then_succeeds(no_sleep):
    limited = httpx.Response(
        429,
        headers={"retry-after": "2"},
        json={"error": {"message": "slow down", "type": "rate_limit_error"}},
    )
    replay = Replay([limited, httpx.Response(503), _ok()])
    async with _client(replay) as client:
        r = await client.create("anchor", "hi")
    assert r.text == "hello"
    assert len(replay.requests) == 3


async def test_does_not_retry_400(no_sleep):
    bad = httpx.Response(
        400, json={"error": {"message": "bad effort", "type": "invalid_request_error"}}
    )
    replay = Replay([bad])
    async with _client(replay) as client:
        with pytest.raises(MetaAPIError, match="bad effort") as e:
            await client.create("anchor", "hi")
    assert e.value.status == 400 and e.value.type == "invalid_request_error"
    assert len(replay.requests) == 1


async def test_gives_up_after_max_retries(no_sleep):
    replay = Replay([httpx.Response(500) for _ in range(3)])
    client = ResponsesClient(api_key="k", transport=replay.transport(), max_retries=2)
    async with client:
        with pytest.raises(MetaAPIError):
            await client.create("anchor", "hi")
    assert len(replay.requests) == 3


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="META_API_KEY"):
        ResponsesClient()
