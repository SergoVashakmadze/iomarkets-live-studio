from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest
from conftest import Replay
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from studio.asr import GuestStarted, GuestTurn
from studio.meta.responses import ResponsesClient
from studio.server import create_app


def _answer(text: str, rid: str) -> httpx.Response:
    message = {"type": "message", "content": [{"type": "output_text", "text": text}]}
    return httpx.Response(200, json={"id": rid, "status": "completed", "output": [message]})


class FakeListener:
    """Stands in for GuestListener: one guest turn once audio has arrived."""

    instances: list[FakeListener] = []

    def __init__(self, keywords=(), anchor_speaking=lambda: False):
        self.keywords = keywords
        self.anchor_speaking = anchor_speaking
        self.session_id = "fake"
        self.audio = bytearray()
        self.got_audio = asyncio.Event()
        self.finished = asyncio.Event()
        FakeListener.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def push(self, pcm: bytes) -> None:
        self.audio += pcm
        self.got_audio.set()

    def finish(self) -> None:
        self.finished.set()

    async def events(self):
        await self.got_audio.wait()
        yield GuestStarted(0, barge_in=self.anchor_speaking())
        yield GuestTurn(0, "We grew five percent.", 3000)
        await self.finished.wait()


class Router:
    """Answers anchor calls in order, and fact-check calls with one supported check."""

    def __init__(self, anchor_lines: list[str]):
        self.anchor = Replay([_answer(t, f"r{i}") for i, t in enumerate(anchor_lines, 1)])
        self.factchecks: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if (body.get("text") or {}).get("format", {}).get("name") == "fact_checks":
            self.factchecks.append(body)
            check = {"claim": "5%", "verdict": "supported", "correct_value": "5%"}
            checks = {"checks": [{**check, "explanation": "Matches.", "source_url": ""}]}
            return _answer(json.dumps(checks), "fc")
        return self.anchor(request)


@pytest.fixture
def app_and_replay():
    FakeListener.instances.clear()
    router = Router(["Welcome, Margherita.", "Where did it come from?"])
    app = create_app(
        client_factory=lambda: ResponsesClient(api_key="k", transport=httpx.MockTransport(router)),
        listener_factory=FakeListener,
    )
    return app, router


def _receive_until(ws, *kinds: str) -> list[dict]:
    """Receive until every one of `kinds` has arrived, in any order."""
    seen, waiting = [], set(kinds)
    while waiting:
        msg = ws.receive_json()
        seen.append(msg)
        waiting.discard(msg["type"])
    return seen


def _last(seen: list[dict], kind: str) -> dict:
    return [m for m in seen if m["type"] == kind][-1]


def test_page_is_served(app_and_replay):
    app, _ = app_and_replay
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "IoMarkets Live Studio" in r.text
    assert "AI system" in r.text  # the synthetic-anchor disclosure stays on the page


def test_live_interview_round_trip(app_and_replay):
    app, replay = app_and_replay
    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_json({"type": "start", "brief": "GUEST: Margherita", "keywords": ["Vodafone"]})
        assert ws.receive_json() == {"type": "ready", "session": "fake"}
        seen = _receive_until(ws, "anchor_line")
        assert seen[-1]["text"] == "Welcome, Margherita."
        ws.send_json({"type": "anchor", "speaking": True})
        ws.send_bytes(b"\x00" * 3840)
        seen = _receive_until(ws, "anchor_line", "fact_check")
        assert {"type": "stop_anchor"} in seen  # the guest spoke over the anchor
        assert _last(seen, "anchor_line")["text"] == "Where did it come from?"
        assert _last(seen, "fact_check")["checks"][0]["verdict"] == "supported"
        ws.send_json({"type": "stop"})
        _receive_until(ws, "ended")

    listener = FakeListener.instances[0]
    assert listener.keywords == ["Vodafone"]
    assert bytes(listener.audio) == b"\x00" * 3840
    second = replay.anchor.bodies()[1]
    assert "previous_response_id" not in second  # chaining costs ~10 s a turn; see anchor.py
    opening, welcome, guest = second["input"]
    assert welcome == {"role": "assistant", "content": "Welcome, Margherita."}
    assert guest == {
        "role": "user",
        "content": "Guest (They interrupted you.): We grew five percent.",
    }
    assert "GUEST: Margherita" in second["instructions"]


def test_bad_start_message_is_refused(app_and_replay):
    app, _ = app_and_replay
    with TestClient(app).websocket_connect("/ws/live") as ws:
        ws.send_json({"type": "start", "brief": ""})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 1008


def test_token_required_when_set(app_and_replay, monkeypatch):
    app, _ = app_and_replay
    monkeypatch.setenv("STUDIO_TOKEN", "s3cret")
    client = TestClient(app)
    assert client.post("/api/brief", json={"subject": "Jane Doe, Example"}).status_code == 403
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
    with client.websocket_connect("/ws/live?token=s3cret") as ws:
        ws.send_json({"type": "start", "brief": "x"})
        assert ws.receive_json()["type"] == "ready"


def test_bad_frames_are_ignored(app_and_replay):
    from studio.server import _jpeg

    assert _jpeg(base64.b64encode(b"\xff\xd8\xff\xe0rest").decode()) == b"\xff\xd8\xff\xe0rest"
    assert _jpeg(base64.b64encode(b"GIF89a").decode()) is None  # not a JPEG
    assert _jpeg("%%%not base64") is None
    assert _jpeg(None) is None
    assert _jpeg("A" * 5_000_000) is None  # too large
