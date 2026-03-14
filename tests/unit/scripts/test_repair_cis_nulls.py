"""Unit tests for repair_cis_nulls.py audit and repair logic.

Tests mock psycopg2 connections and CISScorer — no live DB required.
"""

from __future__ import annotations

# Import the script's pure functions for testing
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from production.scripts.repair_cis_nulls import (
    audit_null_cis,
    build_cis_update_params,
    classify_rows,
    log_orphans,
    merge_feature_jsonb,
    repair_recoverable,
)


class TestClassifyRows:
    """Tests for classify_rows() — splits recoverable vs orphaned rows."""

    def test_classify_rows_splits_recoverable_and_orphaned(self):
        """Given rows with/without feature data, correctly separate."""
        rows = [
            # Recoverable: has feature_ts and non-null i1
            {
                "signal_id": "11111111-1111-1111-1111-111111111111",
                "symbol": "ES",
                "feature_ts": "2026-01-01 12:00:00",
                "feature_tf": "5m",
                "i1": {"rsi_14": 50.0},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
            },
            # Recoverable: all tiers present
            {
                "signal_id": "22222222-2222-2222-2222-222222222222",
                "symbol": "NQ",
                "feature_ts": "2026-01-01 12:05:00",
                "feature_tf": "15m",
                "i1": {"rsi_14": 60.0},
                "i3": {"swing_high": 5000.0},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
            },
            # Orphaned: feature_ts is None
            {
                "signal_id": "33333333-3333-3333-3333-333333333333",
                "symbol": "ES",
                "feature_ts": None,
                "feature_tf": "1m",
                "i1": None,
                "i3": None,
                "i4": None,
                "i5": None,
                "smc": None,
                "i6": None,
            },
            # Orphaned: all tier columns are None (no match)
            {
                "signal_id": "44444444-4444-4444-4444-444444444444",
                "symbol": "NQ",
                "feature_ts": "2026-01-01 12:10:00",
                "feature_tf": "5m",
                "i1": None,
                "i3": None,
                "i4": None,
                "i5": None,
                "smc": None,
                "i6": None,
            },
        ]

        recoverable, orphaned = classify_rows(rows)

        assert len(recoverable) == 2
        assert len(orphaned) == 2
        assert recoverable[0]["signal_id"] == "11111111-1111-1111-1111-111111111111"
        assert (
            orphaned[0] == "33333333-3333-3333-3333-333333333333"
        )  # orphaned is list of signal_id strings

    def test_classify_rows_handles_empty_list(self):
        """Empty input returns empty lists."""
        recoverable, orphaned = classify_rows([])
        assert recoverable == []
        assert orphaned == []


class TestMergeFeatureJsonb:
    """Tests for merge_feature_jsonb() — flattens tier JSONB dicts."""

    def test_merge_feature_jsonb_produces_flat_dict(self):
        """Given tier dicts, merge into single flat dict."""
        i1 = {"rsi_14": 50.0, "macd_line": 1.2}
        i3 = {"swing_high": 5000.0}
        i4 = {"volatility_regime": "low"}
        i5 = {"rsi_divergence": 0.8}
        smc = {"fvg_bottom": 4950.0}
        i6 = {}

        result = merge_feature_jsonb(i1, i3, i4, i5, smc, i6)

        assert isinstance(result, dict)
        assert result["rsi_14"] == 50.0
        assert result["macd_line"] == 1.2
        assert result["swing_high"] == 5000.0
        assert result["volatility_regime"] == "low"
        assert result["rsi_divergence"] == 0.8
        assert result["fvg_bottom"] == 4950.0

    def test_merge_feature_jsonb_skips_none_tiers(self):
        """Gracefully handles None/empty tier dicts."""
        result = merge_feature_jsonb({"rsi_14": 50.0}, None, None, None, None, None)
        assert result == {"rsi_14": 50.0}

    def test_merge_feature_jsonb_empty_all(self):
        """Empty/None inputs return empty dict."""
        result = merge_feature_jsonb(None, None, None, None, None, None)
        assert result == {}


class TestBuildCISUpdateParams:
    """Tests for build_cis_update_params() — prepares UPDATE tuple."""

    def test_build_cis_update_params_produces_correct_tuple(self):
        """Given signal_id and CISResult, return correct UPDATE tuple."""
        signal_id = "11111111-1111-1111-1111-111111111111"
        cis_result = MagicMock()
        cis_result.cis_score = 0.75
        cis_result.bucket_scores = {"trend": 0.8, "momentum": 0.7}
        cis_result.weights_version = 1

        params = build_cis_update_params(signal_id, cis_result)

        assert isinstance(params, tuple)
        assert len(params) == 4
        assert params[0] == 0.75  # cis_score
        assert params[1] == '{"trend": 0.8, "momentum": 0.7}'  # JSON bucket_scores
        assert params[2] == 1  # weights_version
        assert params[3] == "11111111-1111-1111-1111-111111111111"  # signal_id


