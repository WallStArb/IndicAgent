"""Todo 565 part a: the writer that turns failing slot_coverage verdicts into named holds
(scripts/ops/bars/ops_hold_slot_coverage_gaps.py, migration 552's slot_coverage_gap reason).
The selection logic against plain dicts; the DB write itself is bar_hold's, tested in
tests/unit/services/test_bar_hold.py."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.ops.bars.ops_hold_slot_coverage_gaps import hold_requests


def _row(subject="MSM|5m", value=0.975, threshold=0.995, passed=False, **over):
    row = {
        "subject": subject,
        "metric_value": value,
        "threshold_value": threshold,
        "evaluated_at": datetime(2026, 11, 1, 7, 8, 8, tzinfo=UTC),
        "passed": passed,
    }
    row.update(over)
    return row


def test_a_failing_verdict_becomes_a_hold_with_its_evidence():
    requests = hold_requests([_row()])
    assert requests == [
        {
            "symbol": "MSM",
            "timeframe": "5m",
            "detail": {
                "metric_value": 0.975,
                "threshold_value": 0.995,
                "evaluated_at": "2026-11-01T07:08:08Z",
            },
        }
    ]


def test_a_passing_subject_is_not_held():
    assert hold_requests([_row(passed=True)]) == []


def test_a_subject_off_the_5m_check_is_skipped():
    assert hold_requests([_row(subject="MSM|1d"), _row(subject="5m")]) == []


def test_requests_are_sorted_and_one_per_symbol():
    rows = [_row(subject="TSLA|5m"), _row(subject="MSM|5m"), _row(subject="APLD|5m")]
    assert [r["symbol"] for r in hold_requests(rows)] == ["APLD", "MSM", "TSLA"]
