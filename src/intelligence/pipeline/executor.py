"""PluginExecutor — owns thread pool, plugin cache, and tier execution.

Key design decisions:
- DB-ignorant: no DB queries, no cache reads from sibling modules.
- State-pure: plugin_states and shadow_cache are per-call parameters (D-10, D-07).
- State-update contract: returns state_updates keyed by (plugin_name, symbol, tf) so
  the orchestrator can write back via PluginStateManager.update_batch (HIGH finding 1).
- No lateral imports from state_manager or cache_manager — proven by test_no_lateral_imports.
"""

from __future__ import annotations

import asyncio
import functools
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from src.intelligence.pipeline.signal_processor import CacheSnapshot

# ---------------------------------------------------------------------------
# Circuit breaker defaults — single source of truth used by
# _build_plugin_circuit_breakers() (intelligence_pipeline) and _get_plugin_cb() (here).
#
# Shadow mode (default): CBs record failure data but never trip (enabled=False).
# Live mode: set PLUGIN_CB_ENABLED=1 to enable tripping after failure_threshold failures.
# ---------------------------------------------------------------------------
import os as _os

import structlog
from opentelemetry import metrics as otel_metrics

from src.core.service_utils import should_skip_plugin
from src.intelligence.register_plugins import (
    I2_WAVE_A,
    I2_WAVE_B,
    I4_WAVE_A,
    I4_WAVE_B,
    SMC_WAVE_A,
    SMC_WAVE_B,
    TIER_I1,
    TIER_I3,
    TIER_I5,
    TIER_I6,
    TIER_I7,
    TIER_SMC,
)
from src.intelligence.trading.signal_schema import (
    REQUIRED_SIGNAL_FIELDS,
    make_signal_id,
    validate_signal,
)
from src.observability.circuit_breaker import CircuitBreaker, CircuitState
from src.observability.metrics import (
    FEATURES_COMPUTED_TOTAL,
    counter,
)
from src.observability.plugin_observer import NoOpPluginObserver, PluginObserver

_meter = otel_metrics.get_meter("indicagent")
_TIER_LATENCY_MS = _meter.create_histogram(
    "intelligence_pipeline_tier_latency_ms",
    description="Per-tier execution latency in milliseconds",
)

_PLUGIN_CB_ENABLED: bool = _os.environ.get("PLUGIN_CB_ENABLED", "0") == "1"
_SHADOW_CB_DEFAULTS: dict[str, object] = {
    "failure_threshold": 3,
    "timeout_sec": 300,
    "enabled": _PLUGIN_CB_ENABLED,
}

# ---------------------------------------------------------------------------
# Type aliases (shared with orchestrator)
# ---------------------------------------------------------------------------

type _WaveTierDef = tuple[str, tuple[str, ...]]
type _AnalysisWave = tuple[_WaveTierDef, ...]


# ---------------------------------------------------------------------------
# PluginTask — container for parallel plugin execution metadata
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PluginCallResult:
    """Result container from _timed_plugin_call.

    Replaces the (result, duration_ms) tuple with a named, typed container
    that also carries incremental execution metadata for observer recording.
    """

    outputs: dict
    duration_ms: float
    used_incremental: bool
    null_count: int
    state: dict | None


@dataclass
class PluginTask:
    """Container for parallel plugin execution metadata."""

    coroutine: Any
    plugin_name: str
    state_key: tuple
    lock: threading.Lock
    tier_key: str = "I1"  # Track which tier this plugin belongs to
    bar: Any | None = None  # Only for I7 tasks


# ---------------------------------------------------------------------------
# _timed_plugin_call — shared timing wrapper
# ---------------------------------------------------------------------------


async def _fast_path_coroutine(plugin, frames: dict, state: dict) -> Any:
    """D-13 fast-path execution: call plugin synchronously in the event loop.

    Used when plugin.fast_path is True. Eligibility gate (D-13): plugin must have
    supports_incremental=False AND P99 latency < 100µs verified from a 24h histogram.
    No plugin in this plan sets fast_path=True — this branch is infrastructure only.

    Wraps the result in the same (result, duration_ms) format as _timed_plugin_call
    so _collect_plugin_results handles it identically.
    """
    return _timed_plugin_call(plugin, frames, state)


