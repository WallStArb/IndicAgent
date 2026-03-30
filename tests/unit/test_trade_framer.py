"""Tests for trade_framer.py — stop_basis classification, GARCH multiplier, FVG tier.

Task 1 tests: TradeFrame new fields + LedgerEntry 54-element tuple.
Task 2 tests: GARCH multiplier, FVG priority 0, proximity gate, stop_basis.
Task 3 tests: TF_TTL_BARS constants.
"""

from __future__ import annotations

from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Task 1: TradeFrame and LedgerEntry field extension
# ---------------------------------------------------------------------------


def test_tradeframe_has_stop_basis_fields():
    """TradeFrame should have 4 new stop_basis metadata fields with None defaults."""
    from src.intelligence.trading.trade_framer import TradeFrame

    tf = TradeFrame(
        entry=100.0,
        entry_type="at_close",
        stop=98.0,
        stop_type="atr",
    )
    assert hasattr(tf, "stop_basis")
    assert hasattr(tf, "stop_structure_type")
    assert hasattr(tf, "stop_structure_age_bars")
    assert hasattr(tf, "structural_stop_distance_atr")
    assert tf.stop_basis is None
    assert tf.stop_structure_type is None
    assert tf.stop_structure_age_bars is None
    assert tf.structural_stop_distance_atr is None


def test_ledger_entry_has_15_new_fields():
    """LedgerEntry should have all 15 new stop/lifecycle/divergence fields."""
    from src.persistence.repository.signal_ledger_repository import LedgerEntry

    entry = LedgerEntry(
        signal_id="abc",
        timestamp=datetime.now(tz=UTC),
        symbol="ES",
        timeframe="1m",
        setup_plugin="TrendFollowing",
        signal_type="trend_long",
        direction=1,
        entry_price=4500.0,
        stop_loss=4490.0,
        targets=[4520.0],
        confidence=0.8,
        confluence_score=0.7,
        regime_context="trending",
        supporting_factors=["ema_cross"],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="cis",
        composite_rank=1,
    )
    # New stop fields
    assert hasattr(entry, "stop_basis")
    assert hasattr(entry, "stop_structure_type")
    assert hasattr(entry, "stop_structure_age_bars")
    assert hasattr(entry, "structural_stop_distance_atr")
    # New fire-time snapshot fields
    assert hasattr(entry, "hmm_regime_at_fire")
    assert hasattr(entry, "garch_sigma_at_fire")
    assert hasattr(entry, "chandelier_vol_source")
    # New trailing stop fields
    assert hasattr(entry, "trailing_stop_price")
    assert hasattr(entry, "trailing_stop_tightening_rate")
    # New staleness fields
    assert hasattr(entry, "staleness_score")
    assert hasattr(entry, "staleness_trigger_reason")
    # New shadow fields
    assert hasattr(entry, "shadow_tracking_start_ts")
    assert hasattr(entry, "shadow_mae")
    assert hasattr(entry, "shadow_mfe")
    assert hasattr(entry, "shadow_outcome")


def test_ledger_entry_to_insert_params_returns_60_elements():
    """to_insert_params() must return a 60-element tuple (39 original + 15 Phase 32 + 4 Phase 35 + 2 Phase 57)."""
    from src.persistence.repository.signal_ledger_repository import LedgerEntry

    entry = LedgerEntry(
        signal_id="abc",
        timestamp=datetime.now(tz=UTC),
        symbol="ES",
        timeframe="1m",
        setup_plugin="TrendFollowing",
        signal_type="trend_long",
        direction=1,
        entry_price=4500.0,
        stop_loss=4490.0,
        targets=[4520.0],
        confidence=0.8,
        confluence_score=0.7,
        regime_context="trending",
        supporting_factors=["ema_cross"],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="cis",
        composite_rank=1,
    )
    params = entry.to_insert_params()
    assert len(params) == 60, f"Expected 60 params, got {len(params)}"


