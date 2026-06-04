"""Unit tests for SignalProcessor — I7 signal pipeline stages.

Covers:
- CIS weight sync (version-gated mediation, Pitfall 4)
- Kalman state and setup_last_fire checkpoint roundtrips (Pitfall 5)
- DLQ on null CIS score (prepare_signals_or_dlq)
- Signals payload on success (prepare_signals_or_dlq)
- is_backfill flag on old bars
- process() returns SignalProcessorResult with all payloads (HIGH finding 4)
- DLQ path on CIS null in process()
- CacheSnapshot consumption (no CacheManager reference, HIGH finding 2)
- No lateral imports (topic_* / message_key / OutputQueue regression guard)
- Module-level helpers exist
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.intelligence.pipeline.signal_processor import (
    CacheSnapshot,
    SignalProcessor,
    SignalProcessorResult,
)


def _make_snapshot(**overrides) -> CacheSnapshot:
    """Create a minimal CacheSnapshot for testing."""
    defaults = {
        "perf_weights": {},
        "calibration_curves": {},
        "tod_priors": {},
        "drift_penalties": {},
        "cis_weights": {},
        "cis_weights_version": 0,
    }
    defaults.update(overrides)
    return CacheSnapshot(**defaults)


def _make_processor() -> SignalProcessor:
    """Create a SignalProcessor with a MagicMock CIS scorer.

    Phase 112 note: Kalman state is now owned by CISScorer (Design B).
    The MagicMock CISScorer must support get_kalman_state/restore_kalman_state
    for the checkpoint roundtrip tests.
    """
    cis_scorer = MagicMock()
    cis_scorer.update_weights = MagicMock()
    # Phase 112 Design B: CISScorer owns Kalman state.
    # Give the mock a real backing dict so Kalman checkpoint tests work.
    _kalman_backing: dict = {}

    def _mock_get_kalman_state():
        return dict(_kalman_backing)

    def _mock_restore_kalman_state(state):
        _kalman_backing.update(state)

    cis_scorer.get_kalman_state = _mock_get_kalman_state
    cis_scorer.restore_kalman_state = _mock_restore_kalman_state
    cis_scorer._cis_kalman_state = _kalman_backing  # for filtered_cis read-back in process()
    settings = MagicMock()
    settings.regime_prob_min = 0.7
    settings.REGIME_PROB_SOFT_MAX = 0.55
    settings.regime_dur_min = 12
    settings.winner_long_bias = True
    settings.SIGNAL_MIN_PUBLISHABLE_CONFIDENCE = 0.0  # no floor for unit tests
    return SignalProcessor(cis_scorer=cis_scorer, settings=settings, transform_recorder=None)


def _make_bar(symbol="ES", tf="1m", ts=None, close=100.0):
    bar = MagicMock()
    bar.symbol = symbol
    bar.tf = tf
    bar.close = close
    bar.bar_id = "test-bar-id"
    bar.ts = ts or datetime.now(UTC)
    return bar


def _make_signal(plugin_name="trad_TrendFollowing", direction=1, confidence=0.7, raw_cis=0.5):
    return {
        "setup_plugin": plugin_name,
        "direction": direction,
        "confidence": confidence,
        "raw_cis_score": raw_cis,
        "filtered_cis_score": raw_cis,
        "bucket_scores": {},
        "weights_version": 0,
        "symbol": "ES",
        "tf": "1m",
        "regime_type": "trend",
    }


# ---------------------------------------------------------------------------
# sync_cis_weights tests
# ---------------------------------------------------------------------------


def test_sync_cis_weights_updates_scorer_only_on_version_change():
    """CIS scorer is updated only when version changes; no-op on same version."""
    proc = _make_processor()
    scorer = proc._cis_scorer

    # First call with version 1 — should update
    proc.sync_cis_weights({"a": 1.0}, 1)
    assert scorer.update_weights.call_count == 1

    # Same version again — should NOT update
    proc.sync_cis_weights({"a": 1.0}, 1)
    assert scorer.update_weights.call_count == 1

    # New version — should update again
    proc.sync_cis_weights({"a": 2.0}, 2)
    assert scorer.update_weights.call_count == 2


# ---------------------------------------------------------------------------
# Kalman state checkpoint roundtrip
# ---------------------------------------------------------------------------


def test_get_restore_kalman_state_roundtrip():
    """restore_kalman_state followed by get_kalman_state returns the same values."""
    proc = _make_processor()
    proc.restore_kalman_state({"k": 0.5, "p": 0.1})
    state = proc.get_kalman_state()
    assert state == {"k": 0.5, "p": 0.1}

    # Mutating the returned dict must NOT change internal state (defensive copy)
    state["k"] = 99.0
    assert proc.get_kalman_state()["k"] == 0.5


def test_get_restore_setup_last_fire_roundtrip():
    """restore_setup_last_fire followed by get_setup_last_fire returns the same values."""
    proc = _make_processor()
    proc.restore_setup_last_fire({"s1": {"bars_since": 3}})
    state = proc.get_setup_last_fire()
    assert state == {"s1": {"bars_since": 3}}

    # Mutating the returned dict must NOT change internal state (defensive copy)
    state["s1"] = {"bars_since": 99}
    assert proc.get_setup_last_fire()["s1"]["bars_since"] == 3


# ---------------------------------------------------------------------------
# prepare_signals_or_dlq tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_signals_or_dlq_returns_dlq_on_null_cis_score():
    """Signal with raw_cis_score=None triggers DLQ path."""
    proc = _make_processor()
    ranked = [{"raw_cis_score": None, "filtered_cis_score": 0.5, "setup_plugin": "X"}]
    bar = _make_bar()

    with patch.object(proc._signal_dlq_total, "add") as mock_dlq:
        success, dlq, signals = await proc.prepare_signals_or_dlq(ranked, "ES", "1m", bar)

    assert success is False
    assert dlq is not None
    assert "reason" in dlq
    assert dlq["reason"] == "cis_score_null"
    assert signals is None
    mock_dlq.assert_called_once()


@pytest.mark.asyncio
async def test_prepare_signals_or_dlq_returns_signals_payload_on_success():
    """All CIS fields present — returns signals payload with required keys."""
    proc = _make_processor()
    sig = _make_signal()
    bar = _make_bar()

    success, dlq, signals = await proc.prepare_signals_or_dlq([sig], "ES", "1m", bar)

    assert success is True
    assert dlq is None
    assert signals is not None
    assert "symbol" in signals
    assert "tf" in signals
    assert "bar_ts" in signals
    assert "computed_at" in signals
    assert "signals" in signals
    # Each signal must have signal_id assigned
    for s in signals["signals"]:
        assert "signal_id" in s


@pytest.mark.asyncio
async def test_prepare_signals_or_dlq_is_backfill_flag_set_on_old_bar():
    """Bar with ts well in the past gets is_backfill=True on all signals."""
    proc = _make_processor()
    sig = _make_signal()
    # bar_ts 2 hours ago
    old_ts = datetime.now(UTC) - timedelta(hours=2)
    bar = _make_bar(ts=old_ts)

    _, _, signals = await proc.prepare_signals_or_dlq([sig], "ES", "1m", bar)

    assert signals is not None
    for s in signals["signals"]:
        assert s.get("is_backfill") is True


# ---------------------------------------------------------------------------
# process() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_returns_signal_processor_result_with_all_payloads_on_success():
    """process() with valid raw_signals returns SignalProcessorResult with all payloads set (HIGH finding 4)."""
    proc = _make_processor()

    # CIS scorer returns a valid result
    from src.intelligence.trading.cis_scorer import CISResult

    cis_result = CISResult(
        cis_score=0.6,
        direction=1,
        bucket_scores={"trend": 0.5},
        weights_version=0,
        buckets_agreeing=4,
    )
    proc._cis_scorer.score = MagicMock(return_value=cis_result)

    bar = _make_bar()
    snapshot = _make_snapshot()
    raw_signals = [_make_signal()]

    # Patch stage functions to pass-through
    with (
        patch(
            "src.intelligence.pipeline.signal_processor.build_flat_features",
            return_value={"hmm_regime": 1},
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_quality_gate",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_regime_gate",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_tod_adjustment",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
        # Phase 112 D-04: apply_calibration removed from signal_processor (moved to CISScorer)
        patch(
            "src.intelligence.pipeline.signal_processor.rank_signals",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.select_winner",
            return_value=(raw_signals[0], [], "cis_rank"),
        ),
    ):
        result = await proc.process(
            MagicMock(), {}, bar, "ES", "1m", raw_signals=raw_signals, cache_snapshot=snapshot
        )

    assert isinstance(result, SignalProcessorResult)
    assert result.success is True
    assert result.signals_payload is not None  # HIGH finding 4 — signals path
    assert result.winner_payload is not None  # HIGH finding 4 — winner path
    assert result.dlq_payload is None
    assert result.i7_result is not None  # HIGH finding 4 — journal data


def test_cis_result_rejects_none_cis_score():
    """CISResult.__post_init__ enforces the float contract — None raises TypeError.

    The invariant lives at the producer (CISResult) not scattered across consumers.
    CISScorer.score() always returns round(float, 4); this test guards against
    a future scorer regression that returns None.
    """
    from src.intelligence.trading.cis_scorer import CISResult

    with pytest.raises(TypeError, match="cis_score must be float"):
        CISResult(
            cis_score=None,
            direction=0,
            bucket_scores={},
            weights_version=0,
            buckets_agreeing=0,
        )


@pytest.mark.asyncio
async def test_process_consumes_cache_snapshot_not_cache_manager_reference():
    """SignalProcessor constructor does NOT take a cache parameter (HIGH finding 2)."""
    # The constructor should only accept (cis_scorer, settings, transform_recorder)
    import inspect

    sig = inspect.signature(SignalProcessor.__init__)
    params = list(sig.parameters.keys())
    # Must have: self, cis_scorer, settings; must NOT have cache/cache_manager
    assert "cis_scorer" in params
    assert "settings" in params
    assert "cache" not in params
    assert "cache_manager" not in params

    # Constructing with only required args must not raise
    proc = _make_processor()

    # Calling process with CacheSnapshot must not raise AttributeError
    bar = _make_bar()
    snapshot = _make_snapshot()
    with (
        patch(
            "src.intelligence.pipeline.signal_processor.build_flat_features",
            return_value={},
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_quality_gate",
            return_value=[],
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_regime_gate",
            return_value=[],
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_tod_adjustment",
            return_value=[],
        ),
        # Phase 112 D-04: apply_calibration removed from signal_processor
        patch(
            "src.intelligence.pipeline.signal_processor.rank_signals",
            return_value=[],
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.select_winner",
            return_value=(None, [], "no_signal"),
        ),
    ):
        result = await proc.process(
            MagicMock(), {}, bar, "ES", "1m", raw_signals=[], cache_snapshot=snapshot
        )

    assert result.i7_result is not None  # no AttributeError raised


# ---------------------------------------------------------------------------
# Architectural regression guards
# ---------------------------------------------------------------------------


def test_no_lateral_imports():
    """SignalProcessor module must not import OutputQueue, topic_*, message_key, or CacheManager.

    HIGH finding 2 & 4 regression guards.
    """
    import src.intelligence.pipeline.signal_processor as mod

    source = inspect.getsource(mod)
    assert "OutputQueue" not in source, "SignalProcessor must not import OutputQueue (Pitfall 8)"
    assert "topic_signal_dlq" not in source, "SignalProcessor must not import topic_signal_dlq"
    assert (
        "topic_intelligence_i7_signals" not in source
    ), "SignalProcessor must not import topic_intelligence_i7_signals"
    assert (
        "topic_signals_aggregated" not in source
    ), "SignalProcessor must not import topic_signals_aggregated"
    assert (
        "topic_intelligence_journal" not in source
    ), "SignalProcessor must not import topic_intelligence_journal"
    assert "message_key" not in source, "SignalProcessor must not import message_key"
    assert (
        "from src.intelligence.pipeline.cache_manager" not in source
    ), "SignalProcessor must not import CacheManager (HIGH finding 2)"


def test_module_level_helpers_exist():
    """_apply_alpha_decay is a module-level callable in signal_processor.
    _cis_kalman_update was removed in Phase 112 — Kalman logic moved to CISScorer.
    build_flat_features moved to feature_flattening (Plan 05 neutral module) and re-imported."""
    import src.intelligence.pipeline.feature_flattening as ff_mod
    import src.intelligence.pipeline.signal_processor as mod

    assert callable(mod._apply_alpha_decay), "_apply_alpha_decay must be a module-level callable"
    assert not hasattr(
        mod, "_cis_kalman_update"
    ), "_cis_kalman_update must be removed (dead code since Design B migration)"
    # build_flat_features moved to feature_flattening in Plan 05; signal_processor re-imports it.
    assert callable(
        mod.build_flat_features
    ), "build_flat_features must be importable from signal_processor"
    assert callable(
        ff_mod.build_flat_features
    ), "build_flat_features must be callable in feature_flattening"

    # Verify they are NOT class methods
    assert not inspect.ismethod(mod._apply_alpha_decay)
    assert not inspect.ismethod(mod.build_flat_features)


# ---------------------------------------------------------------------------
# Phase-105 regression: shadow winner suppression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_plugin_never_wins_even_with_highest_score():
    """Shadow plugin cannot become the winner even when it has the top CIS score.

    Regression guard for Phase-105 fix: eligible_ranked excludes shadow-cache plugins
    before passing to select_winner, so select_winner never sees shadow signals.
    """
    from src.intelligence.trading.cis_scorer import CISResult

    proc = _make_processor()

    # CIS scorer returns a valid result — score value does not matter here
    cis_result = CISResult(
        cis_score=0.8,
        direction=1,
        bucket_scores={"trend": 0.8},
        weights_version=0,
        buckets_agreeing=5,
    )
    proc._cis_scorer.score = MagicMock(return_value=cis_result)

    bar = _make_bar()

    # Two plugins: shadow one has direction=1 (would score highest), live one has direction=1
    shadow_plugin = "shadow_Plugin"
    live_plugin = "trad_TrendFollowing"

    raw_signals = [
        {
            "setup_plugin": shadow_plugin,
            "direction": 1,
            "confidence": 0.95,  # highest confidence — would win without shadow filter
            "raw_cis_score": 0.8,
            "filtered_cis_score": 0.8,
            "bucket_scores": {},
            "weights_version": 0,
            "symbol": "ES",
            "tf": "1m",
            "regime_type": "trend",
        },
        {
            "setup_plugin": live_plugin,
            "direction": 1,
            "confidence": 0.70,
            "raw_cis_score": 0.8,
            "filtered_cis_score": 0.8,
            "bucket_scores": {},
            "weights_version": 0,
            "symbol": "ES",
            "tf": "1m",
            "regime_type": "trend",
        },
    ]

    # shadow_cache marks shadow_plugin as shadow (True), live_plugin as live (False)
    snapshot = _make_snapshot(
        shadow_cache={shadow_plugin: True, live_plugin: False},
    )

    with (
        patch(
            "src.intelligence.pipeline.signal_processor.build_flat_features",
            return_value={"hmm_regime": 1},
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_quality_gate",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_regime_gate",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
        patch(
            "src.intelligence.pipeline.signal_processor.apply_tod_adjustment",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
        # Phase 112 D-04: apply_calibration removed from signal_processor
        patch(
            "src.intelligence.pipeline.signal_processor.rank_signals",
            side_effect=lambda sigs, *a, **kw: sigs,
        ),
    ):
        result = await proc.process(
            MagicMock(), {}, bar, "ES", "1m", raw_signals=raw_signals, cache_snapshot=snapshot
        )

    assert result.i7_result is not None
    ranked = result.i7_result["ranked"]

    # The shadow signal must appear in ranked (for auditor observation)
    shadow_sigs = [s for s in ranked if s["setup_plugin"] == shadow_plugin]
    assert len(shadow_sigs) == 1, "Shadow signal must be in ranked list"
    shadow_sig = shadow_sigs[0]
    assert shadow_sig.get("is_shadow") is True, "Shadow signal must be stamped is_shadow=True"
    assert (
        shadow_sig.get("status") == "regime_suppressed"
    ), "Shadow signal status must be 'regime_suppressed'"

    # The winner must never be the shadow plugin
    if result.winner_payload is not None:
        winner_plugin = result.winner_payload.get("setup_plugin")
        assert (
            winner_plugin != shadow_plugin
        ), f"Shadow plugin '{shadow_plugin}' must never be the winner"
        assert (
            winner_plugin == live_plugin
        ), f"Live plugin '{live_plugin}' must be the winner, got '{winner_plugin}'"
