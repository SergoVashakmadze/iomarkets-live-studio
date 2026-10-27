from __future__ import annotations

import asyncio
import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from studio import server
from studio.agents import scout
from studio.agents.factcheck import Check, PressurePoint, format_points
from studio.agents.live_scout import LiveResearch
from studio.asr import GuestTurn
from studio.live import LiveSession
from studio.materials import (
    Material,
    MaterialError,
    fetch_link,
    file_material,
    html_to_text,
    input_parts,
    public_address,
)

PAGE = (
    "<html><head><title>Jane Doe</title><script>x()</script></head><body>"
    + ("<p>Jane Doe founded Tidewater Robotics in 2021.</p>" * 10)
    + "</body></html>"
)


def _public(host: str) -> bool:
    return host != "internal.example"


def _transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: routes[str(req.url)])


def test_public_address_rejects_private_and_loopback():
    assert not public_address("127.0.0.1")
    assert not public_address("10.0.0.8")
    assert not public_address("169.254.169.254")  # cloud metadata
    assert not public_address("::1")
    assert not public_address("no-such-host.invalid")
    assert public_address("8.8.8.8")


async def test_link_is_read_as_text():
    t = _transport({"https://jane.example/": httpx.Response(200, text=PAGE,
                    headers={"content-type": "text/html"})})  # fmt: skip
    m = await fetch_link("https://jane.example/", transport=t, resolve=_public)
    assert m.status == "read" and m.text.startswith("Jane Doe\n")
    assert "x()" not in m.text and "Tidewater Robotics in 2021" in m.text
    assert not m.private


async def test_redirect_to_a_private_address_is_not_followed():
    t = _transport({"https://jane.example/": httpx.Response(
        302, headers={"location": "http://internal.example/admin"})})  # fmt: skip
    m = await fetch_link("https://jane.example/", transport=t, resolve=_public)
    assert m.text is None and "not a public address" in m.status


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/a", "javascript:alert(1)"])
async def test_only_http_links(url):
    with pytest.raises(MaterialError):
        await fetch_link(url, resolve=_public)


async def test_login_wall_becomes_a_search_lead():
    t = _transport({"https://www.linkedin.com/in/jane": httpx.Response(999, text="")})
    m = await fetch_link("https://www.linkedin.com/in/jane", transport=t, resolve=_public)
    assert m.status == "not readable (HTTP 999)"
    [part] = input_parts([m])
    assert "search the web for it instead" in part["text"]


def test_file_types_and_sizes():
    pdf = file_material("deck.PDF", b"%PDF-1.4 ...")
    assert pdf.private and pdf.mime == "application/pdf"
    assert file_material("notes.md", b"# Notes").text == "# Notes"
    with pytest.raises(MaterialError, match="export slides"):
        file_material("deck.pptx", b"PK..")
    with pytest.raises(MaterialError, match="not a PDF"):
        file_material("deck.pdf", b"<html>")
    with pytest.raises(MaterialError, match="larger"):
        file_material("big.png", b"x" * 20_000_001)


def test_input_parts_label_every_source():
    parts = input_parts(
        [
            file_material("deck.pdf", b"%PDF-1.4 x"),
            file_material("photo.png", b"\x89PNG"),
            Material("https://jane.example/", "link", text="About Jane"),
        ]
    )
    kinds = [p["type"] for p in parts]
    assert kinds == ["input_text", "input_file", "input_text", "input_image", "input_text"]
    assert (
        parts[1]["file_data"]
        == "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 x").decode()
    )
    assert parts[4]["text"].startswith("[Link: https://jane.example/]")


def test_html_to_text_caps_length():
    assert len(html_to_text("<p>" + "a" * 50_000 + "</p>")) == 15_000


# The brief: materials, the editor rule, pressure points.


class FakeResearch:
    text = "GUEST: Jane.\nCONTEXT: x\nRECENT: x\nFACTS: x\nQUESTIONS: q\nCAUTION: c"
    citations, searches = [], []


@pytest.fixture
def brief_fakes(monkeypatch):
    calls = {}

    async def write_brief(client, subject, materials=()):
        calls["materials"] = list(materials)
        return FakeResearch()

    async def edit_brief(editor, draft):
        calls["edited"] = True
        return draft.replace("GUEST: Jane.", "GUEST: Jane Doe.")

    async def points(client, draft, materials=()):
        calls["points_saw_materials"] = list(materials)
        return [PressurePoint(claim="ARR $2.1M", doubt="No filing.", question="Who audits it?")]

    monkeypatch.setattr(scout, "write_brief", write_brief)
    monkeypatch.setattr(scout, "edit_brief", edit_brief)
    monkeypatch.setattr(scout, "pressure_points", points)
    return calls


