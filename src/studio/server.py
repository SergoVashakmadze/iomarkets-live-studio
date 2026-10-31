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
import shutil
from collections.abc import Callable
from functools import partial
from importlib.resources import files
from typing import Annotated, Any

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field, model_validator

from studio import compose, greeting, ledger
from studio.agents import live_scout
from studio.agents.anchor import COLD_BRIEF, Anchor
from studio.agents.factcheck import FactDesk
from studio.agents.scout import prepare_brief
from studio.asr import AsrError, GuestListener
from studio.ledger import BudgetExceeded, Ledger
from studio.live import Greeting, LiveSession
from studio.materials import (
    MAX_FILES,
    MAX_LINKS,
    MAX_UPLOAD_BYTES,
    MaterialError,
    file_material,
    gather_links,
    input_parts,
    upload_videos,
)
from studio.meta.open_weights import open_weights_client
from studio.meta.responses import ResponsesClient
from studio.segment import MAX_CLIP_BYTES, ROOMS, SegmentRoom
from studio.tts import synthesize

MAX_BRIEF_CHARS = 20_000
MAX_FRAME_BYTES = 1_400_000  # one JPEG frame; base64 must fit a 2 MiB WebSocket message (Modal)
MAX_INTERVIEW_S = 15 * 60
# A forgotten tab must not keep the microphone, speech recognition and the GPU running.
IDLE_END_S = 3 * 60
# The studio's pictures: the set and the anchor, made with Meta's Muse Image
# (scripts/anchor_art.py); the page falls back to backdrop.jpg if one is missing.
ASSETS = {
    "backdrop.jpg": "image/jpeg",
    "studio.jpg": "image/jpeg",
    "anchor.jpg": "image/jpeg",
}


class SegmentRequest(BaseModel):
    name: str = Field("", max_length=80)
    role: str = Field("", max_length=120)


