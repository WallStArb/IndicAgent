"""Tradier daily history. All Tradier HTTP logic lives here.

Primary source for 1d bars (owner decision 2026-10-03). The history endpoint returns a name's whole
daily series in one request, split-adjusted and not dividend-adjusted (measured against IBKR TRADES:
median close ratio 1.000 in every year sampled), the same basis as IBKR TRADES. Volume is
consolidated and runs about 1.25x IBKR SMART volume, so one name never mixes the two sources.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

SOURCE = "tradier"


@dataclass(frozen=True)
class DailyBar:
    timestamp: datetime  # 00:00 UTC of the session date, the 1d key used in market_data_ohlcv
    open: float
    high: float
    low: float
    close: float
    volume: int | None


class TradierError(Exception):
    """A request or payload problem, never a placeholder: callers record it and move on."""


def tradier_symbol(symbol: str) -> str:
    """IndicAgent share-class symbols use a dot (BRK.B); Tradier uses a slash (BRK/B)."""
    return symbol.replace(".", "/")


def parse_daily_history(payload: dict) -> list[DailyBar]:
    """Bars in date order. A null OHLC field drops that day (never filled); a non-positive or
    non-finite price, or two bars for one day, raises TradierError."""
    history = payload.get("history")
    days = history.get("day") if isinstance(history, dict) else None
    if days is None:
        return []
    if isinstance(days, dict):  # one-bar history comes back as an object, not a list
        days = [days]
    bars: dict[date, DailyBar] = {}
    for row in days:
        day = date.fromisoformat(row["date"])
        prices = [row.get(field) for field in ("open", "high", "low", "close")]
        if any(price is None for price in prices):
            continue
        open_, high, low, close = (float(price) for price in prices)
        if not all(math.isfinite(price) and price > 0 for price in (open_, high, low, close)):
            raise TradierError(f"invalid price on {day}: {prices}")
        if day in bars:
            raise TradierError(f"two bars for {day}")
        volume = row.get("volume")
        bars[day] = DailyBar(
            datetime(day.year, day.month, day.day, tzinfo=UTC),
            open_,
            high,
            low,
            close,
            None if volume is None else int(volume),
        )
    return [bars[day] for day in sorted(bars)]


async def fetch_daily_history(
    client: httpx.AsyncClient, symbol: str, start: date, end: date
) -> list[DailyBar]:
    """Daily bars for [start, end] in one request. The client carries the base URL, bearer token
    and timeout (see `make_client`). Raises TradierError on HTTP or payload failure."""
    try:
        response = await client.get(
            "/v1/markets/history",
            params={
                "symbol": tradier_symbol(symbol),
                "interval": "daily",
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        response.raise_for_status()
        return parse_daily_history(response.json())
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise TradierError(f"{symbol}: {type(error).__name__}: {error}"[:200]) from None


def make_client(base_url: str, token: str, timeout_seconds: float) -> httpx.AsyncClient:
    if not token:
        raise TradierError("TRADIER_API_TOKEN is empty")
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=timeout_seconds,
    )
