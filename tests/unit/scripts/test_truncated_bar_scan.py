"""ops_truncated_bar_scan.candidates: a vendor bar far below the session's own volume ratio."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts.ops.bars.ops_truncated_bar_scan import candidates

S0 = datetime(2026, 10, 9, 13, 30, tzinfo=UTC)  # 09:30 EDT


def test_a_bar_far_below_the_session_median_ratio_is_a_candidate():
    # BLK 2026-10-09 14:10: IBKR 1,156 against Alpaca 12,450 while the session runs near 0.9
    pairs = [(S0 + timedelta(minutes=5 * i), 900, 1000) for i in range(78)]
    pairs[8] = (S0 + timedelta(minutes=40), 1156, 12450)
    (found,) = candidates(pairs, 0.2)
    assert found["timestamp"] == (S0 + timedelta(minutes=40)).isoformat()
    assert found["ratio"] < 0.2


def test_a_session_level_volume_difference_is_absorbed_by_the_median():
    pairs = [(S0 + timedelta(minutes=5 * i), 380, 1000) for i in range(78)]  # BKNG-like 0.38
    assert candidates(pairs, 0.2) == []


def test_off_grid_slots_are_never_judged():
    after = S0 + timedelta(hours=6, minutes=30)  # 16:00 EDT, after the close
    pairs = [(S0 + timedelta(minutes=5 * i), 900, 1000) for i in range(10)] + [(after, 1, 1000)]
    assert candidates(pairs, 0.2) == []


def test_canonical_sql_reads_vendor_not_source():
    """191-15: market_data_ohlcv carries (vendor, kind); the canonical-held check selects
    the vendor directly instead of mapping a source label."""
    from scripts.ops.bars import ops_truncated_bar_scan as scan

    sql = " ".join(scan._CANON_SQL.split())
    assert 'SELECT "timestamp", vendor FROM market_data_ohlcv' in sql
    assert "source" not in sql