def test_ledger_entry_to_insert_params_with_all_new_fields():
    """to_insert_params() should serialize new fields correctly."""
    from src.persistence.repository.signal_ledger_repository import LedgerEntry

    ts = datetime.now(tz=UTC)
    entry = LedgerEntry(
        signal_id="abc",
        timestamp=ts,
        symbol="ES",
        timeframe="1m",
        setup_plugin="TrendFollowing",
        signal_type="trend_long",
        direction=1,
        entry_price=4500.0,
        stop_loss=4490.0,
        targets=[4520.0],
        confidence=0.8,
        confluence_score=0.7,
        regime_context="trending",
        supporting_factors=["ema_cross"],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="cis",
        composite_rank=1,
        stop_basis="structure_snap",
        stop_structure_type="ob_bottom",
        stop_structure_age_bars=5,
        structural_stop_distance_atr=0.8,
        hmm_regime_at_fire=1,
        garch_sigma_at_fire=0.015,
        chandelier_vol_source="garch_sigma",
        trailing_stop_price=[{"ts": "2026-01-01T00:00:00Z", "price": 4495.0}],
        trailing_stop_tightening_rate=0.1,
        staleness_score=0.3,
        staleness_trigger_reason="bar_count",
        shadow_tracking_start_ts=ts,
        shadow_mae=5.0,
        shadow_mfe=12.0,
        shadow_outcome="target_1",
    )
    params = entry.to_insert_params()
    assert len(params) == 60  # 39 original + 15 Phase 32 + 4 Phase 35 calibration + 2 Phase 57 attribution
    # Check that stop_basis is at position 39 (0-indexed)
    assert params[39] == "structure_snap"
    assert params[40] == "ob_bottom"
    assert params[41] == 5
    assert params[42] == 0.8
    assert params[43] == 1
    assert params[44] == 0.015
    assert params[45] == "garch_sigma"
    # trailing_stop_price is a list (asyncpg handles JSONB serialization)
    assert params[46] is not None
    assert len(params[46]) == 1
    assert params[46][0]["price"] == 4495.0
    assert params[47] == 0.1
    assert params[48] == 0.3
    assert params[49] == "bar_count"
    assert params[50] == ts
    assert params[51] == 5.0
    assert params[52] == 12.0
    assert params[53] == "target_1"


def test_ledger_entry_trailing_stop_none_serializes_to_none():
    """When trailing_stop_price is None, to_insert_params() should return None for $47."""
    from src.persistence.repository.signal_ledger_repository import LedgerEntry

    entry = LedgerEntry(
        signal_id="abc",
        timestamp=datetime.now(tz=UTC),
        symbol="ES",
        timeframe="1m",
        setup_plugin="TrendFollowing",
        signal_type="trend_long",
        direction=1,
        entry_price=4500.0,
        stop_loss=4490.0,
        targets=[4520.0],
        confidence=0.8,
        confluence_score=0.7,
        regime_context="trending",
        supporting_factors=[],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="cis",
        composite_rank=1,
    )
    params = entry.to_insert_params()
    assert params[46] is None  # trailing_stop_price = None


def test_insert_sql_has_60_columns():
    """_INSERT_SQL must have 60 column names and $1 through $60."""
    from src.persistence.repository.signal_ledger_repository import _INSERT_SQL

    # Count $N placeholders — ensure $54-$60 all exist
    assert "$54" in _INSERT_SQL, "_INSERT_SQL must contain $54"
    assert "$55" in _INSERT_SQL, "_INSERT_SQL must contain $55"
    assert "$56" in _INSERT_SQL, "_INSERT_SQL must contain $56"
    assert "$57" in _INSERT_SQL, "_INSERT_SQL must contain $57"
    assert "$58" in _INSERT_SQL, "_INSERT_SQL must contain $58"
    assert "$59" in _INSERT_SQL, "_INSERT_SQL must contain $59"
    assert "$60" in _INSERT_SQL, "_INSERT_SQL must contain $60"
    assert "$53" in _INSERT_SQL
    assert "$40" in _INSERT_SQL
    # Check Phase 32 column names present
    assert "stop_basis" in _INSERT_SQL
    assert "chandelier_vol_source" in _INSERT_SQL
    assert "shadow_outcome" in _INSERT_SQL
    # Check Phase 35 calibration column names present
    assert "raw_cis_score" in _INSERT_SQL
    assert "filtered_cis_score" in _INSERT_SQL
    assert "calibrated_confidence" in _INSERT_SQL
    assert "regime_type_at_fire" in _INSERT_SQL
    # Check Phase 57 attribution column names present
    assert "pre_quality_confidence" in _INSERT_SQL
    assert "pre_calibration_confidence" in _INSERT_SQL


