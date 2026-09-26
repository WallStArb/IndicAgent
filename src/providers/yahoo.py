"""Yahoo Finance reference data via yfinance. All yfinance logic lives here.

Used only for corporate-action history that IBKR's API does not expose directly (todo 428:
dividends). Never a price source: bars stay IBKR's. yfinance is synchronous (HTTP), so the
async entry point runs it in a worker thread.
"""

from __future__ import annotations

import asyncio
from datetime import date

import yfinance


def yahoo_symbol(symbol: str) -> str:
    """IndicAgent share-class symbols use a dot (BRK.B); Yahoo uses a dash (BRK-B)."""
    return symbol.replace(".", "-").replace(" ", "-")


def _daily_close_and_dividends(symbol: str) -> list[tuple[date, float, float]]:
    history = yfinance.Ticker(yahoo_symbol(symbol)).history(
        period="max", auto_adjust=False, actions=True, raise_errors=True
    )
    # auto_adjust=False: Close is split-adjusted only, the same basis as the Dividends column.
    return [
        (ts.date(), float(close), float(dividend))
        for ts, close, dividend in zip(
            history.index, history["Close"], history["Dividends"], strict=True
        )
    ]


async def fetch_daily_close_and_dividends(
    symbol: str,
) -> tuple[list[tuple[date, float, float]], str | None]:
    """Full daily (day, split-adjusted close, cash dividend with that day as ex-date) history:
    (rows, None) or ([], error)."""
    try:
        rows = await asyncio.to_thread(_daily_close_and_dividends, symbol)
    except Exception as error:
        return [], f"{type(error).__name__}: {error}"[:200]
    if not rows:
        return [], "no history returned"
    return rows, None
