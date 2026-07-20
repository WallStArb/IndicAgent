"""Unit tests for known-corrupt-OHLCV-print cleanup (todo 151) pure functions.

Pure-function tests only -- no DB, no live asyncpg connection. The script's
DB-touching code path is exercised in two ways, NEITHER of which ever hits a live
database or ever passes --apply to the real script: (1) the four decision/
formatting helpers (neighbor-based classification, the subject-key builder, the
correction/audit SQL shape, dry-run report + follow-up-command rendering) are pure
functions tested directly; (2) `_apply_correction`'s SQL-execution order (audit
fact written BEFORE the row is mutated) is tested against a mocked asyncpg
connection (AsyncMock), mirroring test_forward_return_writer.py's
_mock_conn_with_precheck_result pattern for the sync/psycopg2 case.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from scripts.ops.corpus.ops_known_corrupt_print_cleanup import (
    _AUDIT_INSERT_SQL,
    _CORRECTION_UPDATE_SQL,
    _METRIC_NAME,
    _MONITOR_TYPE,
    CandidateRow,
    CandidateVerdict,
    _apply_correction,
    build_subject_key,
    classify_candidate_bar,
    render_dry_run_report,
    render_followup_commands,
)


class TestClassifyCandidateBar:
    def test_uup_corrupt_print_confirmed(self) -> None:
        # The exact UUP 2007-06-20 19:00 row from todo 148/151: open/high corrupted
        # to 1000, low/close still consistent with neighbors (~25-29), neighbors
        # agree closely with each other (25.07 vs 24.08).
        verdict = classify_candidate_bar(
            open_=1000.0,
            high=1000.0,
            low=28.97,
            close=28.97,
            prev_close=25.07,
            next_open=24.08,
        )
        assert verdict.verdict == "CONFIRMED_CORRUPT"
        assert "open" in verdict.implausible_fields
        assert "high" in verdict.implausible_fields
        assert "low" not in verdict.implausible_fields
        assert "close" not in verdict.implausible_fields
        assert verdict.reason == "isolated_spike_neighbors_agree"

    def test_plausible_bar_ruled_plausible(self) -> None:
        verdict = classify_candidate_bar(
            open_=25.0,
            high=25.5,
            low=24.8,
            close=25.2,
            prev_close=25.0,
            next_open=25.3,
        )
        assert verdict.verdict == "PLAUSIBLE"
        assert verdict.implausible_fields == ()

    def test_no_prev_close_is_ambiguous(self) -> None:
        verdict = classify_candidate_bar(
            open_=1000.0,
            high=1000.0,
            low=28.97,
            close=28.97,
            prev_close=None,
            next_open=24.08,
        )
        assert verdict.verdict == "AMBIGUOUS"
        assert verdict.reason == "insufficient_neighbor_data"
        assert verdict.neighbor_ratio is None

    def test_no_next_open_is_ambiguous(self) -> None:
        verdict = classify_candidate_bar(
            open_=1000.0,
            high=1000.0,
            low=28.97,
            close=28.97,
            prev_close=25.07,
            next_open=None,
        )
        assert verdict.verdict == "AMBIGUOUS"
        assert verdict.reason == "insufficient_neighbor_data"

    def test_implausible_but_neighbors_disagree_is_ambiguous(self) -> None:
        # Neighbors themselves are 10x apart (untrustworthy reference) -- even
        # though the bar is implausible relative to the average, we cannot
        # confidently call it corrupt vs. a genuine continuation of a already-
        # volatile move.
        verdict = classify_candidate_bar(
            open_=500.0,
            high=520.0,
            low=490.0,
            close=495.0,
            prev_close=5.0,
            next_open=50.0,
        )
        assert verdict.verdict == "AMBIGUOUS"
        assert verdict.reason == "implausible_but_neighbors_disagree"
        assert verdict.implausible_fields != ()

    def test_boundary_magnitude_exactly_at_threshold_counts_as_implausible(self) -> None:
        # reference = (10 + 10) / 2 = 10; open = 100 -> ratio exactly 10.0 (the
        # default magnitude_threshold) -- >= is inclusive.
        verdict = classify_candidate_bar(
            open_=100.0,
            high=10.0,
            low=10.0,
            close=10.0,
            prev_close=10.0,
            next_open=10.0,
            magnitude_threshold=10.0,
        )
        assert verdict.verdict == "CONFIRMED_CORRUPT"
        assert "open" in verdict.implausible_fields

    def test_custom_thresholds_respected(self) -> None:
        # Same bar as the boundary test, but a stricter (lower) magnitude
        # threshold of 5.0 -- ratio 10.0 clears it easily.
        verdict = classify_candidate_bar(
            open_=100.0,
            high=10.0,
            low=10.0,
            close=10.0,
            prev_close=10.0,
            next_open=10.0,
            magnitude_threshold=5.0,
        )
        assert verdict.verdict == "CONFIRMED_CORRUPT"

        # With a looser (higher) threshold of 20.0, ratio 10.0 no longer counts.
        verdict_loose = classify_candidate_bar(
            open_=100.0,
            high=10.0,
            low=10.0,
            close=10.0,
            prev_close=10.0,
            next_open=10.0,
            magnitude_threshold=20.0,
        )
        assert verdict_loose.verdict == "PLAUSIBLE"


class TestBuildSubjectKey:
    def test_format(self) -> None:
        key = build_subject_key("UUP", "5m", "2007-06-20T19:00:00Z")
        assert key == "symbol=UUP|tf=5m|ts=2007-06-20T19:00:00Z"


class TestCorrectionSqlShape:
    def test_correction_update_sql_shape(self) -> None:
        assert "UPDATE market_data_ohlcv" in _CORRECTION_UPDATE_SQL
        assert "SET volume = 0" in _CORRECTION_UPDATE_SQL
        assert "$1" in _CORRECTION_UPDATE_SQL
        assert "$2" in _CORRECTION_UPDATE_SQL
        assert "$3" in _CORRECTION_UPDATE_SQL
        # Never touch price columns -- Renaissance retention, only volume corrects.
        assert "open" not in _CORRECTION_UPDATE_SQL.lower().split("where")[0]

    def test_audit_insert_sql_shape(self) -> None:
        assert "INSERT INTO integrity_monitor" in _AUDIT_INSERT_SQL
        assert "monitor_type" in _AUDIT_INSERT_SQL
        assert "subject" in _AUDIT_INSERT_SQL
        assert "metric_name" in _AUDIT_INSERT_SQL
        assert "metric_value" in _AUDIT_INSERT_SQL
        assert "threshold_value" in _AUDIT_INSERT_SQL
        assert "NULL" in _AUDIT_INSERT_SQL
        assert "true" in _AUDIT_INSERT_SQL
        assert "ON CONFLICT" in _AUDIT_INSERT_SQL
        assert "$1" in _AUDIT_INSERT_SQL
        assert "$4" in _AUDIT_INSERT_SQL


def _make_row(symbol: str, tf: str, verdict: CandidateVerdict) -> CandidateRow:
    return CandidateRow(
        symbol=symbol,
        tf=tf,
        timestamp="2007-06-20T19:00:00Z",
        open=1000.0,
        high=1000.0,
        low=28.97,
        close=28.97,
        volume=200.0,
        prev_close=25.07,
        next_open=24.08,
        verdict=verdict,
    )


class TestRenderDryRunReport:
    def test_report_includes_counts(self) -> None:
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        ambiguous = _make_row(
            "XRT",
            "15m",
            CandidateVerdict(
                "AMBIGUOUS", ("open",), 15.0, 5.0, "implausible_but_neighbors_disagree"
            ),
        )
        report = render_dry_run_report([confirmed, ambiguous])
        assert "CONFIRMED_CORRUPT: 1" in report
        assert "AMBIGUOUS: 1" in report

    def test_report_includes_confirmed_row_details(self) -> None:
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        report = render_dry_run_report([confirmed])
        assert "UUP" in report
        assert "5m" in report
        assert "isolated_spike_neighbors_agree" in report

    def test_empty_report_zero_candidates(self) -> None:
        report = render_dry_run_report([])
        assert "CONFIRMED_CORRUPT: 0" in report
        assert "AMBIGUOUS: 0" in report


class TestRenderFollowupCommands:
    def test_no_confirmed_returns_no_followup_message(self) -> None:
        text = render_followup_commands([], training_window_end=None)
        assert "No CONFIRMED_CORRUPT rows" in text

    def test_confirmed_rows_produce_apply_and_writer_commands(self) -> None:
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        text = render_followup_commands(
            [confirmed], training_window_end="2025-12-24T05:15:00+00:00"
        )
        assert "--apply" in text
        assert "UUP" in text
        assert "5m" in text
        assert "forward_return_writer.py" in text
        assert "2025-12-24T05:15:00+00:00" in text
        assert "backfill_feature_factory.py" in text

    def test_delete_gotcha_note_present(self) -> None:
        # ON CONFLICT DO NOTHING on both forward_returns and feature_vectors means
        # re-running the writers alone will NOT overwrite pre-existing rows for the
        # corrected neighborhood -- the follow-up text must warn about this.
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        text = render_followup_commands(
            [confirmed], training_window_end="2025-12-24T05:15:00+00:00"
        )
        assert "ON CONFLICT DO NOTHING" in text
        assert "DELETE FROM forward_returns" in text
        assert "DELETE FROM feature_vectors" in text


class TestApplyCorrectionMockedConnection:
    """`_apply_correction` is the only function in this script that ever mutates the
    DB or writes an integrity_monitor row -- exercised here ONLY against a mocked
    asyncpg connection (AsyncMock), never a live database. No test in this file
    passes --apply to the real script or opens a real connection."""

    def test_writes_audit_fact_before_mutating_row(self) -> None:
        conn = AsyncMock()
        row = CandidateRow(
            symbol="UUP",
            tf="5m",
            timestamp="2007-06-20T19:00:00Z",
            open=1000.0,
            high=1000.0,
            low=28.97,
            close=28.97,
            volume=200.0,
            prev_close=25.07,
            next_open=24.08,
            verdict=CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        bar_ts = "2007-06-20T19:00:00+00:00"  # sentinel -- opaque to _apply_correction

        asyncio.run(_apply_correction(conn, row, bar_ts))

        assert conn.execute.call_count == 2
        audit_call, update_call = conn.execute.call_args_list

        # Audit fact (original volume) is written FIRST, before the mutation --
        # non-negotiable per todo 151's "audit trail before mutating" spec.
        assert audit_call.args[0] == _AUDIT_INSERT_SQL
        assert audit_call.args[1:] == (
            _MONITOR_TYPE,
            "symbol=UUP|tf=5m|ts=2007-06-20T19:00:00Z",
            _METRIC_NAME,
            200.0,
        )

        # The correction UPDATE runs second, keyed on symbol/tf/bar_ts (not the
        # display ISO string -- bar_ts is the raw DB timestamp value).
        assert update_call.args[0] == _CORRECTION_UPDATE_SQL
        assert update_call.args[1:] == ("UUP", "5m", bar_ts)
