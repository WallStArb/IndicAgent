"""Unit tests for the zone width gate in frame_trade().

Tests P126-01 Step 6 scenarios:
  1. Supply/demand zone $0.02 wide on equity (ATR $0.75) -> zone_too_narrow (rejected)
  2. FVG zone $0.03 wide on equity (ATR $0.75) -> zone_too_narrow (rejected)
  3. Structural engine zone 0.0020 wide on forex (ATR 0.0004) -> valid (5xATR wide)
  4. Sweep band zone (entry +/- 0.5xATR = 1.0xATR wide) on forex -> passes (>= 1.0 forex threshold)
  5. ATR fallback zone (entry - 1.0xATR to entry + 0.5xATR = 1.5xATR wide) -> passes (>= 1.5 equity threshold)
  6. Rejection logged at WARNING with zone_width/min_width/atr/zone_source fields
"""

from __future__ import annotations

import pytest

from src.intelligence.trading.trade_framer import frame_trade, set_config_service

# ---------------------------------------------------------------------------
# Mock config service for per-asset-class threshold testing
# ---------------------------------------------------------------------------


class _MockCfg:
    """Minimal config service stub for unit tests.

    Returns per-asset-class zone width thresholds matching the APR seeds
    in migration 132: equity=1.5, fx=1.0, futures=1.5, default=1.5.
    Stop distance floor default=0.5.
    """

    _APR_VALUES: dict[str, float] = {
        "feature.zone_engine.min_zone_width_atr": 1.5,
        "feature.zone_engine.min_zone_width_atr.equity": 1.5,
        "feature.zone_engine.min_zone_width_atr.fx": 1.0,
        "feature.zone_engine.min_zone_width_atr.futures": 1.5,
        "feature.zone_engine.min_stop_distance_atr": 0.5,
        "feature.zone_engine.min_stop_distance_atr.equity": 0.5,
        "feature.zone_engine.min_stop_distance_atr.fx": 0.3,
        "feature.zone_engine.min_stop_distance_atr.futures": 0.4,
    }

    def get_sync(self, key: str, default: float) -> float:
        return self._APR_VALUES.get(key, default)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_config_service():
    """Ensure config_service is None (hard-coded defaults) for each test."""
    set_config_service(None)
    yield
    set_config_service(None)


