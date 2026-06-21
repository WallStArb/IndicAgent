"""Unit tests for LiquiditySweepReclaimPlugin structural rewrite (Phase 124-05).

Tests verify the four critical behavioral contracts:
1. Flag-stays-hot (sweep_reclaimed == 1.0 persistent) produces no signal without rising edge
2. Rising edge (transition 0->1) fires once then stops
3. Wick-only reclaim (close on wrong side of level) is rejected
4. deduplicate_event prevents re-fire on same (sweep_level, sweep_type) identity
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.intelligence.archive.trading_i7.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N = 60  # bars


def _make_df(
    n: int = _N, close: float = 4205.0, high: float = 4210.0, low: float = 4195.0
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [close] * n,
            "high": [high] * n,
            "low": [low] * n,
            "close": [close] * n,
            "volume": [1000.0] * n,
        }
    )


def _base_smc(
    sweep_detected: float = 1.0,
    sweep_reclaimed: float = 1.0,
    sweep_type: float = 1.0,
    sweep_level: float = 4200.0,
) -> dict:
    return {
        "sweep_detected": sweep_detected,
        "sweep_reclaimed": sweep_reclaimed,
        "sweep_type": sweep_type,
        "sweep_level": sweep_level,
        "sweep_depth_pct": 1.0,
        "fvg_type": 0.0,
        "ob_type": 0.0,
        "ssl_significance": 0.0,
        "bsl_significance": 0.0,
    }


def _base_i1(atr: float = 10.0) -> dict:
    return {"atr_14": atr}


def _base_i4() -> dict:
    return {"hmm_regime": 0, "hmm_regime_prob": 0.5}


def _build_frames(
    df: pd.DataFrame,
    smc: dict,
    symbol: str = "ESM6",
    timeframe: str = "5m",
) -> dict:
    return {
        "__symbol__": symbol,
        "__timeframe__": timeframe,
        "symbol": symbol,
        "main": df,
        "i1": {**_base_i1(), "timestamp": "2026-01-01T10:00:00Z", "timeframe": timeframe},
        "i2": {},
        "i3": {},
        "i4": _base_i4(),
        "i5": {},
        "smc": smc,
        "i6": {"ctf_score": 0.7, "ctf_confirmed": 1.0},
    }


def _mock_viable_frame(entry: float = 4205.0, direction: int = 1) -> MagicMock:
    offset = direction
    t1, t2, t3 = MagicMock(), MagicMock(), MagicMock()
    t1.price = entry + offset * 20.0
    t2.price = entry + offset * 35.0
    t3.price = entry + offset * 55.0
    frame = MagicMock()
    frame.viable = True
    frame.entry = entry
    frame.stop = entry - offset * 10.0
    frame.targets = [t1, t2, t3]
    frame.stop_basis = "atr_static"
    frame.zone_low = entry - offset * 10.0
    frame.zone_high = entry + offset * 5.0
    return frame


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _is_no_signal(result: dict) -> bool:
    """no_signal() returns {"signal_type": "none", ...}; real signal has an actual type."""
    return result.get("signal_type") in ("none", None)


def _is_signal(result: dict) -> bool:
    return not _is_no_signal(result)


class TestFlagStaysHotNoSignal:
    """sweep_reclaimed == 1.0 persistent (after initial rising edge) must not keep firing."""

    def test_flag_stays_hot_no_signal(self):
        """After initial rising edge fires, 9 subsequent bars with flag still hot must not re-fire."""
        plugin = LiquiditySweepReclaimPlugin()
        smc_off = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0)
        smc_on = _base_smc(sweep_detected=1.0, sweep_reclaimed=1.0)
        df = _make_df()

        with patch(
            "src.intelligence.archive.trading_i7.liquidity_sweep_reclaim.frame_trade"
        ) as mock_ft:
            mock_ft.return_value = _mock_viable_frame()
            # Prime: send one off-bar so onset_guard has a False baseline
            plugin.compute_full(_build_frames(df, smc_off))
            # Rising edge fires (bar 2)
            result_fire = plugin.compute_full(_build_frames(df, smc_on))
            assert _is_signal(result_fire), "rising edge must fire"
            # Bars 3-12: flag stays hot — must not re-fire
            for i in range(9):
                result = plugin.compute_full(_build_frames(df, smc_on))
                assert _is_no_signal(
                    result
                ), f"bar {3+i}: flag-stays-hot must produce no signal (no rising edge)"


class TestRisingEdgeFiresOnce:
    """Transition from 0->1 fires exactly once, then stops."""

    def test_rising_edge_fires_on_bar6(self):
        """Bars 1-5: sweep_reclaimed=0. Bar 6: sweep_reclaimed=1. Must fire only on bar 6."""
        with patch(
            "src.intelligence.archive.trading_i7.liquidity_sweep_reclaim.frame_trade"
        ) as mock_ft:
            mock_ft.return_value = _mock_viable_frame()

            plugin = LiquiditySweepReclaimPlugin()
            smc_off = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0)
            smc_on = _base_smc(sweep_detected=1.0, sweep_reclaimed=1.0, sweep_level=4200.0)
            df = _make_df(close=4205.0)

            # Bars 1-5: no reclaim yet
            for i in range(5):
                result = plugin.compute_full(_build_frames(df, smc_off))
                assert _is_no_signal(result), f"bar {i+1}: should not fire before reclaim"

            # Bar 6: rising edge
            result = plugin.compute_full(_build_frames(df, smc_on))
            assert (
                result.get("signal_type") == "sweep_reclaim_long"
            ), "bar 6: should fire on rising edge"
            assert result.get("direction") == 1

    def test_after_rising_edge_flag_stays_hot_no_more_fires(self):
        """After bar 6 fires, bars 7+ with sweep_reclaimed still 1.0 must not fire again."""
        with patch(
            "src.intelligence.archive.trading_i7.liquidity_sweep_reclaim.frame_trade"
        ) as mock_ft:
            mock_ft.return_value = _mock_viable_frame()

            plugin = LiquiditySweepReclaimPlugin()
            smc_off = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0)
            smc_on = _base_smc(sweep_detected=1.0, sweep_reclaimed=1.0, sweep_level=4200.0)
            df = _make_df(close=4205.0)

            # Bars 1-5: off
            for _ in range(5):
                plugin.compute_full(_build_frames(df, smc_off))

            # Bar 6: fires
            result = plugin.compute_full(_build_frames(df, smc_on))
            assert result.get("signal_type") == "sweep_reclaim_long"

            # Bars 7-10: flag still hot — must not re-fire
            for i in range(4):
                result = plugin.compute_full(_build_frames(df, smc_on))
                assert _is_no_signal(result), f"bar {7+i}: re-fire on hot flag must not happen"


class TestWickOnlyNoFire:
    """Close below swept level (wick-only) must be rejected."""

    def test_wick_reclaim_close_below_level(self):
        """High wick above sweep_level but close below — no signal."""
        plugin = LiquiditySweepReclaimPlugin()
        smc_off = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0)
        # sweep_level=4200, close=4195 (below level), high=4210 (wick above)
        smc_on = _base_smc(
            sweep_detected=1.0, sweep_reclaimed=1.0, sweep_level=4200.0, sweep_type=1.0
        )
        df_wick = _make_df(close=4195.0, high=4210.0, low=4185.0)

        with patch(
            "src.intelligence.archive.trading_i7.liquidity_sweep_reclaim.frame_trade"
        ) as mock_ft:
            mock_ft.return_value = _mock_viable_frame()

            # First deliver off-bar so onset_guard primes for rising edge
            plugin.compute_full(_build_frames(df_wick, smc_off))

            # Rising edge but close is below sweep_level (wick-only reclaim)
            result = plugin.compute_full(_build_frames(df_wick, smc_on))
            assert _is_no_signal(result), "wick-only reclaim must be rejected"
            mock_ft.assert_not_called()

    def test_body_reclaim_close_above_level_fires(self):
        """Close above sweep_level (body acceptance) must fire."""
        plugin = LiquiditySweepReclaimPlugin()
        smc_off = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0)
        smc_on = _base_smc(
            sweep_detected=1.0, sweep_reclaimed=1.0, sweep_level=4200.0, sweep_type=1.0
        )
        df_body = _make_df(close=4205.0, high=4210.0, low=4195.0)

        with patch(
            "src.intelligence.archive.trading_i7.liquidity_sweep_reclaim.frame_trade"
        ) as mock_ft:
            mock_ft.return_value = _mock_viable_frame()

            plugin.compute_full(_build_frames(df_body, smc_off))
            result = plugin.compute_full(_build_frames(df_body, smc_on))
            assert result.get("signal_type") == "sweep_reclaim_long", "body reclaim must fire"


class TestDeduplicatePreventsRefire:
    """deduplicate_event must prevent re-fire on same (sweep_level, sweep_type)."""

    def test_deduplicate_prevents_refire(self):
        """After bar 6 fires, reset onset (off bar), then re-fire with same level/type — blocked."""
        with patch(
            "src.intelligence.archive.trading_i7.liquidity_sweep_reclaim.frame_trade"
        ) as mock_ft:
            mock_ft.return_value = _mock_viable_frame()

            plugin = LiquiditySweepReclaimPlugin()
            smc_off = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0, sweep_level=4200.0)
            smc_on = _base_smc(
                sweep_detected=1.0, sweep_reclaimed=1.0, sweep_level=4200.0, sweep_type=1.0
            )
            df = _make_df(close=4205.0)

            # Prime then fire
            plugin.compute_full(_build_frames(df, smc_off))
            result1 = plugin.compute_full(_build_frames(df, smc_on))
            assert result1.get("signal_type") == "sweep_reclaim_long", "first fire must succeed"

            # Reset onset (off bar) then try to re-trigger with same event_id
            plugin.compute_full(_build_frames(df, smc_off))
            result2 = plugin.compute_full(_build_frames(df, smc_on))
            assert _is_no_signal(
                result2
            ), "deduplicate_event must block re-fire on same (sweep_level, sweep_type)"

    def test_different_sweep_level_fires_again(self):
        """New sweep_level (different event_id) must fire even if same sweep_type."""
        with patch(
            "src.intelligence.archive.trading_i7.liquidity_sweep_reclaim.frame_trade"
        ) as mock_ft:
            mock_ft.return_value = _mock_viable_frame()

            plugin = LiquiditySweepReclaimPlugin()
            smc_off_4200 = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0, sweep_level=4200.0)
            smc_on_4200 = _base_smc(
                sweep_detected=1.0, sweep_reclaimed=1.0, sweep_level=4200.0, sweep_type=1.0
            )
            smc_off_4150 = _base_smc(sweep_detected=1.0, sweep_reclaimed=0.0, sweep_level=4150.0)
            smc_on_4150 = _base_smc(
                sweep_detected=1.0, sweep_reclaimed=1.0, sweep_level=4150.0, sweep_type=1.0
            )
            df = _make_df(close=4205.0)

            # Fire on level 4200
            plugin.compute_full(_build_frames(df, smc_off_4200))
            r1 = plugin.compute_full(_build_frames(df, smc_on_4200))
            assert r1.get("signal_type") == "sweep_reclaim_long"

            # Reset onset, fire on level 4150 (different event_id)
            plugin.compute_full(_build_frames(df, smc_off_4150))
            r2 = plugin.compute_full(_build_frames(df, smc_on_4150))
            assert (
                r2.get("signal_type") == "sweep_reclaim_long"
            ), "different sweep_level must fire despite prior deduplicate"
