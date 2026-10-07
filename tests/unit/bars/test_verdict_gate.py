"""The pure verdict gate (plan 185-41): one function decides promotion and the rebuild."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.bars.verdict_gate import (
    REBUILD_ONLY_CHECKS,
    REQUIRED_CHECKS,
    VerdictRow,
    gate_symbols,
    ready_predicate_sql,
)

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)
MAX_AGE = timedelta(hours=30)


def _rows(symbol: str, tf: str, *, when: datetime = NOW - timedelta(hours=1), **overrides: bool):
    return [
        VerdictRow(symbol, tf, check, overrides.get(check, True), when)
        for check in sorted(REQUIRED_CHECKS[tf])
    ]


def _gate(rows, **kwargs):
    base = {
        "symbols": ["AAA"],
        "timeframes": ["1d"],
        "now": NOW,
        "max_age": MAX_AGE,
        "latest_load": {},
    }
    base.update(kwargs)
    return gate_symbols(rows, **base)


def test_required_checks_match_the_design():
    assert REQUIRED_CHECKS["1d"] == {
        "session_coverage",
        "policy_conformance",
        "lineage_missing",
        "canonical_recompute",
        "digest_fresh",
        "unexplained_seam",
        "vendor_basis_run",
    }
    assert REQUIRED_CHECKS["5m"] == {"slot_coverage", "digest_fresh", "coverage_cache"}
    assert REQUIRED_CHECKS["15m"] == REQUIRED_CHECKS["1h"] == {"digest_fresh", "grid_parity"}
    assert REBUILD_ONLY_CHECKS == {"15m": {"stray_vendor_rows"}, "1h": {"stray_vendor_rows"}}


def test_a_symbol_with_every_check_passed_and_fresh_passes():
    assert _gate(_rows("AAA", "1d")) == {}


def test_a_failed_check_is_named_with_its_timeframe():
    result = _gate(_rows("AAA", "1d", session_coverage=False))
    assert result == {"AAA": ["1d:session_coverage failed"]}


def test_a_missing_check_fails():
    rows = [r for r in _rows("AAA", "1d") if r.check != "unexplained_seam"]
    assert _gate(rows) == {"AAA": ["1d:unexplained_seam missing"]}


def test_a_symbol_with_no_rows_names_every_required_check():
    result = _gate([])
    assert len(result["AAA"]) == len(REQUIRED_CHECKS["1d"])
    assert all(reason.endswith("missing") for reason in result["AAA"])


def test_a_verdict_older_than_max_age_is_stale():
    old = NOW - timedelta(hours=31)
    result = _gate(_rows("AAA", "1d", when=old))
    assert len(result["AAA"]) == 7
    assert all("stale" in reason and "older than" in reason for reason in result["AAA"])


def test_a_verdict_exactly_at_max_age_passes():
    assert _gate(_rows("AAA", "1d", when=NOW - MAX_AGE)) == {}


def test_a_verdict_older_than_the_latest_load_is_stale():
    loaded = NOW - timedelta(minutes=30)
    result = _gate(_rows("AAA", "1d"), latest_load={("AAA", "1d"): loaded})
    assert len(result["AAA"]) == 7
    assert all("newer load" in reason for reason in result["AAA"])


def test_a_load_on_another_series_does_not_stale_this_one():
    loaded = NOW - timedelta(minutes=30)
    assert (
        _gate(_rows("AAA", "1d"), latest_load={("AAA", "5m"): loaded, ("BBB", "1d"): loaded}) == {}
    )


def test_the_latest_verdict_wins_over_an_older_failure():
    rows = _rows("AAA", "1d")
    rows.append(VerdictRow("AAA", "1d", "session_coverage", False, NOW - timedelta(hours=20)))
    assert _gate(rows) == {}


def test_a_newer_failure_wins_over_an_older_pass():
    rows = _rows("AAA", "1d", when=NOW - timedelta(hours=20))
    rows.append(VerdictRow("AAA", "1d", "session_coverage", False, NOW - timedelta(hours=1)))
    assert _gate(rows) == {"AAA": ["1d:session_coverage failed"]}


def test_a_tie_at_the_same_instant_fails():
    rows = _rows("AAA", "1d")
    rows.append(VerdictRow("AAA", "1d", "session_coverage", False, NOW - timedelta(hours=1)))
    assert _gate(rows) == {"AAA": ["1d:session_coverage failed"]}


def test_compute_gates_every_requested_timeframe():
    rows = _rows("AAA", "1d") + _rows("AAA", "5m") + _rows("AAA", "15m") + _rows("AAA", "1h")
    assert _gate(rows, timeframes=["5m", "15m", "1h", "1d"]) == {}
    rows = [r for r in rows if not (r.timeframe == "15m" and r.check == "grid_parity")]
    assert _gate(rows, timeframes=["5m", "15m", "1h", "1d"]) == {"AAA": ["15m:grid_parity missing"]}


def test_other_symbols_and_other_timeframes_do_not_leak():
    rows = _rows("BBB", "1d")
    assert "AAA" in _gate(rows)
    assert _gate(_rows("AAA", "1d", session_coverage=False), timeframes=["5m"])["AAA"][
        0
    ].startswith("5m:")


def test_stray_vendor_rows_gates_only_when_asked():
    rows = _rows("AAA", "15m") + _rows("AAA", "1h")
    assert _gate(rows, timeframes=["15m", "1h"]) == {}
    result = _gate(rows, timeframes=["15m", "1h"], extra_checks=frozenset({"stray_vendor_rows"}))
    assert result == {"AAA": ["15m:stray_vendor_rows missing", "1h:stray_vendor_rows missing"]}
    rows += [
        VerdictRow("AAA", "15m", "stray_vendor_rows", True, NOW - timedelta(hours=1)),
        VerdictRow("AAA", "1h", "stray_vendor_rows", False, NOW - timedelta(hours=1)),
    ]
    result = _gate(rows, timeframes=["15m", "1h"], extra_checks=frozenset({"stray_vendor_rows"}))
    assert result == {"AAA": ["1h:stray_vendor_rows failed"]}


def test_an_unknown_extra_check_is_refused():
    with pytest.raises(ValueError, match="no_such_check"):
        _gate([], extra_checks=frozenset({"no_such_check"}))


def test_a_timeframe_without_required_checks_is_refused_not_passed():
    with pytest.raises(ValueError, match="4h"):
        _gate([], timeframes=["4h"])


def test_symbols_are_reported_in_sorted_order_with_only_the_failing_ones():
    rows = _rows("AAA", "1d") + _rows("CCC", "1d", digest_fresh=False)
    result = _gate(rows, symbols=["CCC", "BBB", "AAA"])
    assert list(result) == ["BBB", "CCC"]
    assert result["CCC"] == ["1d:digest_fresh failed"]


def test_sql_rendering_is_generated_from_required_checks():
    sql = ready_predicate_sql()
    for tf, checks in REQUIRED_CHECKS.items():
        for check in checks:
            assert f"('{tf}', '{check}')" in sql
    assert "stray_vendor_rows" not in sql
    assert "backfill_status" not in sql
    assert "%(timeframes)s" in sql and "%(max_age_hours)s" in sql
    assert "integrity_monitor" in sql and "bar_integrity" in sql and "ohlcv_load" in sql


def test_sql_rendering_for_one_timeframe_has_no_timeframe_binding():
    sql = ready_predicate_sql(("1d",))
    assert "%(timeframes)s" not in sql
    assert "('1d', 'session_coverage')" in sql
    assert "('5m'" not in sql
    assert "%(max_age_hours)s" in sql


def test_sql_rendering_refuses_an_unknown_timeframe():
    with pytest.raises(ValueError, match="4h"):
        ready_predicate_sql(("4h",))
