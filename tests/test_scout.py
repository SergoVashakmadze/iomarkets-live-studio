from __future__ import annotations

import httpx
import pytest
from conftest import Replay, load_recording

from studio.agents.scout import prepare_brief
from studio.meta.open_weights import ATTRIBUTION, MUSE_SPARK_OPEN
from studio.meta.responses import ResponsesClient

RECORDING = load_recording("scout_amd_2026-10-27.json")
EDITED = "GUEST: Lisa Su.\nCONTEXT: AMD.\nRECENT: x\nFACTS: y\nQUESTIONS: q\nCAUTION: c"


def _answer(text: str) -> httpx.Response:
    message = {"type": "message", "content": [{"type": "output_text", "text": text}]}
    return httpx.Response(200, json={"id": "e1", "status": "completed", "output": [message]})


@pytest.fixture(autouse=True)
def no_market(monkeypatch):
    async def quote(ticker: str) -> dict:
        return {"ticker": ticker, "price": 1.0}

    monkeypatch.setattr("studio.tools.market.fetch_quote", quote)


def _research() -> ResponsesClient:
    replay = Replay([httpx.Response(200, json=e["response"]) for e in RECORDING])
    return ResponsesClient(api_key="k", transport=replay.transport())


def _editor(*responses: httpx.Response) -> tuple[ResponsesClient, Replay]:
    replay = Replay(list(responses))
    client = ResponsesClient(
        api_key="fw", base_url="https://fw.example/v1", model=MUSE_SPARK_OPEN,
        transport=replay.transport(), max_retries=0,
    )  # fmt: skip
    return client, replay


async def test_editor_on_open_weights_edits_the_draft():
    editor, replay = _editor(_answer(EDITED))
    brief = await prepare_brief(_research(), "Lisa Su, CEO of AMD", editor)
    assert brief.text == EDITED
    assert brief.edited_by == ATTRIBUTION == "Built with Muse Spark Open"
    [body] = replay.bodies()
    assert body["model"] == MUSE_SPARK_OPEN
    assert body["input"].startswith("GUEST:")  # the research draft, nothing about the guest's media
    assert "Add no fact" in body["instructions"]
    assert replay.requests[0].url.host == "fw.example"


@pytest.mark.parametrize(
    "response",
    [
        _answer("GUEST: Lisa Su.\nQUESTIONS: q"),  # sections dropped
        httpx.Response(500, json={"error": {"message": "cold start"}}),
    ],
)
async def test_falls_back_to_the_research_draft(response):
    editor, _ = _editor(response)
    brief = await prepare_brief(_research(), "Lisa Su, CEO of AMD", editor)
    assert brief.text == brief.research.text and brief.text.startswith("GUEST:")
    assert brief.edited_by is None


async def test_no_editor_configured():
    brief = await prepare_brief(_research(), "Lisa Su, CEO of AMD", None)
    assert brief.edited_by is None and brief.text.startswith("GUEST:")


def test_open_weights_client_needs_a_key(monkeypatch):
    from studio.meta.open_weights import open_weights_client

    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    assert open_weights_client() is None
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw")
    client = open_weights_client()
    assert client.model == MUSE_SPARK_OPEN
