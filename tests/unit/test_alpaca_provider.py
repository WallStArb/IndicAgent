"""AlpacaProvider HistoryProvider conformance (todo 521 T4).

Behavioral cases over a mocked HTTP transport: convention mapping raises
loudly, pagination exhausts to a None resume point, the budget stops the leaf
with an in-span resume point, a definitive empty answer is an
authoritative-empty verdict, and every request is captured as a RequestRecord.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.config.settings import Settings
from src.providers.alpaca import AlpacaProvider
from src.providers.base import FetchBudget, HistoryPage, HistoryRequest

_WINDOW_START = datetime(2026, 10, 6, 13, 30, tzinfo=UTC)
_WINDOW_END = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(alpaca_key_id="key", alpaca_secret_key="secret")


def _bar_payload(stamps: list[str], next_token: str | None = None) -> dict:
    payload = {
        "bars": [
            {
                "t": stamp,
                "o": 1.0,
                "h": 2.0,
                "l": 0.5,
                "c": 1.5,
                "v": 1000,
            }
            for stamp in stamps
        ]
    }
    if next_token:
        payload["next_page_token"] = next_token
    return payload


def _provider_with(handler) -> tuple[AlpacaProvider, list]:
    """A connected provider over a MockTransport; returns (provider, captured records)."""
    records: list = []
    transport = httpx.MockTransport(handler)
    provider = AlpacaProvider(_settings(), on_request=records.append, fetch_run_id="run-1")

    original_connect = provider.connect

    async def connect() -> bool:
        ok = await original_connect()
        provider._client = httpx.AsyncClient(  # noqa: SLF001 - test seam
            base_url="https://data.alpaca.markets/v2/stocks/bars",
            transport=transport,
            timeout=30.0,
        )
        return ok

    provider.connect = connect  # type: ignore[method-assign]
    return provider, records


def test_convention_mapping_raises_loudly() -> None:
    provider, _ = _provider_with(lambda request: httpx.Response(200, json={"bars": []}))

    async def run() -> None:
        await provider.connect()
        try:
            await provider.fetch_ohlcv(
                HistoryRequest(
                    symbol="SPY",
                    timeframe="5m",
                    start=_WINDOW_START,
                    end=_WINDOW_END,
                    adjustment="dividend",
                ),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=5),
            )
        finally:
            await provider.close()

    import asyncio

    with pytest.raises(ValueError, match="adjustment"):
        asyncio.run(run())


def test_split_adjustment_maps_to_the_current_vendor_enum() -> None:
    """Alpaca serves adjustment=split|raw|all since at least 2026-10-26; the stored convention
    "split" must go over the wire as "split" (the older "splits" answers 400)."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"bars": []})

    provider, _ = _provider_with(handler)

    async def run() -> None:
        await provider.connect()
        try:
            await provider.fetch_ohlcv(
                HistoryRequest(
                    symbol="SPY",
                    timeframe="5m",
                    start=_WINDOW_START,
                    end=_WINDOW_END,
                    adjustment="split",
                ),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=5),
            )
        finally:
            await provider.close()

    import asyncio

    asyncio.run(run())
    assert "adjustment=split" in str(calls[0].url)


def test_request_carries_the_configured_feed_and_the_record_names_it() -> None:
    """The leaf asks the feed its caller configured (the nightly's APR-backed iex tail) and the
    request record's route names that feed, so the raw kind derived downstream is honest."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_bar_payload(["2026-10-06T14:30:00Z"]))

    provider, records = _provider_with(handler)
    provider._data_feed = "iex"  # noqa: SLF001 - the constructor value under test

    async def run() -> None:
        await provider.connect()
        try:
            await provider.fetch_ohlcv(
                HistoryRequest(symbol="SPY", timeframe="5m", start=_WINDOW_START, end=_WINDOW_END),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=5),
            )
        finally:
            await provider.close()

    import asyncio

    asyncio.run(run())
    assert "feed=iex" in str(calls[0].url)
    assert records[0].route == "IEX"


def test_symbol_keyed_bars_answer_is_flattened() -> None:
    """The v2 endpoint keys bars by symbol ({"bars": {"SPY": [...]}}); the leaf asks one symbol
    per request and flattens the entries (measured live 2026-10-26 on feed=iex)."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"bars": {"SPY": _bar_payload(["2026-10-06T14:30:00Z"])["bars"]}},
        )

    provider, records = _provider_with(handler)

    async def run() -> HistoryPage:
        await provider.connect()
        try:
            return await provider.fetch_ohlcv(
                HistoryRequest(symbol="SPY", timeframe="5m", start=_WINDOW_START, end=_WINDOW_END),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=5),
            )
        finally:
            await provider.close()

    import asyncio

    page = asyncio.run(run())
    assert len(page.bars) == 1 and page.next_window_start is None
    assert records[0].outcome == "bars" and records[0].n_bars == 1


