"""Sessions the captured bars trail the last completed NYSE session (todo 614 row 21)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

from src.intelligence.bars.capture_freshness import (
    completed_sessions,
    session_date_of,
    sessions_behind,
)

# 2026-11-14 is a Saturday; Friday 2026-11-13 is the last completed session.
SATURDAY = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
TUESDAY_MORNING = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)  # Monday 11-16 closed at 21:00Z


def test_no_captured_bar_is_missing_not_zero():
    assert sessions_behind(None, SATURDAY) is None


def test_a_1d_bar_stamped_at_et_midnight_belongs_to_its_session_in_both_offsets():
    assert session_date_of(datetime(2026, 11, 13, 5, 0, tzinfo=UTC)).isoformat() == "2026-11-13"
    assert session_date_of(datetime(2026, 7, 1, 4, 0, tzinfo=UTC)).isoformat() == "2026-07-01"


def test_a_5m_bar_after_the_close_stays_on_its_session():
    assert session_date_of(datetime(2026, 11, 14, 0, 55, tzinfo=UTC)).isoformat() == "2026-11-13"


def test_current_after_a_weekend_is_zero_behind():
    friday_1d = datetime(2026, 11, 13, 5, 0, tzinfo=UTC)
    assert sessions_behind(friday_1d, SATURDAY) == 0


def test_each_missed_session_counts():
    thursday_1d = datetime(2026, 11, 12, 5, 0, tzinfo=UTC)
    assert sessions_behind(thursday_1d, SATURDAY) == 1
    monday_1d = datetime(2026, 11, 9, 5, 0, tzinfo=UTC)
    assert sessions_behind(monday_1d, SATURDAY) == 4


def test_a_session_still_open_is_not_counted():
    friday_1d = datetime(2026, 11, 13, 5, 0, tzinfo=UTC)
    monday_midday = datetime(2026, 11, 16, 17, 0, tzinfo=UTC)  # Monday session still open
    assert sessions_behind(friday_1d, monday_midday) == 0
    assert sessions_behind(friday_1d, TUESDAY_MORNING) == 1


def test_a_holiday_is_not_a_missed_session():
    # Thanksgiving 2026-11-26 has no session; Wednesday 11-25 captured, Friday 11-27 closed early.
    wednesday_1d = datetime(2026, 11, 25, 5, 0, tzinfo=UTC)
    saturday = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    assert sessions_behind(wednesday_1d, saturday) == 1
    assert datetime(2026, 11, 26).date() not in completed_sessions(saturday)


def test_a_stale_stamp_reports_at_least_the_window_not_zero():
    ancient = datetime(2020, 1, 2, 5, 0, tzinfo=UTC)
    assert sessions_behind(ancient, SATURDAY) >= 10


def test_nightly_emits_completion_duration_and_freshness_and_skips_a_missing_timeframe(
    monkeypatch,
):
    from scripts.ops.bars import ops_bar_nightly as nightly

    completed, duration, gauge = MagicMock(), MagicMock(), MagicMock()
    flushed = MagicMock()
    monkeypatch.setattr(nightly, "JOB_COMPLETED_TOTAL", completed)
    monkeypatch.setattr(nightly, "JOB_DURATION_SECONDS", duration)
    monkeypatch.setattr(nightly, "_SESSIONS_BEHIND", gauge)
    monkeypatch.setattr(nightly, "flush_and_shutdown_metrics", flushed)

    nightly.emit_run_metrics("success", 12.5, {"5m": 0, "1d": None}, "alpaca")

    completed.add.assert_called_once_with(1, {"job": "alpaca-nightly", "status": "success"})
    duration.record.assert_called_once_with(12.5, {"job": "alpaca-nightly", "status": "success"})
    gauge.set.assert_called_once_with(0, {"vendor": "alpaca", "timeframe": "5m"})
    flushed.assert_called_once()


def test_capture_freshness_asks_the_newest_bar_per_timeframe_filtered_by_kind():
    from scripts.ops.bars.ops_bar_nightly import capture_freshness

    cursor = MagicMock()
    cursor.fetchone.side_effect = [(None,), (datetime(2026, 1, 2, 5, 0, tzinfo=UTC),)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    result = capture_freshness(conn, "alpaca", "sip_rth", ("5m", "1d"))

    assert result["5m"] is None and result["1d"] > 0
    first = cursor.execute.call_args_list[0]
    assert first.args[1] == ("alpaca", "5m", "sip_rth", "sip_rth")


def _run_main(
    monkeypatch,
    nightly,
    *,
    apply: bool,
    summary: dict,
    freshness=None,
    crash=False,
    emitted=None,
    freshness_fails=False,
):
    """main() with the database, the leaf and the metric seams replaced; returns (code, emitted)."""
    import sys
    from types import SimpleNamespace

    emitted = [] if emitted is None else emitted
    monkeypatch.setattr(
        sys, "argv", ["ops_bar_nightly", "--vendor", "alpaca"] + (["--apply"] if apply else [])
    )
    monkeypatch.setattr(nightly, "get_settings", lambda: SimpleNamespace(database_url="x"))
    monkeypatch.setattr(nightly, "init_otel_providers", lambda name: None)
    monkeypatch.setattr(nightly.psycopg, "connect", lambda *a, **k: MagicMock())
    monkeypatch.setattr(nightly, "_apr_str", lambda conn, key, default: "sip")
    monkeypatch.setattr(nightly, "_apr_int", lambda conn, key, default: default)
    monkeypatch.setattr(nightly, "read_raw_params", lambda cur: {})
    monkeypatch.setattr(nightly, "read_settle", lambda cur: None)
    monkeypatch.setattr(nightly, "get_active_contracts", lambda *a, **k: [])
    monkeypatch.setattr(nightly, "history_leaf", lambda *a, **k: MagicMock())
    monkeypatch.setattr(nightly, "_NightlySink", lambda *a, **k: MagicMock())
    monkeypatch.setattr(nightly, "RequestSink", lambda *a, **k: MagicMock())

    def fake_run(*args, **kwargs):
        if crash:
            raise RuntimeError("boom")
        return summary

    async def run(*args, **kwargs):
        return fake_run()

    monkeypatch.setattr(nightly, "_run", run)

    def capture(*args, **kwargs):
        if freshness_fails:
            raise RuntimeError("query failed")
        return freshness or {}

    monkeypatch.setattr(nightly, "capture_freshness", capture)
    monkeypatch.setattr(nightly, "emit_run_metrics", lambda *a: emitted.append(a[0]))
    return nightly.main(), emitted


CLEAN = dict(
    errors=0, unfinished=0, unselected=0, basis_flagged=0, pages=1, skipped=0, authored=0,
    raw_1d=0, new=0, changed=0, unchanged=0, flagged=0, superseded=0, excluded=0, partial=0,
)  # fmt: skip


def test_main_emits_success_partial_and_failure_only_when_applying(monkeypatch):
    import pytest

    from scripts.ops.bars import ops_bar_nightly as nightly

    assert _run_main(monkeypatch, nightly, apply=True, summary=CLEAN) == (0, ["success"])
    assert _run_main(monkeypatch, nightly, apply=True, summary={**CLEAN, "unfinished": 2}) == (
        1,
        ["partial"],
    )
    assert _run_main(monkeypatch, nightly, apply=False, summary=CLEAN) == (0, [])
    crashed: list = []
    with pytest.raises(RuntimeError):
        _run_main(monkeypatch, nightly, apply=True, summary=CLEAN, crash=True, emitted=crashed)
    assert crashed == ["failure"]


def test_a_failed_freshness_read_leaves_the_exit_code_and_status_alone(monkeypatch):
    from scripts.ops.bars import ops_bar_nightly as nightly

    assert _run_main(monkeypatch, nightly, apply=True, summary=CLEAN, freshness_fails=True) == (
        0,
        ["success"],
    )
