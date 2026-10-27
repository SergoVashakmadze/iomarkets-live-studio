"""The `studio` command.

- `studio brief "<guest, company>"`: print a cited pre-interview brief.
- `studio listen [--file F] [--keyword K ...]`: transcribe the guest live, turn by turn.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import urlsplit

from studio import asr
from studio.agents.scout import write_brief
from studio.meta.responses import Citation, ResponsesClient

SOURCES_SHOWN = 12


def _load_dotenv(path: str = ".env") -> None:
    try:
        with open(path) as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep and key and not key.startswith("#") and value:
                    os.environ.setdefault(key, value.strip().strip("\"'"))
    except FileNotFoundError:
        pass


def _one_per_site(citations: list[Citation]) -> list[Citation]:
    seen: set[str] = set()
    out = []
    for c in citations:
        site = urlsplit(c.url).hostname or c.url
        site = site.removeprefix("www.")
        if site not in seen:
            seen.add(site)
            out.append(c)
    return out


async def _brief(subject: str) -> int:
    async with ResponsesClient() as client:
        result = await write_brief(client, subject)
    print(result.text)
    if result.citations:
        # Every page web search returned, not a per-line citation: Fact-Check ranks them later.
        shown = _one_per_site(result.citations)[:SOURCES_SHOWN]
        print(f"\nSOURCES CONSULTED ({len(result.citations)} pages, one per site shown)")
        for i, c in enumerate(shown, 1):
            print(f"[{i}] {c.title or c.url}\n    {c.url}")
    tools = ", ".join(
        f"{r.name}({r.arguments}){'' if r.ok else ' FAILED'}" for r in result.tool_runs
    )
    print(
        f"\n({result.turns} turns, {len(result.searches)} searches; tools: {tools or 'none'})",
        file=sys.stderr,
    )
    return 0


def _ffmpeg_pcm(source: str | None) -> list[str]:
    """ffmpeg reading the default mic (PulseAudio) or a file, writing 24 kHz s16le mono."""
    src = ["-f", "pulse", "-i", "default"] if source is None else ["-i", source]
    out = ["-ac", "1", "-ar", str(asr.SAMPLE_RATE), "-f", "s16le", "-"]
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", *src, *out]


async def _listen(source: str | None, keywords: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *_ffmpeg_pcm(source), stdout=asyncio.subprocess.PIPE
    )
    async with asr.GuestListener(keywords=keywords) as listener:
        print(f"(session {listener.session_id}; Ctrl-C to stop)", file=sys.stderr)

        async def feed() -> None:
            assert proc.stdout is not None
            while chunk := await proc.stdout.read(asr.FRAME_BYTES * 4):
                listener.push(chunk)
            listener.finish()

        feeder = asyncio.create_task(feed())
        try:
            async for event in listener.events():
                match event:
                    case asr.GuestPartial(turn_id, text):
                        print(f"\r  [{turn_id}] {text[-100:]}", end="", file=sys.stderr)
                    case asr.GuestTurn(turn_id, text, audio_ms):
                        print(f"\r\x1b[K[{turn_id} @ {audio_ms / 1000:.1f}s] {text}")
        finally:
            feeder.cancel()
            if proc.returncode is None:
                proc.terminate()
            await proc.wait()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studio")
    sub = parser.add_subparsers(dest="command", required=True)
    brief = sub.add_parser("brief", help="research a guest and print a cited brief")
    brief.add_argument("subject", help='e.g. "Jane Doe, CEO of Example plc"')
    listen = sub.add_parser("listen", help="transcribe live speech, one line per turn")
    listen.add_argument("--file", help="an audio or video file instead of the microphone")
    listen.add_argument(
        "--keyword", action="append", default=[], help="a name or term to bias towards"
    )
    args = parser.parse_args(argv)

    _load_dotenv()
    if args.command == "brief":
        return asyncio.run(_brief(args.subject))
    if args.command == "listen":
        try:
            return asyncio.run(_listen(args.file, args.keyword))
        except KeyboardInterrupt:
            return 130
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
