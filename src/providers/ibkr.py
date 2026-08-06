"""
IBKRProvider — DataProvider implementation for Interactive Brokers (ib_async).

Wraps all ib_async logic. The daemon and backfill script interact only
with the DataProvider protocol — no ib_async imports outside this file.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import signal
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

# Python 3.14 removed implicit event loop creation. eventkit (ib_async dependency,
# published as aeventkit but still imported as `eventkit`) calls asyncio.get_event_loop()
# at module import time. Pre-create a loop to satisfy the import; connect() will redirect
# main_event_loop to the real running loop.
# nest_asyncio is intentionally NOT applied here: we use connectAsync() (async API)
# exclusively, and nest_asyncio.apply() breaks Python 3.14's current_task() tracking,
# causing asyncio.timeout() failures throughout the process.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_async import IB, ContFuture, Contract, Forex, Future, Stock

from src.config.settings import Settings  # noqa: E402
from src.core.bar_normalizer import (  # noqa: E402
    SOURCE_IBKR_CONTINUOUS,
    SOURCE_IBKR_GENERIC,
    SOURCE_IBKR_NAMED,
    SOURCE_IBKR_OFFICIAL,
)
from src.core.models import AssetClass, Instrument  # noqa: E402

# Circuit breaker and retry
from src.core.plugin_circuit_breaker import (  # noqa: E402
    CircuitBreakerConfig,
    CircuitState,
    PluginCircuitBreaker,
)

# Circuit breaker metrics
from src.observability.metrics import (  # noqa: E402
    CIRCUIT_BREAKER_FAILURES_TOTAL,
    CIRCUIT_BREAKER_OPEN_SECONDS,
    CIRCUIT_BREAKER_SUCCESSES_TOTAL,
    CIRCUIT_BREAKER_TRANSITIONS_TOTAL,
    IBKR_CLIENT_ID_CURRENT,
    IBKR_ERROR_326_TOTAL,
    PROVIDER_BARS_DROPPED_TOTAL,
)
from src.providers.base import OHLCVBar, Tick  # noqa: E402

logger = logging.getLogger(__name__)

# Pre-labeled drop counters for ib_async → asyncio bridge. Incrementing
# from the ib_async thread is safe (prometheus_client Counters are thread-safe).
_M_DROPPED_RTB_QUEUE_FULL_ATTRS = {
    "provider": "ibkr",
    "agent": "ibkr_provider_agent",
    "reason": "rtb_queue_full",
}
_M_DROPPED_OFFICIAL_QUEUE_ERROR_ATTRS = {
    "provider": "ibkr",
    "agent": "ibkr_provider_agent",
    "reason": "official_queue_error",
}
_M_DROPPED_TICK_QUEUE_FULL_ATTRS = {
    "provider": "ibkr",
    "agent": "ibkr_provider_agent",
    "reason": "tick_queue_full",
}

# Map our timeframe strings to ib_async barSizeSetting values
_TF_TO_IB: dict[str, str] = {
    "1m": "1 min",
    "5m": "5 mins",
    "15m": "15 mins",
    "1h": "1 hour",
    "4h": "4 hours",
    "1d": "1 day",
}

# RTVolume generic tick type — required for futures, not supported on other asset classes
_FUT_TICK_LIST = "233"

# Max days per IBKR historical data request by bar size (conservative, under hard limits).
# These are per-REQUEST chunk limits, NOT retention limits. IBKR retains much more:
#   1m: confirmed 10+ years available for liquid ETFs (SPY probe 2026-06-19, clean returns
#       at 30d/60d/90d/180d/365d/730d/1460d/1825d/2555d/3650d). The fetch loop in
#       fetch_historical_bars() walks backwards in these chunk windows to cover any depth.
#   1d: 20+ years available for liquid equities/ETFs.
#
# APR-overridable: scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py's
# _load_ibkr_chunk_days_config() overlays infra.ibkr.chunk_days.{tf} (migration 197) onto
# this dict in place at backfill startup. These hardcoded values are the fallback defaults.
_MAX_CHUNK_DAYS: dict[str, int] = {
    "1m": 14,  # real IBKR per-request boundary (not the older 6-7d inherited guess).
    "5m": 150,  # confirmed clean; true ceiling is 150-180d (180d confirmed bad), untested
    #       further between those.
    "15m": 730,  # 2-year chunks: 730 = 2*365 exact multiple, avoids the year-rounding
    #        gap a non-multiple value (e.g. 400) produces -- see _days_to_duration_str()
    "1h": 1095,  # 3-year chunks. True ceiling untested between confirmed-good 1095d and
    #        confirmed-BAD 7300d (full-20yr single-shot genuinely failed after 375s retries).
    "4h": 1095,  # 3-year chunks, matching 1h's confirmed-good tier.
    "1d": 7300,  # full 20yr single-shot, 1 request/symbol.
}
# All values above re-verified 2026-08-06 (migrations 302, 303) via
# scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py against real IBKR --
# not inherited assumption. These are fallback defaults only; real values load from
# config_state at backfill startup (see APR-overridable note above). Keep in sync with
# config_state -- see src/providers/CLAUDE.md for the authoritative table + provenance.

# IBKR enforces a hard limit of 60 historical data requests per 10-minute sliding window.
# Exceeding it triggers Error 162 (query cancelled). We track request timestamps and
# pre-emptively sleep before making a request that would breach the limit, eliminating
# reactive pacing violations entirely.
#
# APR-overridable (todo 050, migration 276): the backfill script's
# _load_ibkr_rate_limit_config() overlays infra.ibkr.rate_limit_max_requests /
# infra.ibkr.rate_limit_window_sec onto these constants in place, same pattern as
# _MAX_CHUNK_DAYS above -- _SlidingWindowRateLimiter.acquire() reads them fresh on
# every call, so no reconfigure step is needed on the singleton itself.
_IBKR_HIST_RATE_LIMIT = 55  # conservative: hard limit is 60; 5-slot buffer absorbs jitter
_IBKR_HIST_WINDOW_S = 600.0  # 10-minute sliding window (IBKR's documented period)

# Defense-in-depth outer timeout on reqHistoricalDataAsync, in addition to ib_async's
# own internal `timeout=60` default on that call. [rca_analysis] Live 2026-07-05 backfill
# runs hung for 25+ minutes with near-zero CPU and no "reqHistoricalData: Timeout for..."
# warning ever logged -- confirmed via py-spy + strace that the main thread was genuinely
# idle in epoll_wait, not blocked on a synchronous call, meaning ib_async's own internal
# asyncio.wait_for(future, timeout=60) never fired despite far exceeding 60s elapsed.
# This module already documents Python 3.14 asyncio.timeout()/wait_for reliability risk
# (see the nest_asyncio note above) -- this constant does not assume this wrapper is
# bulletproof against that same class of runtime issue; the actual safety net against an
# indefinite hang is the external bar-count watchdog in backfill_retry_loop.sh, which
# force-kills the process based on observed DB progress, independent of in-process timers.
# This wrapper is still worth having as the first line of defense for the common case.
_HIST_REQUEST_TIMEOUT_SEC = 90.0

# [rca_analysis 2026-07-05, F4] reqContractDetailsAsync (qualify_instrument,
# resolve_instrument) has no timeout at all in ib_async -- not even an internal
# default like reqHistoricalDataAsync's timeout=60. Same failure class as the
# historical-data hang; a contract-qualification hang would otherwise only be
# caught by the external bar-count watchdog (much slower, much less specific).
_CONTRACT_DETAILS_TIMEOUT_SEC = 30.0

# Error 162 "no data" fires for ANY empty query window -- a genuine pre-listing date,
# but also extended halts, thin back-month futures windows, or permission hiccups. A
# single empty chunk while walking a backfill backward is not proof we've passed the
# instrument's launch date. Require this many CONSECUTIVE empty chunks before treating
# it as terminal, so one transient 162 can't silently truncate a multi-year backfill
# (todo 049, 2026-07-02).
#
# APR-overridable (todo 050, migration 235): the backfill script's
# _load_ibkr_retry_config() overlays infra.ibkr.no_data_confirmation_chunks onto this
# constant in place at startup, same pattern as _MAX_CHUNK_DAYS above. This value is
# the fallback default.
_NO_DATA_CONFIRMATION_CHUNKS = 2

# Retry attempts on an ambiguous (non-confirmed-no-data) empty historical-data result
# before giving up on a chunk, and the base seconds for the exponential backoff between
# attempts (base * 2**attempt: 65s then 130s at the defaults below). APR-overridable
# the same way as _NO_DATA_CONFIRMATION_CHUNKS above (infra.ibkr.retry_count /
# infra.ibkr.retry_backoff_base_s, migration 235).
_RETRY_COUNT = 3
_RETRY_BACKOFF_BASE_S = 65


class _SlidingWindowRateLimiter:
    """Pre-emptive rate limiter for IBKR historical data chunk requests.

    Reads _IBKR_HIST_RATE_LIMIT/_IBKR_HIST_WINDOW_S fresh on every acquire() call
    rather than caching them at construction time -- same "mutate the module
    constant in place, read fresh at each call site" pattern as _MAX_CHUNK_DAYS
    above. This is what lets the backfill script's APR overlay
    (_load_ibkr_rate_limit_config) reach this singleton, which is constructed
    eagerly at ibkr.py import time, before any DB connection or ConfigService
    overlay could possibly run.
    """

    def __init__(self) -> None:
        self._ts: deque[float] = deque()

    async def acquire(self) -> None:
        """Block until a request slot is available, then record the request timestamp."""
        now = time.monotonic()
        while self._ts and now - self._ts[0] > _IBKR_HIST_WINDOW_S:
            self._ts.popleft()
        if len(self._ts) >= _IBKR_HIST_RATE_LIMIT:
            wait = _IBKR_HIST_WINDOW_S - (now - self._ts[0]) + 1.0
            if wait > 0:
                logger.info(
                    "ibkr.hist_rate_limit_sleep",
                    extra={"req_in_window": len(self._ts), "sleep_s": round(wait, 1)},
                )
                await asyncio.sleep(wait)
        self._ts.append(time.monotonic())


_hist_rate_limiter = _SlidingWindowRateLimiter()

# reqIds where Error 162 carried "no data".
# Written by _on_ib_error (ib_async thread), consumed+cleared by _fetch_historical_bars_impl
# (asyncio thread). GIL makes set.add/difference_update thread-safe without a lock.
_no_data_req_ids: set[int] = set()

# Circuit breaker for IBKR connection attempts
_ibkr_circuit_breaker = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=180,  # 3 minutes (IBKR reconnection typically faster)
        success_threshold=2,
        max_half_open_calls=2,
        failure_window=120,  # Track failures over 2 minutes
        performance_threshold_ms=20000.0,  # 20s default timeout
    )
)

# Track when IBKR circuit breaker entered OPEN — used to observe duration on recovery.
_ibkr_open_since: float | None = None

# Error 326 hardening: cross-thread signal for clientId collision detection.
# ib_async fires errorEvent from its internal thread; the asyncio connect path
# waits on this Event to detect Error 326 within seconds of connectAsync() returning.
_error_326_detected: threading.Event = threading.Event()
_MAX_CLIENT_ID = 50
_IB_GATEWAY_PROC_PATTERN = "ibcalpha.ibc.IbcGateway"
_IB_GATEWAY_CONTAINER = "ib-gateway"
_ERR_326 = "Error 326"  # IBKR clientId-already-in-use sentinel string


def _on_ib_error(reqId: int, errorCode: int, errorString: str, contract) -> None:
    """ib_async errorEvent handler. Runs on ib_async's internal thread."""
    if errorCode == 326:
        _error_326_detected.set()
        IBKR_ERROR_326_TOTAL.add(1, {"provider": "ibkr", "action": "detected"})
        logger.error(
            "ibkr.error_326_detected",
            extra={"reqId": reqId, "errorString": errorString},
        )
    elif errorCode == 162:
        if "no data" in errorString.lower():
            _no_data_req_ids.add(reqId)
        logger.warning(
            "ibkr.hist_pacing_error",
            extra={"reqId": reqId, "errorString": errorString},
        )
    elif errorCode >= 2100 and errorCode < 2200:
        logger.warning(
            "ibkr.ib_warning",
            extra={"reqId": reqId, "errorCode": errorCode, "errorString": errorString},
        )