# ---------------------------------------------------------------------------
# Task 2: GARCH multiplier + FVG tier + stop_basis classification
# ---------------------------------------------------------------------------


def test_garch_multipliers_constants():
    """GARCH_MULTIPLIERS should map 0->0.8, 1->1.0, 2->1.35."""
    from src.intelligence.trading.trade_framer import GARCH_MULTIPLIERS

    assert GARCH_MULTIPLIERS[0] == 0.8
    assert GARCH_MULTIPLIERS[1] == 1.0
    assert GARCH_MULTIPLIERS[2] == 1.35


def test_structure_snap_proximity_constant():
    """STRUCTURE_SNAP_PROXIMITY_ATR should be 1.5."""
    from src.intelligence.trading.trade_framer import STRUCTURE_SNAP_PROXIMITY_ATR

    assert STRUCTURE_SNAP_PROXIMITY_ATR == 1.5


def test_frame_trade_garch_regime_0_narrows_effective_atr():
    """frame_trade with garch_vol_regime=0 should use effective_atr = atr * 0.8.

    With regime=0 (low vol) the stop should be tighter than with regime=1.
    """
    from src.intelligence.trading.trade_framer import frame_trade

    # Features with OB stop and known regime
    features_r0 = {
        "garch_vol_regime": 0,
        "ob_type": 1.0,
        "ob_bottom": 4490.0,
        "close_price": 4510.0,
    }
    features_r1 = {
        "garch_vol_regime": 1,
        "ob_type": 1.0,
        "ob_bottom": 4490.0,
        "close_price": 4510.0,
    }
    atr = 10.0
    # For OB stop: stop = ob_bottom - atr * ATR_STOP_OB_MULTIPLIER
    # regime=0: effective_atr=8.0, stop = 4490 - 8*0.20 = 4488.4
    # regime=1: effective_atr=10.0, stop = 4490 - 10*0.20 = 4488.0
    # Actually tighter stop (less buffer) for low vol
    frame_r0 = frame_trade("trend_long", 1, 4510.0, features_r0, atr)
    frame_r1 = frame_trade("trend_long", 1, 4510.0, features_r1, atr)
    # regime 0 has smaller buffer → higher stop price (closer to entry)
    assert frame_r0.stop > frame_r1.stop, (
        f"regime=0 stop {frame_r0.stop} should be > regime=1 stop {frame_r1.stop}"
    )


def test_frame_trade_garch_regime_2_widens_effective_atr():
    """frame_trade with garch_vol_regime=2 should use effective_atr = atr * 1.35."""
    from src.intelligence.trading.trade_framer import frame_trade

    features_r2 = {
        "garch_vol_regime": 2,
        "ob_type": 1.0,
        "ob_bottom": 4490.0,
        "close_price": 4510.0,
    }
    features_r1 = {
        "garch_vol_regime": 1,
        "ob_type": 1.0,
        "ob_bottom": 4490.0,
        "close_price": 4510.0,
    }
    atr = 10.0
    frame_r2 = frame_trade("trend_long", 1, 4510.0, features_r2, atr)
    frame_r1 = frame_trade("trend_long", 1, 4510.0, features_r1, atr)
    # regime 2 has larger buffer → lower stop price (further from entry for longs)
    assert frame_r2.stop < frame_r1.stop, (
        f"regime=2 stop {frame_r2.stop} should be < regime=1 stop {frame_r1.stop}"
    )


