"""`market_quote(ticker)`: the last price of one listed security.

Source: Yahoo Finance's chart endpoint, which needs no key but is unofficial and may change.
A quote is a number to check a guest's claim against, never advice, so the tool returns the
facts and the time they were true, nothing more.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from studio.agents.loop import FunctionTool

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


class QuoteArgs(BaseModel):
    ticker: str = Field(
        pattern=r"^[A-Za-z0-9.\-^=]{1,15}$",
        description="Exchange ticker as Yahoo Finance writes it, e.g. AAPL, VOD.L, ^GSPC",
    )


class QuoteNotFound(LookupError):
    pass


async def fetch_quote(ticker: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    async with httpx.AsyncClient(
        timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}, transport=transport
    ) as http:
        r = await http.get(CHART_URL.format(ticker=ticker.upper()), params={"range": "1d"})
    if r.status_code == 404:
        raise QuoteNotFound(f"no quote for {ticker!r}")
    r.raise_for_status()
    results = (r.json().get("chart") or {}).get("result") or []
    if not results:
        raise QuoteNotFound(f"no quote for {ticker!r}")
    return _summarise(results[0]["meta"])


def _summarise(meta: dict[str, Any]) -> dict[str, Any]:
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose")
    as_of = meta.get("regularMarketTime")
    return {
        "ticker": meta.get("symbol"),
        "name": meta.get("longName") or meta.get("shortName"),
        "exchange": meta.get("fullExchangeName"),
        "currency": meta.get("currency"),
        "price": price,
        "previous_close": prev,
        "change_pct": round((price - prev) / prev * 100, 2) if price and prev else None,
        "fifty_two_week_high": meta.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": meta.get("fiftyTwoWeekLow"),
        "as_of": datetime.fromtimestamp(as_of, UTC).isoformat() if as_of else None,
        "source": "Yahoo Finance",
    }


async def _run(args: QuoteArgs) -> dict:
    return await fetch_quote(args.ticker)


market_quote = FunctionTool(
    name="market_quote",
    description=(
        "Last traded price, previous close, day change and 52-week range for one listed "
        "security. Use it to check a price or market-value figure; never to recommend a trade."
    ),
    args=QuoteArgs,
    run=_run,
)
