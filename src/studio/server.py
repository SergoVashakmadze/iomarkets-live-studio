"""The studio web app: one page, a brief endpoint and the live interview socket.

    uv run studio serve        # http://127.0.0.1:8000

`/ws/live` protocol. The page sends `{"type": "start", "brief": ..., "keywords": [...]}`
first, then binary frames of 24 kHz s16le mono PCM from the guest's microphone, plus
`{"type": "anchor", "speaking": bool}` as playback starts and stops,
`{"type": "frame", "jpeg": <base64>}` when the guest shows a chart, and `{"type": "stop"}` to
end. The server answers with the LiveSession messages (see `live.py`).

If `STUDIO_TOKEN` is set, every request must carry it as `?token=`; set it whenever the page
is reachable from anywhere but this machine. `STUDIO_TOKEN_PREV` is also accepted, so the
token can rotate without cutting anyone off (docs/SECRETS.md).
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

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from studio import ledger
from studio.agents.anchor import Anchor
from studio.agents.factcheck import FactDesk
from studio.agents.scout import prepare_brief
from studio.asr import AsrError, GuestListener
from studio.ledger import BudgetExceeded, Ledger
from studio.live import LiveSession
from studio.meta.open_weights import open_weights_client
from studio.meta.responses import ResponsesClient
from studio.segment import MAX_CLIP_BYTES, ROOMS, SegmentRoom
from studio.tts import synthesize

MAX_BRIEF_CHARS = 20_000
MAX_FRAME_BYTES = 1_400_000  # one JPEG frame; base64 must fit a 2 MiB WebSocket message (Modal)
MAX_INTERVIEW_S = 15 * 60


class BriefRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=200)


class Start(BaseModel):
    type: str
    brief: str = Field(min_length=1, max_length=MAX_BRIEF_CHARS)
    keywords: list[str] = Field(default_factory=list, max_length=50)


def _token_ok(given: str | None) -> bool:
    """`STUDIO_TOKEN`, or `STUDIO_TOKEN_PREV` while a rotation overlaps (docs/SECRETS.md)."""
    current = os.environ.get("STUDIO_TOKEN")
    if not current:
        return True
    if given is None:
        return False
    accepted = [current, os.environ.get("STUDIO_TOKEN_PREV") or ""]
    # Compare against every candidate, so timing does not reveal which one matched.
    matches = [hmac.compare_digest(given.encode(), t.encode()) for t in accepted if t]
    return any(matches)


def create_app(
    client_factory: Callable[[], ResponsesClient] = ResponsesClient,
    listener_factory: Callable[..., GuestListener] = GuestListener,
    editor_factory: Callable[[], ResponsesClient | None] = open_weights_client,
    spend: Ledger | None = None,
) -> FastAPI:
    app = FastAPI(title="IoMarkets Live Studio")
    ledger.current = spend or Ledger.from_env()

    def _within_budget() -> None:
        try:
            ledger.current.check()
        except BudgetExceeded as e:
            raise HTTPException(429, str(e)) from e

    @app.get("/api/budget")
    async def budget(token: str | None = Query(None)) -> dict[str, Any]:
        if not _token_ok(token):
            raise HTTPException(403, "bad token")
        return {
            "spent_today_usd": ledger.current.spent_today(),
            "budget_usd": ledger.current.budget_usd,
            "by_kind": ledger.current.today(),
        }

    page = files("studio.web").joinpath("index.html").read_text()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return page

    @app.post("/api/brief")
    async def brief(req: BriefRequest, token: str | None = Query(None)) -> dict[str, Any]:
        if not _token_ok(token):
            raise HTTPException(403, "bad token")
        _within_budget()
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

    def _room(key: str, token: str | None) -> SegmentRoom:
        if not _token_ok(token):
            raise HTTPException(403, "bad token")
        room = ROOMS.get(key)
        if room is None:
            raise HTTPException(404, "no such interview")
        return room

    @app.post("/api/answers/{key}/{turn}")
    async def answer(
        key: str,
        turn: int,
        request: Request,
        start: float = Query(0.0, ge=0, le=600),
        token: str | None = Query(None),
    ) -> dict[str, str]:
        """One guest answer as WebM, recorded by the page; cut out in the background."""
        room = _room(key, token)
        if not 0 <= turn < 10_000:
            raise HTTPException(400, "bad turn")
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_CLIP_BYTES:
                raise HTTPException(413, "clip too large")
        if not body:
            raise HTTPException(400, "empty clip")
        _within_budget()
        try:
            room.add_answer(turn, bytes(body), start)
        except OverflowError as e:
            raise HTTPException(429, str(e)) from e
        return {"status": "accepted"}

    @app.post("/api/segment/{key}")
    async def segment(key: str, token: str | None = Query(None)) -> dict[str, str]:
        room = _room(key, token)
        try:
            return {"file": await room.build_segment()}
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.get("/media/{key}/{name}")
    async def media(key: str, name: str, token: str | None = Query(None)) -> FileResponse:
        path = _room(key, token).media_path(name)
        if path is None:
            raise HTTPException(404, "no such file")
        return FileResponse(path, media_type="video/mp4", filename=name)

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
            ledger.current.check()
        except BudgetExceeded as e:
            await ws.send_json({"type": "error", "message": str(e)})
            await ws.close(code=1008)
            return
        try:
            await _run_live(ws, start, client_factory, listener_factory)
        except WebSocketDisconnect:
            return
        except AsrError as e:
            with contextlib.suppress(Exception):
                await ws.send_json({"type": "error", "message": f"speech recognition: {e}"})
                await ws.close(code=1011)
            return
        with contextlib.suppress(Exception):  # a clean close once the cut-outs are done
            await ws.close(code=1000)

    return app


async def _run_live(
    ws: WebSocket,
    start: Start,
    client_factory: Callable[[], ResponsesClient],
    listener_factory: Callable[..., GuestListener],
) -> None:
    async with client_factory() as client:
        desk = FactDesk(client, start.brief)
        voice = None if os.environ.get("STUDIO_VOICE") == "browser" else synthesize
        session = LiveSession(Anchor(client, start.brief), ws.send_json, desk, voice)
        listener = listener_factory(
            keywords=start.keywords, anchor_speaking=lambda: session.anchor_speaking
        )
        room = SegmentRoom(client, session.send)
        async with listener:
            await session.send({"type": "ready", "session": listener.session_id, "room": room.key})
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

            async def time_limit() -> None:
                await asyncio.sleep(MAX_INTERVIEW_S)
                await session.send({"type": "error", "message": "15-minute limit: ending."})
                listener.finish()

            limiter = asyncio.create_task(time_limit())
            try:
                async for event in listener.events():
                    await session.on_event(event)
                with contextlib.suppress(Exception):  # the page may already be gone
                    await session.send({"type": "ended", "cutouts_pending": room.busy})
            finally:
                reader.cancel()
                limiter.cancel()
                await session.close()
                await room.drain()
                room.close()
                with contextlib.suppress(Exception):
                    await session.send({"type": "cutouts_done"})


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