def _timed_plugin_call(plugin, frames, state: dict) -> Any:
    """Wrapper that returns (result, duration_ms) tuple for per-plugin timing.

    Uses incremental compute_next() when the plugin supports it and has state,
    falling back to compute_full() otherwise.

    PERF-03: state is threaded as an explicit parameter. Callers (run_i1,
    run_tier, run_i7_plugins) capture state locally and pass it via
    functools.partial — zero plugin._state assignments before run_in_executor
    dispatch. The incremental path is gated on the state parameter, not
    plugin._state. Plugins receive state= as a keyword argument; plugins updated
    to accept state= use it directly, while legacy plugins that still read
    self._state internally will see their instance attribute unchanged (empty
    dict from construction) and fall back to compute_full until they are
    individually migrated.
    """
    t0 = time.perf_counter()
    if getattr(plugin, "supports_incremental", False) and state:
        result = plugin.compute_next(frames, state=state)
    else:
        result = plugin.compute_full(frames)
    duration_ms = (time.perf_counter() - t0) * 1000

    # Renaissance validation: Ensure incremental plugins return state for persistence
    # This prevents the state corruption bug that occurred during PERF-03 migration
    # Only validate non-empty results — empty {} means "no data this bar" and is valid.
    # An empty result on an incremental plugin does not update state_updates, so the
    # executor reuses the previous bar's state on the next call (safe recovery path).
    if getattr(plugin, "supports_incremental", False) and isinstance(result, dict) and result:
        if "_state" not in result:
            raise ValueError(
                f"{plugin.name}: incremental plugins MUST return _state in result dict. "
                f"This prevents state corruption. Pattern: return {{**outputs, '_state': state}}"
            )

    return result, duration_ms


# ---------------------------------------------------------------------------
# PluginExecutor
# ---------------------------------------------------------------------------


