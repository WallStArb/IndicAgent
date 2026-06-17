"""Tests for CIS weight updater."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.trading.cis_scorer import BOOTSTRAP_WEIGHTS, BUCKET_NAMES
from src.intelligence.weight_updater import (
    ASSET_CLUSTER_MAP,
    MIN_SAMPLES_TRAIN,
    WIN_OUTCOMES,
    WeightUpdateResult,
    compute_new_weights,
    get_asset_cluster,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    outcome: str = "target_1",
    trend: float = 0.3,
    momentum: float = 0.2,
    structure: float = 0.1,
    pattern: float = 0.05,
    institutional: float = 0.25,
    regime: float = 0.1,
    symbol: str = "ES",
    timeframe: str = "1m",
) -> dict:
    return {
        "bucket_scores": {
            "trend": trend,
            "momentum": momentum,
            "structure": structure,
            "pattern": pattern,
            "institutional": institutional,
            "regime": regime,
        },
        "outcome": outcome,
        "symbol": symbol,
        "timeframe": timeframe,
    }


def _varied_signals(n: int, symbol: str = "ES", timeframe: str = "1m") -> list[dict]:
    """Generate n signals with varied outcomes (cycles win/loss/loss)."""
    outcomes = ["target_1", "stopped_in_trade", "ttl_expired_behind"]
    return [
        _make_signal(outcome=outcomes[i % 3], symbol=symbol, timeframe=timeframe) for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Tests: WIN_OUTCOMES constant
# ---------------------------------------------------------------------------


class TestWinOutcomes:
    def test_win_outcomes_frozenset_contains_three_wins(self):
        assert WIN_OUTCOMES == frozenset({"target_1", "target_1_2", "target_full"})

    def test_win_outcomes_is_frozenset(self):
        assert isinstance(WIN_OUTCOMES, frozenset)


# ---------------------------------------------------------------------------
# Tests: ASSET_CLUSTER_MAP and get_asset_cluster
# ---------------------------------------------------------------------------


class TestAssetClusterMap:
    def test_eq_index_cluster(self):
        assert get_asset_cluster("ES") == "eq_index"
        assert get_asset_cluster("NQ") == "eq_index"
        assert get_asset_cluster("RTY") == "eq_index"
        assert get_asset_cluster("YM") == "eq_index"

    def test_commodity_cluster(self):
        assert get_asset_cluster("CL") == "commodity"
        assert get_asset_cluster("GC") == "commodity"
        assert get_asset_cluster("SI") == "commodity"
        assert get_asset_cluster("NG") == "commodity"
        assert get_asset_cluster("HG") == "commodity"
        assert get_asset_cluster("PL") == "commodity"
        assert get_asset_cluster("PA") == "commodity"

    def test_rates_cluster(self):
        assert get_asset_cluster("ZN") == "rates"
        assert get_asset_cluster("ZB") == "rates"
        assert get_asset_cluster("ZF") == "rates"
        assert get_asset_cluster("ZT") == "rates"

    def test_crypto_cluster(self):
        assert get_asset_cluster("BTC") == "crypto"
        assert get_asset_cluster("ETH") == "crypto"
        assert get_asset_cluster("SOL") == "crypto"

    def test_ag_cluster(self):
        assert get_asset_cluster("ZC") == "ag"
        assert get_asset_cluster("ZS") == "ag"
        assert get_asset_cluster("ZW") == "ag"

    def test_global_fallback_for_etf(self):
        assert get_asset_cluster("SPY") == "global"
        assert get_asset_cluster("QQQ") == "global"
        assert get_asset_cluster("VX") == "global"

    def test_asset_cluster_map_has_21_symbols(self):
        # eq_index(4) + commodity(7) + rates(4) + crypto(3) + ag(3) = 21
        assert len(ASSET_CLUSTER_MAP) == 21

    def test_asset_cluster_map_coverage(self):
        """Spot-check expected mappings."""
        assert get_asset_cluster("ES") == "eq_index"
        assert get_asset_cluster("BTC") == "crypto"
        assert get_asset_cluster("ZC") == "ag"
        assert get_asset_cluster("SPY") == "global"


# ---------------------------------------------------------------------------
# Tests: compute_new_weights — binary labels
# ---------------------------------------------------------------------------


class TestComputeNewWeightsBinaryLabels:
    def test_binary_labels_win_outcomes(self):
        """60 win signals + 40 loss signals → win_rate ≈ 0.60."""
        win_signals = [_make_signal(outcome="target_1") for _ in range(60)]
        loss_signals = [_make_signal(outcome="stopped_in_trade") for _ in range(40)]
        result = compute_new_weights(win_signals + loss_signals)
        assert result is not None
        assert abs(result.win_rate - 0.60) < 1e-6

    def test_binary_labels_all_three_win_outcomes(self):
        """All three WIN_OUTCOMES are treated as wins."""
        signals = (
            [_make_signal(outcome="target_1") for _ in range(30)]
            + [_make_signal(outcome="target_1_2") for _ in range(20)]
            + [_make_signal(outcome="target_full") for _ in range(10)]
            + [_make_signal(outcome="stopped_in_trade") for _ in range(40)]
        )
        result = compute_new_weights(signals)
        assert result is not None
        assert abs(result.win_rate - 0.60) < 1e-6

    def test_binary_labels_loss_outcomes_all_zero(self):
        """Loss outcomes map to 0.0 label."""
        loss_outcomes = [
            "stopped_at_entry",
            "stopped_in_trade",
            "never_activated",
            "ttl_expired_ahead",
            "ttl_expired_behind",
            "condition_expired",
        ]
        # 60 losses (various), 40 wins to avoid degenerate
        signals = [
            _make_signal(outcome=loss_outcomes[i % len(loss_outcomes)]) for i in range(60)
        ] + [_make_signal(outcome="target_1") for _ in range(40)]
        result = compute_new_weights(signals)
        assert result is not None
        assert abs(result.win_rate - 0.40) < 1e-6

    def test_binary_labels_ignores_signal_quality(self):
        """Signals with signal_quality=None but valid outcome still train."""
        signals = []
        for i in range(60):
            s = _make_signal(outcome="target_1" if i % 2 == 0 else "stopped_in_trade")
            s["signal_quality"] = None  # explicitly None
            signals.append(s)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.n_resolved == 60

    def test_filters_signals_with_no_outcome(self):
        """Signals without outcome are filtered out."""
        valid = _varied_signals(60)
        missing = [
            {
                "bucket_scores": {
                    "trend": 0.1,
                    "momentum": 0.1,
                    "structure": 0.1,
                    "pattern": 0.1,
                    "institutional": 0.1,
                    "regime": 0.1,
                }
            }
            for _ in range(20)
        ]
        result = compute_new_weights(valid + missing)
        if result is not None:
            assert result.n_resolved == 60

    def test_returns_none_below_min_samples(self):
        """Under 50 samples → None."""
        signals = _varied_signals(MIN_SAMPLES_TRAIN - 1)
        assert compute_new_weights(signals) is None

    def test_returns_none_with_zero_samples(self):
        assert compute_new_weights([]) is None

    def test_returns_blended_at_50_to_99_samples(self):
        """50-99 samples → blend mode."""
        signals = _varied_signals(75)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.weights_type == "blended"
        assert result.did_retrain is True

    def test_returns_learned_at_100_plus_samples(self):
        """100+ samples → learned weights."""
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.weights_type == "learned"

    def test_weights_sum_to_one_learned(self):
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_weights_sum_to_one_blended(self):
        signals = _varied_signals(75)
        result = compute_new_weights(signals)
        assert result is not None
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_all_weights_above_minimum_learned(self):
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        for bucket, w in result.weights.items():
            assert w >= 0.05, f"Bucket {bucket} weight {w} below minimum 0.05"

    def test_all_6_buckets_present(self):
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        assert set(result.weights.keys()) == set(BUCKET_NAMES)

    def test_n_resolved_correct(self):
        signals = _varied_signals(55)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.n_resolved == 55

    def test_bucket_scores_as_json_string(self):
        """bucket_scores may arrive as a JSON string from asyncpg JSONB rows."""
        bs = json.dumps(
            {
                "trend": 0.4,
                "momentum": 0.3,
                "structure": 0.2,
                "pattern": 0.05,
                "institutional": 0.2,
                "regime": 0.15,
            }
        )
        signals_a = [{"bucket_scores": bs, "outcome": "target_1"} for _ in range(30)]
        signals_b = [{"bucket_scores": bs, "outcome": "stopped_in_trade"} for _ in range(30)]
        result = compute_new_weights(signals_a + signals_b)
        assert result is not None
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_returns_none_with_all_wins_degenerate(self):
        """All signals are wins → degenerate target (all 1s) → None."""
        signals = [_make_signal(outcome="target_1") for _ in range(60)]
        result = compute_new_weights(signals)
        assert result is None

    def test_returns_none_with_all_losses_degenerate(self):
        """All signals are losses → degenerate target (all 0s) → None."""
        signals = [_make_signal(outcome="stopped_in_trade") for _ in range(60)]
        result = compute_new_weights(signals)
        assert result is None

    def test_filters_rows_missing_bucket_scores(self):
        valid = _varied_signals(60)
        missing = [{"bucket_scores": None, "outcome": "target_1"} for _ in range(20)]
        result = compute_new_weights(valid + missing)
        if result is not None:
            assert result.n_resolved == 60


# ---------------------------------------------------------------------------
# Tests: WeightUpdateResult — win_rate field (not signal_quality_mean)
# ---------------------------------------------------------------------------


class TestWeightUpdateResultHasWinRate:
    def test_weight_update_result_has_win_rate(self):
        """WeightUpdateResult must have win_rate field."""
        result = WeightUpdateResult(
            n_resolved=100,
            weights_type="learned",
            weights={
                "trend": 0.2,
                "momentum": 0.2,
                "structure": 0.15,
                "pattern": 0.05,
                "institutional": 0.25,
                "regime": 0.15,
            },
            win_rate=0.55,
            did_retrain=True,
            asset_cluster="global",
            timeframe="global",
        )
        assert hasattr(result, "win_rate")
        assert result.win_rate == 0.55

    def test_weight_update_result_no_signal_quality_mean(self):
        """WeightUpdateResult must NOT have signal_quality_mean field."""
        result = WeightUpdateResult(
            n_resolved=100,
            weights_type="learned",
            weights={},
            win_rate=0.5,
            did_retrain=True,
        )
        assert not hasattr(result, "signal_quality_mean")

    def test_weight_update_result_has_asset_cluster(self):
        """WeightUpdateResult must have asset_cluster field."""
        result = WeightUpdateResult(
            n_resolved=100,
            weights_type="learned",
            weights={},
            win_rate=0.5,
            did_retrain=True,
        )
        assert hasattr(result, "asset_cluster")
        assert result.asset_cluster == "global"

    def test_weight_update_result_has_timeframe(self):
        result = WeightUpdateResult(
            n_resolved=100,
            weights_type="learned",
            weights={},
            win_rate=0.5,
            did_retrain=True,
            asset_cluster="eq_index",
            timeframe="1m",
        )
        assert result.timeframe == "1m"

    def test_compute_new_weights_result_has_win_rate(self):
        """compute_new_weights result has win_rate, not signal_quality_mean."""
        signals = _varied_signals(100)
        result = compute_new_weights(signals)
        assert result is not None
        assert hasattr(result, "win_rate")
        assert not hasattr(result, "signal_quality_mean")

    def test_bootstrap_weights_referenced_correctly(self):
        """BOOTSTRAP_WEIGHTS sum to 1.0 — sanity check for the designed fallback."""
        total = sum(BOOTSTRAP_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Tests: run_weight_update — shadow filter and cluster training
# ---------------------------------------------------------------------------


class TestRunWeightUpdate:
    @pytest.mark.asyncio
    async def test_run_weight_update_is_v211_noop(self):
        """run_weight_update is a V2.11_ACTIVATED no-op.

        bucket_scores-based weight learning read columns that were dropped in the
        3-table migration (Phase 127-00). The DB-querying path is disabled until
        v2.11 reintroduces IC-based weight learning from raw_confidence. Until then
        run_weight_update must return None and touch no DB methods — which also
        guarantees no shadow signal can pollute a training set that never runs.
        """
        from src.intelligence.weight_updater import run_weight_update

        db = MagicMock()
        db.execute_query = AsyncMock()
        db.execute_command = AsyncMock()

        result = await run_weight_update(db)

        assert result is None
        db.execute_query.assert_not_called()
        db.execute_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_version_counter_per_cluster(self):
        """Version counter uses MAX(version) WHERE asset_cluster=$1 AND timeframe=$2."""
        import inspect

        import src.intelligence.weight_updater as wu

        source = inspect.getsource(wu._write_weights_to_db)
        assert "asset_cluster" in source
        assert "timeframe" in source
        # Check the version query uses cluster + timeframe params
        assert "WHERE asset_cluster = $1 AND timeframe = $2" in source
