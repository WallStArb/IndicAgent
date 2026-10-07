"""The compute-readiness predicate derives its required count from the bound timeframe list.

174 review WR-07: the timeframe stack was a module literal in four places and the
predicate hard-coded `= 4`, so reconfiguring `feature.factory.target_timeframes` would
silently leave promotion testing a different stack than the factory computes.

Plan 185-41: both predicates read the latest bar_integrity verdicts (rendered from
verdict_gate.REQUIRED_CHECKS) and the promote script's hold reasons name the failing check.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scripts.infrastructure.instrument_compute_eligibility_audit import (
    COMPUTE_READY_1D_PREDICATE_SQL,
    COMPUTE_READY_PREDICATE_SQL,
    load_compute_timeframes,
    load_report_max_age_hours,
)
from src.intelligence.bars.verdict_gate import REQUIRED_CHECKS, fetch_verdict_scan


def test_predicate_has_no_literal_timeframe_count():
    assert not re.search(r"=\s*\d+\s*$", COMPUTE_READY_PREDICATE_SQL, re.MULTILINE)
    assert COMPUTE_READY_PREDICATE_SQL.count("cardinality(%(timeframes)s::text[])") == 1


def test_both_predicates_read_verdicts_and_never_the_fetch_complete_flag():
    for predicate in (COMPUTE_READY_PREDICATE_SQL, COMPUTE_READY_1D_PREDICATE_SQL):
        assert "backfill_status" not in predicate
        assert "fetch_complete" not in predicate
        assert "integrity_monitor" in predicate and "bar_integrity" in predicate
        assert "%(max_age_hours)s" in predicate
    for tf, checks in REQUIRED_CHECKS.items():
        for check in checks:
            assert f"('{tf}', '{check}')" in COMPUTE_READY_PREDICATE_SQL
    assert "%(timeframes)s" not in COMPUTE_READY_1D_PREDICATE_SQL
    assert "('5m'" not in COMPUTE_READY_1D_PREDICATE_SQL


def _conn_returning(row):
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_load_compute_timeframes_reads_the_factory_key():
    conn, cursor = _conn_returning(('["1h", "1d"]',))
    assert load_compute_timeframes(conn) == ["1h", "1d"]
    assert cursor.execute.call_args.args[1] == ("feature.factory.target_timeframes",)


def test_load_compute_timeframes_fails_loudly_when_unset():
    conn, _ = _conn_returning(None)
    with pytest.raises(RuntimeError, match="not set"):
        load_compute_timeframes(conn)


def test_load_report_max_age_hours_reads_the_apr_key_and_fails_loudly():
    conn, cursor = _conn_returning(("30",))
    assert load_report_max_age_hours(conn) == 30.0
    assert cursor.execute.call_args.args[1] == ("threshold.bar_integrity.report_max_age_hours",)
    conn, _ = _conn_returning(None)
    with pytest.raises(RuntimeError, match="not set"):
        load_report_max_age_hours(conn)
    conn, _ = _conn_returning(("0",))
    with pytest.raises(RuntimeError, match="positive"):
        load_report_max_age_hours(conn)


def test_promote_compute_dimension_binds_apr_timeframes_and_max_age():
    from scripts.infrastructure import universe_expansion_promote_compute_eligible as mod

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    with patch.object(mod, "load_compute_timeframes", return_value=["1h", "1d"]):
        mod._fetch_candidates(conn, mod._DIMENSION_CONFIG["compute"], 30.0)
    assert cursor.execute.call_args.args[1] == {"timeframes": ["1h", "1d"], "max_age_hours": 30.0}


def test_promote_compute_1d_dimension_binds_only_the_max_age():
    from scripts.infrastructure import universe_expansion_promote_compute_eligible as mod

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    with patch.object(mod, "load_compute_timeframes") as mock_load:
        mod._fetch_candidates(conn, mod._DIMENSION_CONFIG["compute_1d"], 30.0)
    mock_load.assert_not_called()
    assert cursor.execute.call_args.args[1] == {"max_age_hours": 30.0}


class _GateConn:
    """A fake psycopg connection answering the audit's three reads in order of their SQL."""

    def __init__(self, ineligible, verdicts, loads=()):
        self.ineligible = ineligible
        self.verdicts = verdicts
        self.loads = loads
        self._last = ""

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._last = sql
        self._params = params

    def fetchall(self):
        if "FROM instruments" in self._last:
            return [(s,) for s in self.ineligible]
        if "integrity_monitor" in self._last:
            wanted = set(self._params["subjects"])
            return [v for v in self.verdicts if v[0] in wanted]
        return list(self.loads)


def _fresh_1d_verdicts(symbol, *, failing=()):
    at = datetime.now(UTC) - timedelta(hours=1)
    return [
        (f"{symbol}|1d", check, check not in failing, at) for check in sorted(REQUIRED_CHECKS["1d"])
    ]


def test_hold_reasons_name_the_failing_check():
    from scripts.infrastructure import universe_expansion_promote_compute_eligible as mod

    conn = _GateConn(
        ["AAA", "BBB"],
        _fresh_1d_verdicts("AAA", failing=("session_coverage",)),  # BBB has no verdicts at all
    )
    holds = mod._fetch_holds(conn, mod._DIMENSION_CONFIG["compute_1d"], [], 30.0)
    assert holds["AAA"] == ["1d:session_coverage failed"]
    assert len(holds["BBB"]) == 7 and all("missing" in reason for reason in holds["BBB"])
    assert mod._hold_check_counts(holds)["1d:session_coverage"] == 2


def test_a_name_held_by_sql_but_passing_the_pure_gate_raises():
    from scripts.infrastructure import universe_expansion_promote_compute_eligible as mod

    conn = _GateConn(["AAA"], _fresh_1d_verdicts("AAA"))
    with pytest.raises(RuntimeError, match="disagreement"):
        mod._fetch_holds(conn, mod._DIMENSION_CONFIG["compute_1d"], [], 30.0)


def test_a_candidate_failing_the_pure_gate_raises():
    from scripts.infrastructure import universe_expansion_promote_compute_eligible as mod

    conn = _GateConn(["AAA"], _fresh_1d_verdicts("AAA", failing=("digest_fresh",)))
    with pytest.raises(RuntimeError, match="disagreement"):
        mod._fetch_holds(conn, mod._DIMENSION_CONFIG["compute_1d"], ["AAA"], 30.0)


def test_fetch_verdict_failures_applies_the_latest_load_freshness_rule():
    loaded = datetime.now(UTC) - timedelta(minutes=10)
    conn = _GateConn([], _fresh_1d_verdicts("AAA"), loads=[("AAA", "1d", loaded)])
    scan = fetch_verdict_scan(conn, ["AAA"], ["1d"], 30.0)
    failures = scan.failures
    assert len(failures["AAA"]) == 7 and all("newer load" in r for r in failures["AAA"])
