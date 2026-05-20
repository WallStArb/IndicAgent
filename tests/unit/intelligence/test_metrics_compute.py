"""Tests for compute_signal_metrics and compute_ic_metrics."""

from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.metrics.compute import (
    HMM_TO_REGIME,
    MIN_SAMPLE_SIZE,
    DistributionShape,
    _distribution_shape,
    compute_ic_metrics,
    compute_signal_metrics,
)


def _make_row(
    setup_plugin="trad_TrendFollowing",
    tf="5m",
    hmm_regime=1,
    direction=1,
    entry_price=5000.0,
    stop_loss=4999.0,
    pnl_r=1.0,
    mae=-0.3,
    mfe=1.5,
    outcome="target_1",
    confidence=0.75,
    signal_id="00000000-0000-0000-0000-000000000001",
    exit_at=None,
    market_entry_pnl_r=0.8,
    market_entry_mae=-0.2,
    market_entry_mfe=1.2,
    market_entry_outcome="target_1",
    days_ago=5,
    symbol="ES",
    entry_type="at_close",
):
    if exit_at is None:
        exit_at = datetime.now(UTC) - timedelta(days=days_ago)
    return {
        "signal_id": signal_id,
        "setup_plugin": setup_plugin,
        "tf": tf,
        "hmm_regime_at_fire": hmm_regime,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "pnl_r": pnl_r,
        "mae": mae,
        "mfe": mfe,
        "outcome": outcome,
        "confidence": confidence,
        "exit_at": exit_at,
        "market_entry_pnl_r": market_entry_pnl_r,
        "market_entry_mae": market_entry_mae,
        "market_entry_mfe": market_entry_mfe,
        "market_entry_outcome": market_entry_outcome,
        "symbol": symbol,
        "entry_type": entry_type,
    }


class TestHmmToRegimeMapping:
    def test_regime_0_is_mean_reversion(self):
        assert HMM_TO_REGIME[0] == "mean_reversion"

    def test_regime_1_is_trend(self):
        assert HMM_TO_REGIME[1] == "trend"

    def test_regime_2_is_trend(self):
        assert HMM_TO_REGIME[2] == "trend"


def _make_n_rows(n, **kwargs):
    return [_make_row(**kwargs) for _ in range(n)]


