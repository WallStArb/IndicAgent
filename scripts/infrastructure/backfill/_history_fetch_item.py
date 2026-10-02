"""One IBKR history queue item: fetch a (symbol, timeframe), bounded against hangs
(phase 189 plan 03; design docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md).

The IBKR history fetcher works its priority queue one (symbol, timeframe) at a time. This
module is that unit of work, moved out of the historical pipeline's monolithic per-symbol
loop (infrastructure_run_historical_pipeline.py main()._run_fetch_stage) so it can be tested
alone and so a single name can never hold the run:

- CD-01: one fetcher, one item at a time; the queue decides order, this module decides how
  one item is fetched.
- CD-04: every provider-returned chunk, archive timeframes (15m/1h) and grid timeframes
  (5m/1d/1m) alike, commits through _intraday_persist.persist_chunk_atomically together with
  its request rows and its ohlcv_coverage update, so the ledger never describes bars that did
  not land and no answered request outruns its bars.
- CD-05: the outcome is classified so the ledger only charges genuine failures. A correct
  empty answer is 'no_data', never 'error'; a lost gateway is not the item's fault at all.
- CD-08: a progress-aware stall bound cancels an item whose provider went silent, reconnects
  the client and retries a bounded number of times. ibkr.py's own per-request wait_for has been
  seen not to fire (2026-07-05 and 2026-10-02 incidents), so this is the in-process layer; the
  systemd WatchdogSec of plan 04 covers the case where asyncio timers never fire at all.

The fetch helpers (gap detection, store paths, per-contract futures, 1m derivation, D1
capture) are imported read-only from infrastructure_run_historical_pipeline.py: the running
todo 449 lane imports that file on every attempt, so it is not edited here. Plan 08 moves the
helpers when the pipeline is retired. All provider access goes through IBKRProvider methods;
src/providers/ibkr.py stays the only ib_async importer.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

import structlog

from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import (
    _flush_capture,
)
from services.ohlcv_coverage_writer import FETCH_STATUSES

logger = structlog.get_logger(__name__)

# The stall bound is checked this many times per stall_timeout_s. Derived check cadence, not a
# tunable: the bound itself is infra.ibkr.history_request_timeout (APR); three checks per
# bound cap how far past it a stall can run before cancellation at a third of the bound.
_STALL_CHECKS_PER_TIMEOUT = 3


@dataclass(frozen=True)
class ItemOutcome:
    """How one queue item ended. The fetcher writes `status` to ohlcv_coverage through
    record_fetch_outcome unless `gateway_lost` is set (a lost gateway is not charged)."""

    symbol: str
    timeframe: str
    status: str
    n_bars: int = 0
    # 5m grid rows written this item (offered to the insert; re-affirmed duplicates count).
    # Plan 04 promotes the derived 15m/1h grid when this is non-zero.
    n_grid_source_rows: int = 0
    attempts: int = 1
    gateway_lost: bool = False
    error: str | None = None
    elapsed_s: float = 0.0

    def __post_init__(self) -> None:
        if self.status not in FETCH_STATUSES:
            raise ValueError(f"unknown item status {self.status!r}; expected {FETCH_STATUSES}")


class ProgressClock:
    """When the item last made progress (a request answered, a chunk persisted)."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._last = now()

    def touch(self) -> None:
        self._last = self._now()

    def age(self) -> float:
        return self._now() - self._last


class ItemStalled(Exception):
    """The item made no progress for the stall bound and was cancelled."""

    def __init__(self, elapsed_s: float) -> None:
        super().__init__(f"no progress for {elapsed_s:.1f}s")
        self.elapsed_s = elapsed_s


class GatewayLost(Exception):
    """The IBKR client is down and could not be reconnected: not the item's failure."""


async def run_with_stall_bound(
    make_coro: Callable[[], Awaitable[Any]],
    *,
    stall_timeout_s: float,
    clock: ProgressClock,
    on_tick: Callable[[], None] | None = None,
) -> Any:
    """Run one item, cancelling it only when it stops making progress.

    asyncio.wait_for is the bound, used as a progress check rather than a whole-item
    deadline: a healthy 15m deep backfill runs 40+ minutes across hundreds of rate-limited
    requests, so a fixed deadline would cancel good work. The item task is shielded so a
    check's timeout never cancels it; only a clock age at or past `stall_timeout_s` does.
    `on_tick` runs on every check (plan 04 feeds the systemd watchdog from it).
    """
    task = asyncio.ensure_future(make_coro())
    check_s = stall_timeout_s / _STALL_CHECKS_PER_TIMEOUT
    try:
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=check_s)
            except TimeoutError:
                if on_tick is not None:
                    on_tick()
                age = clock.age()
                if age >= stall_timeout_s:
                    task.cancel()
                    # Bounded: an item that swallows its cancellation must not hang us here.
                    await asyncio.wait({task}, timeout=check_s)
                    if not task.done():
                        logger.error("ibkr_history_fetcher.cancel_ignored", age_s=age)
                    raise ItemStalled(age) from None
    except asyncio.CancelledError:
        task.cancel()
        raise


