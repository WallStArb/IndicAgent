"""SignalProcessor — I7 signal pipeline stages.

Owns the signal-pipeline-stage orchestration: CIS scoring, quality gate, regime gate,
calibration, ToD adjustment, ranking, winner selection, and DLQ preparation.

Receives cache values via CacheSnapshot per D-07 (no direct cache service reference).
Returns a structured SignalProcessorResult to the orchestrator (no direct enqueue).

HIGH finding 2: no direct reference to the cache service class.
HIGH finding 4: SignalProcessorResult carries all 4 output paths.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config.settings import Settings
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import TF_SECONDS
from src.intelligence.pipeline.calibrator import apply_calibration
from src.intelligence.pipeline.feature_flattening import (
    build_flat_features,
)
from src.intelligence.pipeline.quality_gate import apply_quality_gate
from src.intelligence.pipeline.ranker import rank_signals
from src.intelligence.pipeline.regime_gate import apply_regime_gate
from src.intelligence.pipeline.winner_selector import select_winner
from src.intelligence.trading.cis_scorer import CISScorer
from src.intelligence.trading.confidence_utils import MIN_CTF_SCORE
from src.intelligence.trading.signal_schema import (
    REQUIRED_PIPELINE_FIELDS,
)
from src.observability.metrics import (
    INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL,
    REGIME_GATE_SUPPRESSIONS_TOTAL,
    SIGNAL_PROCESSOR_DLQ_TOTAL,
    SIGNAL_PROCESSOR_GATE_REJECTIONS_TOTAL,
    SIGNAL_PROCESSOR_SIGNALS_EVALUATED_TOTAL,
    SIGNAL_PROCESSOR_WINNER_TOTAL,
    counter,
)

# ---------------------------------------------------------------------------
# Eastern Time for hour extraction
# ---------------------------------------------------------------------------

_ET = zoneinfo.ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Pipeline-layer annotation
# ---------------------------------------------------------------------------

# Surfaced ECL fields: subset of flat_features promoted to top-level indexed
# columns on signal_events for fast SQL queries without JSONB extraction.
# To add a new surfaced field:
#   (1) add to this tuple,
#   (2) add one extraction line in _annotate_signal() below,
#   (3) add a DB migration for the new column on signal_events.
# No plugin changes needed.
_SURFACED_ECL_FIELDS: tuple[str, ...] = (
    "ctf_score",
    "ctf_confirmed",  # derived from ctf_score, not read from flat_features
    "zone_friction_score",
    # future candidates: "exhaustion_score", "hmm_regime_weight", etc.
)


def _annotate_signal(sig: dict, flat_features: dict) -> None:
    """Pipeline-layer extrinsic annotation — applied to every I7 signal uniformly.

    Flat_features audit (Phase 126-06):
      PRESENT  — ctf_score + 17 CTF sub-scores (via I6Confluence sub-model in build_flat_features)
      PRESENT  — exhaustion_score, exhaustion_side, exhaustion_bars (via I2Events)
      PRESENT  — vix_z, vix_level, ftq_score, yield_curve_slope, corr_z (via I4Context)
      PRESENT  — zone_friction_score (via SMCContext, formalized this phase)
      ABSENT   — plugin-local factor_scores (plugin concern; stays in plugin bodies)

    Plugins are pattern detectors — they return intrinsic evidence only.
    This function is the single point where the full market context at emission
    time is attached to every signal. No plugin may call capture_signal_features().

    Extensibility: new tier outputs appear in context_features automatically
    (build_flat_features iterates all sub-models). New surfaced columns require
    only: add to _SURFACED_ECL_FIELDS + one extraction line + DB migration.
    """
    # Complete feature snapshot — the full I1-I6 state at signal emission time.
    # Stored as-is: build_flat_features() already filters None values.
    sig["context_features"] = flat_features

    # Surfaced ECL fields: derived from snapshot, promoted to indexed top-level columns.
    _ctf_raw = flat_features.get("ctf_score")
    ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
    sig["ctf_score"] = ctf_score
    sig["ctf_confirmed"] = (abs(ctf_score) >= MIN_CTF_SCORE) if ctf_score is not None else None
    sig["zone_friction_score"] = flat_features.get("zone_friction_score")


# Quality gate absent-feature defaults.
# 1.0 = neutral pass-through: when a feature is not yet computed for this bar
# (e.g. insufficient bars for Hurst, cold-start), treat as no degradation rather
# than penalizing. This is intentional — a missing feature is not evidence of
# poor quality; it is evidence of insufficient history.
_QUALITY_FEATURE_ABSENT: float = 1.0
_DRIFT_PENALTY_ABSENT: float = 1.0  # no penalty when symbol has no drift history

# Alpha decay half-life bars
# Note: _I1_ALIAS_MAP and build_flat_features are imported from
# feature_flattening (moved in Plan 05 to prevent circular import with
# feature_pipeline_executor.py). _I1_ALIAS_MAP is re-exported above for compat.
ALPHA_HALF_LIFE_BARS: dict[str, int] = {"1m": 10, "5m": 8, "15m": 8, "1h": 6}


# ---------------------------------------------------------------------------
# Module-level helpers (ported from god class lines 193-230)
# ---------------------------------------------------------------------------


def _apply_alpha_decay(sig: dict, tf: str, last_fire_state: dict | None) -> None:
    """QUAL-02: Apply exponential alpha decay to signal confidence in-place.

    Decays confidence by 0.5^(bars_since/half_life) — confidence halves every half_life
    fires since the last win. bars_since counts fires only, not elapsed bars, so silence
    does not penalize re-emergence.

    Invariant: bars_since >= 1 when called with non-None state (caller increments before
    this call, so the zero case is impossible in production).
    """
    if last_fire_state is None:
        return
    bars_since = last_fire_state.get("bars_since", 0)
    half_life = ALPHA_HALF_LIFE_BARS.get(tf, 6)
    multiplier = 0.5 ** (bars_since / half_life)
    sig["confidence"] = round(float(sig.get("confidence", 0.0)) * multiplier, 4)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheSnapshot:
    """Immutable per-bar view of cache values passed by orchestrator into
    SignalProcessor.process(). Decouples SignalProcessor from the cache service (D-07).
    """

    perf_weights: dict
    calibration_curves: dict
    drift_penalties: dict
    cis_weights: dict
    cis_weights_version: int
    # Stream-fed caches migrated from orchestrator (D-19) — default to empty dict
    # so existing call sites (before Task 6 wires them) remain backward compatible.
    cross_asset_data: dict = field(default_factory=dict)
    macro_data: dict = field(default_factory=dict)
    htf_intel: dict = field(default_factory=dict)
    # Shadow registry state for I7 plugin shadow routing (included here so
    # PluginExecutor.run_i7_complete has access without a CacheManager reference)
    shadow_cache: dict = field(default_factory=dict)


@dataclass
class SignalProcessorResult:
    """Structured per-bar result. Orchestrator routes each non-None payload to its topic.
    HIGH finding 4 — all 4 output paths represented.
    """

    success: bool
    signals_payload: dict | None = None  # routed to i7 signals topic by orchestrator
    dlq_payload: dict | None = None  # routed to signal DLQ topic by orchestrator
    winner_payload: dict | None = None  # routed to aggregated signals topic by orchestrator
    i7_result: dict | None = (
        None  # consumed by orchestrator._enqueue_intel_journal (god class line 1683)
    )


# ---------------------------------------------------------------------------
# SignalProcessor
# ---------------------------------------------------------------------------


class SignalProcessor:
    """I7 signal pipeline stage processor.

    Owns: CIS scoring, quality gate, regime gate, calibration, ToD adjustment,
    ranking, winner selection, DLQ preparation.

    Does NOT hold a direct cache service reference (HIGH finding 2).
    Receives cache values via CacheSnapshot passed into process().
    Returns SignalProcessorResult to orchestrator (no direct enqueue, Pitfall 8).
    """

    def __init__(
        self,
        cis_scorer: CISScorer,
        settings: Settings,
        transform_recorder: Any = None,
    ) -> None:
        self._cis_scorer = cis_scorer
        self._settings = settings
        self._transform_recorder = transform_recorder
        self._logger = structlog.get_logger(__name__)

        # Transient state (not checkpointed — checkpointed via get/restore methods)
        self._setup_last_fire: dict = {}
        # NOTE: CIS Kalman state is now owned by CISScorer (Design B migration).
        # self._kalman_state moved to self._cis_scorer._cis_kalman_state.
        self._last_synced_cis_version: int = 0

        # OTel metrics (D-16)
        self._signals_generated = counter(
            "intelligence_pipeline_signals_generated_total",
            "Raw signals generated by I7 plugins",
        )
        self._signals_selected = counter(
            "intelligence_pipeline_signals_selected_total",
            "Winner signals selected by aggregator",
        )
        self._signal_dlq_total = counter(
            "intelligence_pipeline_signal_dlq_total",
            "Bars dropped to DLQ due to CIS assertion failure",
        )

        # I7 config
        self._regime_prob_min: float = getattr(settings, "regime_prob_min", 0.7)
        self._regime_prob_soft_max: float = getattr(settings, "REGIME_PROB_SOFT_MAX", 0.55)
        self._regime_dur_min: int = getattr(settings, "regime_dur_min", 12)

    # ------------------------------------------------------------------
    # CIS sync (Pitfall 4 mediation)
    # ------------------------------------------------------------------

    def sync_cis_weights(self, weights: dict, version: int) -> None:
        """Sync CIS scorer weights when version changes.

        Called by orchestrator at the start of every bar (D-07 mediation of Pitfall 4).
        No-ops if version is unchanged.
        """
        if version != self._last_synced_cis_version and weights:
            self._cis_scorer.update_weights(weights, version)
            self._last_synced_cis_version = version

    # ------------------------------------------------------------------
    # Checkpoint cross-ownership accessors (Pitfall 5)
    # ------------------------------------------------------------------

    def get_kalman_state(self) -> dict:
        """Return defensive copy of CIS Kalman state for checkpoint (delegates to CISScorer)."""
        return self._cis_scorer.get_kalman_state()

    def restore_kalman_state(self, state: dict) -> None:
        """Restore CIS Kalman state from checkpoint (delegates to CISScorer)."""
        self._cis_scorer.restore_kalman_state(state)

    def get_setup_last_fire(self) -> dict:
        """Return defensive copy of setup_last_fire for checkpoint."""
        return dict(self._setup_last_fire)

    def restore_setup_last_fire(self, state: dict) -> None:
        """Restore setup_last_fire from checkpoint."""
        self._setup_last_fire.update(state)

    # ------------------------------------------------------------------
    # Main entry: process()
    # ------------------------------------------------------------------

    async def process(
        self,
        event: Any,
        tiered: dict,
        bar: Any,
        symbol: str,
        tf: str,
        raw_signals: list[dict],
        cache_snapshot: CacheSnapshot,
        flat_features: dict | None = None,
    ) -> SignalProcessorResult:
        """Run signal pipeline stages and return structured result.

        Reads cache values from cache_snapshot — NOT from any self-held cache reference.
        Applies alpha decay to raw_signals before gates (D-21, moved from orchestrator).
        Emits D-22 OTel counters for gate observability.

        Args:
            flat_features: Pre-computed flat feature dict from build_flat_features(event).
                           When provided (Plan 05 hot path), avoids per-bar model_dump()
                           call. When None, falls back to building from event (backward compat).
        """
        # Sync CIS weights at start of every bar (D-07 Pitfall 4 mediation)
        self.sync_cis_weights(cache_snapshot.cis_weights, cache_snapshot.cis_weights_version)

        i7_computed_at = datetime.now(UTC)

        # D-22: total signals entering the pipeline
        SIGNAL_PROCESSOR_SIGNALS_EVALUATED_TOTAL.add(len(raw_signals))
        self._signals_generated.add(len(raw_signals))

        if not raw_signals:
            return SignalProcessorResult(
                success=False,
                signals_payload=None,
                dlq_payload=None,
                winner_payload=None,
                i7_result={
                    "ranked": [],
                    "winner": None,
                    "signals_evaluated": 0,
                    "signals_after_quality": 0,
                    "signals_after_regime": 0,
                    "signals_after_calibration": 0,
                    "i7_computed_at": i7_computed_at,
                },
            )

        # Stamp pre_quality_confidence BEFORE alpha decay — training data must reflect
        # raw plugin confidence, not the post-decay value.
        for sig in raw_signals:
            sig["pre_quality_confidence"] = sig.get("confidence", 0.0)

        # Alpha decay (D-21): bars_since counts fires since last win, not elapsed bars.
        # Silence does not accumulate the counter — only actual fires do. This correctly
        # discounts autocorrelated consecutive fires while leaving re-emergent signals
        # unpenalized for time they did not fire.
        for sig in raw_signals:
            fire_key = (symbol, tf, sig.get("setup_plugin", ""), sig.get("direction", 0))
            state = self._setup_last_fire.get(fire_key)
            if state is not None:
                state["bars_since"] += 1
            _apply_alpha_decay(sig, tf, state)

        # Build features from event — use precomputed flat_features when available (3-E).
        # When flat_features is provided (set once per bar in FeaturePipelineExecutor),
        # avoids per-bar model_dump() call on the hot path.
        features = flat_features if flat_features is not None else build_flat_features(event)

        # Extrinsic annotation — pipeline responsibility, applied uniformly before any gate.
        # Every raw signal gets the full flat_features snapshot as context_features plus
        # surfaced ECL fields (ctf_score, ctf_confirmed, zone_friction_score).
        # Applied AFTER features are resolved and BEFORE calibration/quality/regime gates
        # so even regime-suppressed signals carry full context for ML training integrity.
        for sig in raw_signals:
            _annotate_signal(sig, features)

        # Design B: Update CIS scorer's calibration curves before scoring.
        # The scorer applies calibration to the Kalman-filtered CIS inside score().
        self._cis_scorer.set_calibration_curves(cache_snapshot.calibration_curves)

        # Compute CIS score once per bar (tf/symbol needed for Kalman + calibration in scorer)
        plugin_outputs: dict[str, dict] = {
            sig.get("setup_plugin", ""): sig for sig in raw_signals if sig.get("direction", 0) != 0
        }
        cis_result = self._cis_scorer.score(features, plugin_outputs, tf=tf, symbol=symbol)
        raw_cis: float = cis_result.cis_score  # float enforced by CISResult.__post_init__

        # Design B: filtered_cis and calibrated_cis are now computed inside CISScorer.score().
        # Read back the Kalman-filtered CIS from the scorer's internal state for attribution.
        kalman_key = (tf, symbol)
        filtered_cis = self._cis_scorer._cis_kalman_state.get(kalman_key, {}).get("x", raw_cis)

        def _record_dropped(gate: str, before: list, after: list) -> None:
            dropped = len(before) - len(after)
            if dropped > 0:
                SIGNAL_PROCESSOR_GATE_REJECTIONS_TOTAL.add(dropped, {"gate": gate})

        def _stamp_pre(stage_key: str, sigs: list[dict]) -> None:
            for sig in sigs:
                sig[stage_key] = sig.get("confidence", 0.0)

        # Pipeline stages
        hour_et = bar.ts.astimezone(_ET).hour

        # CRITICAL-02: Calibrate before quality gate so the gate operates on
        # isotonic-calibrated confidence, not raw plugin values. Cold-start
        # (empty cal_curves) passes through unchanged — no behavior delta.
        # After calibration, regime_gate reads calibrated_confidence and its
        # soft-band attenuation now persists (previously wiped by calibration
        # running after regime gate).
        calibrated_signals = await apply_calibration(
            raw_signals,
            cache_snapshot.calibration_curves,
            tf=tf,
            symbol=symbol,
            recorder=self._transform_recorder,
        )

        quality_gated = await apply_quality_gate(
            calibrated_signals,
            {
                "hurst_quality": features.get("hurst_trend_quality", _QUALITY_FEATURE_ABSENT),
                "entropy_quality": features.get("entropy_quality", _QUALITY_FEATURE_ABSENT),
                "drift_penalty": cache_snapshot.drift_penalties.get(symbol, _DRIFT_PENALTY_ABSENT),
            },
            tf=tf,
            recorder=self._transform_recorder,
            min_confidence=getattr(self._settings, "SIGNAL_MIN_PUBLISHABLE_CONFIDENCE", 0.12),
        )
        _record_dropped("quality", calibrated_signals, quality_gated)

        _stamp_pre("pre_regime_confidence", quality_gated)
        regime_gated = await apply_regime_gate(
            quality_gated,
            features,
            prob_min=self._regime_prob_min,
            prob_soft_max=self._regime_prob_soft_max,
            dur_min=self._regime_dur_min,
            tf=tf,
            recorder=self._transform_recorder,
        )
        for sig in regime_gated:
            if not sig.get("regime_eligible", True):
                REGIME_GATE_SUPPRESSIONS_TOTAL.add(
                    1,
                    {
                        "reason": "regime_type",
                        "plugin": sig.get("setup_plugin", ""),
                        "tf": tf,
                    },
                )
        _record_dropped("regime", quality_gated, regime_gated)

        ranked = await rank_signals(
            regime_gated,
            cache_snapshot.perf_weights,
            tf,
            symbol=symbol,
            recorder=self._transform_recorder,
        )

        # Annotate each ranked signal with CIS fields + metadata
        num_signals = len(ranked)
        for rank_idx, sig in enumerate(ranked, start=1):
            sig["composite_rank"] = rank_idx
            sig["num_signals_bar"] = num_signals
            sig["was_selected"] = False
            sig["status"] = "pending" if sig.get("regime_eligible", True) else "regime_suppressed"
            sig["hmm_regime_at_fire"] = features.get("hmm_regime")
            # Stamp CIS fields
            sig["raw_cis_score"] = round(raw_cis, 4)
            sig["filtered_cis_score"] = round(filtered_cis, 4)
            sig["bucket_scores"] = cis_result.bucket_scores
            sig["weights_version"] = cis_result.weights_version
            sig["bar_id"] = str(bar.bar_id)

        # Stamp shadow signals with non-live status, and build the live-eligible list
        # in a single pass. The full ranked list (including shadows) is kept for
        # signal_ledger persistence so the auditor's promotion gate can count shadow
        # observations (is_shadow=TRUE); shadows are excluded from winner selection
        # because they must be observed but never traded live.
        eligible_ranked = []
        for sig in ranked:
            if cache_snapshot.shadow_cache.get(sig.get("setup_plugin", ""), False):
                sig["is_shadow"] = True
                sig["status"] = "regime_suppressed"
            else:
                eligible_ranked.append(sig)

        # Select winner
        winner, _, resolution_method = select_winner(
            eligible_ranked,
            cis_result,
            long_bias=getattr(self._settings, "winner_long_bias", False),
        )

        # Stamp resolution_method on every ranked signal
        for sig in ranked:
            sig["resolution_method"] = resolution_method

        winner_plugin = winner.get("setup_plugin") if winner else None
        if winner_plugin is not None:
            for sig in ranked:
                if sig.get("setup_plugin") == winner_plugin and sig.get("regime_eligible", True):
                    sig["was_selected"] = True
                    break

        # Build i7_result dict (same shape as god class _run_i7_inner return)
        i7_result = {
            "ranked": ranked,
            "winner": winner,
            "signals_evaluated": len(raw_signals),
            "signals_after_quality": len(quality_gated),
            "signals_after_regime": len(regime_gated),
            "signals_after_calibration": len(ranked),
            "i7_computed_at": i7_computed_at,
        }

        # Update setup_last_fire after winner
        if winner is not None:
            self._signals_selected.add(1)
            # D-22: winner counter labeled by entry_type
            SIGNAL_PROCESSOR_WINNER_TOTAL.add(
                1, {"entry_type": winner.get("entry_type", "unknown")}
            )
            w_plugin = winner.get("setup_plugin", "")
            w_dir = winner.get("direction", 0)
            fire_key = (symbol, tf, w_plugin, w_dir)
            self._setup_last_fire[fire_key] = {"bars_since": 0}

        # Call prepare_signals_or_dlq
        success, dlq_payload, signals_payload = await self.prepare_signals_or_dlq(
            ranked, symbol, tf, bar, features=features
        )

        winner_payload = winner if success else None
        if winner_payload is not None:
            # winner_selector returns dict(min(...)) — a copy not in ranked — so
            # prepare_signals_or_dlq's timestamp stamp doesn't propagate to it.
            winner_payload["timestamp"] = format_iso_ts(bar.ts)
            winner_payload["is_backfill"] = (
                datetime.now(UTC) - bar.ts
            ).total_seconds() > TF_SECONDS.get(tf, 60)
            # CIS-level calibration: additive field distinct from plugin-level calibrated_confidence.
            # cis_result.calibrated_cis is None when no curve is available (omit field).
            if cis_result.calibrated_cis is not None:
                winner_payload["cis_calibrated_confidence"] = cis_result.calibrated_cis

        return SignalProcessorResult(
            success=success,
            signals_payload=signals_payload,
            dlq_payload=dlq_payload,
            winner_payload=winner_payload,
            i7_result=i7_result,
        )

    # ------------------------------------------------------------------
    # DLQ / signals payload preparation
    # ------------------------------------------------------------------

    async def prepare_signals_or_dlq(
        self,
        ranked: list[dict],
        symbol: str,
        tf: str,
        bar: Any,
        features: dict | None = None,
    ) -> tuple[bool, dict | None, dict | None]:
        """Assert CIS presence and build signals or DLQ payload.

        Returns:
            (False, dlq_payload_dict, None) when CIS assertion fails
            (True, None, signals_payload_dict) when all stamps applied successfully

        Does NOT call enqueue (Pitfall 8 — orchestrator owns routing).
        """
        # CIS assertion
        for sig in ranked:
            if sig.get("raw_cis_score") is None or sig.get("filtered_cis_score") is None:
                self._signal_dlq_total.add(1)
                SIGNAL_PROCESSOR_DLQ_TOTAL.add(1, {"reason": "cis_assertion_failed"})
                dlq_payload = {
                    "symbol": symbol,
                    "tf": tf,
                    "bar_ts": bar.ts.isoformat(),
                    "reason": "cis_score_null",
                    "signal_count": len(ranked),
                    "ts": datetime.now(UTC).isoformat(),
                }
                self._logger.error(
                    "signal_processor.cis_assertion_failed",
                    symbol=symbol,
                    tf=tf,
                    signal_count=len(ranked),
                )
                return False, dlq_payload, None

        # Terminal pipeline completeness check — signal_id and processor-stamped fields
        # must all be present before publish. Missing fields indicate a pipeline bug.
        complete: list[dict] = []
        for sig in ranked:
            missing = REQUIRED_PIPELINE_FIELDS - set(sig.keys())
            if missing:
                self._signal_dlq_total.add(1)
                SIGNAL_PROCESSOR_DLQ_TOTAL.add(1, {"reason": "pipeline_fields_missing"})
                self._logger.error(
                    "signal_processor.pipeline_fields_missing",
                    plugin=sig.get("setup_plugin", "unknown"),
                    missing_fields=sorted(missing),
                )
                continue
            complete.append(sig)
        ranked = complete

        # Assertion passed — stamp bar close as market_entry_price
        close_price = bar.close
        for sig in ranked:
            sig["market_price_at_signal"] = close_price
            sig["market_entry_price"] = close_price

        # Publisher-side normalization (D-01)
        bar_ts = bar.ts
        computed_at = datetime.now(UTC)
        tf_secs = TF_SECONDS.get(tf, 60)
        try:
            is_backfill = (computed_at - bar_ts).total_seconds() > tf_secs
        except Exception:
            is_backfill = False

        for sig in ranked:
            sig["timestamp"] = format_iso_ts(bar_ts)
            sig["is_backfill"] = is_backfill

        if is_backfill and ranked:
            INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL.add(
                len(ranked), {"symbol": symbol, "timeframe": tf}
            )

        signals_payload = {
            "symbol": symbol,
            "tf": tf,
            "bar_ts": format_iso_ts(bar_ts),
            "computed_at": format_iso_ts(computed_at),
            # Current bar regime state — consumed by signal_tracker to update its
            # per-symbol staleness cache (BUG-02 fix: regime drift was always 0).
            "hmm_regime": (features or {}).get("hmm_regime"),
            "garch_sigma": (features or {}).get("garch_sigma"),
            "signals": ranked,
        }
        return True, None, signals_payload