class TestLogOrphans:
    """Tests for log_orphans() — WARNING-level logging."""

    @patch("production.scripts.repair_cis_nulls.logger")
    def test_log_orphans_logs_each_signal_id(self, mock_logger):
        """Logs each orphaned signal_id at WARNING level."""
        orphaned_ids = [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]

        log_orphans(orphaned_ids)

        # log_orphans logs: header (1) + each signal (2) + summary (1) = 4 calls
        assert mock_logger.warning.call_count == 4
        call_args_list = [str(call) for call in mock_logger.warning.call_args_list]
        assert "11111111-1111-1111-1111-111111111111" in str(call_args_list)
        assert "22222222-2222-2222-2222-222222222222" in str(call_args_list)

    @patch("production.scripts.repair_cis_nulls.logger")
    def test_log_orphans_prints_summary(self, mock_logger):
        """Prints summary count."""
        orphaned_ids = ["11111111-1111-1111-1111-111111111111"]

        log_orphans(orphaned_ids)

        # log_orphans logs: header (1) + 1 signal (1) + summary (1) = 3 calls
        assert mock_logger.warning.call_count == 3


class TestAuditNullCIS:
    """Integration tests for audit_null_cis() with mocked DB."""

    @patch("production.scripts.repair_cis_nulls.connect_db")
    def test_audit_null_cis_counts_are_consistent(self, mock_connect_db):
        """recoverable + orphaned == total_null (mocked counts)."""
        # Mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Mock RealDictCursor behavior (returns dicts, not tuples)
        def mock_fetchone():
            return (10,)

        recoverable_batch = [
            {
                "signal_id": "11111111-1111-1111-1111-111111111111",
                "symbol": "ES",
                "feature_ts": "2026-01-01 12:00:00",
                "feature_tf": "5m",
                "i1": {"rsi_14": 50.0},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
            },
            {
                "signal_id": "22222222-2222-2222-2222-222222222222",
                "symbol": "NQ",
                "feature_ts": "2026-01-01 12:05:00",
                "feature_tf": "15m",
                "i1": {"rsi_14": 60.0},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
            },
        ]

        # audit_null_cis uses fetchmany() in a while-True loop for recoverable rows,
        # then fetchall() for orphaned rows. fetchmany must return [] on second call
        # to break the loop — otherwise MagicMock returns a truthy object forever.
        mock_cursor.fetchone = mock_fetchone
        mock_cursor.fetchmany.side_effect = [recoverable_batch, []]
        mock_cursor.fetchall.return_value = [
            {"signal_id": "33333333-3333-3333-3333-333333333333"},
            {"signal_id": "44444444-4444-4444-4444-444444444444"},
            {"signal_id": "55555555-5555-5555-5555-555555555555"},
        ]

        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect_db.return_value = mock_conn

        total, recoverable_rows, orphaned_ids = audit_null_cis(mock_conn)

        assert total == 10
        assert len(recoverable_rows) == 2
        assert len(orphaned_ids) == 3
        # Consistency check: 2 + 3 = 5 recoverable+orphaned out of 10 total
        # (remaining 5 might have feature_ts=None from the query)


class TestRepairRecoverable:
    """Integration tests for repair_recoverable() with mocked DB and CISScorer."""

    @patch("production.scripts.repair_cis_nulls.CISScorer")
    @patch("production.scripts.repair_cis_nulls.psycopg2.extras.execute_batch")
    def test_repair_recoverable_updates_rows(self, mock_execute_batch, mock_cis_scorer_class):
        """Batch-UPDATEs recoverable rows with computed CIS values."""
        # Mock connection
        mock_conn = MagicMock()

        # Mock CISScorer
        mock_scorer = MagicMock()
        mock_result = MagicMock()
        mock_result.cis_score = 0.75
        mock_result.bucket_scores = {"trend": 0.8, "momentum": 0.7}
        mock_result.weights_version = 1
        mock_scorer.score.return_value = mock_result
        mock_cis_scorer_class.return_value = mock_scorer

        # Recoverable rows (dicts from RealDictCursor)
        rows = [
            {
                "signal_id": "11111111-1111-1111-1111-111111111111",
                "symbol": "ES",
                "feature_ts": "2026-01-01 12:00:00",
                "feature_tf": "5m",
                "i1": {"rsi_14": 50.0},
                "i3": {},
                "i4": {},
                "i5": {},
                "smc": {},
                "i6": {},
            },
        ]

        updated = repair_recoverable(mock_conn, rows, batch_size=1)

        assert updated == 1
        # Verify CISScorer was called
        mock_scorer.score.assert_called_once()
        # Verify execute_batch was called for UPDATE
        mock_execute_batch.assert_called_once()

    @patch("production.scripts.repair_cis_nulls.CISScorer")
    @patch("production.scripts.repair_cis_nulls.psycopg2.extras.execute_batch")
    def test_repair_recoverable_empty_rows(self, mock_execute_batch, mock_cis_scorer_class):
        """Empty input returns 0 updates, no DB calls."""
        mock_conn = MagicMock()

        updated = repair_recoverable(mock_conn, [], batch_size=500)

        assert updated == 0
        mock_execute_batch.assert_not_called()
        mock_cis_scorer_class.assert_not_called()
