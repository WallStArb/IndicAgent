"""FeaturePipelineExecutor — 6th DAG node: I1-I6 compute + IntelligenceEvent construction.

Extracted from IntelligencePipeline._run_i1_to_i6 as part of Phase 089
DAG decomposition (D-18). Owns all I1-I6 compute and dataframe construction; the
orchestrator calls self._feature_pipeline.run(bar, cache_snapshot) and receives a
FeaturePipelineResult without knowing any of the intermediate computation.

Design contract:
- Receives injected services (bar_history, executor, state_mgr, instrument_map, vix_symbol)
  via constructor — same pattern as SignalProcessor.
- Owns carry-forward state (_prev_i1_features, _last_events) migrated from orchestrator.
- Reads stream caches exclusively from CacheSnapshot fields — never self._cross_asset_cache
  etc. (D-19).
- Returns FeaturePipelineResult(event, tiered, main_df, hmm_regime); main_df is passed
  directly to run_i7_complete to avoid a second to_dataframe() call (D-26).
- Does NOT reference CacheManager or OutputQueue — no lateral imports.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from opentelemetry import metrics as otel_metrics
from pydantic import ValidationError

from src.config.settings import Settings
from src.core.bar_history import BarHistory
from src.intelligence.context.vix_context import compute_vix_context
from src.intelligence.cross_asset_features import resolve_eq_index_base
from src.intelligence.pipeline.executor import PluginExecutor
from src.intelligence.pipeline.feature_flattening import build_flat_features
from src.intelligence.pipeline.signal_processor import CacheSnapshot
from src.intelligence.pipeline.state_manager import PluginStateManager
from src.intelligence.schemas import (
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    IntelligenceEvent,
    OHLCVBar,
    SMCContext,
)

if TYPE_CHECKING:
    from src.core.schemas.bar_message import BarMessage

# ---------------------------------------------------------------------------
# Per-tier latency histogram (106-04)
# ---------------------------------------------------------------------------

# Local meter ref to avoid circular import with src.observability.metrics; OTel deduplicates by name.
_meter = otel_metrics.get_meter("indicagent")
INTELLIGENCE_PIPELINE_TIER_LATENCY_MS = _meter.create_histogram(
    "intelligence_pipeline_tier_latency_ms",
    description="Per-tier execution latency in milliseconds",
)

# Standard timeframes for cross-tf frame construction (mirrored from orchestrator)
_STANDARD_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")

# VIX timeframe for regime conditioning (mirrored from orchestrator)
VIX_REGIME_TF: str = "1h"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class FeaturePipelineResult:
    """Typed result from FeaturePipelineExecutor.run().

    Carries all outputs needed by the orchestrator to proceed with I7 and
    signal processing — no orchestrator code needed to inspect or rebuild these.

    Fields:
        event: Typed IntelligenceEvent or None if I1 not yet warm.
        tiered: Per-tier output dicts or None if tiers returned nothing.
        main_df: pandas DataFrame for (symbol, tf) — built once here and reused
                 by run_i7_complete to avoid a duplicate to_dataframe() call (D-26).
        hmm_regime: HMM regime integer from SMC tier output; None before first bar.
        flat_features: Pre-computed flat feature dict from build_flat_features(event).
                       Computed once per bar in FeaturePipelineExecutor.run() and
                       consumed by SignalProcessor — avoids per-signal model_dump() (3-E).
                       Empty dict when event is None.
    """

    event: IntelligenceEvent | None
    tiered: dict | None
    main_df: Any  # pandas DataFrame; typed as Any to avoid hard pandas import at top
    hmm_regime: int | None
    flat_features: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# FeaturePipelineExecutor
# ---------------------------------------------------------------------------


class FeaturePipelineExecutor:
    """I1-I6 compute DAG node.

    Owns frame assembly (bar_history reads, cross-tf event flattening, instrument context,
    VIX context, HTF intel, prev I1 features, cross_asset/macro from CacheSnapshot),
    I1 execution via PluginExecutor, tier execution (I2-I6) via PluginExecutor,
    IntelligenceEvent construction, and _prev_i1_features + _last_events carry-forward state.

    Does NOT hold a CacheManager reference. All stream-cache reads go through CacheSnapshot
    (D-19). Does NOT output to Kafka or write to DB.
    """

    def __init__(
        self,
        bar_history: BarHistory,
        executor: PluginExecutor,
        state_mgr: PluginStateManager,
        instrument_map: dict,
        vix_symbol: str | None,
        settings: Settings | None = None,
    ) -> None:
        self._bar_history = bar_history
        self._executor = executor
        self._state_mgr = state_mgr
        self._instrument_map = instrument_map
        self._vix_symbol = vix_symbol
        self._settings = settings
        # Carry-forward state — migrated from orchestrator __init__ lines 163-165 (D-18)
        self._prev_i1_features: dict = {}  # keyed by f"{symbol}:{tf}"
        self._last_events: dict = {}  # keyed by f"{symbol}:{tf}" or f"{symbol}:{tf}_i1"
        # D-12 I1 deadline carry-forward cache: keyed by (symbol, tf)
        # Used when I1 tier misses its TIER_BUDGET_MS deadline.
        # Note: I2-I6 carry-forward lives in PluginExecutor._last_tier_outputs.
        self._last_i1_outputs: dict[tuple[str, str], dict] = {}
        self._logger = structlog.get_logger(__name__)

    async def run(
        self,
        bar: BarMessage,
        cache_snapshot: CacheSnapshot,
        *,
        gap: bool = False,
    ) -> FeaturePipelineResult:
        """Run I1 through I6 and return FeaturePipelineResult.

        This is the extracted body of _run_i1_to_i6 (orchestrator lines 628-745).
        Reads stream caches from cache_snapshot — never from self._ dicts (D-19).

        Args:
            bar: Incoming BarMessage.
            cache_snapshot: Per-bar CacheSnapshot from CacheManager.snapshot().
            gap: PERF-09 — gap flag passed explicitly instead of via bar.model_copy().
                 Placed in frames["__gap__"] for plugins that need it.

        Returns:
            FeaturePipelineResult with event=None if I1 not warm or tier returned nothing.
        """
        symbol, tf = bar.symbol, bar.tf
        key = f"{symbol}:{tf}"

        main_df = self._bar_history.to_dataframe(symbol, tf)
        frames: dict[str, Any] = {
            "main": main_df,
            "__symbol__": symbol,
            "__timeframe__": tf,
            # PERF-09: gap flag as explicit parameter — no bar.model_copy() needed.
            "__gap__": gap,
        }

        # Cross-tf frames (orchestrator lines 638-655)
        for other_tf in _STANDARD_TFS:
            if other_tf == tf:
                continue
            other_deque = self._bar_history.get(symbol, other_tf)
            if len(other_deque) >= 50:
                frames[f"tf_{other_tf}"] = self._bar_history.to_dataframe(symbol, other_tf)
            cached_evt = self._last_events.get(f"{symbol}:{other_tf}")
            if cached_evt:
                intel_dict = cached_evt.model_dump()
                flattened = {}
                for tier_name, tier_data in intel_dict.items():
                    if tier_name in ("i1", "i2", "i3", "i4", "i5", "smc", "i6") and isinstance(
                        tier_data, dict
                    ):
                        flattened.update(tier_data)
                    else:
                        flattened[tier_name] = tier_data
                frames[f"intel_{other_tf}"] = flattened

        # Instrument context (orchestrator lines 657-659)
        instrument = self._instrument_map.get(symbol)
        if instrument:
            frames["__instrument__"] = instrument

        # Prev I1 features for incremental plugins
        frames["prev_features"] = self._prev_i1_features.get(key, {})

        # Stream caches from CacheSnapshot — not self._cross_asset_cache etc. (D-19)
        if resolve_eq_index_base(symbol) is not None:
            cross_asset = {**cache_snapshot.cross_asset_data.get(tf, {"ready": False})}
            cross_asset.update(cache_snapshot.macro_data.get(tf, {}))
            frames["cross_asset"] = cross_asset
            cross_asset_5m = {**cache_snapshot.cross_asset_data.get("5m", {"ready": False})}
            cross_asset_5m.update(cache_snapshot.macro_data.get("5m", {}))
            frames["cross_asset_5m"] = cross_asset_5m

        # VIX context (orchestrator lines 671-675)
        if self._vix_symbol:
            vix_deque = self._bar_history.get(self._vix_symbol, VIX_REGIME_TF)
            frames["vix"] = compute_vix_context(vix_deque)
        else:
            frames["vix"] = {"ready": False}

        # HTF intel from CacheSnapshot (D-19)
        htf_cache = cache_snapshot.htf_intel.get(tf)
        if htf_cache:
            frames["htf_intel"] = htf_cache

        # Plugin state fetch for I1 + tiers (orchestrator lines 681-682)
        plugin_states = self._state_mgr.get_all_states_for(symbol, tf)
        lock = self._state_mgr.get_lock((symbol, tf))

        # I1 execution (orchestrator lines 684-696)
        _i1_t0 = time.perf_counter()
        i1_result, i1_state_updates = await self._executor.run_i1(
            plugin_states,
            lock,
            frames,
            symbol,
            tf,
            shadow_cache=cache_snapshot.shadow_cache,
        )
        _i1_duration_ms = (time.perf_counter() - _i1_t0) * 1000
        INTELLIGENCE_PIPELINE_TIER_LATENCY_MS.record(_i1_duration_ms, {"tier": "i1"})
        # D-12 tier deadline budget check for I1.
        # I1 contains only non-stateful indicator plugins (supports_incremental=False),
        # so on a deadline miss we carry forward the previous bar's output.
        _i1_budget = self._settings.tier_budget_ms.get("i1", 50.0) if self._settings else 50.0
        if _i1_duration_ms > _i1_budget:
            _cf_key = (symbol, tf)
            _cached = self._last_i1_outputs.get(_cf_key)
            if _cached:
                self._logger.debug(
                    "tier_budget.miss.carry_forward",
                    tier="i1",
                    symbol=symbol,
                    tf=tf,
                    duration_ms=round(_i1_duration_ms, 1),
                    budget_ms=_i1_budget,
                )
                i1_result = _cached
        else:
            self._last_i1_outputs[(symbol, tf)] = dict(i1_result)
        if i1_state_updates:
            self._state_mgr.update_batch(i1_state_updates)
        frames["i1"] = dict(i1_result)
        self._prev_i1_features[key] = dict(i1_result)
        self._last_events[key + "_i1"] = i1_result

        # Tier execution I2-I6 (orchestrator lines 698-710)
        _tiers_t0 = time.perf_counter()
        _tier_budgets = self._settings.tier_budget_ms if self._settings else None
        tiered, tier_state_updates = await self._executor.run_tiers(
            plugin_states,
            lock,
            bar,
            symbol,
            tf,
            frames,
            shadow_cache=cache_snapshot.shadow_cache,
            tier_budget_ms=_tier_budgets,
        )
        INTELLIGENCE_PIPELINE_TIER_LATENCY_MS.record(
            (time.perf_counter() - _tiers_t0) * 1000, {"tier": "i2_i6"}
        )
        if tier_state_updates:
            self._state_mgr.update_batch(tier_state_updates)
        if not tiered:
            return FeaturePipelineResult(event=None, tiered=None, main_df=main_df, hmm_regime=None)

        # IntelligenceEvent construction (orchestrator lines 715-745)
        # PERF-05: None filtering now happens at the run_i1 / run_tier merge site in
        # executor.py, so i1_result and tiered tier dicts are already None-free here.
        # No comprehensions needed — pass tier dicts directly to tier constructors.
        try:
            event = IntelligenceEvent(
                ts=bar.ts,
                symbol=symbol,
                tf=tf,
                bar=OHLCVBar(o=bar.open, h=bar.high, l=bar.low, c=bar.close, v=bar.volume),
                i1=I1Indicators(**i1_result),
                i2=I2Events(**tiered.get("i2", {})),
                i3=I3Structure(**tiered.get("i3", {})),
                i4=I4Context(**tiered.get("i4", {})),
                i5=I5Patterns(**tiered.get("i5", {})),
                smc=SMCContext(**tiered.get("smc", {})),
                i6=I6Confluence(**tiered.get("i6", {})),
                source="live",
                session_type=bar.session_type,
                pipeline_latency_ms=0.0,  # orchestrator measures and sets this separately
                computed_at=datetime.now(UTC),
                bar_id=bar.bar_id,
            )
        except ValidationError as error:
            self._logger.error(
                "FeaturePipelineExecutor.IntelligenceEvent validation failed",
                symbol=symbol,
                tf=tf,
                error=str(error),
            )
            return FeaturePipelineResult(event=None, tiered=None, main_df=main_df, hmm_regime=None)

        # Persist event for cross-tf context reads on subsequent bars
        self._last_events[key] = event

        # 3-E: Precompute flat feature dict once per bar — avoids per-signal model_dump()
        # in SignalProcessor.process(). Both signal_processor and feature_pipeline_executor
        # import build_flat_features from feature_flattening (neutral module, no circular dep).
        flat_features = build_flat_features(event)

        # Inject asset_class into flat_features for per-asset-class APR dispatch in
        # trade_framer._min_zone_width_atr(). Uses Instrument.asset_class.value from
        # instrument_map — no hardcoded symbol lists; adapts automatically to futures rolls
        # and new contracts. Falls back to None (trade_framer uses default threshold).
        if instrument is not None:
            flat_features["asset_class"] = instrument.asset_class.value

        # Extract HMM regime from smc tier output for CacheManager (D-25)
        # hmm_regime lives in SMCContext (produced by smc_HMMRegime plugin, tier key "smc")
        hmm_val = frames.get("smc", {}).get("hmm_regime")
        hmm_regime = int(hmm_val) if isinstance(hmm_val, (int, float)) else None

        return FeaturePipelineResult(
            event=event,
            tiered=tiered,
            main_df=main_df,
            hmm_regime=hmm_regime,
            flat_features=flat_features,
        )
