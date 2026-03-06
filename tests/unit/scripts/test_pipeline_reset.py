import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3]))

import pytest
from unittest.mock import MagicMock, patch


def test_preflight_shows_row_counts():
    """Preflight prints table name and row count for each target table."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (42,)

    summary = build_preflight_summary(conn, keep_ohlcv=False, clear_llm=False)

    assert "signal_ledger" in summary
    assert "intelligence_features" in summary
    assert "market_data_ohlcv" in summary
    assert "42" in summary


def test_preflight_omits_ohlcv_when_keep_ohlcv():
    """With --keep-ohlcv, market_data_ohlcv should not appear in summary."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (0,)

    summary = build_preflight_summary(conn, keep_ohlcv=True, clear_llm=False)

    assert "market_data_ohlcv" not in summary


def test_preflight_includes_llm_when_flag_set():
    """With --clear-llm, llm_calls should appear in summary."""
    from production.scripts.pipeline_reset import build_preflight_summary

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (7,)

    summary = build_preflight_summary(conn, keep_ohlcv=False, clear_llm=True)

    assert "llm_calls" in summary


def test_clear_redis_streams_deletes_matching_keys():
    """clear_redis_streams deletes all keys matching the pipeline patterns."""
    from production.scripts.pipeline_reset import clear_redis_streams

    r = MagicMock()
    r.scan_iter.side_effect = [
        [b"development:indicators:ESH6:1m"],
        [b"development:intelligence:ESH6:1m"],
        [b"development:signals:ESH6:1m:aggregated"],
        [b"development:narratives:ESH6:1m"],
    ]
    r.delete = MagicMock()

    count = clear_redis_streams(r, env_prefix="development")

    assert r.delete.call_count == 4
    assert count == 4


def test_clear_redis_streams_returns_zero_when_no_keys():
    """Returns 0 when no matching keys exist."""
    from production.scripts.pipeline_reset import clear_redis_streams

    r = MagicMock()
    r.scan_iter.return_value = []

    count = clear_redis_streams(r, env_prefix="development")
    assert count == 0