def test_frame_trade_no_garch_regime_uses_atr_static():
    """frame_trade with no garch_vol_regime should produce stop_basis='atr_static'."""
    from src.intelligence.trading.trade_framer import frame_trade

    # Minimal features — no structural levels → ATR fallback
    features = {
        "garch_vol_regime": None,
        "close_price": 100.0,
    }
    atr = 5.0
    frame = frame_trade("trend_long", 1, 100.0, features, atr)
    # ATR fallback when no garch_vol_regime → atr_static
    assert frame.stop_basis == "atr_static", f"Expected atr_static, got {frame.stop_basis}"


def test_fvg_stop_long_priority_0():
    """FVG long stop (fvg_bottom) should be Priority 0 — beats demand zone stop."""
    from src.intelligence.trading.trade_framer import frame_trade

    # Demand zone present — would normally be priority 1
    # FVG present — should be priority 0, overrides demand zone
    features = {
        "garch_vol_regime": 1,
        "fvg_type": 1.0,
        "fvg_bottom": 4492.0,
        "in_demand_zone": 1.0,
        "nearest_demand_low": 4488.0,
        "close_price": 4510.0,
    }
    atr = 10.0
    frame = frame_trade("trend_long", 1, 4510.0, features, atr)
    assert frame.stop_type == "fvg_low", f"Expected fvg_low, got {frame.stop_type}"


def test_fvg_stop_short_priority_0():
    """FVG short stop (fvg_top) should be Priority 0 — beats supply zone stop."""
    from src.intelligence.trading.trade_framer import frame_trade

    features = {
        "garch_vol_regime": 1,
        "fvg_type": -1.0,
        "fvg_top": 4518.0,
        "in_supply_zone": 1.0,
        "nearest_supply_high": 4522.0,
        "close_price": 4510.0,
    }
    atr = 10.0
    frame = frame_trade("trend_short", -1, 4510.0, features, atr)
    assert frame.stop_type == "fvg_high", f"Expected fvg_high, got {frame.stop_type}"


def test_stop_basis_structure_snap_within_proximity():
    """Structural stop within 1.5xATR of ATR fallback → stop_basis='structure_snap'."""
    from src.intelligence.trading.trade_framer import (
        GARCH_MULTIPLIERS,
        STRUCTURE_SNAP_PROXIMITY_ATR,
        _classify_stop_basis,
    )

    atr = 10.0
    effective_atr = atr * GARCH_MULTIPLIERS[1]  # regime=1: no change
    entry = 100.0
    direction = 1
    # atr_fallback_stop reference: entry - effective_atr * ATR_STOP_FALLBACK_MULTIPLIER = 80.0

    # Structural stop very close to ATR fallback (within 1.5×ATR = 15 pts)
    close_structural_stop = 82.0  # distance = |82 - 80| / 10 = 0.2 ATR → structure_snap
    stop_basis, structure_type, dist_atr = _classify_stop_basis(
        "ob_bottom", close_structural_stop, entry, effective_atr, 1, direction
    )
    assert stop_basis == "structure_snap"
    assert dist_atr <= STRUCTURE_SNAP_PROXIMITY_ATR


def test_stop_basis_garch_adaptive_outside_proximity():
    """Structural stop beyond 1.5xATR of ATR fallback → stop_basis='garch_adaptive'."""
    from src.intelligence.trading.trade_framer import (
        GARCH_MULTIPLIERS,
        STRUCTURE_SNAP_PROXIMITY_ATR,
        _classify_stop_basis,
    )

    atr = 10.0
    effective_atr = atr * GARCH_MULTIPLIERS[1]
    entry = 100.0
    direction = 1
    # atr_fallback_stop reference: entry - effective_atr * ATR_STOP_FALLBACK_MULTIPLIER = 80.0

    # Far structural stop (> 1.5×ATR from fallback)
    far_structural_stop = 60.0  # distance = |60 - 80| / 10 = 2.0 ATR → garch_adaptive
    stop_basis, structure_type, dist_atr = _classify_stop_basis(
        "swing_low", far_structural_stop, entry, effective_atr, 1, direction
    )
    assert stop_basis == "garch_adaptive"
    assert dist_atr > STRUCTURE_SNAP_PROXIMITY_ATR


