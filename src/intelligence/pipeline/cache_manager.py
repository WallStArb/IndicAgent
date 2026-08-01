"""CacheManager — owns the 6 DB-loaded caches and their refresh schedule.

Extracted from IntelligencePipeline as part of Phase 088 god-class
decomposition. CacheManager has zero lateral references: it pushes data via
properties and its own background loops. The orchestrator stores task handles,
calls load_initial() eagerly, and calls update_hmm_regime() per bar.

Eager-load contract (HIGH finding 3):
    load_initial() runs all 6 loaders BEFORE start_refresh_loops() ever sleeps.
    Without this, the service starts cold for up to 4 hours.

Enrollment ordering (MEDIUM finding):
    The orchestrator calls enroll_all_plugins(conn) BEFORE awaiting load_initial().
    _load_shadow_cache reads the shadow_registry table that enroll_all_plugins populates.

Seed API:
    seed_* methods are the SINGLE allowed way to populate caches from outside the
    class (tests, checkpoint restore, repair tooling). Direct mutation of private
    _* attributes is forbidden.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import asyncpg
import structlog

from src.monitoring.ks_drift_monitor import DRIFT_PENALTIES
from src.observability.metrics import gauge

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.core.database_manager import DatabaseManager
    from src.intelligence.pipeline.signal_processor import CacheSnapshot

# CIS Kalman defaults (mirrors the god-class module-level dict)
_CIS_KALMAN_DEFAULTS: dict[str, dict[str, float]] = {
    "1m": {"Q": 0.01, "R": 0.08},
    "5m": {"Q": 0.01, "R": 0.06},
    "15m": {"Q": 0.01, "R": 0.04},
    "1h": {"Q": 0.01, "R": 0.02},
    "4h": {"Q": 0.01, "R": 0.01},
    "1d": {"Q": 0.01, "R": 0.01},
    "default": {"Q": 0.01, "R": 0.05},
}


def _load_cis_kalman_params() -> dict[str, dict[str, float]]:
    """Load per-TF CIS Kalman Q/R from config/kalman_parameters.json.

    Config file can override defaults for specific timeframes, but "default"
    key is always guaranteed via merge with hardcoded defaults.
    """
    config_path = Path(__file__).parent.parent.parent / "config" / "kalman_parameters.json"
    try:
        data = json.loads(config_path.read_text())
        config_params = data.get("cis_kalman", {})
        merged = {}
        all_tfs = set(_CIS_KALMAN_DEFAULTS) | set(config_params)
        for tf in all_tfs:
            base = dict(_CIS_KALMAN_DEFAULTS.get(tf, _CIS_KALMAN_DEFAULTS["default"]))
            base.update(config_params.get(tf, {}))
            merged[tf] = base
        return merged
    except Exception:
        return dict(_CIS_KALMAN_DEFAULTS)


def _instrument_from_row(row: dict) -> Any:
    """Build an Instrument from an instruments table row (asyncpg dict).

    asyncpg returns JSONB columns as plain dicts — no json.loads() needed.
    For FX instruments the DB primary key is the base currency (e.g. USD),
    but contract_details.symbol holds the full pair (e.g. USDJPY), so we
    prefer the contract_details value.
    """
    from src.core.models import Instrument  # noqa: PLC0415 — avoids circular import

    cd: dict = row["contract_details"] or {}
    return Instrument(
        symbol=cd.get("symbol") or row["symbol"],
        base=row.get("base", ""),
        name=cd.get("name", ""),
        asset_class=cd.get("asset_class", "equity"),
        exchange=cd.get("exchange", ""),
        sector=cd.get("sector", ""),
        tick_size=float(cd.get("tick_size") or 0),
        point_value=float(cd.get("point_value") or 0),
        session_id=cd.get("session_id", "equity_regular"),
        provider_meta=cd.get("provider_meta") or {},
        expiry=cd.get("expiry", ""),
    )


class CacheManager:
    """Owns the 6 DB-loaded caches and their background refresh schedule.

    Constructor: CacheManager(db: DatabaseManager, settings: Settings, symbols=None)

    Caches (properties):
        perf_weights, cis_weights, cis_kalman_params, calibration_curves,
        drift_penalties, shadow_cache

    Lifecycle:
        1. Orchestrator calls enroll_all_plugins(conn)  -- shadow registry seeding
        2. Orchestrator calls await load_initial()       -- eager load all 5 caches
        3. Orchestrator calls start_refresh_loops()      -- returns 5 background Tasks

    Seed API (for tests and checkpoint restore):
        seed_perf_weights, seed_cis_weights, seed_calibration_curves,
        seed_shadow_cache, seed_drift_penalties

    Symbol scoping (D-30):
        When symbols is provided, all DB queries add WHERE symbol = ANY($N) clauses
        so sharded deployments only load data for their assigned symbol set.
        When None (default), queries are unscoped — current behavior preserved.
    """

    def __init__(
        self,
        db: DatabaseManager,
        settings: Settings,
        symbols: frozenset[str] | None = None,
        on_instruments_changed: Callable[[], None] | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._symbol_filter = symbols  # None = all symbols (D-30)
        self._on_instruments_changed = on_instruments_changed or (lambda: None)
        self._listener_connected = gauge(
            "instruments_listener_connected",
            "1 when LISTEN instruments connection is active, 0 when reconnecting",
        )
        self._logger = structlog.get_logger(__name__)

        # 6 cache dicts — atomic replacement on every load
        self._perf_weights: dict = {}
        self._cis_weights: dict = {}
        self._calibration_curves: dict = {}
        self._shadow_cache: dict[str, bool] = {}
        self._drift_penalties: dict = {}

        # CIS Kalman params loaded once from config file (no refresh loop per D-13)
        self._cis_kalman_params: dict = _load_cis_kalman_params()

        # HMM regime state for regime-conditioned perf_weights loading
        self._last_hmm_regime: int | None = None

        # CIS weights version for scorer mediation (orchestrator polls this)
        self._cis_weights_version: int = 0

        # Stream-fed caches (D-19) — keyed by tf; mutated by update_* methods
        self._cross_asset: dict = {}
        self._macro: dict = {}
        self._htf_intel: dict = {}
        self._hmm_regime: int | None = None

        # Per-cache locks (REVIEW-MEDIUM): guards read-modify-write in update_macro
        # (setdefault + update are two operations) against concurrent per-key workers.
        self._cross_asset_lock = asyncio.Lock()
        self._macro_lock = asyncio.Lock()
        self._htf_intel_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties (read surface)
    # ------------------------------------------------------------------

    @property
    def perf_weights(self) -> dict:
        """Performance weights keyed by (setup_plugin, tf, symbol) 3-tuples."""
        return self._perf_weights

    @property
    def cis_weights(self) -> dict:
        """CIS bucket weights from cis_weights table."""
        return self._cis_weights

    @property
    def cis_kalman_params(self) -> dict[str, dict[str, float]]:
        """Per-TF CIS Kalman Q/R parameters (loaded once from config file)."""
        return self._cis_kalman_params

    @property
    def calibration_curves(self) -> dict:
        """Isotonic calibration curves keyed by (setup_plugin, tf, symbol)."""
        return self._calibration_curves

    @property
    def drift_penalties(self) -> dict:
        """KS drift penalties from DRIFT_PENALTIES config."""
        return self._drift_penalties

    @property
    def shadow_cache(self) -> dict[str, bool]:
        """Shadow registry state keyed by component_name."""
        return self._shadow_cache

    @property
    def cis_weights_version(self) -> int:
        """Current CIS weights version; orchestrator compares to detect staleness."""
        return self._cis_weights_version

    # ------------------------------------------------------------------
    # HMM regime helpers
    # ------------------------------------------------------------------

    def update_hmm_regime(self, hmm_val: int | None) -> None:
        """Called by orchestrator per bar to track last-observed HMM regime."""
        self._last_hmm_regime = hmm_val
        self._hmm_regime = hmm_val

    def current_hmm_regime_label(self) -> str:
        """Map last-observed HMM regime integer to signal_metrics regime_type string.

        0 = ranging  -> 'mean_reversion'
        1/2 = trending -> 'trend'
        None (no bars yet) -> 'all'
        """
        hmm = self._last_hmm_regime
        if hmm == 0:
            return "mean_reversion"
        if hmm in (1, 2):
            return "trend"
        return "all"

    # ------------------------------------------------------------------
    # Stream cache update methods (D-19)
    # ------------------------------------------------------------------

    async def store_cross_asset_payload(self, tf: str, payload: dict) -> None:
        """Store latest cross-asset spread-feature payload (topic_cross_asset) for CacheSnapshot.

        Renamed from update_cross_asset (todo 221) -- was colliding in name (but not
        contract) with FeatureCache.update_cross_asset(), which computes vix_z/
        flight_quality/yield_slope_z from raw SPY/TLT/SHY OHLCV bars. This method just
        stores cross_asset_analyzer's already-computed spread/correlation payload
        (corr_z, eq_index features) for CacheSnapshot/API exposure -- unrelated data.
        """
        async with self._cross_asset_lock:
            self._cross_asset[tf] = payload
        self._logger.debug("cache_manager.cross_asset_updated", tf=tf)

    async def update_macro(self, tf: str, payload: dict) -> None:
        """Merge macro fields into the per-tf macro cache entry."""
        async with self._macro_lock:
            self._macro.setdefault(tf, {}).update(payload)
        self._logger.debug("cache_manager.macro_updated", tf=tf)

    async def update_htf_intel(self, tf: str, data: dict) -> None:
        """Store latest HTF intel data for the given timeframe."""
        async with self._htf_intel_lock:
            self._htf_intel[tf] = data
        self._logger.debug("cache_manager.htf_intel_updated", tf=tf)

    # ------------------------------------------------------------------
    # CacheSnapshot construction (D-19)
    # ------------------------------------------------------------------

    def snapshot(self) -> CacheSnapshot:
        """Build a CacheSnapshot from current cache state for per-bar consumption.

        Imports CacheSnapshot locally to avoid a circular import between
        cache_manager and signal_processor at module level.
        """
        # sync method - cannot be preempted in asyncio event loop; lock-free reads are safe
        from src.intelligence.pipeline.signal_processor import CacheSnapshot  # noqa: PLC0415

        return CacheSnapshot(
            perf_weights=self._perf_weights,
            calibration_curves=self._calibration_curves,
            drift_penalties=self._drift_penalties,
            cis_weights=self._cis_weights,
            cis_weights_version=self._cis_weights_version,
            cross_asset_data=dict(self._cross_asset),
            macro_data=dict(self._macro),
            htf_intel=dict(self._htf_intel),
            shadow_cache=dict(self._shadow_cache),
        )

    # ------------------------------------------------------------------
    # Public seed API (single contract for outside writers)
    # ------------------------------------------------------------------

    def seed_perf_weights(self, weights: dict) -> None:
        """Atomically replace perf_weights (no merge — fresh DB load wins)."""
        self._perf_weights = dict(weights)

    def seed_cis_weights(self, weights: dict, version: int = 0) -> None:
        """Atomically replace cis_weights. Does NOT call cis_scorer.update_weights (Pitfall 4).

        The orchestrator mediates scorer updates by comparing cis_weights_version
        before calling cis_scorer.update_weights. CacheManager never touches the scorer.
        """
        self._cis_weights = dict(weights)
        if version:
            self._cis_weights_version = int(version)

    def seed_calibration_curves(self, curves: dict) -> None:
        """Atomically replace calibration_curves."""
        self._calibration_curves = dict(curves)

    def seed_shadow_cache(self, cache: dict) -> None:
        """Atomically replace shadow_cache."""
        self._shadow_cache = dict(cache)

    def seed_drift_penalties(self, penalties: dict) -> None:
        """Atomically replace drift_penalties."""
        self._drift_penalties = dict(penalties)

    # ------------------------------------------------------------------
    # Eager load entry point (HIGH finding 3)
    # ------------------------------------------------------------------

    async def load_initial(self) -> None:
        """Eagerly populate all 6 caches before refresh loops start.

        Preserves god-class _setup behavior — without this the service starts
        cold for up to 4 hours (one refresh interval per cache).

        CRITICAL ordering contract (MEDIUM finding from REVIEWS.md):
            The orchestrator MUST call enroll_all_plugins(conn) BEFORE calling
            load_initial(). The final step here (_load_shadow_cache) reads the
            shadow_registry table that enroll_all_plugins populates.
        """
        await self._load_perf_weights()
        await self._refresh_drift_penalties()
        await self._load_cis_weights()
        await self._load_calibration_curves()
        await self._load_shadow_cache()  # caller must run enroll_all_plugins BEFORE invoking load_initial

    # ------------------------------------------------------------------
    # Refresh loop management
    # ------------------------------------------------------------------

    async def _run_refresh_loop(self, load_fn: Any, interval_sec: int) -> None:
        """Background loop: sleep then reload. Loops sleep FIRST because load_initial()
        has already populated the cache — no cold-start gap.
        """
        while True:
            try:
                await asyncio.sleep(interval_sec)
                await load_fn()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._logger.warning(
                    "cache_manager.refresh_loop_error",
                    loader=getattr(load_fn, "__name__", str(load_fn)),
                    error=str(error),
                )

    def start_refresh_loops(self) -> list[asyncio.Task]:
        """Create and return 5 background refresh Tasks at their configured intervals.

        Intervals (seconds):
            perf_weights=3600, drift_penalties=14400, cis_weights=1800,
            calibration_curves=1800, shadow_cache=300

        The loops sleep before reloading — this is correct ONLY because
        load_initial() has already populated the caches.
        """
        return [
            asyncio.create_task(self._run_refresh_loop(self._load_perf_weights, 3600)),
            asyncio.create_task(self._run_refresh_loop(self._refresh_drift_penalties, 14400)),
            asyncio.create_task(self._run_refresh_loop(self._load_cis_weights, 1800)),
            asyncio.create_task(self._run_refresh_loop(self._load_calibration_curves, 1800)),
            asyncio.create_task(self._run_refresh_loop(self._load_shadow_cache, 300)),
        ]

    def start_instruments_listener(self) -> asyncio.Task:
        """Returns an asyncio.Task that runs LISTEN instruments on a dedicated asyncpg
        connection, with reconnect on failure.

        Caller must add the returned task to its _background_tasks for lifecycle
        management. The listener uses a raw asyncpg.connect() connection (NOT the
        pool context manager) and holds it for the listener lifetime so the LISTEN
        subscription is never accidentally released.
        """
        return asyncio.create_task(self._run_instruments_listener())

    async def _run_instruments_listener(self) -> None:
        """Infinite retry loop: LISTEN on a dedicated asyncpg connection.

        On NOTIFY 'instruments', schedules _reload_instruments_cache() via
        asyncio.ensure_future so the sync callback never blocks the event loop.
        Re-raises asyncio.CancelledError so the caller can cancel cleanly.
        On any other exception, logs at WARNING and retries after 5s backoff.
        """
        while True:
            try:
                conn = await asyncpg.connect(self._settings.database_url)
                try:
                    await conn.execute("LISTEN instruments")
                    self._listener_connected.add(1)
                    await conn.add_listener("instruments", self._on_instrument_notify)
                    # Heartbeat loop — asyncpg delivers NOTIFY via the event loop
                    # without polling; the sleep just keeps this task alive.
                    while not conn.is_closed():
                        await asyncio.sleep(10)
                finally:
                    # Guard remove_listener: a connection closed mid-loop would
                    # raise ConnectionDoesNotExistError and mask the real error.
                    if not conn.is_closed():
                        await conn.remove_listener("instruments", self._on_instrument_notify)
                    await conn.close()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._logger.warning(
                    "cache_manager.instruments_listener_error",
                    error=str(error),
                )
                self._listener_connected.add(-1)
                await asyncio.sleep(5)

    def _on_instrument_notify(self, conn: object, pid: int, channel: str, payload: str) -> None:
        """Called synchronously by asyncpg on NOTIFY instruments.

        Logs the change and schedules the async reload via call_soon_threadsafe +
        asyncio.ensure_future so this sync callback never blocks the event loop.
        """
        self._logger.info("cache_manager.instrument_changed", symbol=payload)
        asyncio.get_running_loop().call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._reload_instruments_cache())
        )

    async def _reload_instruments_cache(self) -> None:
        """Reload non-futures instruments from DB and invoke the on_instruments_changed callback.

        On success: builds the instrument list and calls self._on_instruments_changed()
        so the caller (e.g. intelligence_pipeline_agent) can invalidate its TTL cache.

        On failure: logs at ERROR and leaves state unchanged so the pipeline continues
        operating on the last good state.
        """
        try:
            rows = await self._db.execute_query(
                "SELECT symbol, base, contract_details FROM instruments"
                " WHERE is_active = true AND contract_details->>'asset_class' != 'futures'"
            )
            instruments = [_instrument_from_row(r) for r in rows]
            self._on_instruments_changed()
            self._logger.info("cache_manager.instruments_reloaded", count=len(instruments))
        except Exception as error:
            self._logger.error(
                "cache_manager.instruments_reload_failed",
                error=str(error),
            )

    # ------------------------------------------------------------------
    # Private loaders (ported verbatim from god class with minimal adjustments)
    # ------------------------------------------------------------------

    async def _load_perf_weights(self) -> None:
        """Load perf_weights from signal_metrics (market track, regime-conditioned).

        Uses current_hmm_regime_label() instead of _current_hmm_regime_label().
        Atomic replacement of self._perf_weights at end.
        When self._symbol_filter is set, queries are scoped to those symbols (D-30).
        """
        if self._db is None:
            return
        try:
            current_regime = self.current_hmm_regime_label()

            async def _fetch(regime: str) -> list:
                base = (
                    "SELECT setup_plugin, tf, symbol, sharpe FROM signal_metrics"
                    " WHERE track = 'market' AND window_days = 30 AND n >= 100"
                )
                if self._symbol_filter is not None:
                    return await self._db.execute_query(
                        f"{base} AND regime_type = $1 AND symbol = ANY($2::text[])",
                        regime,
                        list(self._symbol_filter),
                    )
                return await self._db.execute_query(f"{base} AND regime_type = $1", regime)

            rows = await _fetch(current_regime)
            if not rows:
                rows = await _fetch("all")

            if not rows:
                self._perf_weights = {}
                self._logger.info("perf_weights.empty", regime=current_regime)
                return

            ranked = sorted(rows, key=lambda r: (r["sharpe"] or 0.0))
            n = len(ranked)
            weights: dict = {}
            for rank, row in enumerate(ranked):
                sym = row.get("symbol", "*")
                weights[(row["setup_plugin"], row["tf"], sym)] = round(
                    0.5 + ((n - 1 - rank) / n),
                    4,
                )

            self._perf_weights = weights
            self._logger.info(
                "perf_weights.loaded",
                regime=current_regime,
                n_setups=n,
            )
        except Exception as error:
            self._logger.warning("perf_weights.load_failed", error=str(error))

    async def _load_shadow_cache(self) -> None:
        """Load shadow_registry into shadow_cache. Atomic replacement."""
        if self._db is None:
            return
        try:
            rows = await self._db.execute_query(
                "SELECT component_name, is_shadow FROM shadow_registry"
            )
            self._shadow_cache = {r["component_name"]: bool(r["is_shadow"]) for r in rows}
        except Exception as error:
            self._logger.warning("shadow_cache.load_failed", error=str(error))

    async def _refresh_drift_penalties(self) -> None:
        """Refresh drift penalties from DRIFT_PENALTIES config. Atomic replacement."""
        self._drift_penalties = dict(DRIFT_PENALTIES)

    async def _load_cis_weights(self) -> None:
        """Load CIS bucket weights from cis_weights table. Atomic replacement.

        CRITICAL (Pitfall 4): does NOT call cis_scorer.update_weights.
        The orchestrator mediates scorer updates by comparing cis_weights_version.
        """
        if self._db is None:
            return
        try:
            rows = await self._db.execute_query(
                """SELECT version, trend_w, momentum_w, structure_w, pattern_w,
                          institutional_w, regime_w
                   FROM cis_weights
                   WHERE asset_cluster = 'global' AND timeframe = 'global'
                   ORDER BY version DESC LIMIT 1"""
            )
            if rows:
                row = rows[0]
                weights = {
                    "trend": float(row["trend_w"]),
                    "momentum": float(row["momentum_w"]),
                    "structure": float(row["structure_w"]),
                    "pattern": float(row["pattern_w"]),
                    "institutional": float(row["institutional_w"]),
                    "regime": float(row["regime_w"]),
                }
                self._cis_weights = weights
                self._cis_weights_version = int(row["version"])
        except Exception as error:
            self._logger.warning("cis_weights.load_failed", error=str(error))

    async def _load_calibration_curves(self) -> None:
        """Load calibration curves from calibration_curves table. Atomic replacement.

        When self._symbol_filter is set, scopes to those symbols (D-30).
        """
        if self._db is None:
            return
        try:
            import numpy as np

            base = "SELECT setup_plugin, timeframe, symbol, curve_data FROM calibration_curves"
            if self._symbol_filter is not None:
                # Always include symbol='*' rows (global CIS fallback) regardless of filter.
                rows = await self._db.execute_query(
                    f"{base} WHERE (symbol = ANY($1::text[]) OR symbol = '*')",
                    list(self._symbol_filter),
                )
            else:
                rows = await self._db.execute_query(base)
            curves: dict = {}
            for r in rows:
                curve_data = r.get("curve_data") or {}
                bp = curve_data.get("breakpoints")
                vals = curve_data.get("values")
                if not bp or not vals:
                    continue
                key = (r["setup_plugin"], r["timeframe"], r["symbol"] or "*")
                curves[key] = (np.array(bp, dtype=float), np.array(vals, dtype=float))
            self._calibration_curves = curves
        except Exception as error:
            self._logger.warning("calibration_curves.load_failed", error=str(error))
