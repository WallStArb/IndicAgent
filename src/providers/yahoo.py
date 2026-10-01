"""Yahoo Finance reference data via yfinance. All yfinance logic lives here.

Two owner-approved uses, nothing else: corporate-action history IBKR's API does not expose (todo 428,
dividends), and long-history index levels (`^GSPC` from 1927, `^NDX` from 1985) stored as context-only
economic series (`YahooSource`, owner decision 2026-10-01). Never a tradeable price: bars stay IBKR's,
and `YahooSource` accepts index tickers only. yfinance is synchronous (HTTP), so async entry points run
it in a worker thread.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import yfinance

from src.core.retry_utils import retry_with_backoff
from src.providers.economic_source import Series, SourceError

SOURCE = "yahoo"
INDEX_UNIT = "index"  # FRED's declared code for the same quantity
_EXCHANGE_TZ = ZoneInfo("America/New_York")


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


def index_series_id(ticker: str) -> str:
    """`^GSPC` -> `YAHOO_GSPC_CLOSE`."""
    return f"YAHOO_{ticker.lstrip('^')}_CLOSE"


def index_close_rows(pairs: Iterable[tuple[date, float]], before: date) -> list[tuple[date, float]]:
    """Completed sessions only (`day < before`: today's value is provisional until the close and is
    taken on the next run), date order, a missing close absent (never filled). Raises ValueError on a
    non-positive or infinite close or two closes for one day."""
    by_day: dict[date, float] = {}
    for day, close in pairs:
        if day >= before or math.isnan(close):
            continue
        if not math.isfinite(close) or close <= 0:
            raise ValueError(f"invalid close {close} on {day}")
        if day in by_day:
            raise ValueError(f"two closes for {day}")
        by_day[day] = close
    return sorted(by_day.items())


def _daily_index_closes(ticker: str, before: date) -> list[tuple[date, float]]:
    history = yfinance.Ticker(ticker).history(period="max", auto_adjust=False, raise_errors=True)
    return index_close_rows(
        (
            (ts.date(), float(close))
            for ts, close in zip(history.index, history["Close"], strict=True)
        ),
        before,
    )


class YahooSource:
    """`EconomicSource` for long-history index levels: context only, never a tradeable price."""

    name = SOURCE

    def __init__(self, max_attempts: int) -> None:
        self._max_attempts = max_attempts

    def validate(self, entry_id: str) -> None:
        if not entry_id.startswith("^"):
            raise ValueError(
                f"{entry_id}: Yahoo entries are index tickers (^...), never tradeables"
            )

    async def fetch(self, entry_id: str, client: httpx.AsyncClient) -> dict[str, Series]:
        # yfinance owns its own HTTP session, so the shared client is not used here.
        before = datetime.now(_EXCHANGE_TZ).date()
        try:
            rows = await retry_with_backoff(
                asyncio.to_thread,
                _daily_index_closes,
                entry_id,
                before,
                max_attempts=self._max_attempts,
            )
        except Exception as error:
            raise SourceError(f"{type(error).__name__}: {error}"[:200]) from None
        if not rows:
            raise SourceError("no history returned")
        return {index_series_id(entry_id): Series(INDEX_UNIT, rows)}
