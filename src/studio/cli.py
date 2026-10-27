"""`studio brief "<guest, company>"`: print a cited pre-interview brief."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from urllib.parse import urlsplit

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studio")
    sub = parser.add_subparsers(dest="command", required=True)
    brief = sub.add_parser("brief", help="research a guest and print a cited brief")
    brief.add_argument("subject", help='e.g. "Jane Doe, CEO of Example plc"')
    args = parser.parse_args(argv)

    _load_dotenv()
    if args.command == "brief":
        return asyncio.run(_brief(args.subject))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