class PluginExecutor:
    """Owns thread pool, plugin cache, instrument map, and per-plugin circuit breakers.

    Executes I1, analysis waves (I2-I6), and I7 plugins. Receives plugin_states
    (keyed by plugin_name) and shadow_cache as per-call parameters — never holds
    references to PluginStateManager or CacheManager (D-10, D-07).

    State-update contract (HIGH finding 1):
    - Input: plugin_states: dict[str, dict] — keyed by plugin_name
    - Output: state_updates: dict[tuple, dict] — keyed by (plugin_name, symbol, tf)
      so PluginStateManager.update_batch writes back at the correct 3-tuple keys.
    """

    # Wave-based tier execution — tiers within each wave run in parallel.
    # Each wave documents which prior-tier FRAME KEYS it legitimately reads.
    # This contract is regression-tested by test_wave_isolation.py (task 4-2).
    #
    # Wave 1: I2-WaveA(8) + I3(8) + SMC-WaveA(10)
    #   Reads: frames["i1"] (all indicator fields from I1Indicators)
    #   Does NOT read: i2, i3, smc, i4, i5, i6 (not yet computed)
    #
    # Wave 2: I2-WaveB(2) + SMC-WaveB(3) + I4-WaveA(11)
    #   Reads: frames["i1"], frames["i3"] (I4 context uses I3 swing/sr/trend data)
    #   Does NOT read: i2 (wave-A outputs), smc (wave-A outputs) in this wave
    #   NOTE: I4-WaveA context plugins (GARCHVolatility, TrendRegime, VolumeProfile, etc.)
    #   read I1 indicators + I3 structure. I2-WaveB and SMC-WaveB read I1 only.
    #
    # Wave 3: I4-WaveB(1) + I5(16)
    #   Reads: frames["i1"], frames["i2"], frames["i3"], frames["i4"] (partial),
    #          frames["smc"] (partial from wave-A SMC plugins)
    #   KalmanTrend (I4-WaveB) must run after GARCHVolatility (I4-WaveA).
    #   I5 patterns read I1-I4 and SMC-A.
    #
    # Wave 4: I6(1)
    #   Reads: frames["i1"], frames["i2"], frames["i3"], frames["i4"],
    #          frames["i5"], frames["smc"]
    #   Cross-timeframe confluence reads all prior tiers.
    _ANALYSIS_WAVES: ClassVar[tuple[_AnalysisWave, ...]] = (
        # Wave 1 — reads: i1 only
        (("i2", I2_WAVE_A), ("i3", TIER_I3), ("smc", SMC_WAVE_A)),
        # Wave 2 — reads: i1, i3
        (("i2", I2_WAVE_B), ("smc", SMC_WAVE_B), ("i4", I4_WAVE_A)),
        # Wave 3 — reads: i1, i2, i3, i4 (partial), smc (partial)
        (("i4", I4_WAVE_B), ("i5", TIER_I5)),
        # Wave 4 — reads: i1, i2, i3, i4, i5, smc (all prior tiers)
        (("i6", TIER_I6),),
    )

    def __init__(
        self,
        thread_pool: ThreadPoolExecutor,
        plugin_cache: dict,
        instrument_map: dict,
        circuit_breakers: dict,
        observer: PluginObserver | NoOpPluginObserver | None = None,
    ) -> None:
        self._thread_pool = thread_pool
        self._plugin_cache = plugin_cache
        self._instrument_map = instrument_map
        self._plugin_circuit_breakers: dict[str, CircuitBreaker] = dict(circuit_breakers)
        self._plugin_call_counts: dict = {}
        self._logger = structlog.get_logger(__name__)
        self._observer: NoOpPluginObserver = (
            observer if observer is not None else NoOpPluginObserver()
        )

        # D-12 tier deadline carry-forward cache.
        # Keyed by (tier_key, symbol, tf) -> last successfully completed tier output.
        # Used by run_tier: on deadline miss, non-stateful plugins reuse this cache;
        # stateful plugins log WARNING and run regardless.
        self._last_tier_outputs: dict[tuple[str, str, str], dict] = {}

        # OTel metric owned by executor (D-16): skipped plugin counter
        self._plugin_skipped_total = counter(
            "intelligence_pipeline_plugin_skipped_total",
            "Plugin executions skipped due to asset class mismatch",
        )

        # PERF-03 startup enforcement (D-07): hard crash if any incremental plugin
        # has not confirmed PERF-03 migration. This is a RuntimeError (not assert)
        # so it survives -O (optimized mode) in production.
        incremental_names = [
            name
            for name, p in self._plugin_cache.items()
            if getattr(p, "supports_incremental", False)
        ]
        incomplete = [
            name
            for name in incremental_names
            if not getattr(self._plugin_cache.get(name), "_state_migration_complete", False)
        ]
        if incomplete:
            raise RuntimeError(
                f"PERF-03 migration incomplete for plugins: {incomplete}. "
                f"Set _state_migration_complete = True on each plugin after auditing "
                f"that compute_next() correctly uses the state= parameter."
            )

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def circuit_breakers(self) -> dict[str, CircuitBreaker]:
        """Read-only view of per-plugin circuit breakers (Phase 108)."""
        return self._plugin_circuit_breakers

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Shut down the thread pool. Called by orchestrator.stop()."""
        self._thread_pool.shutdown(wait=True)

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _get_plugin_cb(self, plugin_name: str) -> CircuitBreaker:
        """Get or create a CircuitBreaker for the named plugin (lazy-init).

        Uses _SHADOW_CB_DEFAULTS so any plugin discovered post-deploy gets the same
        mode (shadow or live) as plugins pre-populated at startup.
        Set PLUGIN_CB_ENABLED=1 to enable live circuit breaking.
        """
        cb = self._plugin_circuit_breakers.get(plugin_name)
        if cb is None:
            cb = CircuitBreaker(**_SHADOW_CB_DEFAULTS)
            self._plugin_circuit_breakers[plugin_name] = cb
        return cb

    # ------------------------------------------------------------------
    # Shadow state helper
    # ------------------------------------------------------------------

    def _is_shadow(self, plugin_name: str, shadow_cache: dict) -> bool:
        """Look up shadow state from the passed shadow_cache parameter.

        Returns False (live) if not enrolled.
        Reads from the passed parameter — never from self._* shadow attr (Pitfall 2 / D-07).
        """
        return shadow_cache.get(plugin_name, False)

    # ------------------------------------------------------------------
    # Result collection
    # ------------------------------------------------------------------

    def _collect_plugin_results(
        self,
        tasks: list[PluginTask],
        results: list,
        lock: threading.Lock,
        symbol: str,
        tf: str,
        log_prefix: str = "plugin",
    ) -> tuple[list[dict], dict]:
        """Collect results from parallel plugin execution.

        Returns (outputs, state_updates) tuple.

        outputs: list of successful dict outputs (exceptions logged and skipped).
        state_updates: dict keyed by (plugin_name, symbol, tf) -> state dict,
            matching PluginStateManager.update_batch contract (HIGH finding 1).
            State is popped from the output dict so callers receive clean dicts.

        Args:
            tasks: List of PluginTask objects
            results: List of results from asyncio.gather (may contain Exceptions)
            lock: Per-(symbol,tf) threading.Lock (passed in, not held)
            symbol: Symbol name for 3-tuple key construction
            tf: Timeframe name for 3-tuple key construction
            log_prefix: Prefix for log messages (e.g. "plugin" or "i7.plugin")
        """
        outputs: list[dict] = []
        state_updates: dict[tuple, dict] = {}

        for i, task in enumerate(tasks):
            out = results[i]
            tier = task.tier_key
            cb = self._get_plugin_cb(task.plugin_name)

            if isinstance(out, Exception):
                self._observer.record_error(task.plugin_name, tier, str(out))
                cb.record_failure()
                if cb.state == CircuitState.OPEN:
                    self._observer.record_circuit_breaker_change(task.plugin_name, "open")
                    self._logger.warning("plugin.circuit_breaker_opened", plugin=task.plugin_name)
                self._logger.warning(
                    f"{log_prefix}.error",
                    plugin=task.plugin_name,
                    tier=tier,
                    error=str(out),
                )
            elif isinstance(out, tuple) and len(out) == 2:
                result_dict, duration_ms = out
                used_incremental = getattr(task, "_used_incremental", False)
                self._observer.record_result(
                    task.plugin_name,
                    tier,
                    duration_ms,
                    used_incremental=used_incremental,
                    null_count=0,
                )
                if isinstance(result_dict, dict):
                    # Handle SMC-specific field renaming
                    if tier == "smc" and "trend_direction" in result_dict:
                        result_dict["smc_trend_direction"] = result_dict.pop("trend_direction")
                    result_dict["_tier_key"] = tier

                    # Extract state update (Pitfall 3: return, do not write externally)
                    if "_state" in result_dict:
                        with lock:
                            state_updates[(task.plugin_name, symbol, tf)] = result_dict.pop(
                                "_state"
                            )

                    prev_state = cb.state
                    cb.record_success()
                    if prev_state != CircuitState.CLOSED:
                        self._observer.record_circuit_breaker_change(task.plugin_name, "closed")
                        self._logger.info("plugin.circuit_breaker_closed", plugin=task.plugin_name)
                    outputs.append(result_dict)

        return outputs, state_updates

    # ------------------------------------------------------------------
    # I1 execution
    # ------------------------------------------------------------------

    async def run_i1(
        self,
        plugin_states: dict[str, dict],
        lock: threading.Lock,
        frames: dict,
        symbol: str,
        tf: str,
        shadow_cache: dict,
    ) -> tuple[dict, dict]:
        """Run all I1 plugins in parallel.

        Args:
            plugin_states: Dict keyed by plugin_name -> state dict (HIGH finding 1).
            lock: Per-(symbol,tf) threading.Lock.
            frames: Feature frames dict.
            symbol: Symbol name.
            tf: Timeframe.
            shadow_cache: Shadow enrollment cache (passed in, not held — Pitfall 2).

        Returns:
            (tier_outputs, state_updates) where state_updates is keyed by
            (plugin_name, symbol, tf) for PluginStateManager.update_batch.
        """
        result: dict[str, Any] = {}
        tasks: list[PluginTask] = []
        loop = asyncio.get_running_loop()

        df_main = frames.get("main")
        for plugin_name in TIER_I1:
            plugin = self._plugin_cache.get(plugin_name)
            if plugin is None:
                continue
            if should_skip_plugin(
                plugin,
                self._instrument_map.get(symbol),
                self._plugin_skipped_total,
                plugin_name,
            ):
                continue
            cb = self._get_plugin_cb(plugin_name)
            if not cb.allow_request():
                continue

            # Frame pre-validation: skip plugins whose min_lookback is not met.
            # Plugins may set allows_partial_output=True to opt out (e.g. session-boundary plugins).
            min_lb = getattr(plugin, "min_lookback", 0)
            allows_partial = getattr(plugin, "allows_partial_output", False)
            if not allows_partial and min_lb > 0 and (df_main is None or len(df_main) < min_lb):
                self._observer.record_warmup_skip(plugin_name, "I1")
                continue

            # PERF-03: state passed as parameter — no pre-dispatch plugin._state assignment.
            state = plugin_states.get(plugin_name, {})

            # D-13 fast-path branch: plugins with fast_path=True run synchronously in the
            # event loop via _fast_path_coroutine (no thread offload). Eligibility (D-13):
            # supports_incremental=False AND P99 latency < 100µs from 24h histogram.
            # No plugin sets fast_path=True in this plan — the branch is infrastructure only.
            if getattr(plugin, "fast_path", False):
                coroutine = _fast_path_coroutine(plugin, frames, state)
            else:
                coroutine = loop.run_in_executor(
                    self._thread_pool,
                    functools.partial(_timed_plugin_call, plugin, frames, state),
                )
            tasks.append(
                PluginTask(
                    coroutine=coroutine,
                    plugin_name=plugin_name,
                    state_key=(plugin_name, symbol, tf),
                    lock=lock,
                )
            )

        gather_results = await asyncio.gather(*[t.coroutine for t in tasks], return_exceptions=True)
        outputs, state_updates = self._collect_plugin_results(
            tasks, gather_results, lock, symbol, tf, log_prefix="plugin"
        )
        for output in outputs:
            # PERF-05: filter None and NaN at merge site so IntelligenceEvent
            # construction receives already-clean dicts (no comprehension needed).
            for k, v in output.items():
                if v is not None and not (isinstance(v, float) and math.isnan(v)):
                    result[k] = v

        return result, state_updates

    # ------------------------------------------------------------------
    # Single-tier execution
    # ------------------------------------------------------------------

    async def run_tier(
        self,
        tier_key: str,
        tier_plugins: tuple[str, ...],
        plugin_states: dict[str, dict],
        lock: threading.Lock,
        symbol: str,
        tf: str,
        frames: dict,
        loop: asyncio.AbstractEventLoop,
        shadow_cache: dict,
        tier_budget_ms: float | None = None,
    ) -> tuple[dict[str, Any], dict]:
        """Run one tier's plugins in parallel.

        Does NOT merge into frames — caller (_run_tiers) handles frame merging
        after each wave completes.

        Args:
            tier_budget_ms: Optional per-tier deadline in milliseconds (D-12).
                On a deadline miss:
                - Non-stateful plugins (supports_incremental=False): carry forward
                  previous-bar output from self._last_tier_outputs.
                - Stateful plugins (supports_incremental=True): run anyway; log WARNING.
                When None, no deadline enforcement is applied.

        Returns (tier_outputs, state_updates) keyed by (plugin_name, symbol, tf).
        """
        tasks: list[PluginTask] = []
        df_main_tier = frames.get("main")
        # Classify plugins in this tier by stateful vs non-stateful for deadline logic
        stateful_plugins: set[str] = set()
        for plugin_name in tier_plugins:
            plugin = self._plugin_cache.get(plugin_name)
            if plugin is not None and getattr(plugin, "supports_incremental", False):
                stateful_plugins.add(plugin_name)

        for plugin_name in tier_plugins:
            plugin = self._plugin_cache.get(plugin_name)
            if plugin is None:
                continue
            if should_skip_plugin(
                plugin,
                self._instrument_map.get(symbol),
                self._plugin_skipped_total,
                plugin_name,
            ):
                continue
            cb = self._get_plugin_cb(plugin_name)
            if not cb.allow_request():
                continue

            # Frame pre-validation: skip plugins whose min_lookback is not met.
            min_lb = getattr(plugin, "min_lookback", 0)
            allows_partial = getattr(plugin, "allows_partial_output", False)
            if (
                not allows_partial
                and min_lb > 0
                and (df_main_tier is None or len(df_main_tier) < min_lb)
            ):
                self._observer.record_warmup_skip(plugin_name, tier_key)
                continue

            # PERF-03: state passed as parameter — no pre-dispatch plugin._state assignment.
            state = plugin_states.get(plugin_name, {})

            # D-13 fast-path branch: run synchronously in event loop when fast_path=True.
            # See eligibility gate in run_i1 comment. No plugin sets fast_path=True here.
            if getattr(plugin, "fast_path", False):
                coroutine = _fast_path_coroutine(plugin, frames, state)
            else:
                coroutine = loop.run_in_executor(
                    self._thread_pool,
                    functools.partial(_timed_plugin_call, plugin, frames, state),
                )
            tasks.append(
                PluginTask(
                    coroutine=coroutine,
                    plugin_name=plugin_name,
                    tier_key=tier_key,
                    state_key=(plugin_name, symbol, tf),
                    lock=lock,
                )
            )

        if not tasks:
            return {}, {}

        _tier_t0 = time.perf_counter()
        gather_results = await asyncio.gather(*[t.coroutine for t in tasks], return_exceptions=True)
        _tier_duration_ms = (time.perf_counter() - _tier_t0) * 1000

        outputs, state_updates = self._collect_plugin_results(
            tasks, gather_results, lock, symbol, tf, log_prefix="plugin"
        )

        tier_output: dict[str, Any] = {}
        for output in outputs:
            output.pop("_tier_key", None)
            # PERF-05: filter None and NaN at merge site so IntelligenceEvent
            # construction receives already-clean dicts (no comprehension needed).
            for k, v in output.items():
                if v is not None and not (isinstance(v, float) and math.isnan(v)):
                    tier_output[k] = v

        # D-12 tier deadline budget enforcement
        if tier_budget_ms is not None and _tier_duration_ms > tier_budget_ms:
            cf_key = (tier_key, symbol, tf)
            cached = self._last_tier_outputs.get(cf_key)
            if stateful_plugins:
                # Stateful tier: run anyway, emit WARNING per D-12
                self._logger.warning(
                    "tier_budget.miss.stateful_ran",
                    tier=tier_key,
                    symbol=symbol,
                    tf=tf,
                    duration_ms=round(_tier_duration_ms, 1),
                    budget_ms=tier_budget_ms,
                    stateful_plugins=sorted(stateful_plugins),
                )
            elif cached:
                # Non-stateful: carry forward previous-bar output
                self._logger.debug(
                    "tier_budget.miss.carry_forward",
                    tier=tier_key,
                    symbol=symbol,
                    tf=tf,
                    duration_ms=round(_tier_duration_ms, 1),
                    budget_ms=tier_budget_ms,
                )
                return cached, {}
        else:
            # Under budget: update carry-forward cache
            self._last_tier_outputs[(tier_key, symbol, tf)] = dict(tier_output)

        return tier_output, state_updates

    # ------------------------------------------------------------------
    # Multi-wave (I2-I6) execution
    # ------------------------------------------------------------------

    async def run_tiers(
        self,
        plugin_states: dict[str, dict],
        lock: threading.Lock,
        bar: Any,
        symbol: str,
        tf: str,
        frames: dict,
        shadow_cache: dict,
        tier_budget_ms: dict[str, float] | None = None,
    ) -> tuple[dict, dict]:
        """Run I2-I6 in waves — parallel within each wave, sequential between.

        Wave 1: [I2-A + I3 + SMC-A] — independent, need I1 only
        Wave 2: [I2-B + SMC-B + I4-A] — I4 now has I3 data
        Wave 3: [I4-B + I5] — kalman after garch; I5 reads I1-I4
        Wave 4: [I6] — cross-timeframe confluence

        Accumulates state_updates across all tiers; orchestrator writes once via
        PluginStateManager.update_batch(state_updates).

        Args:
            tier_budget_ms: Optional dict of per-tier deadlines in ms (D-12).
                            Passed through to each run_tier call.

        Returns:
            (tiered, state_updates) where:
            - tiered: dict[tier_key, outputs] for IntelligenceEvent construction
            - state_updates: merged dict keyed by (plugin_name, symbol, tf)
        """
        loop = asyncio.get_running_loop()
        tiered: dict[str, dict] = {}
        all_state_updates: dict[tuple, dict] = {}

        async def _timed_tier(tier_key: str, tier_plugins: tuple) -> tuple:
            _t0 = time.perf_counter()
            result = await self.run_tier(
                tier_key,
                tier_plugins,
                plugin_states,
                lock,
                symbol,
                tf,
                frames,
                loop,
                shadow_cache,
                tier_budget_ms=tier_budget_ms.get(tier_key) if tier_budget_ms else None,
            )
            _TIER_LATENCY_MS.record((time.perf_counter() - _t0) * 1000, {"tier": tier_key})
            return result

        for wave in self._ANALYSIS_WAVES:
            coros = [_timed_tier(tier_key, tier_plugins) for tier_key, tier_plugins in wave]
            wave_results = await asyncio.gather(*coros, return_exceptions=True)

            for (tier_key, _), wave_result in zip(wave, wave_results, strict=True):
                if isinstance(wave_result, Exception):
                    self._logger.error("wave.tier_error", tier=tier_key, error=str(wave_result))
                    tiered.setdefault(tier_key, {})
                    continue

                tier_output, state_updates = wave_result
                # Merge state updates from this tier
                all_state_updates.update(state_updates)

                if tier_key in tiered:
                    tiered[tier_key].update(tier_output)
                else:
                    tiered[tier_key] = tier_output
                frames[tier_key] = tiered[tier_key]
                FEATURES_COMPUTED_TOTAL.add(1, {"tier": tier_key})

        return tiered, all_state_updates

    # ------------------------------------------------------------------
    # I7 plugin execution
    # ------------------------------------------------------------------

    async def run_i7_plugins(
        self,
        plugin_states: dict[str, dict],
        lock: threading.Lock,
        bar: Any,
        symbol: str,
        tf: str,
        plugin_input: dict,
        shadow_cache: dict,
    ) -> tuple[list[PluginTask], list[dict], dict]:
        """Run all I7 plugins in parallel.

        Extracts the I7-plugin-execution portion — runs TIER_I7 plugins and
        returns raw task/output pairs + state_updates. Signal pipeline stages
        (quality_gate, regime_gate, calibration, ranking) remain in the orchestrator
        until plan 05 (SignalProcessor).

        Returns:
            (tasks, outputs, state_updates) where:
            - tasks: list of PluginTask (for plugin_name/bar access in signal processing)
            - outputs: list of output dicts from successful plugins
            - state_updates: dict keyed by (plugin_name, symbol, tf)
        """
        tasks: list[PluginTask] = []
        loop = asyncio.get_running_loop()
        df_main_i7 = plugin_input.get("main")

        for plugin_name in TIER_I7:
            plugin = self._plugin_cache.get(plugin_name)
            if plugin is None:
                continue
            if should_skip_plugin(
                plugin,
                self._instrument_map.get(symbol),
                self._plugin_skipped_total,
                plugin_name,
            ):
                continue
            cb = self._get_plugin_cb(plugin_name)
            if not cb.allow_request():
                continue

            # Frame pre-validation: skip plugins whose min_lookback is not met.
            min_lb = getattr(plugin, "min_lookback", 0)
            allows_partial = getattr(plugin, "allows_partial_output", False)
            if (
                not allows_partial
                and min_lb > 0
                and (df_main_i7 is None or len(df_main_i7) < min_lb)
            ):
                self._observer.record_warmup_skip(plugin_name, "i7")
                continue

            # PERF-03: state passed as parameter — no pre-dispatch plugin._state assignment.
            state = plugin_states.get(plugin_name, {})

            tasks.append(
                PluginTask(
                    coroutine=loop.run_in_executor(
                        self._thread_pool,
                        functools.partial(_timed_plugin_call, plugin, plugin_input, state),
                    ),
                    plugin_name=plugin_name,
                    tier_key="i7",
                    state_key=(plugin_name, symbol, tf),
                    lock=lock,
                    bar=bar,
                )
            )

        gather_results = await asyncio.gather(*[t.coroutine for t in tasks], return_exceptions=True)
        outputs, state_updates = self._collect_plugin_results(
            tasks, gather_results, lock, symbol, tf, log_prefix="i7.plugin"
        )

        # Keep tasks aligned with outputs: only include tasks whose result was not an Exception.
        # _collect_plugin_results skips exceptions, so len(outputs) <= len(tasks).
        # zip(tasks, outputs) would silently misalign plugin identity on any exception.
        successful_tasks = [
            t for t, r in zip(tasks, gather_results) if not isinstance(r, Exception)
        ]
        return successful_tasks, outputs, state_updates

    # ------------------------------------------------------------------
    # I7 completion (D-20): consolidated 52-line I7 setup block
    # ------------------------------------------------------------------

    async def run_i7_complete(
        self,
        intel_event: Any,
        bar: Any,
        cache_snapshot: CacheSnapshot,
        plugin_states: dict,
        lock: threading.Lock,
        *,
        main_df: Any,
    ) -> list[dict]:
        """Consolidate I7 feature build, plugin execution, and signal post-processing.

        D-15: PluginExecutor MUST NOT hold a PluginStateManager reference.
        Caller pre-fetches plugin_states and lock and passes them as parameters.

        D-20: internally calls build_flat_features once, assembles plugin_input,
        calls run_i7_plugins, and post-processes each signal dict:
          - Sets setup_plugin, symbol, tf from PluginTask and bar.
          - Sets regime_type via self._plugin_cache (no private cross-class access).

        Does NOT apply alpha decay — that is SignalProcessor.process() responsibility (D-21).

        Args:
            intel_event: Typed IntelligenceEvent from FeaturePipelineExecutor.
            bar: BarMessage for symbol, tf, bar metadata.
            cache_snapshot: Per-bar CacheSnapshot (passed to plugin_input).
            plugin_states: Pre-fetched per-plugin state dict (from PluginStateManager).
            lock: Per-(symbol, tf) threading.Lock (from PluginStateManager).
            main_df: pandas DataFrame for this (symbol, tf) — built once by FPE (D-26).

        Returns:
            list[dict]: Post-processed raw signals with direction != 0.
        """
        from src.intelligence.pipeline.feature_flattening import (  # noqa: PLC0415
            build_flat_features,
        )

        symbol = bar.symbol
        tf = bar.tf

        features = build_flat_features(intel_event)

        plugin_input = {
            "main": main_df,
            "features": features,
            "__symbol__": symbol,
            "symbol": symbol,
            "__timeframe__": tf,
            "timeframe": tf,
            "__instrument__": self._instrument_map.get(symbol),
            "intel_event": intel_event,
            "cache_snapshot": cache_snapshot,
        }

        # Phase 112-04 migrated all I7 plugins to read tier sub-dicts
        # (frames.get("i1"), frames.get("smc"), etc.) instead of the flat
        # frames["features"] dict. Provide each tier's model_dump() so
        # plugins can merge features from their expected keys.
        for tier_key in ("i1", "i2", "i3", "i4", "i5", "smc", "i6"):
            sub = getattr(intel_event, tier_key, None)
            if sub is not None:
                plugin_input[tier_key] = {
                    k: v for k, v in sub.model_dump().items() if v is not None
                }

        tasks, outputs, sig_state_updates = await self.run_i7_plugins(
            plugin_states,
            lock,
            bar,
            symbol,
            tf,
            plugin_input,
            shadow_cache=cache_snapshot.shadow_cache,
        )

        # D-15: PluginExecutor cannot hold a PluginStateManager reference.
        # State updates are stored on _last_i7_state_updates so the orchestrator
        # can retrieve and write back via update_batch without this class knowing
        # about PluginStateManager.
        self._last_i7_state_updates: dict = sig_state_updates

        raw_signals: list[dict] = []
        for task, output in zip(tasks, outputs, strict=False):
            output.pop("_tier_key", None)
            if output.get("direction", 0) != 0:
                sig = output
                sig["setup_plugin"] = task.plugin_name
                sig["symbol"] = symbol
                sig["tf"] = tf
                # regime_type looked up locally — no cross-class private access (D-20)
                plugin_inst = self._plugin_cache.get(task.plugin_name)
                sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")
                sig["is_shadow"] = self._is_shadow(task.plugin_name, cache_snapshot.shadow_cache)
                result = validate_signal(sig)
                if not result:
                    missing = REQUIRED_SIGNAL_FIELDS - set(sig.keys())
                    self._logger.error(
                        "executor.schema_violation",
                        plugin=task.plugin_name,
                        missing_fields=sorted(missing),
                        reason=result.reason,
                    )
                    continue
                sig["signal_id"] = make_signal_id(
                    symbol=symbol,
                    feature_ts_ns=int(bar.ts.timestamp() * 1e9),
                    feature_tf=tf,
                    open_=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    setup_plugin=task.plugin_name,
                    direction=int(sig.get("direction", 0)),
                )
                raw_signals.append(sig)

        return raw_signals

    # ------------------------------------------------------------------
    # HMM parameter reload (SIGUSR1)
    # ------------------------------------------------------------------

    def reload_hmm_parameters(self) -> list[str]:
        """Reload parameters on all HMM instances in TIER_SMC (SIGUSR1 trigger).

        Iterates TIER_SMC filtered to HMMRegimePlugin instances, calls
        reload_parameters() on each. Per-TF failures are caught and logged;
        a single TF failure does not abort the remaining reloads.

        Returns list of reloaded plugin names.
        """
        from src.intelligence.features.smc_context.hmm_regime import (
            HMMRegimePlugin,  # noqa: PLC0415
        )

        reloaded_names: list[str] = []
        for plugin_name in TIER_SMC:
            plugin = self._plugin_cache.get(plugin_name)
            if not isinstance(plugin, HMMRegimePlugin):
                continue
            try:
                plugin.reload_parameters()
                reloaded_names.append(plugin_name)
            except Exception as error:
                self._logger.warning(
                    "intelligence_pipeline.hmm_reload_tf_failed",
                    plugin_name=plugin_name,
                    error=str(error),
                )
        return reloaded_names
