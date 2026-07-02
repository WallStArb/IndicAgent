"""Tests for _run_ensemble_ic_worker's per-worker DB fetch (todo 047).

Confirms each worker fetches its own (symbol, tf) slice over its own read-only
psycopg2 connection rather than receiving pre-fetched arrays from the main process,
and that a connection/query failure in one worker surfaces as an error result rather
than an unhandled exception -- so the main process's exe.map() loop can skip a failed
worker and continue instead of the whole corpus run crashing on one bad connection.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.ensemble_ic_engine import EnsembleICConfig, _run_ensemble_ic_worker


def _make_config(**overrides) -> EnsembleICConfig:
    defaults = dict(
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_min_windows=30,
        subsample_min_stride=1,
        min_reliable_n=5,
        hac_max_lag=3,
        lookahead_fast=1,
        lookahead_mid=5,
        lookahead_slow=20,
        lookahead_extended=60,
        n_workers=1,
        decay_threshold=0.1,
        min_qualifying_fraction=0.6,
        wf_stability_ratio=3.0,
        gate_lookahead="fast",
        wf_stability_metric="ic_ratio",
        min_obs_per_regime=3,
    )
    defaults.update(overrides)
    return EnsembleICConfig(**defaults)


def _mock_cursor(rows: list[dict]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    return cur


def _worker_args(config: EnsembleICConfig) -> tuple:
    return (
        "SPY",
        "5m",
        "postgresql://fake",
        datetime(2026, 1, 1, tzinfo=UTC),
        config,
        datetime.now(UTC),
    )


class TestWorkerFetch:
    def test_fetches_and_computes_ic_for_symbol_tf(self):
        fetched_rows = [
            {
                "alpha_score": float(i % 5) - 2.0,
                "return_fast": float(i % 5) * 0.001,
                "return_mid": float(i % 5) * 0.002,
                "return_slow": float(i % 5) * 0.003,
                "return_extended": float(i % 5) * 0.004,
                "regime_label": "bull",
            }
            for i in range(20)
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _mock_cursor(fetched_rows)

        with patch("services.ensemble_ic_engine.psycopg2.connect", return_value=mock_conn):
            result = _run_ensemble_ic_worker(_worker_args(_make_config()))

        assert result["error"] is None
        assert len(result["rows"]) > 0
        assert all(row["symbol"] == "SPY" and row["tf"] == "5m" for row in result["rows"])
        mock_conn.close.assert_called_once()

    def test_returns_empty_when_no_rows(self):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _mock_cursor([])

        with patch("services.ensemble_ic_engine.psycopg2.connect", return_value=mock_conn):
            result = _run_ensemble_ic_worker(_worker_args(_make_config()))

        assert result == {
            "rows": [],
            "pvals": [],
            "pval_idxs": [],
            "is_pooled": False,
            "error": None,
        }
        mock_conn.close.assert_called_once()

    def test_connection_failure_returns_error_instead_of_raising(self):
        with patch(
            "services.ensemble_ic_engine.psycopg2.connect", side_effect=RuntimeError("boom")
        ):
            result = _run_ensemble_ic_worker(_worker_args(_make_config()))

        assert result["rows"] == []
        assert result["pvals"] == []
        assert result["pval_idxs"] == []
        assert result["error"] is not None
        assert "SPY/5m" in result["error"]

    def test_pooled_symbol_sets_is_pooled_true(self):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _mock_cursor([])

        with patch("services.ensemble_ic_engine.psycopg2.connect", return_value=mock_conn):
            result = _run_ensemble_ic_worker(
                (
                    "POOLED",
                    "5m",
                    "postgresql://fake",
                    datetime(2026, 1, 1, tzinfo=UTC),
                    _make_config(),
                    datetime.now(UTC),
                )
            )

        assert result["is_pooled"] is True
