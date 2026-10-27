"""The studio web app: one page, a brief endpoint and the live interview socket.

    uv run studio serve        # http://127.0.0.1:8000

`/ws/live` protocol. The page sends `{"type": "start", "brief": ..., "keywords": [...]}`
first, then binary frames of 24 kHz s16le mono PCM from the guest's microphone, plus
`{"type": "anchor", "speaking": bool}` as playback starts and stops,
`{"type": "frame", "jpeg": <base64>}` when the guest shows a chart, and `{"type": "stop"}` to
end. The server answers with the LiveSession messages (see `live.py`).

If `STUDIO_TOKEN` is set, every request must carry it as `?token=`; set it whenever the page
is reachable from anywhere but this machine.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hmac
import json
import os
from collections.abc import Callable
from importlib.resources import files
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from studio.agents.anchor import Anchor
from studio.agents.factcheck import FactDesk
from studio.agents.scout import prepare_brief
from studio.asr import AsrError, GuestListener
from studio.live import LiveSession
from studio.meta.open_weights import open_weights_client
from studio.meta.responses import ResponsesClient

MAX_BRIEF_CHARS = 20_000
MAX_FRAME_BYTES = 3_000_000  # one JPEG camera frame


class BriefRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=200)


class Start(BaseModel):
    type: str
    brief: str = Field(min_length=1, max_length=MAX_BRIEF_CHARS)
    keywords: list[str] = Field(default_factory=list, max_length=50)


def _token_ok(given: str | None) -> bool:
    expected = os.environ.get("STUDIO_TOKEN")
    if not expected:
        return True
    return given is not None and hmac.compare_digest(given.encode(), expected.encode())


def create_app(
    client_factory: Callable[[], ResponsesClient] = ResponsesClient,
    listener_factory: Callable[..., GuestListener] = GuestListener,
    editor_factory: Callable[[], ResponsesClient | None] = open_weights_client,
) -> FastAPI:
    app = FastAPI(title="IoMarkets Live Studio")
    page = files("studio.web").joinpath("index.html").read_text()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return page

    @app.post("/api/brief")
    async def brief(req: BriefRequest, token: str | None = Query(None)) -> dict[str, Any]:
        if not _token_ok(token):
            raise HTTPException(403, "bad token")
        editor = editor_factory()
        async with client_factory() as client:
            try:
                brief = await prepare_brief(client, req.subject, editor)
            finally:
                if editor:
                    await editor.aclose()
        return {
            "text": brief.text,
            "sources": [{"title": c.title, "url": c.url} for c in brief.research.citations],
            "searches": brief.research.searches,
            "edited_by": brief.edited_by,
        }

    @app.websocket("/ws/live")
    async def live(ws: WebSocket, token: str | None = Query(None)) -> None:
        if not _token_ok(token):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            start = Start.model_validate(await ws.receive_json())
        except (ValueError, WebSocketDisconnect):
            await ws.close(code=1008)
            return
        try:
            await _run_live(ws, start, client_factory, listener_factory)
        except WebSocketDisconnect:
            pass
        except AsrError as e:
            with contextlib.suppress(Exception):
                await ws.send_json({"type": "error", "message": f"speech recognition: {e}"})
                await ws.close(code=1011)

    return app


async def _run_live(
    ws: WebSocket,
    start: Start,
    client_factory: Callable[[], ResponsesClient],
    listener_factory: Callable[..., GuestListener],
) -> None:
    async with client_factory() as client:
        desk = FactDesk(client, start.brief)
        session = LiveSession(Anchor(client, start.brief), ws.send_json, desk)
        listener = listener_factory(
            keywords=start.keywords, anchor_speaking=lambda: session.anchor_speaking
        )
        async with listener:
            await session.send({"type": "ready", "session": listener.session_id})
            await session.open()

            async def from_page() -> None:
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        listener.finish()
                        return
                    if msg.get("bytes"):
                        listener.push(msg["bytes"])
                    elif msg.get("text"):
                        control = _json(msg["text"])
                        if control.get("type") == "anchor":
                            session.set_anchor_speaking(bool(control.get("speaking")))
                        elif control.get("type") == "frame":
                            jpeg = _jpeg(control.get("jpeg"))
                            if jpeg:
                                await session.on_frame(jpeg)
                        elif control.get("type") == "stop":
                            listener.finish()

            reader = asyncio.create_task(from_page())
            try:
                async for event in listener.events():
                    await session.on_event(event)
                with contextlib.suppress(Exception):  # the page may already be gone
                    await session.send({"type": "ended"})
            finally:
                reader.cancel()
                await session.close()


def _jpeg(b64: Any) -> bytes | None:
    if not isinstance(b64, str) or len(b64) > MAX_FRAME_BYTES * 4 // 3 + 4:
        return None
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    return data if data.startswith(b"\xff\xd8") else None  # JPEG magic


def _json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
