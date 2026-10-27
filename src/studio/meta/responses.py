"""A small client for Meta's Responses API (`POST /v1/responses`).

Responses, not Chat Completions: only Responses carries reasoning across turns for external keys,
via `previous_response_id`. That chaining is slow, though: ~10 s per call against 1-2 s for the
same call with the history resent (measured 2026-10-27). Use it where reasoning must carry over
(tool loops); a live speaker resends its history instead (see agents/anchor.py).

Two things the docs and our own measurements (2026-10-26) make us handle here:

- Reasoning tokens count against `max_output_tokens`. A spent budget comes back as a response
  with no text, which must be an error, never an empty reply. So every call names a role, and
  each role has its own effort and budget.
- 429, 500 and 503 are retryable; 429 and 503 send `Retry-After`. 504 is not retried: the
  request has to get smaller instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"

Effort = Literal["minimal", "low", "medium", "high", "max"]


@dataclass(frozen=True)
class Budget:
    effort: Effort
    max_output_tokens: int


# Starting points from the build plan §9.3; tune them against real runs.
ROLE_BUDGETS: dict[str, Budget] = {
    "anchor": Budget("minimal", 800),
    "producer": Budget("low", 1500),
    "factcheck": Budget("medium", 4000),
    "vision": Budget("low", 4000),
    "scout": Budget("medium", 6000),
}

RETRYABLE = {429, 500, 503}

log = logging.getLogger(__name__)


class MetaAPIError(RuntimeError):
    def __init__(self, status: int, message: str, type_: str | None = None):
        super().__init__(f"Meta API {status}: {message}")
        self.status = status
        self.type = type_


class EmptyOutputError(RuntimeError):
    """The model returned no text, usually because reasoning spent the token budget."""


@dataclass
class Citation:
    url: str
    title: str


@dataclass
class FunctionCall:
    call_id: str
    name: str
    arguments: str


@dataclass
class Response:
    """The parts of a response the studio uses.

    `text` is the answer only. Muse Spark also narrates its progress between tool calls in
    messages marked `phase: "commentary"`; those are kept apart in `commentary`, for status
    lines, so they never leak into a brief or a spoken turn.

    `citations` holds inline `url_citation` annotations plus the pages web search returned.
    Measured 2026-10-27: Spark adds no annotations, so the sources only arrive when the request
    sets `include: ["web_search_call.results"]`.
    """

    id: str
    status: str
    text: str
    function_calls: list[FunctionCall] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    commentary: list[str] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    incomplete_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, body: dict[str, Any]) -> Response:
        texts: list[str] = []
        commentary: list[str] = []
        searches: list[str] = []
        calls: list[FunctionCall] = []
        cites: dict[str, Citation] = {}

        def cite(url: str | None, title: str | None) -> None:
            if url:
                cites.setdefault(url, Citation(url, title or ""))

        for item in body.get("output") or []:
            kind = item.get("type")
            if kind == "function_call":
                calls.append(FunctionCall(item["call_id"], item["name"], item.get("arguments", "")))
            elif kind == "web_search_call":
                query = (item.get("action") or {}).get("query")
                if query:
                    searches.append(query)
                for result in item.get("results") or []:
                    cite(result.get("url"), result.get("title"))
            elif kind == "message":
                sink = commentary if item.get("phase") == "commentary" else texts
                for part in item.get("content") or []:
                    if part.get("type") != "output_text":
                        continue
                    sink.append(part.get("text") or "")
                    for ann in part.get("annotations") or []:
                        if ann.get("type") == "url_citation":
                            cite(ann.get("url"), ann.get("title"))
        details = body.get("incomplete_details") or {}
        return cls(
            id=body["id"],
            status=body.get("status", ""),
            text="".join(texts).strip(),
            function_calls=calls,
            citations=list(cites.values()),
            commentary=[c.strip() for c in commentary if c.strip()],
            searches=searches,
            incomplete_reason=details.get("reason"),
            raw=body,
        )


class ResponsesClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 4,
        timeout: float = 120.0,
    ):
        key = api_key or os.environ.get("META_API_KEY")
        if not key:
            raise RuntimeError("META_API_KEY is not set (see .env.example)")
        self.model = model or os.environ.get("META_MODEL") or DEFAULT_MODEL
        self.max_retries = max_retries
        self._http = httpx.AsyncClient(
            base_url=base_url or os.environ.get("META_API_BASE_URL") or DEFAULT_BASE_URL,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> ResponsesClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create(
        self,
        role: str,
        input: str | list[dict[str, Any]],
        *,
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_response_id: str | None = None,
        include: list[str] | None = None,
        allow_empty: bool = False,
    ) -> Response:
        """One Responses call under `role`'s budget.

        Raises EmptyOutputError when there is neither text nor a tool call, unless
        `allow_empty` is set.
        """
        budget = ROLE_BUDGETS[role]
        body: dict[str, Any] = {
            "model": self.model,
            "input": input,
            "reasoning": {"effort": budget.effort},
            "max_output_tokens": budget.max_output_tokens,
        }
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = tools
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        if include:
            body["include"] = include

        resp = Response.parse(await self._post("/responses", body))
        if not allow_empty and not resp.text and not resp.function_calls:
            reason = resp.incomplete_reason or resp.status or "unknown"
            raise EmptyOutputError(
                f"{role}: empty output (status={resp.status}, reason={reason}); "
                f"raise max_output_tokens above {budget.max_output_tokens} or lower the effort"
            )
        return resp

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            r = await self._http.post(path, json=body)
            if r.status_code < 400:
                return r.json()
            if r.status_code not in RETRYABLE or attempt == self.max_retries:
                raise _error(r)
            delay = _delay(r, attempt)
            log.warning("Meta %s on %s, retry %d in %.1fs", r.status_code, path, attempt + 1, delay)
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")


def _delay(r: httpx.Response, attempt: int) -> float:
    retry_after = r.headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return min(1.0 * 2**attempt, 30.0) + random.random()


def _error(r: httpx.Response) -> MetaAPIError:
    try:
        err = r.json().get("error") or {}
    except ValueError:
        err = {}
    return MetaAPIError(r.status_code, err.get("message") or r.text[:300], err.get("type"))