@pytest.fixture()
def with_apr_config():
    """Inject mock APR config service (per-asset-class thresholds)."""
    set_config_service(_MockCfg())
    yield
    set_config_service(None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_features(**kwargs) -> dict:
    return kwargs


ENTRY_EQUITY = 100.0  # equity-like entry price
ATR_EQUITY = 0.75  # $0.75 ATR — realistic for a mid-cap equity
# equity threshold at default 1.5: min_width = 1.5 * 0.75 = $1.125

ENTRY_FOREX = 148.00  # USDJPY-like entry
ATR_FOREX = 0.0004  # 4 pip ATR — realistic for USDJPY on 1m
# forex threshold at default 1.0: min_width = 1.0 * 0.0004 = 0.0004


# ---------------------------------------------------------------------------
# Scenario 1: Supply/demand $0.02 zone on equity -> rejected
# ---------------------------------------------------------------------------


class TestNarrowSupplyDemandZoneRejected:
    """supply_demand zone $0.02 wide on equity (ATR $0.75) -> zone_too_narrow."""

    def test_viable_false(self):
        # zone_high - zone_low = $0.02 << $1.125 threshold
        f = _make_features(
            nearest_demand_low=ENTRY_EQUITY - 0.02,
            nearest_demand_high=ENTRY_EQUITY,  # zone is $0.02 wide
            asset_class="equity",
        )
        tf = frame_trade("supply_demand_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        assert tf.viable is False

    def test_rejection_reason_starts_with_zone_too_narrow(self):
        f = _make_features(
            nearest_demand_low=ENTRY_EQUITY - 0.02,
            nearest_demand_high=ENTRY_EQUITY,
            asset_class="equity",
        )
        tf = frame_trade("supply_demand_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        assert tf.rejection_reason is not None
        assert tf.rejection_reason.startswith("zone_too_narrow:")

    def test_rejection_reason_contains_zone_source(self):
        f = _make_features(
            nearest_demand_low=ENTRY_EQUITY - 0.02,
            nearest_demand_high=ENTRY_EQUITY,
            asset_class="equity",
        )
        tf = frame_trade("supply_demand_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        assert "supply_demand" in tf.rejection_reason

    def test_warning_logged(self):
        from structlog.testing import capture_logs

        f = _make_features(
            nearest_demand_low=ENTRY_EQUITY - 0.02,
            nearest_demand_high=ENTRY_EQUITY,
            asset_class="equity",
        )
        with capture_logs() as cap_logs:
            frame_trade("supply_demand_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        events = [e["event"] for e in cap_logs]
        assert "frame_trade.zone_too_narrow" in events, f"Expected warning in {events}"
        warning_entry = next(e for e in cap_logs if e["event"] == "frame_trade.zone_too_narrow")
        assert "zone_width" in warning_entry
        assert "min_width" in warning_entry
        assert "atr" in warning_entry
        assert "zone_source" in warning_entry


# ---------------------------------------------------------------------------
# Scenario 2: FVG $0.03 zone on equity -> rejected
# ---------------------------------------------------------------------------


class TestNarrowFVGZoneRejected:
    """FVG zone $0.03 wide on equity (ATR $0.75) -> zone_too_narrow."""

    def test_viable_false(self):
        # fvg_top - fvg_bottom = $0.03 << $1.125 threshold
        f = _make_features(
            fvg_bottom=ENTRY_EQUITY - 0.03,
            fvg_top=ENTRY_EQUITY,  # zone is $0.03 wide
            asset_class="equity",
        )
        tf = frame_trade("fvg_fill_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        assert tf.viable is False

    def test_rejection_reason_starts_with_zone_too_narrow(self):
        f = _make_features(
            fvg_bottom=ENTRY_EQUITY - 0.03,
            fvg_top=ENTRY_EQUITY,
            asset_class="equity",
        )
        tf = frame_trade("fvg_fill_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        assert tf.rejection_reason is not None
        assert tf.rejection_reason.startswith("zone_too_narrow:")

    def test_rejection_reason_contains_fvg(self):
        f = _make_features(
            fvg_bottom=ENTRY_EQUITY - 0.03,
            fvg_top=ENTRY_EQUITY,
            asset_class="equity",
        )
        tf = frame_trade("fvg_fill_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        assert "fvg" in tf.rejection_reason


# ---------------------------------------------------------------------------
# Scenario 3: Structural engine zone 0.0020 wide on forex -> VALID (5xATR)
# ---------------------------------------------------------------------------


class TestWideForexStructuralZoneValid:
    """Structural engine zone 0.0020 wide on forex (ATR 0.0004) = 5xATR -> valid.

    forex threshold = 1.0; 5xATR >> 1.0xATR -> gate does not trigger.
    Uses ob_type zone path (CHoCH uses ob_bottom/ob_top) to inject specific zone bounds.
    """

    def test_viable_true_for_wide_forex_zone(self):
        # CHoCH reversal uses ob zone path; inject a zone 0.0020 wide (5xATR)
        zone_low = ENTRY_FOREX - 0.0020
        zone_high = ENTRY_FOREX
        # Also provide swing_high for stop resolution on short side
        f = _make_features(
            ob_type=-1.0,
            ob_bottom=zone_low,
            ob_top=zone_high,
            swing_high=ENTRY_FOREX + ATR_FOREX * 5,  # stop well above entry
            # Give a structural target so no_targets_found does not reject
            sr_nearest_support=ENTRY_FOREX - ATR_FOREX * 3,
            asset_class="fx",
        )
        tf = frame_trade("choch_short", -1, ENTRY_FOREX, f, ATR_FOREX)
        # Zone width 0.0020 >= 1.0 * 0.0004 = 0.0004 (5x threshold) -> gate passes
        if tf.rejection_reason:
            assert not tf.rejection_reason.startswith(
                "zone_too_narrow"
            ), f"Expected wide forex zone to pass, got: {tf.rejection_reason}"


# ---------------------------------------------------------------------------
# Scenario 4: Sweep band zone (1.0xATR wide) on forex -> passes gate (D-02)
# ---------------------------------------------------------------------------


class TestSweepBandZonePassesGate:
    """Sweep band: entry +/- 0.5xATR = 1.0xATR wide.

    Tested with forex asset_class (APR threshold = 1.0xATR) via mock config service.
    1.0xATR >= 1.0xATR -> gate does NOT trigger (D-02 self-exempt by construction).
    """

    def test_sweep_band_not_rejected_for_zone_too_narrow(self, with_apr_config):
        # With APR config: fx threshold = 1.0xATR; sweep band = 1.0xATR -> exactly at threshold
        # Strict less-than: 1.0 < 1.0 is False -> zone_too_narrow does NOT fire
        f = _make_features(
            asset_class="fx",
            sr_nearest_support=ENTRY_FOREX - ATR_FOREX * 3,  # target exists
        )
        tf = frame_trade("sweep_reclaim_long", 1, ENTRY_FOREX, f, ATR_FOREX)
        # If rejected, must NOT be for zone_too_narrow
        if not tf.viable:
            assert tf.rejection_reason is None or not tf.rejection_reason.startswith(
                "zone_too_narrow"
            ), f"Sweep band should not be zone_too_narrow, got: {tf.rejection_reason}"


# ---------------------------------------------------------------------------
# Scenario 5: ATR fallback zone (1.5xATR wide) on equity -> passes gate (D-02)
# ---------------------------------------------------------------------------


class TestATRFallbackZonePassesGate:
    """ATR fallback: entry - 1.0xATR to entry + 0.5xATR = 1.5xATR wide.

    Tested with equity asset_class (threshold = 1.5xATR).
    1.5xATR >= 1.5xATR (strict less-than check) -> gate does NOT trigger.
    """

    def test_atr_fallback_zone_not_rejected_for_zone_too_narrow(self):
        # No zone features -> falls through to ATR fallback zone
        f = _make_features(asset_class="equity")
        tf = frame_trade("trend_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        # If rejected, must NOT be for zone_too_narrow
        if not tf.viable:
            assert tf.rejection_reason is None or not tf.rejection_reason.startswith(
                "zone_too_narrow"
            )

    def test_zone_width_exactly_at_threshold_passes(self):
        """zone_width == threshold (1.5xATR) must NOT be rejected (gate is strict <)."""
        # ATR fallback zone is entry - 1.0xATR to entry + 0.5xATR = 1.5xATR wide
        # With ATR_EQUITY=0.75: zone_width = 1.5 * 0.75 = 1.125
        # threshold for equity = 1.5 * 0.75 = 1.125
        # 1.125 < 1.125 is False -> passes
        f = _make_features(asset_class="equity")
        tf = frame_trade("trend_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        if not tf.viable:
            assert not (
                tf.rejection_reason and tf.rejection_reason.startswith("zone_too_narrow")
            ), f"ATR fallback zone at exact threshold should not be rejected: {tf.rejection_reason}"


# ---------------------------------------------------------------------------
# Scenario 6: Default (no asset_class) uses global threshold
# ---------------------------------------------------------------------------


class TestDefaultThresholdWithNoAssetClass:
    """When asset_class is absent, gate falls back to default threshold (1.5xATR)."""

    def test_narrow_zone_rejected_without_asset_class(self):
        # $0.02 zone << 1.5 * 0.75 = $1.125 threshold -> rejected regardless
        f = _make_features(
            nearest_demand_low=ENTRY_EQUITY - 0.02,
            nearest_demand_high=ENTRY_EQUITY,
            # no asset_class key
        )
        tf = frame_trade("supply_demand_long", 1, ENTRY_EQUITY, f, ATR_EQUITY)
        assert tf.viable is False
        assert tf.rejection_reason is not None
        assert tf.rejection_reason.startswith("zone_too_narrow:")
