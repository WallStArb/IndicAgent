"""ops_selection_gate.py: the pure comparison, classes, span derivation and the read contract.

Fakes only (todo 494): no database.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.ops.bars import ops_selection_gate as gate
from src.intelligence.bars.selection import Candidate, PolicyRow

KIND_ORDER = {"named": 1, "venue": 2, "sip_rth": 10, "generic": 5}
DAY1 = datetime(2026, 10, 12, 13, 30, tzinfo=UTC)  # 09:30 EDT
DAY2 = datetime(2026, 10, 13, 13, 30, tzinfo=UTC)
DAY3 = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
IBKR = ("ibkr", "named")
ALPACA = ("alpaca", "sip_rth")
DEFAULT_I = PolicyRow("5m", None, date(1990, 1, 1), None, "ibkr", None)


def _vals(close=10.0, volume=100):
    return (9.0, 11.0, 8.5, close, volume)


def _cand(ts, vk=IBKR, close=10.0, volume=100, symbol="SPY"):
    return Candidate(ts, symbol, "5m", vk[0], vk[1], 9.0, 11.0, 8.5, close, volume)


def _day(day, vk, n=3, close=10.0):
    return [(day + timedelta(minutes=5 * i), vk, close) for i in range(n)]


def _canonical(*groups):
    return {ts: (vk, _vals(close)) for group in groups for ts, vk, close in group}


def _raw(*groups):
    return [_cand(ts, vk, close) for group in groups for ts, vk, close in group]


# --- classify and compare ------------------------------------------------------------------


def test_identical_series_totals_zero_and_no_row_level_work():
    canonical = _canonical(_day(DAY1, IBKR))
    selected, counts = gate.selected_rows(_raw(_day(DAY1, IBKR)), [DEFAULT_I], KIND_ORDER)
    diff = gate.compare_series("SPY", "5m", canonical, selected, counts=counts)
    assert (diff.n_canonical, diff.n_selected) == (3, 3)
    assert diff.n_months_digest_mismatch == 0 and not diff.kinds and diff.clean()


def test_a_value_difference_without_evidence_is_real_and_localised_to_its_month():
    canonical = _canonical(_day(DAY1, IBKR))
    raw = _raw(_day(DAY1, IBKR))
    raw[1] = _cand(raw[1].timestamp, IBKR, close=10.5)
    selected, _ = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER)
    diff = gate.compare_series("SPY", "5m", canonical, selected)
    assert diff.kinds == {(gate.VALUE, gate.REAL): 1} and not diff.clean()
    assert diff.n_months == 1 and diff.n_months_digest_mismatch == 1
    assert diff.samples[0]["kind"] == "value" and diff.samples[0]["class"] == "real"


def test_row_level_diff_only_runs_for_a_differing_month():
    jan = datetime(2026, 1, 12, 14, 30, tzinfo=UTC)
    canonical = _canonical(_day(jan, IBKR), _day(DAY1, IBKR))
    raw = _raw(_day(jan, IBKR), _day(DAY1, IBKR))
    raw[4] = _cand(raw[4].timestamp, IBKR, close=11.0)  # October only
    selected, _ = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER)
    diff = gate.compare_series("SPY", "5m", canonical, selected)
    assert (diff.n_months, diff.n_months_digest_mismatch) == (2, 1)
    assert sum(diff.kinds.values()) == 1


def test_null_volume_winner_is_skipped_and_counted_like_the_writer():
    raw = [_cand(DAY1, IBKR, volume=None), _cand(DAY1 + timedelta(minutes=5))]
    rows, counts = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER)
    assert list(rows) == [DAY1 + timedelta(minutes=5)] and counts["skipped_null_volume"] == 1


def test_extended_hours_alpaca_never_reaches_the_comparison():
    pre = datetime(2026, 10, 12, 8, 30, tzinfo=UTC)
    policy = PolicyRow("5m", None, date(1990, 1, 1), None, "alpaca", None)
    rows, counts = gate.selected_rows(
        [_cand(pre, ALPACA), _cand(DAY1, ALPACA)], [policy], KIND_ORDER
    )
    assert list(rows) == [DAY1] and counts["off_grid"] == 1


# --- spans -----------------------------------------------------------------------------------


def _plan(canonical, raw, default=("ibkr",)):
    return gate.derive_spans("SPY", "5m", canonical, raw, KIND_ORDER, default)


def test_ranking_options_prefer_the_default_primary_with_a_fallback():
    options = gate.ranking_options(("ibkr",), ["ibkr", "alpaca", "derived"])
    assert options == [("ibkr", "alpaca"), ("ibkr",), ("alpaca", "ibkr"), ("alpaca",)]
    assert gate.ranking_options(("ibkr",), ["ibkr"]) == [("ibkr",)]


def test_an_ibkr_only_series_needs_no_span():
    plan = _plan(_canonical(_day(DAY1, IBKR)), _raw(_day(DAY1, IBKR)))
    assert plan.spans == [] and plan.blocker_dates == []


def test_a_series_alpaca_fills_gets_one_open_ended_ibkr_then_alpaca_span():
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA))
    raw = _raw(_day(DAY1, IBKR), _day(DAY1, ALPACA, close=10.1), _day(DAY2, ALPACA))
    (span,) = _plan(canonical, raw).spans
    assert (span.primary_source, span.fallback_source) == ("ibkr", "alpaca")
    assert span.valid_from == date(2026, 10, 12) and span.valid_to is None


def test_canonical_alpaca_over_held_ibkr_rows_needs_an_alpaca_first_span_for_those_dates():
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA), _day(DAY3, IBKR))
    raw = _raw(
        _day(DAY1, IBKR),
        _day(DAY1, ALPACA, close=10.1),
        _day(DAY2, IBKR, close=10.2),
        _day(DAY2, ALPACA),
        _day(DAY3, IBKR),
        _day(DAY3, ALPACA, close=10.1),
    )
    spans = _plan(canonical, raw).spans
    assert [(s.valid_from, s.valid_to, s.primary_source, s.fallback_source) for s in spans] == [
        (date(2026, 10, 12), date(2026, 10, 13), "ibkr", "alpaca"),
        (date(2026, 10, 13), date(2026, 10, 14), "alpaca", "ibkr"),
        (date(2026, 10, 14), None, "ibkr", "alpaca"),
    ]


def test_spans_reproduce_canonical_when_applied_as_policy():
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA), _day(DAY3, IBKR))
    raw = _raw(
        _day(DAY1, IBKR),
        _day(DAY1, ALPACA, close=10.1),
        _day(DAY2, IBKR, close=10.2),
        _day(DAY2, ALPACA),
        _day(DAY3, IBKR),
    )
    policy = [DEFAULT_I] + [
        PolicyRow("5m", "SPY", s.valid_from, s.valid_to, s.primary_source, s.fallback_source)
        for s in _plan(canonical, raw).spans
    ]
    selected, _ = gate.selected_rows(raw, policy, KIND_ORDER)
    diff = gate.compare_series("SPY", "5m", canonical, selected)
    assert diff.clean() and not diff.kinds


def test_a_day_mixing_both_vendors_while_both_hold_it_is_a_blocker():
    mixed = _day(DAY1, IBKR, n=2) + [(DAY1 + timedelta(minutes=10), ALPACA, 10.0)]
    canonical = _canonical(mixed)
    raw = _raw(_day(DAY1, IBKR, n=3), _day(DAY1, ALPACA, n=3, close=10.1))
    plan = _plan(canonical, raw)
    assert plan.blocker_dates == [date(2026, 10, 12)]


def test_span_row_json_round_trip_and_reason():
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA))
    raw = _raw(_day(DAY1, IBKR), _day(DAY2, ALPACA))
    (span,) = _plan(canonical, raw).spans
    payload = json.loads(json.dumps(span.to_json()))
    assert payload["reason"] == "reproduces canonical (selection gate, plan 191-07)"
    assert payload["evidence"]["canonical_rows"] == 6 and payload["evidence"]["first_bar"]
    assert gate.SpanRow.from_json(payload) == span


# --- report totals, merge, verdict ---------------------------------------------------------


def _report(real, shard=None, symbol="SPY", **counts):
    kinds = {}
    if real:
        kinds[(gate.VALUE, gate.REAL)] = real
    diff = gate.SeriesDiff(symbol, "5m", n_canonical=10, n_selected=10, kinds=gate.Counter(kinds))
    for name, value in counts.items():
        setattr(diff, name, value)
    meta = {"target": "market_data_ohlcv", "timeframes": ["5m"], "with_spans": []}
    if shard:
        meta["shard"] = shard
    return gate.build_report([diff], meta)


def test_verdict_is_clean_only_when_canonical_equals_the_selection_exactly():
    assert gate.verdict(_report(0)["totals"]) == gate.EXIT_CLEAN
    assert gate.verdict(_report(0, mixed_vendor_sessions=1)["totals"]) == gate.EXIT_RESIDUE == 3
    assert gate.verdict(_report(0, session_choices_unrecorded=2)["totals"]) == gate.EXIT_RESIDUE
    assert gate.verdict(_report(0, sessions_partial=5)["totals"]) == gate.EXIT_CLEAN
    assert gate.verdict(_report(2)["totals"]) == gate.EXIT_REAL
    assert gate.verdict(_report(0, unmapped_canonical=4)["totals"]) == gate.EXIT_REAL
    assert _report(0, unmapped_canonical=4)["totals"]["unmapped_canonical_rows"] == 4


def test_merge_sums_a_complete_shard_set():
    merged = gate.merge_reports(
        [
            _report(1, shard="0/3", symbol="A"),
            _report(0, shard="1/3", symbol="B", sessions_partial=2),
            _report(0, shard="2/3", symbol="C"),
        ]
    )
    assert merged["totals"]["series"] == 3 and merged["totals"]["real_differences"] == 1
    assert merged["totals"]["sessions_partial"] == 2
    assert merged["totals"]["by_timeframe"]["5m"]["n_canonical"] == 30
    assert len(merged["meta"]["merged"]) == 3


def test_merge_refuses_a_missing_repeated_or_mixed_shard():
    with pytest.raises(SystemExit, match="once each"):
        gate.merge_reports([_report(0, shard="0/3"), _report(0, shard="2/3", symbol="C")])
    with pytest.raises(SystemExit, match="once each"):
        gate.merge_reports([_report(0, shard="0/2"), _report(0, shard="0/2")])
    with pytest.raises(SystemExit, match="different N"):
        gate.merge_reports([_report(0, shard="0/2"), _report(0, shard="1/3")])
    with pytest.raises(SystemExit, match="unsharded"):
        gate.merge_reports([_report(0), _report(0, shard="0/1")])
    with pytest.raises(SystemExit, match="more than one report"):
        gate.merge_reports([_report(1, shard="0/2"), _report(1, shard="1/2")])


def test_spans_carry_their_own_evidence_not_the_whole_series():
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA), _day(DAY3, IBKR))
    raw = _raw(
        _day(DAY1, IBKR),
        _day(DAY1, ALPACA, close=10.1),
        _day(DAY2, IBKR, close=10.2),
        _day(DAY2, ALPACA),
        _day(DAY3, IBKR),
        _day(DAY3, ALPACA, close=10.1),
    )
    spans = _plan(canonical, raw).spans
    assert [s.n_canonical for s in spans] == [3, 3, 3]
    assert spans[1].first_bar.startswith("2026-10-13") and spans[1].last_bar.startswith(
        "2026-10-13"
    )


# --- the canonical read contract -----------------------------------------------------------


class _Cur:
    def __init__(self, columns, rows=()):
        self.columns, self.rows, self.sql, self.params = columns, rows, "", None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchall(self):
        if "information_schema" in self.sql:
            return [(c,) for c in self.columns]
        return self.rows


def test_target_with_a_vendor_column_is_read_on_vendor_and_kind_directly():
    cur = _Cur(["timestamp", "symbol", "timeframe", "vendor", "kind", "volume"])
    assert gate.introspect_target(cur, "market_data_ohlcv_v2") == "vendor"
    cur.rows = [(DAY1, "ibkr", "named", 9.0, 11.0, 8.5, 10.0, 100)]
    out = gate.read_canonical(cur, "market_data_ohlcv_v2", "vendor", "SPY", "5m")
    assert out == {DAY1: (IBKR, _vals())} and "vendor <>" in cur.sql


def test_target_with_a_source_column_is_read_through_the_label_map():
    cur = _Cur(["timestamp", "symbol", "timeframe", "source", "volume"])
    assert gate.introspect_target(cur, "market_data_ohlcv") == "source"
    cur.rows = [
        (DAY1, "ibkr_named", 9.0, 11.0, 8.5, 10.0, 100),
        (DAY2, "alpaca", 9.0, 11.0, 8.5, 10.0, 7),
    ]
    out = gate.read_canonical(cur, "market_data_ohlcv", "source", "SPY", "5m")
    assert out[DAY1][0] == IBKR and out[DAY2][0] == ALPACA
    assert "derived_5m" not in cur.params[2] and "ibkr_named" in cur.params[2]


def test_target_name_is_validated_and_must_have_a_vendor_or_source_column():
    with pytest.raises(SystemExit, match="not a plain table name"):
        gate.introspect_target(_Cur([]), "x; drop table y")
    with pytest.raises(SystemExit, match="neither"):
        gate.introspect_target(_Cur(["timestamp"]), "market_data_ohlcv_x")


def test_default_ranking_needs_exactly_one_open_default_row():
    rows = [DEFAULT_I, PolicyRow("5m", "SPY", date(2026, 1, 1), None, "alpaca", None)]
    assert gate.default_ranking(rows, "5m") == ("ibkr",)
    with pytest.raises(SystemExit, match="expected 1"):
        gate.default_ranking(rows, "1m")


def test_shards_partition_the_symbols():
    symbols = [f"S{i:02d}" for i in range(10)]
    parts = [gate.shard_of(symbols, f"{k}/3") for k in range(3)]
    assert sorted(sum(parts, [])) == symbols and all(parts)
    with pytest.raises(SystemExit):
        gate.shard_of(symbols, "3/3")


def test_idempotence_names_spread_across_both_vendor_groups():
    by = {
        "alpaca": [f"A{i:02d}" for i in range(40)],
        "ibkr_named": [f"I{i:02d}" for i in range(40)],
    }
    names = gate.spread_names(by, 25)
    assert len(names) == len(set(names)) == 25
    assert (
        sum(n.startswith("A") for n in names) >= 10 and sum(n.startswith("I") for n in names) >= 10
    )


def test_the_gate_covers_only_the_direct_timeframes():
    with pytest.raises(SystemExit):
        gate.main(["--compare", "--timeframes", "1d"])


def test_apply_spans_is_a_dry_run_without_apply(tmp_path, capsys):
    path = tmp_path / "spans.json"
    row = {
        "timeframe": "5m",
        "symbol": "AAPL",
        "valid_from": "2016-01-01",
        "valid_to": None,
        "primary_source": "ibkr",
        "fallback_source": "alpaca",
        "reason": gate.SPAN_REASON,
        "evidence": {"plan": "191-07", "canonical_rows": 1, "first_bar": "", "last_bar": ""},
    }
    path.write_text(json.dumps({"spans": [row], "blockers": []}))
    assert gate.main(["--apply-spans", "--spans", str(path)]) == 0
    assert "dry run: nothing written" in capsys.readouterr().out
    path.write_text(json.dumps({"spans": [row], "blockers": [{"symbol": "X"}]}))
    assert gate.main(["--apply-spans", "--spans", str(path), "--apply"]) == 2


class _LocateCur:
    """Answers the three reads of locate_groups in order: raw groups, intraday store keys, observation."""

    def __init__(self, raw, intraday, observation):
        self.answers = [raw, intraday, observation]
        self.sql: list[str] = []
        self._next: list = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self._next = self.answers.pop(0)

    def fetchall(self):
        return self._next


def test_locate_groups_reports_only_groups_with_more_raw_rows_than_store_keys():
    d1, d2, d3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)
    cur = _LocateCur(
        raw=[
            ("5m", "ibkr", "named", 3),
            ("5m", "alpaca", "sip_rth", 2),
            ("1d", "ibkr", "smart_trades", 2),
        ],
        intraday=[("5m", "ibkr_named", 2), ("5m", "alpaca", 2), ("5m", "derived_5m", 9)],
        observation=[
            ("ibkr", "SMART", "TRADES", d1),
            ("ibkr", "LEGACY_IMPORT", "TRADES", d1),  # the same session under two routes is one key
            ("ibkr", "SMART", "TRADES", d2),
            ("ibkr", "NOT_A_ROUTE", "TRADES", d3),  # unmapped route is skipped, not fatal
        ],
    )
    assert gate.locate_groups(cur, "SPY") == [("5m", "ibkr", "named", 3, 2)]
    assert "test-%%" in cur.sql[-1] and "UNION" in cur.sql[1]


def test_candidate_policy_turns_emitted_spans_into_policy_rows(tmp_path):
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA))
    raw = _raw(_day(DAY1, IBKR), _day(DAY2, ALPACA))
    (span,) = _plan(canonical, raw).spans
    path = tmp_path / "spans.json"
    path.write_text(json.dumps({"spans": [span.to_json()], "blockers": []}))
    (row,) = gate.candidate_policy([str(path)])
    assert row == PolicyRow("5m", "SPY", date(2026, 10, 12), None, "ibkr", "alpaca")


def test_the_last_span_is_followed_by_the_preferred_ranking_going_forward():
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA), _day(DAY3, ALPACA))
    raw = _raw(
        _day(DAY1, IBKR), _day(DAY2, IBKR, close=10.2), _day(DAY2, ALPACA), _day(DAY3, ALPACA)
    )
    spans = _plan(canonical, raw).spans
    # one alpaca-first run reproduces all three days; the preferred ranking takes over after them
    assert [(s.valid_from, s.valid_to, s.primary_source) for s in spans] == [
        (date(2026, 10, 12), date(2026, 10, 15), "alpaca"),
        (date(2026, 10, 15), None, "ibkr"),
    ]
    assert spans[-1].fallback_source == "alpaca"


def test_canonical_rows_outside_the_vendor_map_are_counted_not_skipped():
    class _CountCur(_Cur):
        def fetchone(self):
            return (2,)

    cur = _CountCur([])
    assert gate.count_unmapped(cur, "market_data_ohlcv", "source", "SPY", "5m") == 2
    assert "source IS NULL" in cur.sql and "ibkr_named" in cur.params[2]
    assert gate.count_unmapped(cur, "market_data_ohlcv_v2", "vendor", "SPY", "5m") == 0


def test_a_derived_label_in_a_direct_timeframe_counts_as_unmapped():
    """read_canonical never compares a derived row; in 1m/5m/4h selection is the only writer,
    so a derived label there is counted (second review of 191-07, low item)."""

    class _CountCur(_Cur):
        def fetchone(self):
            return (0,)

    cur = _CountCur([])
    gate.count_unmapped(cur, "market_data_ohlcv", "source", "SPY", "5m")
    assert "derived_5m" not in cur.params[2] and "ibkr_named" in cur.params[2]
    gate.count_unmapped(cur, "market_data_ohlcv", "source", "SPY", "15m")
    assert "derived_5m" in cur.params[2]  # a derived timeframe keeps the whole label map


def test_a_canonical_session_spliced_from_two_vendors_is_counted_residue():
    """Second review of 191-07, finding 3 (52 of 57 series on 2026-10-09): selection takes a
    session whole from one vendor, so a mixed canonical session is never clean."""
    canonical = _canonical(_day(DAY1, ALPACA, n=2), [(DAY1 + timedelta(minutes=10), IBKR, 10.0)])
    canonical.update(_canonical(_day(DAY2, IBKR)))
    assert gate.mixed_vendor_sessions(canonical) == 1
    report = _report(0, mixed_vendor_sessions=1)
    assert report["totals"]["mixed_vendor_sessions"] == 1
    assert gate.verdict(report["totals"]) == gate.EXIT_RESIDUE


def test_the_gate_selects_a_session_whole_from_a_complete_fallback():
    alpaca_first = PolicyRow("5m", "SPY", date(2026, 10, 1), None, "alpaca", "ibkr")
    raw = _raw(_day(DAY1, ALPACA, n=2), _day(DAY1, IBKR, n=3))
    selected, counts = gate.selected_rows(raw, [DEFAULT_I, alpaca_first], KIND_ORDER)
    assert {row[0] for row in selected.values()} == {IBKR} and len(selected) == 3
    assert (counts["sessions_fallback"], counts["sessions_incomplete"]) == (1, 0)


def test_session_choices_are_counted_partial_and_checked_against_their_record():
    # third review of plan 191-07, finding 4: a session the vendor holds only partly against the
    # calendar is counted; the persisted choice must equal the selection's
    raw = _raw(_day(DAY1, IBKR, n=48))
    expected: list = []
    _selected, counts = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER, choices_out=expected)
    assert counts["sessions_partial"] == 1 and len(expected) == 1
    assert gate.unrecorded_choices(expected, expected) == 0
    assert gate.unrecorded_choices(expected, []) == 1
    stale = [(date(2020, 1, 2), "ibkr", True, 78, 78, 78, 70)]
    assert gate.unrecorded_choices(expected, expected + stale) == 1
    diff = gate.SeriesDiff("SPY", "5m", 0, 0)
    diff.session_choices_unrecorded = 1
    assert not diff.clean()


def test_an_unreviewed_basis_change_flag_is_residue_and_shards_do_not_sum_it():
    # fourth review of 191-07, finding 2
    flagged = _report(0)
    flagged["totals"]["unreviewed_basis_flags"] = 2
    assert gate.verdict(flagged["totals"]) == gate.EXIT_RESIDUE
    reviewed = _report(0)
    reviewed["totals"]["unreviewed_basis_flags"] = 0
    assert gate.verdict(reviewed["totals"]) == gate.EXIT_CLEAN


def test_the_unreviewed_flags_are_read_over_the_whole_table():
    class Cur:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append((sql, params))

        def fetchall(self):
            from datetime import UTC, datetime

            return [
                (
                    "L1",
                    "GE",
                    "5m",
                    "ibkr",
                    "named",
                    1014,
                    1014,
                    1.0,
                    ["share", "price_ratio"],
                    "d",
                    datetime(2026, 10, 15, tzinfo=UTC),
                )
            ]

    cur = Cur()
    (entry,) = gate.count_unreviewed_basis(cur)
    assert entry["series"] == "GE 5m ibkr/named" and entry["signatures"][-1] == "price_ratio"
    ((sql, params),) = cur.sql
    assert "reviewed_at IS NULL" in sql and "symbol =" not in sql
    assert set(params[0]) == {"price_ratio", "volume_ratio", "time_shift"}