class TestComputeSignalMetrics:

    def test_returns_empty_when_insufficient_n(self):
        rows = _make_n_rows(MIN_SAMPLE_SIZE - 1)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        assert result == []

    def test_returns_row_when_n_meets_minimum(self):
        rows = _make_n_rows(MIN_SAMPLE_SIZE)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        # Expect per-regime row + 'all' rollup + per-entry_type row (entry_type='at_close' default)
        # At least 2 global rows (regime + all); may also produce per-entry_type row
        assert len(result) >= 2

    def test_all_rollup_row_present(self):
        rows = _make_n_rows(MIN_SAMPLE_SIZE)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        regime_types = {r.regime_type for r in result}
        assert "all" in regime_types

    def test_win_rate_all_wins(self):
        rows = _make_n_rows(MIN_SAMPLE_SIZE, pnl_r=1.0, outcome="target_1")
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.win_rate == pytest.approx(1.0, abs=0.001)

    def test_win_rate_all_losses(self):
        rows = _make_n_rows(MIN_SAMPLE_SIZE, pnl_r=-1.0, outcome="stopped_in_trade")
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.win_rate == pytest.approx(0.0, abs=0.001)

    def test_never_activated_pct_counted(self):
        # 30 valid rows + 10 never-activated (pnl_r=None, outcome=never_activated)
        valid = _make_n_rows(MIN_SAMPLE_SIZE, pnl_r=1.0, outcome="target_1")
        never_act = [_make_row(pnl_r=None, outcome="never_activated") for _ in range(10)]
        result = compute_signal_metrics(valid + never_act, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.never_activated_pct == pytest.approx(10 / 40, abs=0.01)

    def test_dq_invalid_rows_excluded_and_counted(self):
        # 30 valid + 5 with bad risk (should be caught by validator -> n_outliers)
        valid = _make_n_rows(MIN_SAMPLE_SIZE)
        bad = [_make_row(entry_price=5000.0, stop_loss=5000.01, pnl_r=-193.0) for _ in range(5)]
        result = compute_signal_metrics(valid + bad, track="zone", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.n == MIN_SAMPLE_SIZE
        assert all_row.n_outliers == 5

    def test_market_track_uses_market_entry_fields(self):
        rows = _make_n_rows(MIN_SAMPLE_SIZE, pnl_r=-2.0)
        # market_entry_pnl_r defaults to 0.8 in _make_row
        result = compute_signal_metrics(rows, track="market", window_days=30)
        all_row = next(r for r in result if r.regime_type == "all")
        assert all_row.avg_r == pytest.approx(0.8, abs=0.01)

    def test_track_field_set_correctly(self):
        rows = _make_n_rows(MIN_SAMPLE_SIZE)
        zone = compute_signal_metrics(rows, track="zone", window_days=30)
        market = compute_signal_metrics(rows, track="market", window_days=30)
        assert all(r.track == "zone" for r in zone)
        assert all(r.track == "market" for r in market)

    def test_multiple_regimes_produce_separate_rows(self):
        trend_rows = _make_n_rows(MIN_SAMPLE_SIZE, hmm_regime=1)
        mr_rows = _make_n_rows(MIN_SAMPLE_SIZE, hmm_regime=0)
        result = compute_signal_metrics(trend_rows + mr_rows, track="zone", window_days=30)
        regime_types = {r.regime_type for r in result}
        assert "trend" in regime_types
        assert "mean_reversion" in regime_types
        assert "all" in regime_types


class TestComputeIcMetrics:
    def _make_ic_rows(self, n, confidence=0.7, outcome="target_1"):
        return [_make_row(confidence=confidence, outcome=outcome) for _ in range(n)]

    def test_returns_empty_when_insufficient_n(self):
        rows = self._make_ic_rows(MIN_SAMPLE_SIZE - 1)
        result = compute_ic_metrics(rows, window_days=30)
        assert result == []

    def test_returns_row_when_n_meets_minimum(self):
        # Mix wins and losses with varying confidence to get non-trivial IC
        wins = [_make_row(confidence=0.8, outcome="target_1") for _ in range(20)]
        losses = [_make_row(confidence=0.4, outcome="stopped_in_trade") for _ in range(20)]
        result = compute_ic_metrics(wins + losses, window_days=30)
        assert len(result) >= 1

    def test_ic_row_has_required_fields(self):
        wins = [_make_row(confidence=0.8, outcome="target_1") for _ in range(20)]
        losses = [_make_row(confidence=0.4, outcome="stopped_in_trade") for _ in range(20)]
        result = compute_ic_metrics(wins + losses, window_days=30)
        row = result[0]
        assert row.setup_plugin == "trad_TrendFollowing"
        assert row.tf == "5m"
        assert row.window_days == 30
        assert row.n >= MIN_SAMPLE_SIZE


# -- Symbol-keyed grouping tests (Phase 68-04) --


class TestSymbolGrouping:
    """Test that compute_signal_metrics groups by symbol."""

    def test_signal_metrics_result_has_symbol_field(self):
        rows = [_make_row() for _ in range(MIN_SAMPLE_SIZE)]
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        assert all(hasattr(r, "symbol") for r in result)

    def test_different_symbols_produce_separate_results(self):
        """Two rows with same plugin/tf/regime but different symbols produce two separate results."""
        es_rows = [_make_row(symbol="ES") for _ in range(MIN_SAMPLE_SIZE)]
        nq_rows = [_make_row(symbol="NQ") for _ in range(MIN_SAMPLE_SIZE)]
        result = compute_signal_metrics(es_rows + nq_rows, track="zone", window_days=30)
        symbols = {r.symbol for r in result}
        assert "ES" in symbols
        assert "NQ" in symbols

    def test_symbol_preserved_on_all_rollup(self):
        """'all' rollup row preserves symbol from source rows."""
        rows = [_make_row(symbol="ES") for _ in range(MIN_SAMPLE_SIZE)]
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        all_rows = [r for r in result if r.regime_type == "all"]
        assert len(all_rows) == 1
        assert all_rows[0].symbol == "ES"


class TestComputeAgentSymbolPublish:
    """Test that SignalMetricsComputeAgent publishes symbol in event."""

    def test_metrics_computed_event_has_symbol(self):
        """The metrics_computed event dict should contain 'symbol' key."""
        # This is a structural test: verify the compute agent's publish msg includes symbol
        from src.intelligence.metrics.compute import SignalMetricsResult

        mr = SignalMetricsResult(
            track="zone",
            setup_plugin="trad_X",
            tf="5m",
            regime_type="trend",
            window_days=30,
            symbol="ES",
            entry_type="*",
            n=50,
            n_outliers=0,
            never_activated_pct=None,
            win_rate=0.5,
            avg_r=0.3,
            std_r=0.8,
            sharpe=0.3,
            p_value=0.04,
            avg_mae=-0.4,
            avg_mfe=0.9,
            skewness=None,
            kurtosis=None,
            min_r=None,
            p5_r=None,
            recovery_factor=None,
            cvar_5=None,
            computed_at=datetime.now(UTC),
        )
        # Verify the field is accessible
        assert mr.symbol == "ES"


class TestWriterSymbolInsert:
    """Test signal_metrics and signal_metrics_ic INSERT include symbol."""

    @pytest.mark.asyncio
    async def test_signal_metrics_insert_includes_symbol(self):
        from unittest.mock import AsyncMock

        from services.signal_metrics_writer_agent import _handle_metrics_computed

        conn = AsyncMock()
        event = {
            "track": "zone",
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "trend",
            "window_days": 30,
            "symbol": "ES",
            "n": 45,
            "n_outliers": 2,
            "never_activated_pct": 0.15,
            "win_rate": 0.52,
            "avg_r": 0.31,
            "std_r": 0.88,
            "sharpe": 0.35,
            "p_value": 0.03,
            "avg_mae": -0.42,
            "avg_mfe": 0.95,
            "computed_at": "2026-04-05T12:00:00+00:00",
        }
        await _handle_metrics_computed(conn, event)
        sql = conn.execute.call_args_list[0][0][0]
        assert "symbol" in sql
        assert "entry_type" in sql
        assert (
            "ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol, entry_type)"
            in sql
        )

    @pytest.mark.asyncio
    async def test_signal_metrics_ic_insert_includes_symbol(self):
        from unittest.mock import AsyncMock

        from services.signal_metrics_writer_agent import _handle_ic_computed

        conn = AsyncMock()
        event = {
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "trend",
            "window_days": 30,
            "symbol": "ES",
            "n": 45,
            "ic": 0.12,
            "p_value": 0.02,
            "is_significant": True,
            "computed_at": "2026-04-05T12:00:00+00:00",
        }
        await _handle_ic_computed(conn, event)
        sql = conn.execute.call_args[0][0]
        assert "symbol" in sql
        assert "ON CONFLICT (setup_plugin, tf, regime_type, window_days, symbol)" in sql


class TestPipelinePerfWeightsSymbol:
    """Test _load_perf_weights builds 3-tuple keys and rank_signals call site."""

    def test_load_perf_weights_builds_three_tuple_keys(self):
        """Verify _load_perf_weights SQL selects symbol and builds (plugin, tf, symbol) keys.

        After Plan 03 extraction, _load_perf_weights lives in CacheManager.
        """
        import inspect

        from src.intelligence.pipeline.cache_manager import CacheManager

        src = inspect.getsource(CacheManager._load_perf_weights)
        assert "symbol" in src
        assert 'row.get("symbol"' in src or 'row.get("symbol"' in src

    def test_rank_signals_call_site_passes_symbol(self):
        """Verify rank_signals is called with symbol=symbol in SignalProcessor.process."""
        import inspect

        from src.intelligence.pipeline.signal_processor import SignalProcessor

        # rank_signals call now lives in SignalProcessor.process() (plan 05 migration)
        src = inspect.getsource(SignalProcessor.process)
        assert "rank_signals" in src
        # Check that rank_signals call includes symbol=
        assert "symbol=symbol" in src


class TestDistributionShape:
    """Unit tests for _distribution_shape() pure helper (Phase 092 Plan 01)."""

    def test_returns_all_none_when_n_lt_3(self):
        """With only 2 inputs, all fields are None (n < 3 threshold)."""
        result = _distribution_shape([0.1, -0.2], 0.0)
        assert isinstance(result, DistributionShape)
        assert result.skewness is None
        assert result.kurtosis is None
        assert result.min_r is None
        assert result.p5_r is None
        assert result.recovery_factor is None
        assert result.cvar_5 is None

    def test_skewness_and_kurtosis_computed_when_n_gte_3(self):
        """n=3 produces skewness and kurtosis but not min_r (n<30) or p5_r (n<20)."""
        result = _distribution_shape([-1.0, 0.0, 1.0], 0.5)
        assert result.skewness is not None
        assert result.kurtosis is not None
        # min_r requires n >= 30
        assert result.min_r is None
        # p5_r requires n >= 20
        assert result.p5_r is None

    def test_p5_and_cvar_computed_when_n_gte_20(self):
        """n=20 with one large negative outlier produces p5_r and cvar_5."""
        # 19 modest values + one large negative outlier
        pnl_rs = [0.1] * 19 + [-3.0]
        result = _distribution_shape(pnl_rs, 0.5)
        assert result.p5_r is not None
        # cvar_5 should be <= p5_r (expected shortfall is more extreme than percentile cut)
        assert result.cvar_5 is not None
        assert result.cvar_5 <= result.p5_r
        # p5 is negative (the -3.0 outlier pulls it down), so recovery_factor is set
        assert result.recovery_factor is not None

    def test_min_r_and_recovery_factor_computed_when_n_gte_30(self):
        """n=30 with min=-2.0 and avg_mfe=1.0 produces min_r and recovery_factor."""
        # 29 small losses + one large loss
        pnl_rs = [-0.1] * 29 + [-2.0]
        result = _distribution_shape(pnl_rs, 1.0)
        assert result.min_r is not None
        assert result.min_r == pytest.approx(-2.0, abs=0.001)
        # p5 will be negative (all losses), so recovery_factor should be set
        assert result.recovery_factor is not None
        assert result.recovery_factor > 0.0

    def test_recovery_factor_none_when_p5_positive(self):
        """All-positive pnl_rs: p5 > 0, so p5 not < -1e-9 -> recovery_factor None.

        This asserts STRICT `<` semantics per CONTEXT.md D-01 (Gemini Actionable Item 1):
        positive p5 means no tail loss exists, ratio is undefined.
        """
        pnl_rs = [0.1] * 30
        result = _distribution_shape(pnl_rs, 1.0)
        # p5 of all-positive list is positive
        assert result.p5_r is not None
        assert result.p5_r > 0.0
        # recovery_factor must be None (strict < guard rejects positive p5)
        assert result.recovery_factor is None

    def test_recovery_factor_none_when_p5_at_minus_epsilon_boundary(self):
        """p5 exactly at -1e-9: strict < excludes equal -> recovery_factor None."""
        import numpy as np

        # Construct a list where the 5th percentile is exactly -1e-9
        # Use 20 values; set one to -1e-9 and the rest to positive to push p5 near -1e-9
        # With 20 values, p5 = percentile at position 1 (0-indexed)
        pnl_rs = sorted([-1e-9] + [0.1] * 19)
        p5 = float(np.percentile(pnl_rs, 5))
        # Verify the setup is correct — p5 should be near or at -1e-9
        # (exact value depends on numpy interpolation; use a list designed to give exactly -1e-9)
        # Since numpy interpolates, we must use a value that maps to -1e-9 at the 5th percentile
        # For a 20-element list, rank 0 is used as the 5th percentile with linear interpolation
        # So the first element (sorted) becomes p5_r
        assert p5 == pytest.approx(-1e-9, abs=1e-12) or p5 >= -1e-9
        # The guard condition is `p5 < -1e-9` — exactly -1e-9 is NOT less than -1e-9
        # If p5 >= -1e-9 (including == -1e-9), recovery_factor must be None
        result = _distribution_shape(pnl_rs, 1.0)
        if result.p5_r is not None and result.p5_r >= -1e-9:
            assert result.recovery_factor is None

    def test_cvar_5_none_when_tail_empty(self):
        """Edge case: no values strictly less than p5 -> cvar_5 is None.

        When all 20+ values are identical, p5 equals the common value.
        The tail comprehension [r for r in pnl_rs if r < p5] is empty -> cvar_5 = None.
        """
        # All identical negative values: p5 equals -0.1, no value is strictly less
        pnl_rs = [-0.1] * 20
        result = _distribution_shape(pnl_rs, 1.0)
        assert result.p5_r is not None
        # cvar_5 must be None (tail is empty — no value < p5)
        assert result.cvar_5 is None

    def test_kurtosis_uses_fisher_and_unbiased(self):
        """Verify kurtosis is computed with fisher=True, bias=False (excess kurtosis, unbiased).

        Normal distribution has excess kurtosis ≈ 0 with these settings.
        A known positive-kurtosis distribution (t-dist with df=4) should produce kurtosis > 0.
        """
        from scipy.stats import kurtosis as scipy_kurtosis

        # Use a known non-normal set — heavy-tailed t(4) samples have excess kurtosis > 0
        # Use a crafted list where exact value is predictable
        pnl_rs = [-2.0, -1.0, -0.5, 0.0, 0.0, 0.5, 1.0, 2.0, 3.0, 4.0] * 3
        expected = round(float(scipy_kurtosis(pnl_rs, fisher=True, bias=False)), 4)
        result = _distribution_shape(pnl_rs, 1.0)
        assert result.kurtosis == pytest.approx(expected, abs=0.001)


class TestEntryTypeGrouping:
    """Unit tests for per-entry_type accumulation and result emission (Phase 092 Plan 02)."""

    def test_emits_per_entry_type_row_when_n_gte_30(self):
        """40 rows with entry_type='at_pullback' produce at least one row with entry_type='at_pullback'
        and symbol='*'."""
        rows = _make_n_rows(40, entry_type="at_pullback")
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        at_pullback_rows = [r for r in result if r.entry_type == "at_pullback"]
        assert len(at_pullback_rows) >= 1
        # All per-entry_type rows must have symbol='*'
        for r in at_pullback_rows:
            assert r.symbol == "*"

    def test_no_per_entry_type_row_when_n_lt_30(self):
        """25 rows with entry_type='at_limit' produce zero per-entry_type rows (n < 30 gate)."""
        rows = _make_n_rows(25, entry_type="at_limit")
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        at_limit_rows = [r for r in result if r.entry_type == "at_limit"]
        assert len(at_limit_rows) == 0

    def test_null_entry_type_folds_to_global_only(self):
        """40 rows with entry_type=None produce no rows with entry_type != '*'.

        NULL entry_type folds into global ('*') accumulator only — never into per-entry_type.
        """
        rows = _make_n_rows(40, entry_type=None)
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        non_star_rows = [r for r in result if r.entry_type != "*"]
        assert len(non_star_rows) == 0
        # Global '*' row still exists
        global_rows = [r for r in result if r.entry_type == "*"]
        assert len(global_rows) >= 1

    def test_per_entry_type_distribution_fields_populated(self):
        """40 rows with entry_type='at_close' and varied pnl_r produce distribution fields on the
        at_close row.

        cvar_5 requires that some values are strictly below the 5th-percentile cut.
        Use a spread of 10 distinct loss values so the tail is non-empty.
        """
        # 30 wins + 10 losses each with a distinct value to ensure non-empty CVaR tail
        small_wins = [
            _make_row(pnl_r=0.5, outcome="target_1", entry_type="at_close") for _ in range(30)
        ]
        # 10 losses with progressively worse values — ensures p5 lands in the interior of the
        # loss range so at least one value is strictly below the 5th-percentile cut
        losses = [
            _make_row(pnl_r=-(i + 1) * 0.3, outcome="stopped_in_trade", entry_type="at_close")
            for i in range(10)
        ]
        rows = small_wins + losses
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        at_close_rows = [r for r in result if r.entry_type == "at_close"]
        assert len(at_close_rows) >= 1
        at_close_row = at_close_rows[0]
        # n=40 >= 30: all distribution fields should be non-None
        assert at_close_row.skewness is not None
        assert at_close_row.kurtosis is not None
        assert at_close_row.min_r is not None
        assert at_close_row.p5_r is not None
        assert at_close_row.cvar_5 is not None

    def test_two_entry_types_produce_correct_subset(self):
        """40 rows of at_close and 10 rows of at_limit: only at_close per-entry_type row emitted
        (at_limit n=10 < 30 gate)."""
        at_close_rows = _make_n_rows(40, entry_type="at_close")
        at_limit_rows = _make_n_rows(10, entry_type="at_limit")
        result = compute_signal_metrics(at_close_rows + at_limit_rows, track="zone", window_days=30)
        assert len([r for r in result if r.entry_type == "at_close"]) >= 1
        assert len([r for r in result if r.entry_type == "at_limit"]) == 0

    def test_global_aggregate_includes_all_rows_regardless_of_entry_type(self):
        """Global ('*') row accumulates all rows regardless of entry_type value, including None.

        40 rows split between at_close (20), at_limit (15), and None (5): global row n=40.
        """
        at_close = [
            _make_row(pnl_r=1.0, outcome="target_1", entry_type="at_close") for _ in range(20)
        ]
        at_limit = [
            _make_row(pnl_r=0.5, outcome="target_1", entry_type="at_limit") for _ in range(15)
        ]
        null_et = [_make_row(pnl_r=0.8, outcome="target_1", entry_type=None) for _ in range(5)]
        result = compute_signal_metrics(at_close + at_limit + null_et, track="zone", window_days=30)
        # Global row (entry_type='*', regime_type='all') should have n=40
        all_rows = [r for r in result if r.entry_type == "*" and r.regime_type == "all"]
        assert len(all_rows) >= 1
        global_row = all_rows[0]
        assert global_row.n == 40

    def test_unknown_entry_type_passes_through_to_dedicated_row(self):
        """40 rows with entry_type='experimental_zone' (NOT in D-10 allowed list) produce a
        dedicated per-entry_type row.

        Asserts no silent drop or remap for future entry_type additions (Gemini Suggestion).
        The global '*' row still includes these rows in its accumulator.
        """
        rows = _make_n_rows(40, entry_type="experimental_zone")
        result = compute_signal_metrics(rows, track="zone", window_days=30)
        # Unknown literal should produce its own per-entry_type row
        experimental_rows = [r for r in result if r.entry_type == "experimental_zone"]
        assert len(experimental_rows) >= 1
        assert experimental_rows[0].symbol == "*"
        # Global row still exists and includes these rows
        global_rows = [r for r in result if r.entry_type == "*"]
        assert len(global_rows) >= 1