async def fetch_item(
    ctx: Any,
    instrument: Any,
    row: Any,
    *,
    gap_days: int,
    full_scan: bool,
    clock: ProgressClock,
) -> ItemOutcome:
    """Fetch one (symbol, timeframe). Implemented in plan 03 task 2."""
    raise NotImplementedError("fetch_item lands in plan 189-03 task 2")


async def fetch_item_with_retries(
    ctx: Any,
    instrument: Any,
    row: Any,
    *,
    gap_days: int,
    full_scan: bool,
    config: Any,
    reconnect: Callable[[], Awaitable[bool]],
    on_tick: Callable[[], None] | None = None,
) -> ItemOutcome:
    """fetch_item under the stall bound, retried after a stall at most
    config.history_request_retries times (CD-08).

    - A stall cancels the attempt, flushes the D1 sink (the cancelled attempt's answered
      requests and observations are raw answers that must not be dropped; its persisted
      chunks are already committed atomically), disconnects and reconnects the client. A
      failed reconnect ends the item as gateway_lost, which the caller does not charge.
    - Stalling on every attempt is 'error', a genuine consecutive failure. The client is
      reconnected after the last stall too, so the next item starts on a live connection.
    - Any other exception ends the item as 'error' with its message, logged once, never a
      crash: one name never blocks the run (phase 185 D-05).
    """
    started = time.monotonic()
    symbol, timeframe = row.symbol, row.timeframe
    max_attempts = 1 + config.history_request_retries

    def ended(status: str, attempt: int, **fields: Any) -> ItemOutcome:
        return ItemOutcome(
            symbol,
            timeframe,
            status,
            attempts=attempt,
            elapsed_s=time.monotonic() - started,
            **fields,
        )

    last_stall: ItemStalled | None = None
    for attempt in range(1, max_attempts + 1):
        clock = ProgressClock()

        def attempt_coro(_clock: ProgressClock = clock) -> Awaitable[ItemOutcome]:
            return fetch_item(
                ctx, instrument, row, gap_days=gap_days, full_scan=full_scan, clock=_clock
            )

        try:
            outcome = await run_with_stall_bound(
                attempt_coro,
                stall_timeout_s=config.history_request_timeout_s,
                clock=clock,
                on_tick=on_tick,
            )
        except ItemStalled as stall:
            last_stall = stall
            logger.warning(
                "ibkr_history_fetcher.item_stalled",
                symbol=symbol,
                timeframe=timeframe,
                attempt=attempt,
                elapsed_s=round(stall.elapsed_s, 1),
            )
            flush_error = _flush_after_cancel(ctx)
            if not await _reconnect(ctx, reconnect):
                return ended(
                    "error", attempt, gateway_lost=True, error=f"reconnect failed: {stall}"
                )
            if flush_error is not None:
                return ended(
                    "error", attempt, error=f"sink flush after stall failed: {flush_error}"
                )
            continue
        except GatewayLost as error:
            logger.warning(
                "ibkr_history_fetcher.gateway_lost",
                symbol=symbol,
                timeframe=timeframe,
                error=str(error),
            )
            return ended("error", attempt, gateway_lost=True, error=str(error))
        except Exception as error:
            logger.error(
                "ibkr_history_fetcher.item_failed",
                symbol=symbol,
                timeframe=timeframe,
                attempt=attempt,
                error=str(error),
                error_type=type(error).__name__,
            )
            return ended("error", attempt, error=f"{type(error).__name__}: {error}")
        return replace(outcome, attempts=attempt, elapsed_s=time.monotonic() - started)
    return ended(
        "error", max_attempts, error=f"stalled on all {max_attempts} attempts: {last_stall}"
    )


def _flush_after_cancel(ctx: Any) -> Exception | None:
    """Write what the cancelled attempt captured but had not yet flushed. Returns the error
    instead of raising so the client is still reconnected for the next item."""
    try:
        _flush_capture(ctx.sink, ctx.settings)
    except Exception as error:
        logger.error("ibkr_history_fetcher.stall_flush_failed", error=str(error))
        return error
    return None


async def _reconnect(ctx: Any, reconnect: Callable[[], Awaitable[bool]]) -> bool:
    try:
        await ctx.provider.disconnect()
    except Exception as error:  # a dead socket may refuse a clean disconnect
        logger.warning("ibkr_history_fetcher.disconnect_failed", error=str(error))
    try:
        return bool(await reconnect())
    except Exception as error:
        logger.error("ibkr_history_fetcher.reconnect_failed", error=str(error))
        return False
