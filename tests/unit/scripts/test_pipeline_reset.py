import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from unittest.mock import MagicMock


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


def test_truncate_tables_always_clears_core_tables():
    """truncate_tables always clears signal_ledger, intelligence_features, technical_indicators."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=True, clear_llm=False)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("signal_ledger" in sql for sql in executed)
    assert any("intelligence_features" in sql for sql in executed)
    assert any("technical_indicators" in sql for sql in executed)
    assert not any("market_data_ohlcv" in sql for sql in executed)


def test_truncate_tables_includes_ohlcv_when_not_keep():
    """truncate_tables includes market_data_ohlcv when keep_ohlcv=False."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=False, clear_llm=False)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("market_data_ohlcv" in sql for sql in executed)


def test_truncate_tables_includes_llm_when_flag_set():
    """truncate_tables includes llm_calls when clear_llm=True."""
    from production.scripts.pipeline_reset import truncate_tables

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    truncate_tables(conn, keep_ohlcv=True, clear_llm=True)

    executed = [call.args[0] for call in cur.execute.call_args_list]
    assert any("llm_calls" in sql for sql in executed)


def test_verify_dataset_passes_when_rows_exist():
    """verify_dataset returns True when all tables have rows."""
    from production.scripts.pipeline_reset import verify_dataset

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    # Returns different counts per call: signal_ledger=1000, intelligence_features=5000
    conn.cursor.return_value.fetchone.side_effect = [(1000,), (5000,), (10,)]
    conn.cursor.return_value.fetchall.return_value = [
        ("ESH6", "1m", 500, "2026-03-01", "2026-03-06"),
    ]

    ok, report = verify_dataset(conn)

    assert ok is True
    assert "ESH6" in report


def test_verify_dataset_fails_when_signal_ledger_empty():
    """verify_dataset returns False when signal_ledger has 0 rows."""
    from production.scripts.pipeline_reset import verify_dataset

    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.side_effect = [(0,), (0,), (0,)]
    conn.cursor.return_value.fetchall.return_value = []

    ok, report = verify_dataset(conn)

    assert ok is False
    assert "EMPTY" in report or "0" in report
