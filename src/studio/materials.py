"""Guest materials: links and files the producer gives Scout and the Devil's Advocate.

Links (a LinkedIn profile, a personal site, a company page) are fetched and reduced to text.
Files (a pitch deck as PDF, images, plain-text notes) go to Muse Spark as they are: Spark reads
PDFs and images itself (checked 2026-10-27 on a test deck).

Video: Spark takes MP4 only, picture and sound (a 16 s clip in 9.6 s, 2026-10-27), and
rejects a YouTube page URL ("unsupported media type text/html"). So:
- a direct .mp4 link goes to Spark by URL, and Meta fetches it;
- a dropped MP4 (one the producer has the rights to, an old interview say) is uploaded to the
  Files API for the brief and deleted straight after;
- a YouTube or Vimeo page is read through the platform's official oEmbed endpoint and the
  page's own description, and Scout searches the web for coverage and transcripts of it. The
  studio never downloads from those platforms: their terms forbid it.

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
MAX_VIDEO_BYTES = 200_000_000
MAX_UPLOAD_BYTES = MAX_VIDEO_BYTES  # what the server reads before checking the type
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
    ".mp4": "video/mp4",
}

# Video platforms whose pages are read through their official oEmbed endpoints.
OEMBED = {
    "youtube.com": "https://www.youtube.com/oembed",
    "youtu.be": "https://www.youtube.com/oembed",
    "vimeo.com": "https://vimeo.com/api/oembed.json",
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
    video_url: str | None = None  # a direct MP4 link, which Meta fetches itself
    file_id: str | None = None  # a dropped video, once uploaded to the Files API

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
            "PNG, JPEG, WebP, TXT, MD or MP4 video"
        )
    if mime == "video/mp4":
        if len(data) > MAX_VIDEO_BYTES:
            raise MaterialError(f"{name}: video larger than {MAX_VIDEO_BYTES // 1_000_000} MB")
        if data[4:8] != b"ftyp":
            raise MaterialError(f"{name}: not an MP4 video")
        return Material(name, "file", mime, data=data)
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


def _meta_description(page: str) -> str:
    for attr in ("og:description", "description"):
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{attr}["\'][^>]+content=["\']([^"\']*)', page, re.I
        )
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def html_to_text(page: str) -> str:
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    description = _meta_description(page)
    page = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.I | re.S)
    page = re.sub(r"<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", page, flags=re.I)
    page = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in page.splitlines()]
    text = "\n".join(line for line in lines if line)
    if description:
        text = description + "\n" + text
    if title:
        text = html.unescape(title.group(1).strip()) + "\n" + text
    return text[:MAX_LINK_CHARS]


def video_platform(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.").removeprefix("m.")
    return OEMBED.get(host)


@dataclass
class _Fetched:
    url: str
    status: str  # "ok", or why not
    kind: str = ""  # content type
    body: bytes = b""


async def _guarded_get(url: str, transport: httpx.AsyncBaseTransport | None, resolve) -> _Fetched:
    """GET a public http(s) URL: every hop's address checked, size and time capped.

    An MP4 is not downloaded (Meta fetches it itself): its body comes back empty.
    """
    headers = {"User-Agent": "Mozilla/5.0 (IoMarkets Live Studio research)"}
    async with httpx.AsyncClient(timeout=10, headers=headers, transport=transport) as http:
        for _ in range(MAX_REDIRECTS + 1):
            if not await asyncio.to_thread(resolve, urlsplit(url).hostname or ""):
                return _Fetched(url, "not fetched: not a public address")
            try:
                async with http.stream("GET", url) as r:
                    if r.is_redirect and "location" in r.headers:
                        url = urljoin(url, r.headers["location"])
                        if urlsplit(url).scheme not in ("http", "https"):
                            return _Fetched(url, "not fetched: bad redirect")
                        continue
                    if r.status_code >= 400:
                        return _Fetched(url, f"not readable (HTTP {r.status_code})")
                    kind = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if kind == "video/mp4":
                        return _Fetched(url, "ok", kind)
                    body = bytearray()
                    async for chunk in r.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_LINK_BYTES:
                            break
                    return _Fetched(url, "ok", kind, bytes(body))
            except httpx.HTTPError as e:
                return _Fetched(url, f"not readable ({type(e).__name__})")
    return _Fetched(url, "not fetched: too many redirects")


async def read_video_page(
    url: str, endpoint: str, *, transport: httpx.AsyncBaseTransport | None = None, resolve=None
) -> Material:
    """A YouTube or Vimeo link: title, channel and description, never the video itself.

    These pages are almost all script, so the description comes from the page's own metadata,
    and title and channel from the platform's official oEmbed endpoint.
    """
    resolve = resolve or public_address
    meta: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=10, transport=transport) as http:
        try:
            r = await http.get(endpoint, params={"url": url, "format": "json"})
            if r.status_code == 200:
                meta = r.json()
        except (httpx.HTTPError, ValueError):
            pass
    page = await _guarded_get(url, transport, resolve)
    description = _meta_description(page.body.decode("utf-8", "replace")) if page.body else ""
    title, author = meta.get("title", ""), meta.get("author_name", "")
    if not (title or description):
        return Material(url, "link", status="not readable (video page)")
    text = (
        f"Video page ({meta.get('provider_name', 'video')}): {title or 'untitled'}"
        f"{f' by {author}' if author else ''}.\nDescription: {description or 'none'}\n"
        "The video itself cannot be watched from a page link: search the web for coverage, "
        "articles or transcripts of this talk, and use only what you can confirm."
    )
    return Material(url, "link", text=text)


async def fetch_link(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolve=public_address,
) -> Material:
    """A pasted link as readable text, or a Material saying why it could not be read."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise MaterialError(f"{url}: only http(s) links")
    endpoint = video_platform(url)
    if endpoint:
        return await read_video_page(url, endpoint, transport=transport, resolve=resolve)
    got = await _guarded_get(url, transport, resolve)
    if got.status != "ok":
        return Material(got.url, "link", status=got.status)
    if got.kind == "video/mp4":  # Meta fetches it itself; no need to download
        return Material(got.url, "link", "video/mp4", video_url=got.url)
    if got.kind == "application/pdf" and got.body.startswith(b"%PDF"):
        return Material(got.url, "link", "application/pdf", data=got.body)
    text = html_to_text(got.body.decode("utf-8", "replace"))
    if len(text) < 200:  # a login wall or a script-only page
        return Material(got.url, "link", status="not readable (no page text)")
    return Material(got.url, "link", text=text)


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
        elif m.video_url or m.file_id:
            parts.append({"type": "input_text", "text": f"[{label}: {m.name}] (video follows)"})
            source = {"file_id": m.file_id} if m.file_id else {"video_url": m.video_url}
            parts.append({"type": "input_video", **source})
        elif m.data is not None and m.mime == "video/mp4":
            raise ValueError(f"{m.name}: upload the video (upload_videos) before building parts")
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


async def upload_videos(client: Any, materials: list[Material]) -> list[str]:
    """Upload dropped videos to the Files API; returns their ids, to delete after the brief."""
    ids = []
    for m in materials:
        if m.mime == "video/mp4" and m.data is not None and m.file_id is None:
            m.file_id = await client.upload_bytes(m.name, m.data)
            ids.append(m.file_id)
    return ids
