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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from src.intelligence.pipeline.signal_processor import CacheSnapshot

import structlog

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
from src.observability.circuit_breaker import CircuitBreaker, CircuitState
from src.observability.metrics import (
    CIRCUIT_BREAKER_STATE,
    FEATURES_COMPUTED_TOTAL,
    PLUGIN_DURATION_MS,
    PLUGIN_ERRORS_TOTAL,
    counter,
)

# ---------------------------------------------------------------------------
# Type aliases (shared with orchestrator)
# ---------------------------------------------------------------------------

type _WaveTierDef = tuple[str, tuple[str, ...]]
type _AnalysisWave = tuple[_WaveTierDef, ...]


# ---------------------------------------------------------------------------
# PluginTask — container for parallel plugin execution metadata
# ---------------------------------------------------------------------------


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


def _timed_plugin_call(plugin, frames):
    """Wrapper that returns (result, duration_ms) tuple for per-plugin timing.

    Uses incremental compute_next() when the plugin supports it and has state,
    falling back to compute_full() otherwise.
    """
    t0 = time.perf_counter()
    if getattr(plugin, "supports_incremental", False) and plugin._state:
        result = plugin.compute_next(frames)
    else:
        result = plugin.compute_full(frames)
    duration_ms = (time.perf_counter() - t0) * 1000
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
    # Dependency analysis (violations resolved via sub-waves):
    #   Wave 1: I2-WaveA(8) + I3(8) + SMC-WaveA(10) — independent, need I1 only
    #   Wave 2: I2-WaveB(2) + SMC-WaveB(3) + I4-WaveA(11) — I4 now has I3 data
    #   Wave 3: I4-WaveB(1) + I5(16) — kalman after garch; I5 reads I1-I4
    #   Wave 4: I6(1) — cross-timeframe confluence
    _ANALYSIS_WAVES: ClassVar[tuple[_AnalysisWave, ...]] = (
        (("i2", I2_WAVE_A), ("i3", TIER_I3), ("smc", SMC_WAVE_A)),
        (("i2", I2_WAVE_B), ("smc", SMC_WAVE_B), ("i4", I4_WAVE_A)),
        (("i4", I4_WAVE_B), ("i5", TIER_I5)),
        (("i6", TIER_I6),),
    )

    def __init__(
        self,
        thread_pool: ThreadPoolExecutor,
        plugin_cache: dict,
        instrument_map: dict,
        circuit_breakers: dict,
    ) -> None:
        self._thread_pool = thread_pool
        self._plugin_cache = plugin_cache
        self._instrument_map = instrument_map
        self._plugin_circuit_breakers: dict[str, CircuitBreaker] = dict(circuit_breakers)
        self._plugin_call_counts: dict = {}
        self._logger = structlog.get_logger(__name__)

        # OTel metric owned by executor (D-16): skipped plugin counter
        self._plugin_skipped_total = counter(
            "intelligence_pipeline_plugin_skipped_total",
            "Plugin executions skipped due to asset class mismatch",
        )

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
        """Get or create a CircuitBreaker for the named plugin (lazy-init)."""
        cb = self._plugin_circuit_breakers.get(plugin_name)
        if cb is None:
            cb = CircuitBreaker(failure_threshold=3, timeout_sec=300)
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
                PLUGIN_ERRORS_TOTAL.add(1, {"plugin_name": task.plugin_name, "tier": tier})
                cb.record_failure()
                if cb.state == CircuitState.OPEN:
                    CIRCUIT_BREAKER_STATE.set(1, {"plugin_name": task.plugin_name})
                    self._logger.warning("plugin.circuit_breaker_opened", plugin=task.plugin_name)
                self._logger.warning(
                    f"{log_prefix}.error",
                    plugin=task.plugin_name,
                    tier=tier,
                    error=str(out),
                )
            elif isinstance(out, tuple) and len(out) == 2:
                result_dict, duration_ms = out
                PLUGIN_DURATION_MS.record(
                    duration_ms, {"plugin_name": task.plugin_name, "tier": tier}
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
                        CIRCUIT_BREAKER_STATE.set(0, {"plugin_name": task.plugin_name})
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

            # State injection: read from passed plugin_states (D-10)
            plugin._state = plugin_states.get(plugin_name, {})

            tasks.append(
                PluginTask(
                    coroutine=loop.run_in_executor(
                        self._thread_pool, _timed_plugin_call, plugin, frames
                    ),
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
            # PERF-05: filter None values at merge site so IntelligenceEvent
            # construction receives already-clean dicts (no comprehension needed).
            for k, v in output.items():
                if v is not None:
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
    ) -> tuple[dict[str, Any], dict]:
        """Run one tier's plugins in parallel.

        Does NOT merge into frames — caller (_run_tiers) handles frame merging
        after each wave completes.

        Returns (tier_outputs, state_updates) keyed by (plugin_name, symbol, tf).
        """
        tasks: list[PluginTask] = []
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

            # State injection: read from passed plugin_states (D-10)
            plugin._state = plugin_states.get(plugin_name, {})

            tasks.append(
                PluginTask(
                    coroutine=loop.run_in_executor(
                        self._thread_pool, _timed_plugin_call, plugin, frames
                    ),
                    plugin_name=plugin_name,
                    tier_key=tier_key,
                    state_key=(plugin_name, symbol, tf),
                    lock=lock,
                )
            )

        if not tasks:
            return {}, {}

        gather_results = await asyncio.gather(*[t.coroutine for t in tasks], return_exceptions=True)
        outputs, state_updates = self._collect_plugin_results(
            tasks, gather_results, lock, symbol, tf, log_prefix="plugin"
        )

        tier_output: dict[str, Any] = {}
        for output in outputs:
            output.pop("_tier_key", None)
            # PERF-05: filter None values at merge site so IntelligenceEvent
            # construction receives already-clean dicts (no comprehension needed).
            for k, v in output.items():
                if v is not None:
                    tier_output[k] = v

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
    ) -> tuple[dict, dict]:
        """Run I2-I6 in waves — parallel within each wave, sequential between.

        Wave 1: [I2-A + I3 + SMC-A] — independent, need I1 only
        Wave 2: [I2-B + SMC-B + I4-A] — I4 now has I3 data
        Wave 3: [I4-B + I5] — kalman after garch; I5 reads I1-I4
        Wave 4: [I6] — cross-timeframe confluence

        Accumulates state_updates across all tiers; orchestrator writes once via
        PluginStateManager.update_batch(state_updates).

        Returns:
            (tiered, state_updates) where:
            - tiered: dict[tier_key, outputs] for IntelligenceEvent construction
            - state_updates: merged dict keyed by (plugin_name, symbol, tf)
        """
        loop = asyncio.get_running_loop()
        tiered: dict[str, dict] = {}
        all_state_updates: dict[tuple, dict] = {}

        for wave in self._ANALYSIS_WAVES:
            coros = [
                self.run_tier(
                    tier_key,
                    tier_plugins,
                    plugin_states,
                    lock,
                    symbol,
                    tf,
                    frames,
                    loop,
                    shadow_cache,
                )
                for tier_key, tier_plugins in wave
            ]
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
                # Dual-write: keyed frames[tier_key] for typed tier access;
                # flat frames["features"] for plugins that use the legacy flat dict.
                features = frames.setdefault("features", {})
                features.update(tier_output)

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

            # State injection: read from passed plugin_states (D-10)
            plugin._state = plugin_states.get(plugin_name, {})

            tasks.append(
                PluginTask(
                    coroutine=loop.run_in_executor(
                        self._thread_pool, _timed_plugin_call, plugin, plugin_input
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

        return tasks, outputs, state_updates

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

        D-20: internally calls _build_features_from_event once, assembles plugin_input,
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
        from src.intelligence.pipeline.signal_processor import (  # noqa: PLC0415
            _build_features_from_event,
        )

        symbol = bar.symbol
        tf = bar.tf

        features = _build_features_from_event(intel_event)

        plugin_input = {
            "main": main_df,
            "features": features,
            "__symbol__": symbol,
            "__timeframe__": tf,
            "timeframe": tf,
            "__instrument__": self._instrument_map.get(symbol),
            "intel_event": intel_event,
            "cache_snapshot": cache_snapshot,
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
            except Exception as exc:
                self._logger.warning(
                    "intelligence_pipeline.hmm_reload_tf_failed",
                    plugin_name=plugin_name,
                    error=str(exc),
                )
        return reloaded_names