async def test_private_files_skip_the_editor_and_get_pressure_points(brief_fakes):
    parts = [{"type": "input_text", "text": "[Producer's file: deck.pdf]"}]
    b = await scout.prepare_brief(object(), "Jane Doe", editor=object(), materials=parts,
                                  private=True)  # fmt: skip
    assert "edited" not in brief_fakes and b.edited_by is None
    assert b.editor_note.startswith("skipped")
    assert brief_fakes["materials"] == parts == brief_fakes["points_saw_materials"]
    assert b.text.endswith(format_points(b.pressure))
    assert "Ask: Who audits it?" in b.text


async def test_public_links_still_use_the_editor(brief_fakes):
    b = await scout.prepare_brief(object(), "Jane Doe", editor=object(), materials=[],
                                  private=False)  # fmt: skip
    assert b.text.startswith("GUEST: Jane Doe.") and b.edited_by == "Built with Muse Spark Open"


def test_brief_endpoint_takes_links_and_files(monkeypatch):
    seen = {}

    async def prepare(client, subject, editor, materials, private):
        seen.update(subject=subject, materials=materials, private=private)
        b = scout.Brief("GUEST: x", FakeResearch(), None,
                        [PressurePoint(claim="c", doubt="d", question="q")], "skipped")  # fmt: skip
        return b

    async def links(urls):
        return [Material(u, "link", status="not readable (HTTP 999)") for u in urls]

    monkeypatch.setattr(server, "prepare_brief", prepare)
    monkeypatch.setattr(server, "gather_links", links)
    monkeypatch.delenv("STUDIO_TOKEN", raising=False)

    class NoClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    app = server.create_app(client_factory=NoClient, editor_factory=lambda: None)
    http = TestClient(app)
    r = http.post(
        "/api/brief",
        data={"subject": "Jane Doe, founder", "links": "https://www.linkedin.com/in/jane\n"},
        files=[("files", ("deck.pdf", b"%PDF-1.4 deck", "application/pdf"))],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["private"] is True and seen["subject"] == "Jane Doe, founder"
    assert [m["kind"] for m in body["materials"]] == ["file", "link"]
    assert body["pressure_points"][0]["question"] == "q"
    pptx = ("files", ("deck.pptx", b"PK", "application/octet-stream"))
    bad = http.post("/api/brief", data={"subject": "Jane Doe"}, files=[pptx])
    assert bad.status_code == 400 and "PDF" in bad.json()["detail"]


# Live: cold-start research and the Devil's Advocate's challenges.


class Anchor:
    def __init__(self):
        self.calls = []

    async def opening(self):
        return "Welcome. Tell us about yourself?"

    async def reply(self, said, *, interrupted=False, notes=(), research=""):
        self.calls.append({"said": said, "notes": list(notes), "research": research})
        return "Go on?"


class Desk:
    def __init__(self, checks=()):
        self.checks = list(checks)
        self.learned = ""

    async def check(self, said):
        found, self.checks = self.checks, []
        return found

    async def read_chart(self, jpeg):
        raise AssertionError

    def learn(self, research):
        self.learned = research


def _session(**kw):
    sent = []

    async def send(m):
        sent.append(m)

    anchor = Anchor()
    return LiveSession(anchor, send, **kw), sent, anchor


async def _settle(n=30):
    for _ in range(n):
        await asyncio.sleep(0)


async def test_cold_start_researches_and_feeds_the_anchor_and_the_desk():
    seen = []
    gate = asyncio.Event()

    async def researcher(transcript, known):
        seen.append((transcript, known))
        await gate.wait()
        return LiveResearch(who="Jane Doe, founder of Tidewater", facts=["14 ports (site)"],
                            angles=["hull cleaning economics"])  # fmt: skip

    desk = Desk()
    s, sent, anchor = _session(desk=desk, researcher=researcher)
    await s.on_event(GuestTurn(0, "I'm Jane, I run Tidewater.", 0))
    await _settle()
    await s.on_event(GuestTurn(1, "We clean ship hulls with robots.", 0))  # while searching
    await _settle()
    assert len(seen) == 1  # one search at a time
    gate.set()
    await _settle()
    assert len(seen) == 2  # one more for the turn that arrived meanwhile
    assert "Guest: We clean ship hulls" in seen[1][0] and "Tidewater" in seen[1][1]
    assert [m["type"] for m in sent].count("research") == 2
    assert desk.learned.startswith("Guest: Jane Doe, founder of Tidewater")
    await s.on_event(GuestTurn(2, "Thanks.", 0))
    await _settle()
    assert "hull cleaning economics" in anchor.calls[-1]["research"]


async def test_challenges_reach_the_anchor_capped():
    checks = [
        Check(
            claim=f"claim {i}",
            verdict="unverifiable",
            correct_value="",
            explanation="",
            source_url="",
            challenge=f"evidence for {i}?",
        )  # fmt: skip
        for i in range(5)
    ]
    s, sent, anchor = _session(desk=Desk(checks))
    await s.on_event(GuestTurn(0, "We are the market leader in 40 ports.", 0))
    await _settle()
    assert len(s.notes) == 3
    await s.on_event(GuestTurn(1, "Next.", 0))
    await _settle()
    notes = anchor.calls[-1]["notes"]
    assert len(notes) == 3 and "You could ask: evidence for 0?" in notes[0]


# Video: platform pages, direct MP4 links, dropped MP4 files.

from studio.materials import upload_videos, video_platform  # noqa: E402

YT = "https://www.youtube.com/watch?v=abc123"
YT_PAGE = (
    "<html><head><title>Jane Doe on hull robots - YouTube</title>"
    '<meta property="og:description" content="Keynote at Port Tech 2026: 14 ports and counting.">'
    "</head><body>" + "<script>var x=1;</script>" * 50 + "</body></html>"
)


def test_video_platforms_are_recognised():
    assert video_platform(YT) == "https://www.youtube.com/oembed"
    assert video_platform("https://youtu.be/abc123") == "https://www.youtube.com/oembed"
    assert video_platform("https://m.youtube.com/watch?v=x") == "https://www.youtube.com/oembed"
    assert video_platform("https://vimeo.com/12345") == "https://vimeo.com/api/oembed.json"
    assert video_platform("https://example.com/talk") is None


async def test_youtube_page_is_read_never_downloaded():
    requested = []

    def handler(req: httpx.Request) -> httpx.Response:
        requested.append(str(req.url))
        if req.url.path == "/oembed":
            meta = {"title": "Jane Doe on hull robots", "author_name": "Port Tech"}
            return httpx.Response(200, json={**meta, "provider_name": "YouTube"})
        return httpx.Response(200, text=YT_PAGE, headers={"content-type": "text/html"})

    m = await fetch_link(YT, transport=httpx.MockTransport(handler), resolve=_public)
    assert m.status == "read" and m.text.startswith("Video page (YouTube): Jane Doe on hull robots")
    assert "by Port Tech" in m.text and "14 ports and counting" in m.text
    assert "search the web" in m.text
    assert all("googlevideo" not in u and ".mp4" not in u for u in requested)


async def test_direct_mp4_link_goes_to_spark_by_url():
    mp4 = httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42",
                         headers={"content-type": "video/mp4"})  # fmt: skip
    t = _transport({"https://cdn.example/talk.mp4": mp4})
    m = await fetch_link("https://cdn.example/talk.mp4", transport=t, resolve=_public)
    assert m.video_url == "https://cdn.example/talk.mp4" and m.data is None
    [_, part] = input_parts([m])
    assert part == {"type": "input_video", "video_url": "https://cdn.example/talk.mp4"}