def test_stop_basis_atr_static_when_no_regime():
    """stop_type='atr' and no garch_vol_regime → stop_basis='atr_static'."""
    from src.intelligence.trading.trade_framer import _classify_stop_basis

    stop_basis, structure_type, dist_atr = _classify_stop_basis(
        "atr", 80.0, 100.0, 10.0, None, 1
    )
    assert stop_basis == "atr_static"
    assert structure_type == "atr_fallback"
    assert dist_atr == 0.0


def test_stop_basis_garch_adaptive_for_atr_with_regime():
    """stop_type='atr' with garch_vol_regime set → stop_basis='garch_adaptive'."""
    from src.intelligence.trading.trade_framer import _classify_stop_basis

    stop_basis, structure_type, dist_atr = _classify_stop_basis(
        "atr", 80.0, 100.0, 10.0, 1, 1
    )
    assert stop_basis == "garch_adaptive"
    assert structure_type == "atr_fallback"


def test_stop_structure_type_mapping():
    """_classify_stop_basis should correctly map stop_type to stop_structure_type."""
    from src.intelligence.trading.trade_framer import _classify_stop_basis

    # Test ob_bottom maps to ob_bottom
    _, structure_type, _ = _classify_stop_basis("ob_bottom", 82.0, 100.0, 10.0, 1, 1)
    assert structure_type == "ob_bottom"

    # Test swing_low maps to swing_low
    _, structure_type, _ = _classify_stop_basis("swing_low", 82.0, 100.0, 10.0, 1, 1)
    assert structure_type == "swing_low"

    # Test demand_zone maps to demand_zone
    _, structure_type, _ = _classify_stop_basis("demand_zone", 82.0, 100.0, 10.0, 1, 1)
    assert structure_type == "demand_zone"


def test_structural_stop_distance_atr_computed_correctly():
    """structural_stop_distance_atr = abs(structural_stop - atr_fallback) / effective_atr."""
    from src.intelligence.trading.trade_framer import (
        ATR_STOP_FALLBACK_MULTIPLIER,
        _classify_stop_basis,
    )

    entry = 100.0
    effective_atr = 10.0
    direction = 1
    atr_fallback_stop = entry - effective_atr * ATR_STOP_FALLBACK_MULTIPLIER  # 80.0
    structural_stop = 84.0

    expected_dist = abs(structural_stop - atr_fallback_stop) / effective_atr  # 0.4

    _, _, dist_atr = _classify_stop_basis(
        "ob_bottom", structural_stop, entry, effective_atr, 1, direction
    )
    assert abs(dist_atr - expected_dist) < 1e-9


def test_frame_trade_populates_stop_basis_fields():
    """frame_trade() should return TradeFrame with all stop_basis fields populated."""
    from src.intelligence.trading.trade_framer import frame_trade

    features = {
        "garch_vol_regime": 1,
        "swing_low": 4490.0,
        "swing_low_age_bars": 7,
        "close_price": 4510.0,
    }
    atr = 10.0
    frame = frame_trade("trend_long", 1, 4510.0, features, atr)

    assert frame.stop_basis is not None
    assert frame.stop_structure_type is not None
    assert frame.structural_stop_distance_atr is not None
    # swing_low should have age_bars populated
    assert frame.stop_structure_age_bars == 7


# ---------------------------------------------------------------------------
# Task 3: TF_TTL_BARS constants
# ---------------------------------------------------------------------------


def test_tf_ttl_bars_constants():
    """TF_TTL_BARS should define per-TF TTL values."""
    from services.signal_generator_service import TF_TTL_BARS

    assert TF_TTL_BARS["1m"] == 20
    assert TF_TTL_BARS["5m"] == 12
    assert TF_TTL_BARS["15m"] == 8
    assert TF_TTL_BARS["1h"] == 6