def test_default_feed_is_sip_end_to_end() -> None:
    """A caller that passes no feed keeps the admission build's basis: feed=sip on the wire,
    route SIP on the record."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_bar_payload(["2026-10-06T14:30:00Z"]))

    provider, records = _provider_with(handler)

    async def run() -> None:
        await provider.connect()
        try:
            await provider.fetch_ohlcv(
                HistoryRequest(symbol="SPY", timeframe="5m", start=_WINDOW_START, end=_WINDOW_END),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=5),
            )
        finally:
            await provider.close()

    import asyncio

    asyncio.run(run())
    assert "feed=sip" in str(calls[0].url)
    assert records[0].route == "SIP"


def test_pagination_exhausts_to_none_resume() -> None:
    pages = [
        _bar_payload(["2026-10-06T14:30:00Z"], next_token="tok1"),
        _bar_payload(["2026-10-06T14:35:00Z", "2026-10-06T14:40:00Z"]),
    ]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=pages.pop(0))

    provider, records = _provider_with(handler)

    async def run() -> HistoryPage:
        await provider.connect()
        try:
            return await provider.fetch_ohlcv(
                HistoryRequest(symbol="SPY", timeframe="5m", start=_WINDOW_START, end=_WINDOW_END),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=5),
            )
        finally:
            await provider.close()

    import asyncio

    page = asyncio.run(run())
    assert page.next_window_start is None and page.verdict is None
    assert len(page.bars) == 3
    assert page.bars[0].source == "alpaca"
    assert [json.loads(c.content.decode()) for c in []] == []
    assert "page_token" in str(calls[1].url) or "page_token" in calls[1].url.params
    assert len(records) == 2
    assert all(r.outcome == "bars" and r.n_bars > 0 for r in records)
    assert records[0].fetch_run_id == "run-1" and records[0].route == "SIP"


def test_budget_stops_with_in_span_resume() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_bar_payload(["2026-10-06T14:30:00Z"], next_token="tok"))

    provider, _ = _provider_with(handler)

    async def run() -> HistoryPage:
        await provider.connect()
        try:
            return await provider.fetch_ohlcv(
                HistoryRequest(symbol="SPY", timeframe="5m", start=_WINDOW_START, end=_WINDOW_END),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=1),
            )
        finally:
            await provider.close()

    import asyncio

    page = asyncio.run(run())
    assert page.next_window_start == datetime(2026, 10, 6, 14, 30, tzinfo=UTC)
    assert len(page.bars) == 1


def test_definitive_empty_answer_is_authoritative_verdict() -> None:
    provider, records = _provider_with(lambda request: httpx.Response(200, json={"bars": []}))

    async def run() -> HistoryPage:
        await provider.connect()
        try:
            return await provider.fetch_ohlcv(
                HistoryRequest(symbol="SPY", timeframe="5m", start=_WINDOW_START, end=_WINDOW_END),
                FetchBudget(deadline=datetime.now(UTC) + timedelta(seconds=30), max_requests=5),
            )
        finally:
            await provider.close()

    import asyncio

    page = asyncio.run(run())
    assert page.next_window_start is None
    assert page.verdict is not None
    assert page.verdict.authoritative_empty is True
    assert records[0].outcome == "no_data"
