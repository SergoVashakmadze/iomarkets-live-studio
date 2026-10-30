"""Shared test helpers. Tests replay recorded Meta responses, so CI needs no key."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_recording(name: str) -> list[dict]:
    """A list of {request, status, response} exchanges recorded from the live API."""
    return json.loads((FIXTURES / name).read_text())


class Replay:
    """An httpx transport that answers with queued responses and keeps every request."""

    def __init__(self, responses: list[httpx.Response]):
        self.queue = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.queue:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        return self.queue.pop(0)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr("studio.meta.responses.asyncio.sleep", instant)


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Never write to the real spend ledger; start each test unmetered."""
    from studio import ledger

    monkeypatch.setenv("STUDIO_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.delenv("STUDIO_DAILY_BUDGET_USD", raising=False)
    monkeypatch.setattr(ledger, "current", None)
    monkeypatch.setenv("STUDIO_VOICE", "browser")  # no Edge TTS calls from tests
    monkeypatch.setenv("STUDIO_LIPSYNC_URL", "")  # nor lip-sync, even if a server is running