class Start(BaseModel):
    type: str
    brief: str = Field("", max_length=MAX_BRIEF_CHARS)
    cold: bool = False  # no brief: the anchor improvises and Live Scout researches as it goes
    keywords: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _brief_or_cold(self) -> Start:
        if not self.cold and not self.brief.strip():
            raise ValueError("a brief, or a cold start")
        return self


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
    warming: set[asyncio.Task] = set()

    @app.get("/", response_class=HTMLResponse)
    async def index(token: str | None = Query(None)) -> str:
        # Make the greeting ready while the operator sets up, so going live starts at once.
        # Only for the token's holders: a stranger or a crawler must not spend anything.
        if os.environ.get("STUDIO_VOICE") != "browser" and _token_ok(token) and not warming:
            task = asyncio.create_task(_warm_greeting())
            warming.add(task)
            task.add_done_callback(warming.discard)
        return page

    @app.get("/assets/{name}")
    async def asset(name: str, token: str | None = Query(None)) -> Response:
        """The studio backdrop and the anchor's frames, by exact name only."""
        if not _token_ok(token):
            raise HTTPException(403, "bad token")
        path = files("studio.assets").joinpath(name)
        if name not in ASSETS or not path.is_file():
            raise HTTPException(404, "no such asset")
        return Response(
            path.read_bytes(), media_type=ASSETS[name], headers={"cache-control": "max-age=3600"}
        )

    @app.post("/api/brief")
    async def brief(
        subject: str = Form(min_length=3, max_length=300),
        links: str = Form("", max_length=4000),
        files: Annotated[list[UploadFile] | None, File()] = None,
        token: str | None = Query(None),
    ) -> dict[str, Any]:
        """Scout's brief on a guest, from the web and from any links and files attached."""
        if not _token_ok(token):
            raise HTTPException(403, "bad token")
        _within_budget()
        urls = [u.strip() for u in links.splitlines() if u.strip()]
        if len(urls) > MAX_LINKS or len(files or []) > MAX_FILES:
            raise HTTPException(400, f"at most {MAX_LINKS} links and {MAX_FILES} files")
        try:
            found = [
                file_material(f.filename or "file", await _read_capped(f)) for f in files or []
            ]
            found += await gather_links(urls)
        except MaterialError as e:
            raise HTTPException(400, str(e)) from e
        private = any(m.private for m in found)
        editor = editor_factory()
        async with client_factory() as client:
            uploaded: list[str] = []
            try:
                uploaded = await upload_videos(client, found)
                brief = await prepare_brief(
                    client, subject, editor, input_parts(found), private=private
                )
            finally:
                for file_id in uploaded:  # guest video is kept no longer than the brief
                    with contextlib.suppress(Exception):
                        await client.delete_file(file_id)
                if editor:
                    await editor.aclose()
        return {
            "text": brief.text,
            "sources": [{"title": c.title, "url": c.url} for c in brief.research.citations],
            "searches": brief.research.searches,
            "edited_by": brief.edited_by,
            "editor_note": brief.editor_note,
            "materials": [m.summary() for m in found],
            "pressure_points": [p.model_dump() for p in brief.pressure],
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
    async def segment(
        key: str, req: SegmentRequest | None = None, token: str | None = Query(None)
    ) -> dict[str, str]:
        room = _room(key, token)
        req = req or SegmentRequest()
        try:
            return {"file": await room.build_segment(req.name.strip(), req.role.strip())}
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


async def _warm_greeting() -> None:
    with contextlib.suppress(Exception):
        await greeting.prepare(synthesize, await compose.lipsync_up())


async def _run_live(
    ws: WebSocket,
    start: Start,
    client_factory: Callable[[], ResponsesClient],
    listener_factory: Callable[..., GuestListener],
) -> None:
    async with client_factory() as client:
        desk = FactDesk(client, start.brief or COLD_BRIEF)
        researcher = partial(live_scout.research, client) if start.cold else None
        voice = None if os.environ.get("STUDIO_VOICE") == "browser" else synthesize
        anchor = Anchor(client, start.brief, cold=start.cold)
        # Live lip-sync when the lip-sync server is up (the workstation; not Modal).
        synced = voice is not None and await compose.lipsync_up()

        # The greeting plays the moment the interview starts (greeting.py); made once, then kept.
        hello = None
        if voice is not None:
            with contextlib.suppress(Exception):
                hello = await asyncio.wait_for(greeting.prepare(voice, synced), 30)
        # Her loop starts where the greeting's clip ended, or from her still.
        starts = [hello.cursor if hello and hello.clip else 0]

        async def lipsync(mp3: bytes, line_id: int, part: int) -> str | None:
            name = f"say-{line_id}-{part}"
            src = room.dir / f"{name}.mp3"
            src.write_bytes(mp3)
            try:
                start = starts.pop() if starts else None  # later clips carry on by themselves
                end = await compose.lipsync(src, room.dir / f"{name}.mp4", "live", start=start)
            finally:
                src.unlink(missing_ok=True)
            return f"{name}.mp4" if end is not None else None

        greet = None
        if hello:
            greet = Greeting(greeting.GREETING, hello.mp3.read_bytes(), None, hello.seconds)
        session = LiveSession(
            anchor, ws.send_json, desk, voice, researcher, lipsync if synced else None, greet
        )
        listener = listener_factory(
            keywords=start.keywords, anchor_speaking=lambda: session.anchor_speaking
        )
        room = SegmentRoom(client, session.send, questions=session.question_for_turn, voice=voice)
        if greet and hello and hello.clip and synced:
            shutil.copy(hello.clip, room.dir / "say-0-0.mp4")
            greet.video = "say-0-0.mp4"
        async with listener:
            await session.send(
                {
                    "type": "ready",
                    "session": listener.session_id,
                    "room": room.key,
                    "lipsync": synced,
                }
            )
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
                loop = asyncio.get_running_loop()
                started = loop.time()
                while True:
                    await asyncio.sleep(min(10, IDLE_END_S))
                    now = loop.time()
                    if now - started >= MAX_INTERVIEW_S:
                        reason = "15-minute limit: ending."
                    elif now - session.last_heard >= IDLE_END_S and not session.anchor_speaking:
                        reason = f"No one has spoken for {IDLE_END_S // 60} minutes: ending."
                    else:
                        continue
                    await session.send({"type": "error", "message": reason})
                    listener.finish()
                    return

            limiter = asyncio.create_task(time_limit())
            try:
                async for event in listener.events():
                    await session.on_event(event)
                with contextlib.suppress(Exception):  # the page may already be gone
                    await session.send({"type": "ended", "cutouts_pending": room.busy})
            finally:
                reader.cancel()
                limiter.cancel()
                await session.drain()
                await session.close()
                await room.drain()
                room.close()
                if synced and compose._on_modal():  # the GPU idles five minutes, then stops
                    ledger.charge("gpu", ledger.gpu_seconds(ledger.GPU_IDLE_S))
                with contextlib.suppress(Exception):
                    await session.send({"type": "cutouts_done"})


async def _read_capped(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise MaterialError(f"{upload.filename}: larger than {MAX_UPLOAD_BYTES // 1_000_000} MB")
    return data


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
