"""Alpaca REST market-data leaf (todo 521 T4; provider history plane, phase 190).

The vendor knowledge ring: every Alpaca API mechanic lives here, and callers
dispatch through the HistoryProvider protocol (``src.providers.base``), never
this concrete class (CI-enforced by tests/unit/test_provider_leaf_boundary.py).

Conventions, from the 521 admission build's measured rulings
(docs/plans/2026-10-09-alpaca-5m-admission-build.md):
- Feed is SIP (``feed=sip``); the lineage is Polygon/Massive on Alpaca's side.
- ``adjustment="split"`` maps to Alpaca's ``adjustment=splits`` (the stored
  convention); ``"none"`` maps to ``raw``. Anything else raises: a silent
  convention mismatch is forbidden.
- There is no native RTH knob on Alpaca's bars endpoint: the session
  convention is the engine's grid (``services.bar_load.split_series``), which
  routes out-of-grid bars to the raw archive instead of dropping them. The
  leaf therefore returns every bar the vendor serves for the window;
  ``rth_only`` is consumed downstream, never here.

Pacing: one sustained request rate, APR-backed
(``infra.alpaca.rate_limit_max_requests`` requests/minute; the constructor
takes the loaded value, the Settings field is the fallback). Pagination walks
``next_page_token`` until the vendor's span is exhausted or the budget stops
the leaf; a definitive empty answer returns a NoDataVerdict with
``authoritative_empty`` (the REST analogue of IBKR's confirming-chunk walk).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import structlog

from src.config.settings import Settings
from src.providers.base import (
    FetchBudget,
    HistoryPage,
    HistoryRequest,
    NoDataVerdict,
    OHLCVBar,
    RequestRecord,
)

logger = structlog.get_logger(__name__)

_TF_TO_ALPACA = {"1m": "1Min", "5m": "5Min", "1d": "1Day"}
_ADJUSTMENT_TO_ALPACA = {"none": "raw", "split": "splits"}
_BASE_URL = "https://data.alpaca.markets/v2/stocks/bars"
_PAGE_LIMIT = 10_000  # vendor API maximum, a documented shape, not a tunable


class AlpacaProvider:
    """HistoryProvider leaf for Alpaca's REST bars endpoint."""

    name = "alpaca"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        rate_limit_max_requests: int | None = None,
        on_request: Callable[[RequestRecord], None] | None = None,
        fetch_run_id: str | None = None,
    ):
        self._settings = settings or Settings()
        self._on_request = on_request
        self._fetch_run_id = fetch_run_id or (str(uuid.uuid4()) if on_request else None)
        effective_rate = rate_limit_max_requests or self._settings.alpaca_rate_limit_max_requests
        self._min_interval = 60.0 / effective_rate
        self._last_request_monotonic = 0.0
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> bool:
        """Open the REST client. REST is connectionless; this only builds it."""
        if not self._settings.alpaca_key_id or not self._settings.alpaca_secret_key:
            raise RuntimeError("ALPACA_KEY_ID / ALPACA_SECRET_KEY missing from settings")
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "APCA-API-KEY-ID": self._settings.alpaca_key_id,
                "APCA-API-SECRET-KEY": self._settings.alpaca_secret_key,
            },
            timeout=30.0,
        )
        return True

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _pace(self) -> None:
        """One sustained request rate, the leaf's native pacing model."""
        now = time.monotonic()
        wait = self._last_request_monotonic + self._min_interval - now
        if wait > 0:
            time.sleep(wait)
        self._last_request_monotonic = time.monotonic()

    def _record(
        self,
        request: HistoryRequest,
        page_start: datetime,
        window_end: datetime,
        outcome: str,
        n_bars: int,
        requested_at: datetime,
        error_text: str | None = None,
    ) -> None:
        if self._on_request is None:
            return
        self._on_request(
            RequestRecord(
                request_id=str(uuid.uuid4()),
                fetch_run_id=self._fetch_run_id,
                symbol=request.symbol,
                timeframe=request.timeframe,
                route="SIP",
                what_to_show=_TF_TO_ALPACA[request.timeframe],
                primary_exchange=None,
                window_start=page_start,
                window_end=window_end,
                ib_req_id=None,
                outcome=outcome,  # type: ignore[arg-type]
                error_code=None,
                error_text=error_text,
                n_bars=n_bars,
                client_id=None,
                requested_at=requested_at,
                answered_at=datetime.now(UTC),
            )
        )

    async def fetch_ohlcv(self, request: HistoryRequest, budget: FetchBudget) -> HistoryPage:
        """One caller-driven window of (request.start, request.end], paginated.

        Pages ``next_page_token`` until the vendor's span for the window is
        exhausted (resume point None), the budget's deadline passes, or
        ``max_requests`` is spent (resume point = the furthest bar's stamp, so
        the caller resumes exactly where the budget stopped). A definitive
        empty answer is a NoDataVerdict with ``authoritative_empty``.
        """
        if request.timeframe not in _TF_TO_ALPACA:
            raise ValueError(
                f"Unsupported timeframe '{request.timeframe}'. Valid: {list(_TF_TO_ALPACA)}"
            )
        if request.adjustment not in _ADJUSTMENT_TO_ALPACA:
            raise ValueError(
                f"Alpaca windowed history supports adjustment "
                f"{sorted(_ADJUSTMENT_TO_ALPACA)} only, got {request.adjustment!r}"
            )
        if request.start >= request.end:
            raise ValueError(f"Empty window: start {request.start} >= end {request.end}")
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")

        bars: list[OHLCVBar] = []
        page_token: str | None = None
        resume: datetime | None = request.start
        requests_spent = 0
        while True:
            if datetime.now(UTC) >= budget.deadline or requests_spent >= budget.max_requests:
                return HistoryPage(bars=tuple(bars), next_window_start=resume)
            self._pace()
            params: dict = {
                "symbols": request.symbol,
                "timeframe": _TF_TO_ALPACA[request.timeframe],
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
                "adjustment": _ADJUSTMENT_TO_ALPACA[request.adjustment],
                "feed": "sip",
                "limit": _PAGE_LIMIT,
            }
            if page_token is not None:
                params["page_token"] = page_token
            requests_spent += 1
            requested_at = datetime.now(UTC)
            response = await self._client.get("/", params=params)
            if response.status_code == 429:
                retry_after = float(response.headers.get("retry-after", "1"))
                logger.warning("alpaca rate limited", retry_after_s=retry_after)
                await asyncio.sleep(retry_after)
                requests_spent -= 1  # a 429 is pacing, not a spent request
                continue
            response.raise_for_status()
            payload = response.json() or {}
            page_bars = payload.get("bars") or []
            n_bars = len(page_bars)
            self._record(
                request,
                resume,
                request.end,
                "bars" if n_bars else "no_data",
                n_bars,
                requested_at,
            )
            for row in page_bars:
                bars.append(
                    OHLCVBar(
                        symbol=request.symbol,
                        timeframe=request.timeframe,
                        timestamp=datetime.fromisoformat(row["t"]),
                        open=float(row["o"]),
                        high=float(row["h"]),
                        low=float(row["l"]),
                        close=float(row["c"]),
                        volume=int(row["v"]),
                        source=self.name,
                    )
                )
            page_token = payload.get("next_page_token")
            if page_token is None:
                verdict = None
                if not bars:
                    verdict = NoDataVerdict(
                        provider=self.name,
                        symbol=request.symbol,
                        timeframe=request.timeframe,
                        empty_from=request.start,
                        empty_through=request.end,
                        reached_request_start=True,
                        authoritative_empty=True,
                    )
                return HistoryPage(bars=tuple(bars), next_window_start=None, verdict=verdict)
            resume = datetime.fromisoformat(page_bars[-1]["t"])