def _find_ib_gateway_pid() -> int | None:
    """Scan /proc to find the ibgateway Java process PID. No subprocess needed."""
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                with open(f"/proc/{entry.name}/cmdline", "rb") as f:
                    cmdline = f.read().decode(errors="replace")
                if _IB_GATEWAY_PROC_PATTERN in cmdline:
                    return int(entry.name)
            except (FileNotFoundError, PermissionError):
                continue
    except Exception as error:
        logger.warning("ibkr.find_gateway_pid_failed", extra={"error": str(error)})
    return None


async def _wait_for_gateway_port(port: int, timeout: float = 90.0) -> bool:
    """Poll until ibgateway's API port accepts TCP connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(5)
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port),
                timeout=2.0,
            )
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(3)  # brief settle — ibgateway needs a moment after TCP bind
            return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            pass
    return False


async def _restart_ib_gateway(port: int) -> bool:
    """Kill the ibgateway Java process so IBC auto-restarts it, clearing stale sessions.

    ibgateway runs as a native IBC-managed process (not Docker). IBC's ibcstart.sh
    detects the process death and relaunches it automatically, typically within 30-60s.
    """
    gw_pid = await asyncio.to_thread(_find_ib_gateway_pid)
    if gw_pid is None:
        logger.error("ibkr.gateway_process_not_found", extra={"pattern": _IB_GATEWAY_PROC_PATTERN})
        return False

    logger.warning("ibkr.restarting_gateway_process", extra={"pid": gw_pid, "port": port})
    try:
        os.kill(gw_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # already gone — proceed to wait for restart
    except OSError as error:
        logger.error("ibkr.gateway_kill_failed", extra={"pid": gw_pid, "error": str(error)})
        return False

    ready = await _wait_for_gateway_port(port=port, timeout=90.0)
    if ready:
        IBKR_ERROR_326_TOTAL.add(1, {"provider": "ibkr", "action": "gateway_restarted"})
        logger.info("ibkr.gateway_restart_complete", extra={"port": port})
        return True

    logger.error("ibkr.gateway_restart_timeout", extra={"port": port, "waited_s": 90})
    return False


async def _connect_with_circuit_breaker(
    host: str, port: int, client_id: int, timeout: float
) -> tuple[IB | None, int]:
    """Connect to IBKR with circuit breaker, Error 326 detection, and clientId rotation.

    Returns (ib_instance, actual_client_id) or (None, client_id) on failure.
    On Error 326, rotates clientId upward. After exhaustion, restarts the
    ib-gateway container and retries with the original clientId.
    """
    global _ibkr_open_since
    provider_id = "ibkr:connection"
    plugin_state = _ibkr_circuit_breaker.plugin_states[provider_id]
    previous_state = plugin_state.state

    async def _try_connect(cid: int) -> IB:
        """Single connection attempt with Error 326 post-connect guard."""
        _error_326_detected.clear()
        ib_instance = IB()
        ib_instance.errorEvent += _on_ib_error
        try:
            await ib_instance.connectAsync(
                host=host,
                port=port,
                clientId=cid,
                timeout=timeout,
                readonly=False,
            )
            if not ib_instance.isConnected():
                raise ConnectionError("IBKR connection established but not connected")

            # Post-connect guard: Error 326 fires within ~100-500ms of TCP
            # handshake. 2s is a generous upper bound that keeps total connect
            # time under the 20s ib_timeout_sec.
            # asyncio.to_thread() avoids blocking the event loop.
            if await asyncio.to_thread(_error_326_detected.wait, 2.0):
                ib_instance.disconnect()
                raise ConnectionError(f"{_ERR_326}: clientId {cid} already in use")

            IBKR_CLIENT_ID_CURRENT.add(cid, {"provider": "ibkr"})
            return ib_instance
        finally:
            ib_instance.errorEvent -= _on_ib_error

    def _record_success():
        global _ibkr_open_since
        CIRCUIT_BREAKER_SUCCESSES_TOTAL.add(1, {"plugin_name": provider_id})
        plugin_state.success_count += 1
        plugin_state.last_success_time = datetime.now()
        plugin_state.total_calls += 1
        if plugin_state.state != previous_state and previous_state != CircuitState.CLOSED:
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.add(
                1,
                {
                    "plugin_name": provider_id,
                    "from_state": previous_state.name.lower(),
                    "to_state": "closed",
                },
            )
            if _ibkr_open_since is not None:
                CIRCUIT_BREAKER_OPEN_SECONDS.record(
                    time.monotonic() - _ibkr_open_since, {"plugin_name": provider_id}
                )
                _ibkr_open_since = None

    def _record_failure(error_type: str):
        global _ibkr_open_since
        CIRCUIT_BREAKER_FAILURES_TOTAL.add(
            1, {"plugin_name": provider_id, "error_type": error_type}
        )
        plugin_state.failure_count += 1
        plugin_state.last_failure_time = datetime.now()
        plugin_state.total_calls += 1
        if plugin_state.state == CircuitState.OPEN and previous_state != CircuitState.OPEN:
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.add(
                1,
                {
                    "plugin_name": provider_id,
                    "from_state": previous_state.name.lower(),
                    "to_state": "open",
                },
            )
            _ibkr_open_since = time.monotonic()

    # Phase 1: clientId rotation (client_id → client_id+1 → ... → _MAX_CLIENT_ID)
    # Error 326 is deterministic — retrying the same clientId is pointless.
    # Try each once and rotate immediately. The while/else fires Phase 2 only when
    # all clientIds are exhausted by 326 (not on non-326 errors, which break early).
    current_cid = client_id
    while current_cid <= _MAX_CLIENT_ID:
        try:
            ib_instance = await _try_connect(current_cid)
            _record_success()
            logger.info(
                "IBKR connected",
                extra={"host": host, "port": port, "client_id": current_cid},
            )
            return ib_instance, current_cid

        except ConnectionError as error:
            if _ERR_326 in str(error):
                IBKR_ERROR_326_TOTAL.add(1, {"provider": "ibkr", "action": "client_id_rotated"})
                logger.warning(
                    "ibkr.error_326_rotating_client_id",
                    extra={
                        "old_cid": current_cid,
                        "new_cid": current_cid + 1,
                        "max": _MAX_CLIENT_ID,
                    },
                )
                current_cid += 1
                continue
            _record_failure(type(error).__name__)
            break
        except Exception as error:
            _record_failure(type(error).__name__)
            break
    else:
        # Phase 2: all clientIds returned 326 → restart gateway to clear stale sessions
        IBKR_ERROR_326_TOTAL.add(1, {"provider": "ibkr", "action": "rotation_exhausted"})
        logger.error(
            "ibkr.client_id_rotation_exhausted",
            extra={"base_client_id": client_id, "max_client_id": _MAX_CLIENT_ID},
        )
        restarted = await _restart_ib_gateway(port=port)
        if restarted:
            for cid in range(client_id, _MAX_CLIENT_ID + 1):
                try:
                    ib_instance = await _try_connect(cid)
                    _record_success()
                    logger.info("IBKR connected after gateway restart", extra={"client_id": cid})
                    return ib_instance, cid
                except ConnectionError as error:
                    if _ERR_326 in str(error):
                        continue
                    _record_failure(type(error).__name__)
                    break
                except Exception as error:
                    _record_failure(type(error).__name__)
                    break
            else:
                _record_failure("326_post_restart")

    logger.error(
        "IBKR connect failed",
        extra={"host": host, "port": port, "client_id": client_id},
    )
    return None, client_id


def _normalize_ib_bar_ts(raw_date) -> datetime:
    """Normalize an ib_async bar.date to a UTC-aware datetime.

    ib_async returns either a `datetime` (possibly naive) or an ISO-8601 string
    depending on `formatDate` and bar size. Always produce a tz-aware UTC datetime.
    """
    ts = raw_date if isinstance(raw_date, datetime) else datetime.fromisoformat(str(raw_date))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _is_circuit_breaker_open() -> bool:
    """Check if IBKR circuit breaker is OPEN."""
    state = _ibkr_circuit_breaker.plugin_states["ibkr:connection"].state
    return state == CircuitState.OPEN


async def reset_circuit_breaker() -> bool:
    """Force reset IBKR circuit breaker state."""

    provider_id = "ibkr:connection"
    plugin_state = _ibkr_circuit_breaker.plugin_states[provider_id]
    previous_state = plugin_state.state

    result = await _ibkr_circuit_breaker.force_reset_plugin(provider_id)

    # Record manual reset transition
    if result and previous_state != CircuitState.CLOSED:
        CIRCUIT_BREAKER_TRANSITIONS_TOTAL.add(
            1,
            {
                "plugin_name": provider_id,
                "from_state": previous_state.name.lower(),
                "to_state": "closed",
            },
        )

    return result


def _days_to_duration_str(total_days: int) -> str:
    """IBKR rejects "N D" durations over 365 days (Error 321: "Historical data requests
    for durations longer than 365 days must be made in years"). Shared by both
    fetch_historical_bars branches (continuous-contract and regular chunked) -- they
    independently duplicated this exact conversion until 2026-08-06, when the chunked
    branch's missing copy caused a real bug (discovered via the chunk-size headroom probe
    widening _MAX_CHUNK_DAYS past 365 for the first time). One shared function so the two
    branches can't drift out of sync on this again."""
    if total_days > 365:
        return f"{math.ceil(total_days / 365)} Y"
    return f"{total_days} D"


