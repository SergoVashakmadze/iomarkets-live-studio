"""Guest materials: links and files the producer gives Scout and the Devil's Advocate.

Links (a LinkedIn profile, a personal site, a company page) are fetched and reduced to text.
Files (a pitch deck as PDF, images, plain-text notes) go to Muse Spark as they are: Spark reads
PDFs and images itself (checked 2026-10-27 on a test deck).

Fetching a URL someone pasted is a server-side request forgery risk, so a link is fetched only
over http(s), only from a public address (checked again at every redirect), with a size and
time cap. (httpx resolves the name again when it connects, so a DNS-rebinding host could still
slip through between the check and the request; acceptable for a demo, not for production.)
Pages that refuse robots (LinkedIn does) are not forced: the model gets the URL as a
lead to search for instead.

Files are guest material, not public research: they are held in memory for one brief, never
written to disk, and never sent to the open-weights editor on Fireworks (see scout.py).
"""

from __future__ import annotations

import asyncio
import base64
import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

MAX_FILES = 5
MAX_FILE_BYTES = 20_000_000
MAX_LINKS = 6
MAX_LINK_BYTES = 2_000_000
MAX_LINK_CHARS = 15_000
MAX_REDIRECTS = 3

FILE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/plain",
}


class MaterialError(ValueError):
    pass


@dataclass
class Material:
    name: str  # file name or URL
    kind: str  # "file" or "link"
    mime: str = "text/plain"
    data: bytes | None = None  # a file's bytes
    text: str | None = None  # a link's readable text, or a text file's
    status: str = "read"  # "read", or why it could not be

    @property
    def private(self) -> bool:
        """Files are the guest's own material; links are public pages."""
        return self.kind == "file"

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.kind, "status": self.status}


def file_material(name: str, data: bytes) -> Material:
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    mime = FILE_TYPES.get(ext)
    if mime is None:
        raise MaterialError(
            f"{name}: unsupported type; use PDF (export slides or documents as PDF), "
            "PNG, JPEG, WebP, TXT or MD"
        )
    if len(data) > MAX_FILE_BYTES:
        raise MaterialError(f"{name}: larger than {MAX_FILE_BYTES // 1_000_000} MB")
    if mime == "application/pdf" and not data.startswith(b"%PDF"):
        raise MaterialError(f"{name}: not a PDF")
    if mime == "text/plain":
        return Material(name, "file", mime, text=data.decode("utf-8", "replace")[:MAX_LINK_CHARS])
    return Material(name, "file", mime, data=data)


def public_address(host: str) -> bool:
    """True only if every address the host resolves to is public."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs)


def html_to_text(page: str) -> str:
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    page = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.I | re.S)
    page = re.sub(r"<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", page, flags=re.I)
    page = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in page.splitlines()]
    text = "\n".join(line for line in lines if line)
    if title:
        text = html.unescape(title.group(1).strip()) + "\n" + text
    return text[:MAX_LINK_CHARS]


async def fetch_link(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None, resolve=public_address
) -> Material:
    """A pasted link as readable text, or a Material saying why it could not be read."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise MaterialError(f"{url}: only http(s) links")
    headers = {"User-Agent": "Mozilla/5.0 (IoMarkets Live Studio research)"}
    async with httpx.AsyncClient(timeout=10, headers=headers, transport=transport) as http:
        for _ in range(MAX_REDIRECTS + 1):
            host = urlsplit(url).hostname or ""
            if not await asyncio.to_thread(resolve, host):
                return Material(url, "link", status="not fetched: not a public address")
            try:
                async with http.stream("GET", url) as r:
                    if r.is_redirect and "location" in r.headers:
                        url = urljoin(url, r.headers["location"])
                        if urlsplit(url).scheme not in ("http", "https"):
                            return Material(url, "link", status="not fetched: bad redirect")
                        continue
                    if r.status_code >= 400:
                        return Material(url, "link", status=f"not readable (HTTP {r.status_code})")
                    body = bytearray()
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_LINK_BYTES:
                            break
                    kind = r.headers.get("content-type", "").split(";")[0].strip().lower()
            except httpx.HTTPError as e:
                return Material(url, "link", status=f"not readable ({type(e).__name__})")
            if kind == "application/pdf" and body.startswith(b"%PDF"):
                return Material(url, "link", "application/pdf", data=bytes(body))
            text = html_to_text(body.decode("utf-8", "replace"))
            if len(text) < 200:  # a login wall or a script-only page
                return Material(url, "link", status="not readable (no page text)")
            return Material(url, "link", text=text)
    return Material(url, "link", status="not fetched: too many redirects")


async def gather_links(urls: list[str]) -> list[Material]:
    urls = [u for u in (u.strip() for u in urls) if u][:MAX_LINKS]
    results = await asyncio.gather(*(fetch_link(u) for u in urls), return_exceptions=True)
    out = []
    for url, res in zip(urls, results, strict=True):
        if isinstance(res, Material):
            out.append(res)
        else:
            out.append(Material(url, "link", status=f"not fetched: {res}"))
    return out


def input_parts(materials: list[Material]) -> list[dict[str, Any]]:
    """Responses API content parts for the materials, each labelled with where it came from."""
    parts: list[dict[str, Any]] = []
    for m in materials:
        label = "Producer's file" if m.kind == "file" else "Link"
        if m.text is not None:
            parts.append({"type": "input_text", "text": f"[{label}: {m.name}]\n{m.text}"})
        elif m.data is not None and m.mime == "application/pdf":
            parts.append({"type": "input_text", "text": f"[{label}: {m.name}] (PDF follows)"})
            data = base64.b64encode(m.data).decode()
            parts.append(
                {
                    "type": "input_file",
                    "filename": m.name.rsplit("/", 1)[-1] or "document.pdf",
                    "file_data": f"data:application/pdf;base64,{data}",
                }
            )
        elif m.data is not None:
            parts.append({"type": "input_text", "text": f"[{label}: {m.name}] (image follows)"})
            data = base64.b64encode(m.data).decode()
            parts.append({"type": "input_image", "image_url": f"data:{m.mime};base64,{data}"})
        else:
            parts.append(
                {
                    "type": "input_text",
                    "text": f"[{label}: {m.name}] could not be read directly ({m.status}); "
                    "search the web for it instead.",
                }
            )
    return parts