async def test_dropped_mp4_is_uploaded_then_referenced():
    mp4 = file_material("old-interview.mp4", b"\x00\x00\x00\x18ftypisom" + b"0" * 100)
    assert mp4.private and mp4.mime == "video/mp4"
    with pytest.raises(ValueError, match="upload the video"):
        input_parts([mp4])

    class Files:
        uploaded = []

        async def upload_bytes(self, name, data):
            self.uploaded.append(name)
            return "file-v1"

    ids = await upload_videos(Files(), [mp4, file_material("notes.md", b"x")])
    assert ids == ["file-v1"] and Files.uploaded == ["old-interview.mp4"]
    assert input_parts([mp4])[1] == {"type": "input_video", "file_id": "file-v1"}


def test_video_files_are_checked():
    with pytest.raises(MaterialError, match="not an MP4"):
        file_material("clip.mp4", b"RIFF....AVI ")
    with pytest.raises(MaterialError, match="unsupported"):
        file_material("clip.mov", b"\x00\x00\x00\x14ftypqt  ")


def test_brief_endpoint_deletes_uploaded_video_even_on_failure(monkeypatch):
    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def upload_bytes(self, name, data):
            calls.append(("upload", name))
            return "file-v9"

        async def delete_file(self, file_id):
            calls.append(("delete", file_id))

    async def prepare(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(server, "prepare_brief", prepare)
    monkeypatch.delenv("STUDIO_TOKEN", raising=False)
    app = server.create_app(client_factory=Client, editor_factory=lambda: None)
    video = ("files", ("talk.mp4", b"\x00\x00\x00\x18ftypisom0000", "video/mp4"))
    with pytest.raises(RuntimeError):
        TestClient(app).post("/api/brief", data={"subject": "Jane Doe"}, files=[video])
    assert calls == [("upload", "talk.mp4"), ("delete", "file-v9")]