class IBKRProvider:
    """DataProvider implementation for Interactive Brokers via ib_async."""

    name = "ibkr"

    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        tick_queue_size: int = 5000,
        settings: Settings | None = None,
    ):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._tick_queue_size = tick_queue_size
        self._settings = settings or Settings()
        self._ib: IB | None = None
        self._tick_queue: asyncio.Queue[Tick] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._qualified_contracts: dict[str, object] = {}
        self._local_to_canonical: dict[str, str] = {}  # IBKR localSymbol -> instrument.symbol

    async def connect(self) -> bool:
        """Connect to TWS/Gateway. Returns True on success."""
        # Python 3.14 compat: redirect eventkit's stored main_event_loop to the real
        # running loop. The import-time pre-created loop is a dummy; TWS callbacks use
        # main_event_loop.call_soon_threadsafe() — must point to this loop or bars drop.
        import eventkit.util

        eventkit.util.main_event_loop = asyncio.get_running_loop()

        # Check circuit breaker state first
        if _is_circuit_breaker_open():
            logger.warning(
                "IBKR circuit breaker OPEN, skipping connection attempt",
                extra={"host": self._host, "port": self._port},
            )
            return False

        # Use circuit breaker for connection attempt (returns tuple with rotated clientId)
        self._ib, active_client_id = await _connect_with_circuit_breaker(
            host=self._host,
            port=self._port,
            client_id=self._client_id,
            timeout=self._settings.ib_timeout_sec,
        )
        if self._ib is not None:
            # Persist rotated clientId so subsequent reconnects start from it
            self._client_id = active_client_id
        return self._ib is not None

    async def ping(self) -> bool:
        """Active health check — query IBKR server time.

        Returns True if connection is alive, False otherwise.
        Called every 30 seconds by provider agent to detect idle-but-dead connections.
        """
        if not self._ib or not self._ib.isConnected():
            return False
        try:
            # reqCurrentTime is lightweight and fast
            await asyncio.wait_for(self._ib.reqCurrentTimeAsync(), timeout=5.0)
            return True
        except (TimeoutError, ConnectionError, OSError) as error:
            logger.warning(
                "IBKR ping failed", extra={"error": str(error), "error_type": type(error).__name__}
            )
            return False

    async def disconnect(self) -> None:
        """Disconnect from TWS."""
        if self._ib:
            self._ib.disconnect()
            logger.info("IBKRProvider disconnected")

    def is_connected(self) -> bool:
        return bool(self._ib and self._ib.isConnected())

    async def fetch_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        continuous: bool = False,
        on_chunk: Callable[[list[OHLCVBar]], Awaitable[None]] | None = None,
    ) -> list[OHLCVBar]:
        """Fetch historical OHLCV bars from IBKR.

        Automatically chunks long requests to stay within IBKR per-request
        duration limits (e.g. 6-day chunks for 1m bars). Chunks are fetched
        chronologically with a 10-second pause between requests for pacing.

        Requires the contract to be pre-qualified via qualify_instrument().

        Args:
            continuous: If True, fetch back-adjusted continuous contract data
                (ContFuture + ADJUSTED_LAST) instead of the named contract.
                Use for multi-year history that spans contract rolls. The named
                contract must still be pre-qualified so the base symbol and
                exchange can be resolved.
            on_chunk: Optional async callback invoked with each chunk's bars as
                soon as they're parsed, in addition to the full list still being
                returned at the end. [rca_analysis 2026-07-05] Persistence used
                to happen only once, on the full return value, after the whole
                (potentially many-chunk, many-minute) fetch completed — so a kill
                or disconnect mid-fetch discarded all in-memory progress for that
                (symbol, timeframe), and a bar-count-based external stall watchdog
                had no true per-chunk heartbeat to observe. Callers that pass this
                get truthful incremental progress; ibkr.py stays DB-ignorant
                (DAG invariant 3) since the callback itself is the caller's.
        """
        if timeframe not in _TF_TO_IB:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Valid: {list(_TF_TO_IB)}")

        if not self._ib:
            raise RuntimeError("Not connected. Call connect() first.")

        # _try_connect (nested inside connect_ibkr) unregisters _on_ib_error in its
        # finally block, so re-register here for the duration of the fetch — Error 162
        # "no data" callbacks must populate _no_data_req_ids while chunks are in flight.
        # NOTE: not re-entrant — do not call concurrently on the same IBKRProvider instance.
        self._ib.errorEvent += _on_ib_error
        try:
            return await self._fetch_historical_bars_impl(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                continuous=continuous,
                on_chunk=on_chunk,
            )
        finally:
            self._ib.errorEvent -= _on_ib_error

    async def _fetch_historical_bars_impl(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        continuous: bool = False,
        on_chunk: Callable[[list[OHLCVBar]], Awaitable[None]] | None = None,
    ) -> list[OHLCVBar]:
        named_contract = self._qualified_contracts.get(symbol)
        if not named_contract:
            logger.warning(
                "fetch_historical_bars: symbol not qualified",
                symbol=symbol,
                qualified_symbols=list(self._qualified_contracts.keys())[:5],
            )
            raise ValueError(f"Unknown symbol '{symbol}'. Call qualify_instrument() first.")

        if continuous:
            base = getattr(named_contract, "symbol", symbol)
            exchange = getattr(named_contract, "exchange", "CME")
            contract = ContFuture(symbol=base, exchange=exchange)
            what_to_show = "ADJUSTED_LAST"
            source_tag = SOURCE_IBKR_CONTINUOUS
            use_rth = False
        else:
            contract = named_contract
            sec_type = getattr(named_contract, "secType", "")
            if sec_type == "CASH":
                what_to_show = "MIDPOINT"
            elif sec_type == "CRYPTO":
                what_to_show = "AGGTRADES"
            else:
                what_to_show = "TRADES"
            source_tag = SOURCE_IBKR_NAMED
            use_rth = sec_type == "STK"

        all_bars: list[OHLCVBar] = []

        if continuous:
            # ContFuture + ADJUSTED_LAST: IBKR prohibits setting endDateTime.
            # Fetch in a single request from now backwards by total duration.
            total_days = max(1, (end - start).days + 1)
            duration_str = _days_to_duration_str(total_days)
            try:
                ib_bars = await asyncio.wait_for(
                    self._ib.reqHistoricalDataAsync(
                        contract,
                        endDateTime="",  # must be empty for ContFuture
                        durationStr=duration_str,
                        barSizeSetting=_TF_TO_IB[timeframe],
                        whatToShow=what_to_show,
                        useRTH=False,
                        formatDate=1,
                    ),
                    timeout=_HIST_REQUEST_TIMEOUT_SEC,
                )
            except TimeoutError:
                logger.error(
                    "ibkr.hist_request_outer_timeout",
                    extra={"symbol": symbol, "timeframe": timeframe, "continuous": True},
                )
                ib_bars = []
            continuous_bars: list[OHLCVBar] = []
            for bar in ib_bars or []:
                bar_ts = _normalize_ib_bar_ts(bar.date)
                continuous_bars.append(
                    OHLCVBar(
                        symbol=symbol,
                        timeframe=timeframe,
                        timestamp=bar_ts,
                        open=float(bar.open),
                        high=float(bar.high),
                        low=float(bar.low),
                        close=float(bar.close),
                        volume=int(bar.volume),
                        source=source_tag,
                    )
                )
            all_bars.extend(continuous_bars)
            if on_chunk and continuous_bars:
                await on_chunk(continuous_bars)
        else:
            chunk_days = _MAX_CHUNK_DAYS.get(timeframe, 6)
            chunk_end = end
            consecutive_no_data_chunks = 0

            # Chunk backward from end→start so recent (high-value) bars are stored
            # first. A mid-run disconnect still leaves useful data. The no-data early
            # exit also fires as soon as we pass the instrument's launch date rather
            # than burning through years of empty pre-launch chunks going forward.
            while chunk_end > start:
                # Pre-emptive rate limit: sleep if approaching IBKR's 60 req/10min ceiling.
                # This is the sole throttle — a flat 10s courtesy sleep used to run before
                # this on every chunk, stacking on top of the adaptive limiter and forcing
                # a minimum 10s/chunk even when the rolling window had full headroom
                # (removed 2026-07-02; the limiter alone has cleanly handled every fetch
                # since it was added, no Error 162 regressions observed).
                await _hist_rate_limiter.acquire()

                chunk_start = max(chunk_end - timedelta(days=chunk_days - 1), start)
                chunk_delta = chunk_end - chunk_start
                window_seconds = int(chunk_delta.total_seconds())
                if window_seconds < 86400:
                    duration_str = f"{max(120, window_seconds + 60)} S"
                else:
                    duration_str = _days_to_duration_str(max(1, chunk_delta.days + 1))

                # Retry (infra.ibkr.retry_count, default 3) with exponential backoff
                # (infra.ibkr.retry_backoff_base_s, default 65) on an empty result.
                # reqId-based matching (not snapshot-diff — see migration 199 / F3
                # 2026-07-05): BarDataList carries .reqId, so a no-data Error 162 can be
                # attributed to exactly the request that caused it. Our own outer
                # asyncio.wait_for timeout below cancels the coroutine before it returns
                # a BarDataList, so we never get a reqId for THAT attempt — treated as a
                # plain retryable failure, never as a no-data signal (the alternative,
                # snapshot-diffing the global _no_data_req_ids set, could misattribute a
                # late 162 callback for an abandoned request to an unrelated later chunk).
                ib_bars: list = []
                hit_definitive_no_data = False
                for attempt in range(_RETRY_COUNT):
                    outer_timed_out = False
                    try:
                        result = await asyncio.wait_for(
                            self._ib.reqHistoricalDataAsync(
                                contract,
                                endDateTime=chunk_end.strftime("%Y%m%d %H:%M:%S"),
                                durationStr=duration_str,
                                barSizeSetting=_TF_TO_IB[timeframe],
                                whatToShow=what_to_show,
                                useRTH=use_rth,
                                formatDate=1,
                            ),
                            timeout=_HIST_REQUEST_TIMEOUT_SEC,
                        )
                    except TimeoutError:
                        logger.error(
                            "ibkr.hist_request_outer_timeout",
                            extra={
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "chunk_end": chunk_end.isoformat(),
                                "attempt": attempt + 1,
                            },
                        )
                        result = None
                        outer_timed_out = True
                    if result:
                        ib_bars = result
                        break

                    # Yield so any late Error 162 callback for this reqId can fire.
                    await asyncio.sleep(0)
                    req_id = getattr(result, "reqId", None) if result is not None else None
                    if not outer_timed_out and req_id in _no_data_req_ids:
                        _no_data_req_ids.discard(req_id)
                        logger.warning(
                            "ibkr.hist_no_data_skip",
                            extra={
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "chunk_end": chunk_end.isoformat(),
                                "reqId": req_id,
                            },
                        )
                        hit_definitive_no_data = True
                        break  # Definitive "no data" — don't retry

                    if attempt < _RETRY_COUNT - 1:
                        backoff = _RETRY_BACKOFF_BASE_S * (2**attempt)  # 65s then 130s (defaults)
                        logger.warning(
                            "ibkr.hist_chunk_retry",
                            extra={
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "chunk_end": chunk_end.isoformat(),
                                "attempt": attempt + 1,
                                "backoff_s": backoff,
                                "outer_timed_out": outer_timed_out,
                            },
                        )
                        await asyncio.sleep(backoff)
                        await _hist_rate_limiter.acquire()
                else:
                    logger.error(
                        "ibkr.hist_chunk_failed_all_retries",
                        extra={
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "chunk_start": chunk_start.isoformat(),
                            "chunk_end": chunk_end.isoformat(),
                        },
                    )

                chunk_bars: list[OHLCVBar] = []
                for bar in ib_bars or []:
                    bar_ts = (
                        bar.date
                        if isinstance(bar.date, datetime)
                        else datetime.fromisoformat(str(bar.date))
                    )
                    if bar_ts.tzinfo is None:
                        bar_ts = bar_ts.replace(tzinfo=UTC)
                    chunk_bars.append(
                        OHLCVBar(
                            symbol=symbol,
                            timeframe=timeframe,
                            timestamp=bar_ts,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=int(bar.volume),
                            source=source_tag,
                        )
                    )
                all_bars.extend(chunk_bars)
                if on_chunk and chunk_bars:
                    await on_chunk(chunk_bars)

                if hit_definitive_no_data:
                    consecutive_no_data_chunks += 1
                    if consecutive_no_data_chunks >= _NO_DATA_CONFIRMATION_CHUNKS:
                        # N consecutive fully-empty chunks while walking backward is strong
                        # evidence we've passed the instrument's launch date — a single
                        # empty chunk is not (see _NO_DATA_CONFIRMATION_CHUNKS, todo 049).
                        # Stop here instead of burning rate-limit budget on years of
                        # known-empty requests (this was previously walking the full
                        # requested depth regardless of actual listing date; see todo
                        # 042-adjacent finding 2026-07-02).
                        break
                else:
                    consecutive_no_data_chunks = 0

                chunk_end = chunk_start - timedelta(days=1)

        all_bars.sort(key=lambda b: b.timestamp)
        return all_bars

    async def qualify_instrument(
        self,
        instrument: Instrument,
        *,
        ibkr_symbol: str = "",
        trading_class: str = "",
    ) -> bool:
        """Qualify an instrument with IBKR and cache the contract.

        Must be called before fetch_historical_bars() or stream_ticks().
        ibkr_symbol and trading_class are resolved by the caller (IBKRAdapter);
        direct callers may omit them and they are derived from provider_meta.
        Returns True if successfully qualified.
        """
        if not self._ib:
            return False
        try:
            if instrument.asset_class == AssetClass.FUTURES:
                if not ibkr_symbol:
                    ibkr_meta = instrument.provider_meta.get("ibkr", {})
                    ibkr_symbol = ibkr_meta.get("symbol") or instrument.base or instrument.symbol
                    trading_class = (
                        trading_class
                        or ibkr_meta.get("trading_class")
                        or instrument.provider_meta.get("trading_class", "")
                    )
                contract = Future(
                    symbol=ibkr_symbol,
                    lastTradeDateOrContractMonth=instrument.expiry,
                    exchange=instrument.exchange,
                    currency="USD",
                    **({"tradingClass": trading_class} if trading_class else {}),
                )
            elif instrument.asset_class == AssetClass.FX:
                contract = Forex(pair=instrument.symbol)
            elif instrument.asset_class == AssetClass.CRYPTO:
                contract = Contract(secType="CRYPTO", symbol=instrument.base, currency="USD")
            elif instrument.asset_class == AssetClass.EQUITY:
                contract = Stock(
                    symbol=instrument.symbol,
                    exchange=instrument.exchange or "SMART",
                    currency="USD",
                )
            else:
                contract = Stock(symbol=instrument.symbol, exchange=instrument.exchange)

            # [rca_analysis 2026-07-05, F4] reqContractDetailsAsync has NO timeout of its
            # own in ib_async (unlike reqHistoricalDataAsync's internal default=60) --
            # fully unbounded without this wrapper. Same failure class as the historical-
            # data hang migration 199 fixed elsewhere in this file.
            details = await asyncio.wait_for(
                self._ib.reqContractDetailsAsync(contract), timeout=_CONTRACT_DETAILS_TIMEOUT_SEC
            )
            if details:
                qualified = details[0].contract
                self._qualified_contracts[instrument.symbol] = qualified
                # Store reverse mapping for localSymbol → canonical (e.g. "EUR.USD" → "EURUSD")
                local_sym = getattr(qualified, "localSymbol", None)
                if local_sym and local_sym != instrument.symbol:
                    self._local_to_canonical[local_sym] = instrument.symbol
                    self._qualified_contracts[local_sym] = qualified
                return True
            logger.warning(
                "qualify_instrument: no contract details returned",
                extra={
                    "symbol": instrument.symbol,
                    "base": instrument.base,
                    "exchange": instrument.exchange,
                    "expiry": instrument.expiry,
                },
            )
            return False
        except Exception as e:
            logger.warning(
                "qualify_instrument failed", extra={"symbol": instrument.symbol, "error": str(e)}
            )
            return False

    async def get_quote(self, symbol: str, timeout_sec: float | None = None) -> dict | None:
        """Request a one-off snapshot quote for a pre-qualified symbol.

        Sleeps for timeout_sec to allow IBKR to fill the snapshot, then returns
        a dict with bid, ask, last (and optionally lastSize), or None if no data arrived.

        If not provided, uses Settings.ib_timeout_sec as default.

        Returns None if circuit breaker is OPEN or quote fails.
        """
        # Check circuit breaker state
        if _is_circuit_breaker_open():
            logger.warning(
                "IBKR circuit breaker OPEN, skipping quote request",
                extra={"symbol": symbol},
            )
            return None

        if not self._ib:
            return None
        contract = self._qualified_contracts.get(symbol)
        if not contract:
            logger.warning("get_quote: symbol not qualified", extra={"symbol": symbol})
            return None
        sec_type = getattr(contract, "secType", "")
        tick_list = _FUT_TICK_LIST if sec_type == "FUT" else ""
        ticker = self._ib.reqMktData(contract, genericTickList=tick_list, snapshot=True)
        actual_timeout = timeout_sec or self._settings.ib_timeout_sec
        try:
            await asyncio.sleep(actual_timeout)
            bid = getattr(ticker, "bid", None)
            ask = getattr(ticker, "ask", None)
            last = getattr(ticker, "last", None) or getattr(ticker, "close", None)
            last_size = getattr(ticker, "lastSize", None)
            result = {}
            if isinstance(bid, (int, float)) and bid > 0:
                result["bid"] = float(bid)
            if isinstance(ask, (int, float)) and ask > 0:
                result["ask"] = float(ask)
            if isinstance(last, (int, float)) and last > 0:
                result["last"] = float(last)
            if isinstance(last_size, (int, float)) and last_size > 0:
                result["lastSize"] = int(last_size)
            return result if result else None
        finally:
            self._ib.cancelMktData(contract)

    def _normalize_ticker(self, ticker) -> Tick | None:
        """Normalize an ib_async Ticker to a Tick. Returns None if no valid price."""
        symbol = getattr(ticker.contract, "localSymbol", None)
        if not symbol:
            return None
        symbol = self._local_to_canonical.get(symbol, symbol)

        price = None
        for attr in ("last", "close", "bid", "ask"):
            val = getattr(ticker, attr, None)
            if isinstance(val, (int, float)) and val > 0:
                price = float(val)
                break
        if not price:
            return None

        def _pos_float(val) -> float | None:
            return float(val) if isinstance(val, (int, float)) and val > 0 else None

        def _pos_int(val) -> int | None:
            return int(val) if isinstance(val, (int, float)) and val > 0 else None

        return Tick(
            symbol=symbol,
            timestamp=datetime.now(UTC),
            price=price,
            size=_pos_int(getattr(ticker, "lastSize", None)),
            bid=_pos_float(getattr(ticker, "bid", None)),
            ask=_pos_float(getattr(ticker, "ask", None)),
            bid_size=_pos_int(getattr(ticker, "bidSize", None)),
            ask_size=_pos_int(getattr(ticker, "askSize", None)),
            source=SOURCE_IBKR_GENERIC,
        )

    def _handle_pending_tickers(self, tickers) -> None:
        """ib_async callback — runs on ib_async's thread. Bridge to asyncio queue."""
        if not self._tick_queue or not self._loop:
            return
        try:
            for ticker in tickers:
                if ticker.contract.localSymbol not in self._qualified_contracts:
                    continue
                tick = self._normalize_ticker(ticker)
                if tick:
                    try:
                        self._loop.call_soon_threadsafe(self._tick_queue.put_nowait, tick)
                    except Exception:
                        PROVIDER_BARS_DROPPED_TOTAL.add(1, _M_DROPPED_TICK_QUEUE_FULL_ATTRS)
        except Exception:
            logger.exception("ibkr._handle_pending_tickers callback error")

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[Tick]:
        """Async iterator yielding normalized Ticks.

        Bridges ib_async's sync callbacks to asyncio via a bounded Queue.
        Subscribes to all symbols via reqMktData on entry.
        """
        self._loop = asyncio.get_event_loop()
        self._tick_queue = asyncio.Queue(maxsize=self._tick_queue_size)

        # Register callback
        self._ib.pendingTickersEvent += self._handle_pending_tickers

        # Subscribe to market data for each symbol
        for symbol in symbols:
            contract = self._qualified_contracts.get(symbol)
            if contract and self._ib:
                # RTVolume is futures-only; FX (CASH) uses basic bid/ask/last
                sec_type = getattr(contract, "secType", "")
                tick_list = _FUT_TICK_LIST if sec_type == "FUT" else ""
                self._ib.reqMktData(contract, genericTickList=tick_list, snapshot=False)

        try:
            while True:
                tick = await self._tick_queue.get()
                yield tick
        finally:
            self._ib.pendingTickersEvent -= self._handle_pending_tickers

    async def stream_real_time_bars(self, symbols: list[str]) -> AsyncIterator[tuple[str, object]]:
        """Async iterator yielding (symbol, RealTimeBar) tuples as 5-second bars arrive.

        Bridges ib_async's sync updateEvent callbacks to asyncio via a bounded Queue.
        whatToShow per asset class: CASH -> MIDPOINT, all others -> TRADES.
        useRTH=False: include all sessions (pre/post market, 24h crypto/FX).

        Note: AGGTRADES is only valid for reqHistoricalData, not reqRealTimeBars.
        Crypto (PAXOS) uses TRADES here; verify BTCUSD/ETHUSD on paper account.
        """
        self._loop = asyncio.get_event_loop()
        self._rtb_queue: asyncio.Queue = asyncio.Queue(maxsize=self._tick_queue_size)

        subscribed: list = []
        for symbol in symbols:
            contract = self._qualified_contracts.get(symbol)
            if not contract or not self._ib:
                continue
            sec_type = getattr(contract, "secType", "")
            what = "MIDPOINT" if sec_type == "CASH" else "TRADES"
            bars = self._ib.reqRealTimeBars(contract, barSize=5, whatToShow=what, useRTH=False)

            def _on_bar(bars_list, has_new_bar, *, _symbol=symbol):
                """ib_async callback — runs on ib_async thread; bridge to asyncio queue."""
                if not has_new_bar or not bars_list:
                    return
                bar = bars_list[-1]
                try:
                    self._loop.call_soon_threadsafe(self._rtb_queue.put_nowait, (_symbol, bar))
                except Exception:
                    PROVIDER_BARS_DROPPED_TOTAL.add(1, _M_DROPPED_RTB_QUEUE_FULL_ATTRS)
                    logger.warning("ibkr.rtb_queue_full_dropping symbol=%s", _symbol)

            bars.updateEvent += _on_bar
            subscribed.append((bars, _on_bar))

        try:
            while True:
                item = await self._rtb_queue.get()
                yield item
        finally:
            for bars, cb in subscribed:
                bars.updateEvent -= cb
                try:
                    self._ib.cancelRealTimeBars(bars)
                except Exception:
                    pass

    async def stream_official_bars(
        self, symbols: list[str], timeframe: str = "1m"
    ) -> AsyncIterator[tuple[str, OHLCVBar]]:
        """Async iterator yielding official, audited bars from IBKR's historical stream.

        Uses reqHistoricalData with keepUpToDate=True. These bars are typically
        more accurate/complete than 5s RealTimeBars but arrive with higher latency
        (usually 2-5s after the bar close).

        Provides a secondary 'Official' stream for reconciliation and failover.
        """
        if timeframe not in _TF_TO_IB:
            raise ValueError(f"Unsupported timeframe '{timeframe}'")

        self._loop = asyncio.get_running_loop()
        # Separate queue for official bars to prevent crosstalk
        official_queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

        subscribed: list = []
        for symbol in symbols:
            contract = self._qualified_contracts.get(symbol)
            if not contract or not self._ib:
                continue

            sec_type = getattr(contract, "secType", "")
            # CRYPTO: AGGTRADES not supported with keepUpToDate=True (IBKR error 321).
            # Skip official bar stream for crypto — RTBs provide coverage.
            if sec_type == "CRYPTO":
                continue
            what = "MIDPOINT" if sec_type == "CASH" else "TRADES"

            # 1-day duration is the minimum for keepUpToDate.
            # reqHistoricalDataAsync is required here — nest_asyncio is not applied
            # (removed for Python 3.14 compat), so the sync version would raise
            # "event loop already running" when called from an async context.
            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr="1 D",
                barSizeSetting=_TF_TO_IB[timeframe],
                whatToShow=what,
                useRTH=False,
                formatDate=1,
                keepUpToDate=True,
            )

            def _on_official_bar(bars_list, has_new_bar=True, *, _symbol=symbol, _tf=timeframe):
                if not has_new_bar or not bars_list:
                    return
                bar = bars_list[-1]
                try:
                    # Map IB bar to our OHLCVBar schema
                    bar_ts = _normalize_ib_bar_ts(bar.date)

                    normalized = OHLCVBar(
                        symbol=_symbol,
                        timeframe=_tf,
                        timestamp=bar_ts,
                        open=float(bar.open),
                        high=float(bar.high),
                        low=float(bar.low),
                        close=float(bar.close),
                        volume=int(bar.volume),
                        source=SOURCE_IBKR_OFFICIAL,
                    )
                    self._loop.call_soon_threadsafe(
                        official_queue.put_nowait, (_symbol, normalized)
                    )
                except Exception:
                    PROVIDER_BARS_DROPPED_TOTAL.add(1, _M_DROPPED_OFFICIAL_QUEUE_ERROR_ATTRS)
                    logger.warning("ibkr.official_queue_error_dropping symbol=%s", _symbol)

            bars.updateEvent += _on_official_bar
            subscribed.append((bars, _on_official_bar))

        try:
            while True:
                item = await official_queue.get()
                yield item
        finally:
            # Cleanup subscriptions
            for bars, cb in subscribed:
                bars.updateEvent -= cb
                # Note: ib_async automatically cancels keepUpToDate when the IB instance
                # is cleaned up, but we could explicitly cancel if needed.

    async def resolve_instrument(self, query: str) -> Instrument | None:
        """Resolve a symbol query to an Instrument via IBKR contract details."""
        if not self._ib:
            return None
        try:
            # Try as futures first (most common for this platform)
            contract = Future(symbol=query)
            details = await asyncio.wait_for(
                self._ib.reqContractDetailsAsync(contract), timeout=_CONTRACT_DETAILS_TIMEOUT_SEC
            )
            if details:
                d = details[0]
                c = d.contract
                return Instrument(
                    symbol=c.localSymbol or c.symbol,
                    name=getattr(d, "longName", ""),
                    asset_class=AssetClass.FUTURES,
                    exchange=c.exchange,
                    base=c.symbol,
                    expiry=c.lastTradeDateOrContractMonth,
                    tick_size=float(d.minTick),
                    point_value=float(c.multiplier or 0),
                    provider_meta={"con_id": c.conId},
                )
        except Exception as e:
            logger.debug(
                "resolve_instrument futures lookup failed", extra={"query": query, "error": str(e)}
            )
        return None
