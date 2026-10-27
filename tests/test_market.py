from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from studio.tools.market import QuoteArgs, QuoteNotFound, fetch_quote

META = {
    "symbol": "AMD",
    "longName": "Advanced Micro Devices, Inc.",
    "fullExchangeName": "NasdaqGS",
    "currency": "USD",
    "regularMarketPrice": 110.0,
    "chartPreviousClose": 100.0,
    "regularMarketTime": 1793044801,
    "fiftyTwoWeekHigh": 120.0,
    "fiftyTwoWeekLow": 80.0,
}


def _transport(response: httpx.Response) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _req: response)


async def test_summarises_quote():
    body = {"chart": {"result": [{"meta": META}]}}
    q = await fetch_quote("amd", transport=_transport(httpx.Response(200, json=body)))
    assert q["ticker"] == "AMD"
    assert q["price"] == 110.0
    assert q["change_pct"] == 10.0
    assert q["as_of"].startswith("2026-10-26")


async def test_unknown_ticker():
    with pytest.raises(QuoteNotFound):
        await fetch_quote("ZZZZQQ", transport=_transport(httpx.Response(404)))


async def test_empty_result():
    body = {"chart": {"result": None}}
    with pytest.raises(QuoteNotFound):
        await fetch_quote("ZZZZQQ", transport=_transport(httpx.Response(200, json=body)))


@pytest.mark.parametrize("ticker", ["", "AMD; rm -rf", "x" * 16, "../etc"])
def test_rejects_bad_tickers(ticker):
    with pytest.raises(ValidationError):
        QuoteArgs(ticker=ticker)


@pytest.mark.parametrize("ticker", ["AMD", "VOD.L", "^GSPC", "BRK-B"])
def test_accepts_real_tickers(ticker):
    assert QuoteArgs(ticker=ticker).ticker == ticker
