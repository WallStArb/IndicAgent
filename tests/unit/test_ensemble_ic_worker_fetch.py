"""Tests for _run_ensemble_ic_worker's per-worker DB fetch (todo 047).

Confirms each worker opens ONE read-only connection for its symbol and loops over
all of that symbol's TFs (not one connection per (symbol, tf) pair -- the original
047 fix mirrored ic_engine._run_ic_worker's "own connection" half but missed the
"amortize across TFs" half, doubling back to one connection per symbol), and that a
connection/query failure surfaces as an error result rather than an unhandled
exception -- so the main process's exe.map() loop can skip a failed worker/TF and
continue instead of the whole corpus run crashing on one bad connection.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.ensemble_ic_engine import (
    _POOLED_WORKER_FETCH_SQL,
    _WORKER_FETCH_SQL,
    EnsembleICConfig,
    _run_ensemble_ic_worker,
)


def test_worker_fetch_sql_masks_suspect_returns_to_null():
    """todo 148 price-sanity guard: both fetch paths must mask each scale's
    return_{scale} to NULL in SQL when its own return_{scale}_suspect flag is set
    (a CASE WHEN ... THEN NULL expression) rather than fetching the raw value +
    flag and branching in Python -- fetched rows must NOT carry a separate
    return_{scale}_suspect key (downstream code treats NULL as "exclude" via a
    plain None-check; see the KeyError regression this guards against: an earlier
    version fetched raw value + flag, but _aggregate_pooled_series's reduced
    output never propagated the flag, so the per-symbol worker's shared
    returns_by_scale construction crashed with KeyError on any real pooled-path
    row)."""
    for scale in ("fast", "mid", "slow", "extended"):
        assert f"return_{scale}_suspect" in _WORKER_FETCH_SQL
        assert f"return_{scale}_suspect" in _POOLED_WORKER_FETCH_SQL
        assert "CASE WHEN" in _WORKER_FETCH_SQL
        assert "CASE WHEN" in _POOLED_WORKER_FETCH_SQL


def _make_config(**overrides) -> EnsembleICConfig:
    defaults = dict(
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=2000,
        sharpe_window_size_subsampled=100,
        sharpe_min_windows=30,
        subsample_min_stride=1,
        min_reliable_n=5,
        hac_max_lag=3,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 5, "15m": 5, "1h": 5, "1d": 5},
        lookahead_slow={"5m": 20, "15m": 20, "1h": 20, "1d": 20},
        lookahead_extended={"5m": 60, "15m": 60, "1h": 60, "1d": 60},
        n_workers=1,
        pooled_fetch_itersize=50_000,
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


def _fetched_rows(n: int = 20) -> list[dict]:
    """Mirrors what _WORKER_FETCH_SQL/_POOLED_WORKER_FETCH_SQL actually return post
    todo 148: suspect returns are already NULL-masked in SQL, so fetched rows carry
    only the (possibly-None) return_{scale} value -- no separate *_suspect key."""
    return [
        {
            "alpha_score": float(i % 5) - 2.0,
            "return_fast": float(i % 5) * 0.001,
            "return_mid": float(i % 5) * 0.002,
            "return_slow": float(i % 5) * 0.003,
            "return_extended": float(i % 5) * 0.004,
            "regime_label": "bull",
        }
        for i in range(n)
    ]


def _worker_args(config: EnsembleICConfig, tfs: list[str] | None = None) -> tuple:
    return (
        "SPY",
        tfs if tfs is not None else ["5m"],
        "postgresql://fake",
        datetime(2026, 1, 1, tzinfo=UTC),
        config,
        datetime.now(UTC),
        "v1",
    )


class TestWorkerFetch:
    def test_fetches_and_computes_ic_for_symbol_tf(self):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _mock_cursor(_fetched_rows())

        with patch("services.ensemble_ic_engine.connect_db_from_url", return_value=mock_conn):
            result = _run_ensemble_ic_worker(_worker_args(_make_config()))

        assert result["errors"] == []
        assert len(result["rows"]) > 0
        assert all(row["symbol"] == "SPY" and row["tf"] == "5m" for row in result["rows"])
        mock_conn.close.assert_called_once()

    def test_one_connection_reused_across_all_tfs(self):
        """The whole point of the todo 047 follow-up: one connect_db_from_url call per
        worker dispatch, not one per TF -- connection setup amortized across TFs."""
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _mock_cursor(_fetched_rows())

        with patch(
            "services.ensemble_ic_engine.connect_db_from_url", return_value=mock_conn
        ) as mock_connect:
            result = _run_ensemble_ic_worker(_worker_args(_make_config(), tfs=["5m", "15m", "1h"]))

        mock_connect.assert_called_once_with("postgresql://fake")
        assert mock_conn.cursor.call_count == 3
        assert {row["tf"] for row in result["rows"]} == {"5m", "15m", "1h"}
        mock_conn.close.assert_called_once()

    def test_returns_empty_when_no_rows(self):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _mock_cursor([])

        with patch("services.ensemble_ic_engine.connect_db_from_url", return_value=mock_conn):
            result = _run_ensemble_ic_worker(_worker_args(_make_config()))

        assert result == {
            "rows": [],
            "pvals": [],
            "pval_idxs": [],
            "is_pooled": False,
            "errors": [],
        }
        mock_conn.close.assert_called_once()

    def test_connection_failure_returns_error_instead_of_raising(self):
        with patch(
            "services.ensemble_ic_engine.connect_db_from_url",
            side_effect=RuntimeError("boom"),
        ):
            result = _run_ensemble_ic_worker(_worker_args(_make_config()))

        assert result["rows"] == []
        assert result["pvals"] == []
        assert result["pval_idxs"] == []
        assert len(result["errors"]) == 1
        assert "SPY" in result["errors"][0]

    def test_one_tf_query_failure_does_not_discard_other_tfs(self):
        """A per-TF query error must be recorded and skipped, not abort the whole
        symbol -- the other TFs on the same connection still get scored."""
        good_cursor = _mock_cursor(_fetched_rows())
        bad_cursor = MagicMock()
        bad_cursor.__enter__.return_value = bad_cursor
        bad_cursor.__exit__.return_value = False
        bad_cursor.execute.side_effect = RuntimeError("query failed")

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = [bad_cursor, good_cursor]

        with patch("services.ensemble_ic_engine.connect_db_from_url", return_value=mock_conn):
            result = _run_ensemble_ic_worker(_worker_args(_make_config(), tfs=["5m", "15m"]))

        assert len(result["errors"]) == 1
        assert "SPY/5m" in result["errors"][0]
        assert all(row["tf"] == "15m" for row in result["rows"])
        assert len(result["rows"]) > 0
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_pooled_symbol_sets_is_pooled_true(self):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = _mock_cursor([])

        with patch("services.ensemble_ic_engine.connect_db_from_url", return_value=mock_conn):
            result = _run_ensemble_ic_worker(
                (
                    "POOLED",
                    ["5m"],
                    "postgresql://fake",
                    datetime(2026, 1, 1, tzinfo=UTC),
                    _make_config(),
                    datetime.now(UTC),
                    "v1",
                )
            )

        assert result["is_pooled"] is True

    def test_pooled_symbol_with_real_rows_does_not_crash(self):
        """Regression guard: an earlier version of the todo 148 price-sanity guard
        fetched raw return_{scale} + a separate return_{scale}_suspect flag, but
        _aggregate_pooled_series's reduced output never propagated the suspect keys
        -- the per-symbol worker's shared returns_by_scale construction then did
        r[_SUSPECT_COL_FOR_RETURN_COL[col]] unconditionally and crashed with KeyError
        on the very first non-empty pooled result. test_pooled_symbol_sets_is_pooled_true
        above didn't catch this because it mocks an EMPTY cursor, so the buggy
        code path was never exercised. This test uses non-empty rows (the pooled
        cursor is iterated directly by _aggregate_pooled_series, not .fetchall()'d)
        to prove the worker completes and produces pooled IC rows."""
        raw_rows = [
            {
                "symbol": symbol,
                "bar_ts": datetime(2026, 1, 1, i, tzinfo=UTC),
                "alpha_score": float(i % 5) - 2.0,
                "return_fast": float(i % 5) * 0.001,
                "return_mid": float(i % 5) * 0.002,
                "return_slow": float(i % 5) * 0.003,
                "return_extended": float(i % 5) * 0.004,
                "regime_label": "bull",
            }
            for i in range(20)
            for symbol in ("AAA", "BBB")
        ]
        mock_cursor = MagicMock()
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.__exit__.return_value = False
        mock_cursor.__iter__.return_value = iter(raw_rows)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch("services.ensemble_ic_engine.connect_db_from_url", return_value=mock_conn):
            result = _run_ensemble_ic_worker(
                (
                    "POOLED",
                    ["5m"],
                    "postgresql://fake",
                    datetime(2026, 1, 1, tzinfo=UTC),
                    _make_config(),
                    datetime.now(UTC),
                    "v1",
                )
            )

        assert result["errors"] == []
        assert result["is_pooled"] is True
        assert len(result["rows"]) > 0
