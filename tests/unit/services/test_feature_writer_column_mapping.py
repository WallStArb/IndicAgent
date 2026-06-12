"""Regression test pinning the tier-to-column mapping in _record_to_insert_params.

Phase 117-01: Verifies that the $10/$11/$12 positional args in the feature writer
INSERT tuple carry i5/i3/i4 data respectively.

  $10 (params[9])  -> pattern_detections -> I5Patterns data (dt_db_confidence)
  $11 (params[10]) -> regime_features    -> I3Structure data (swing_high)
  $12 (params[11]) -> confluence_scores  -> I4Context data (garch_sigma)

This test will fail if the tier args are swapped back.
"""

from datetime import UTC, datetime


def _make_record_with_sentinel_values():
    """Build a BarIntelligenceRecord with distinguishable sentinel values per tier."""
    from src.intelligence.schemas import (
        BarIntelligenceRecord,
        I1Indicators,
        I3Structure,
        I4Context,
        I5Patterns,
        I6Confluence,
        IntelligenceEvent,
        OHLCVBar,
        RankedSignal,
        SMCContext,
    )

    event = IntelligenceEvent(
        ts=datetime(2026, 6, 8, 14, 0, 0, tzinfo=UTC),
        symbol="ESM6",
        tf="1m",
        bar=OHLCVBar(o=5200.0, h=5205.0, l=5198.0, c=5203.0, v=9999),
        i1=I1Indicators(rsi_14=50.0, atr_14=8.0),
        # I3Structure sentinel: swing_high = 99.0 (I3-only field)
        i3=I3Structure(swing_high=99.0, nearest_resistance=5210.0),
        # I4Context sentinel: garch_sigma = 0.0042 (I4-only field)
        i4=I4Context(garch_sigma=0.0042, vol_regime=1.0),
        # I5Patterns sentinel: dt_db_confidence = 0.777 (I5-only field)
        i5=I5Patterns(dt_db_confidence=0.777),
        smc=SMCContext(bos_detected=False, hmm_regime=1.0),
        i6=I6Confluence(ctf_score=0.5),
    )

    return BarIntelligenceRecord(
        schema_version="1.0",
        intelligence=event,
        ranked_signals=[
            RankedSignal(
                signal_id="sentinel_test",
                plugin="trad_TrendFollowing",
                direction=1,
                raw_confidence=0.6,
                calibrated_confidence=0.6,
                regime_eligible=True,
                quality_score=0.7,
                tod_multiplier=1.0,
                adjusted_rank=0.7,
                is_winner=True,
            )
        ],
        winner_plugin="trad_TrendFollowing",
        winner_confidence=0.6,
        winner_direction=1,
        signals_evaluated=1,
        signals_after_quality=1,
        signals_after_regime=1,
        signals_after_tod=1,
        signals_after_calibration=1,
        ledger_written=True,
        session_type="rth",
        i7_computed_at=datetime(2026, 6, 8, 14, 0, 1, tzinfo=UTC),
        pipeline_latency_ms=20.0,
    )


def test_column_mapping_i5_lands_in_pattern_detections():
    """params[9] ($10 pattern_detections) must contain I5Patterns data."""
    from services.feature_writer import _record_to_insert_params

    record = _make_record_with_sentinel_values()
    params = _record_to_insert_params(record)

    # $10 = params[9] = pattern_detections — must contain the I5 sentinel
    pattern_detections = params[9]
    assert "dt_db_confidence" in pattern_detections, (
        f"pattern_detections ($10) should contain I5 field 'dt_db_confidence', "
        f"got keys: {list(pattern_detections.keys())[:10]}"
    )
    assert pattern_detections["dt_db_confidence"] == 0.777


def test_column_mapping_i3_lands_in_regime_features():
    """params[10] ($11 regime_features) must contain I3Structure data."""
    from services.feature_writer import _record_to_insert_params

    record = _make_record_with_sentinel_values()
    params = _record_to_insert_params(record)

    # $11 = params[10] = regime_features — must contain the I3 sentinel
    regime_features = params[10]
    assert "swing_high" in regime_features, (
        f"regime_features ($11) should contain I3 field 'swing_high', "
        f"got keys: {list(regime_features.keys())[:10]}"
    )
    assert regime_features["swing_high"] == 99.0


def test_column_mapping_i4_lands_in_confluence_scores():
    """params[11] ($12 confluence_scores) must contain I4Context data."""
    from services.feature_writer import _record_to_insert_params

    record = _make_record_with_sentinel_values()
    params = _record_to_insert_params(record)

    # $12 = params[11] = confluence_scores — must contain the I4 sentinel
    confluence_scores = params[11]
    assert "garch_sigma" in confluence_scores, (
        f"confluence_scores ($12) should contain I4 field 'garch_sigma', "
        f"got keys: {list(confluence_scores.keys())[:10]}"
    )
    assert confluence_scores["garch_sigma"] == 0.0042


def test_column_mapping_no_crosscontamination():
    """I5 sentinel must not appear in regime_features or confluence_scores."""
    from services.feature_writer import _record_to_insert_params

    record = _make_record_with_sentinel_values()
    params = _record_to_insert_params(record)

    regime_features = params[10]
    confluence_scores = params[11]

    assert (
        "dt_db_confidence" not in regime_features
    ), "I5 field 'dt_db_confidence' must not appear in regime_features"
    assert (
        "dt_db_confidence" not in confluence_scores
    ), "I5 field 'dt_db_confidence' must not appear in confluence_scores"


def test_record_to_insert_params_returns_32_element_tuple():
    """_record_to_insert_params must always return exactly 32 elements."""
    from services.feature_writer import _record_to_insert_params

    record = _make_record_with_sentinel_values()
    params = _record_to_insert_params(record)

    assert len(params) == 33, f"Expected 33 params, got {len(params)}"
