"""The step 7 rebuild driver's pure parts (todo 600): windows, preconditions, resume state."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from scripts.ops.bars.ops_canonical_rebuild import (
    State,
    chunk_windows,
    from_violations,
    grid_misaligned,
    has_written,
    lineage_gate,
    main,
    read_card_lineage,
    result_violation,
    session_bounds,
    source_shortfalls,
)
from src.intelligence.bars.selection import SESSION_TZ

_90D = 90 * 86400


def test_windows_are_the_epoch_aligned_chunk_grid():
    # the live grid (2026-11-10): ... [2026-06-06, 2026-09-04), [2026-09-04, 2026-12-03)
    windows = chunk_windows(_90D, date(2026, 7, 1), datetime(2026, 11, 11, tzinfo=UTC))
    assert windows == [
        (datetime(2026, 6, 6, tzinfo=UTC), datetime(2026, 9, 4, tzinfo=UTC)),
        (datetime(2026, 9, 4, tzinfo=UTC), datetime(2026, 12, 3, tzinfo=UTC)),
    ]
    assert (
        grid_misaligned([(int(a.timestamp()), int(b.timestamp())) for a, b in windows], _90D) == []
    )


def test_an_off_grid_chunk_is_reported():
    assert grid_misaligned([(86400, 86400 + _90D)], _90D) == [(86400, 86400 + _90D)]
    assert grid_misaligned([(0, 86400)], _90D) == [(0, 86400)]


def test_session_bounds_keep_every_session_inside_its_chunk():
    window = (datetime(2026, 9, 4, tzinfo=UTC), datetime(2026, 12, 3, tzinfo=UTC))
    start, end = session_bounds(window)
    assert start == datetime.combine(date(2026, 9, 4), time.min, SESSION_TZ)
    assert end == datetime.combine(date(2026, 12, 3), time.min, SESSION_TZ)
    # the 09-03 session's bars (13:30-20:00 UTC) sit in the previous chunk, the 12-02 session's
    # last bar (20:55 UTC on 12-02) in this one
    assert start > datetime(2026, 9, 3, 21, tzinfo=UTC)
    assert end > datetime(2026, 12, 2, 21, tzinfo=UTC)
    assert end < datetime(2026, 12, 3, 13, 30, tzinfo=UTC)


def test_source_shortfalls_hard_abort_on_1m_mismatch_and_missing_raw():
    canonical = {"1m": 9_775_958, "5m": 400, "15m": 100, "1h": 30, "1d": 7}
    assert source_shortfalls(canonical, {"1m": 9_775_958, "5m": 900, "1d": 20}) == []
    assert source_shortfalls(canonical, {"1m": 9_775_957, "5m": 900, "1d": 20}) == [
        "1m: canonical 9775958, raw 9775957"
    ]
    assert source_shortfalls({"4h": 3}, {}) == ["4h: canonical 3, raw 0"]
    assert source_shortfalls({"1d": 7}, {"1d": 6}) == ["1d: canonical 7, raw 6"]


def test_state_round_trips_and_resumes(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.data["horizon"] = "2026-11-12T00:00:00+00:00"
    assert not state.done("5m", "2003-07-14")
    assert state.inflight("5m|2003-07-14") == {"last": None, "pending": None, "totals": {}}
    entry = state.inflight("5m|2003-07-14")
    entry["last"], entry["totals"]["new"] = "AAPL", 7
    state.finish("5m", "2003-04-15")
    again = State(path)
    assert again.horizon == datetime(2026, 11, 12, tzinfo=UTC)
    assert again.done("5m", "2003-04-15")
    assert again.inflight("5m|2003-07-14") == {
        "last": "AAPL",
        "pending": None,
        "totals": {"new": 7},
    }
    again.finish("5m", "2003-07-14")
    assert State(path).data["inflight"] == {}


def test_rebuild_refuses_without_a_clean_preflight(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"horizon": "2026-11-12T00:00:00+00:00", "preflight_failures": ["x"]}')
    assert main(["--rebuild", "--state", str(path), "--from", "2003-09-01"]) == 2


def test_cli_refuses_a_derived_timeframe_and_a_naive_horizon(tmp_path):
    with pytest.raises(SystemExit):
        main(
            [
                "--rebuild",
                "--state",
                str(tmp_path / "s"),
                "--timeframes",
                "1d",
                "--from",
                "2003-09-01",
            ]
        )
    with pytest.raises(SystemExit):
        main(["--preflight", "--state", str(tmp_path / "s"), "--horizon", "2026-11-12T00:00:00"])
    with pytest.raises(SystemExit):
        main(["--rebuild", "--state", str(tmp_path / "s")])


# --- the lineage gate before the TRUNCATE (review 2026-11-11, finding 1) ----------------------

_RED = ["CTVA|1d|canonical_recompute", "CTVA|1d|lineage_missing", "SCCO|1d|lineage_missing"]


def test_every_red_lineage_verdict_needs_a_disposition_and_an_export():
    dispositions = {v: "expected D1 difference: raw cannot rebuild" for v in _RED}
    assert lineage_gate(_RED, dispositions, ["CTVA", "SCCO"]) == []
    assert lineage_gate([], {}, []) == []
    failures = lineage_gate(_RED, {_RED[0]: "x", _RED[1]: ""}, ["CTVA"])
    assert "red 1d verdict with no disposition: CTVA|1d|lineage_missing" in failures
    assert "red 1d verdict with no disposition: SCCO|1d|lineage_missing" in failures
    assert "red 1d lineage names missing from the card's export: ['SCCO']" in failures


def test_the_card_lineage_names_come_from_card_json(tmp_path):
    (tmp_path / "card.json").write_text(
        '{"red_lineage": {"verdicts": [], "exported_symbols": ["CTVA", "SCCO"], "rows": 9}}'
    )
    assert read_card_lineage(tmp_path) == ["CTVA", "SCCO"]
    (tmp_path / "card.json").write_text("{}")
    assert read_card_lineage(tmp_path) == []


def test_preflight_requires_the_card():
    with pytest.raises(SystemExit):
        main(["--preflight", "--state", "/nonexistent/state.json"])


# --- rebuild guards (review 2026-11-11, finding 3) --------------------------------------------


class _Result:
    def __init__(self, new=0, changed=0, unchanged=0, dropped=0):
        self.new, self.changed, self.unchanged, self.dropped = new, changed, unchanged, dropped


def test_an_empty_target_takes_only_new_rows():
    assert result_violation(_Result(new=500), "AAPL", None) is None
    assert result_violation(_Result(changed=1), "AAPL", None) == "AAPL: changed 1, dropped 0"
    assert result_violation(_Result(dropped=2), "AAPL", None) == "AAPL: changed 0, dropped 2"
    assert result_violation(_Result(new=3, unchanged=1), "AAPL", None) == "AAPL: unchanged 1"


def test_only_the_symbol_a_crash_left_pending_may_find_its_rows_already_there():
    assert result_violation(_Result(unchanged=40), "AAPL", "AAPL") is None
    assert result_violation(_Result(unchanged=40), "MSFT", "AAPL") == "MSFT: unchanged 40"
    assert result_violation(_Result(changed=1), "AAPL", "AAPL") is not None


def test_from_must_not_skip_any_timeframes_first_raw_bar():
    first = {"5m": "2003-09-10T13:30:00+00:00", "1m": "2026-03-23T13:30:00+00:00", "4h": None}
    assert from_violations(date(2003, 9, 1), first, ["5m", "1m"]) == []
    assert from_violations(date(2003, 9, 1), first, ["4h"]) == []
    assert from_violations(date(2004, 1, 1), first, ["5m", "1m"]) == [
        "5m: first raw bar 2003-09-10T13:30:00+00:00 is before --from 2004-01-01"
    ]


def test_has_written_reads_done_and_inflight_windows():
    assert not has_written({"done": {}, "inflight": {}})
    assert not has_written({"done": {"5m": []}, "inflight": {}})
    assert has_written({"done": {"5m": ["2003-07-14"]}, "inflight": {}})
    assert has_written({"done": {}, "inflight": {"5m|2003-07-14": {"last": "A"}}})


def test_reset_refuses_once_a_window_was_written(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"horizon": "2026-11-12T00:00:00+00:00", "done": {"5m": ["2003-07-14"]}}')
    argv = ["--preflight", "--state", str(path), "--card", str(tmp_path), "--reset"]
    assert main(argv) == 2


def test_resume_refuses_when_the_quiet_list_is_not_quiet(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"horizon": "2026-11-12T00:00:00+00:00", "preflight_failures": []}')
    monkeypatch.setattr(
        "scripts.ops.bars.ops_canonical_rebuild.quiet_failures", lambda: ["units not quiet: x"]
    )
    assert main(["--rebuild", "--state", str(path), "--from", "2003-09-01"]) == 2
