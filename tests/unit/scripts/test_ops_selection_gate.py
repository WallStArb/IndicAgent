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
    diff = gate.compare_series("SPY", "5m", canonical, selected, gate.Evidence(), counts=counts)
    assert (diff.n_canonical, diff.n_selected) == (3, 3)
    assert diff.n_months_digest_mismatch == 0 and not diff.kinds and diff.clean()


def test_a_value_difference_without_evidence_is_real_and_localised_to_its_month():
    canonical = _canonical(_day(DAY1, IBKR))
    raw = _raw(_day(DAY1, IBKR))
    raw[1] = _cand(raw[1].timestamp, IBKR, close=10.5)
    selected, _ = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER)
    diff = gate.compare_series("SPY", "5m", canonical, selected, gate.Evidence())
    assert diff.kinds == {(gate.VALUE, gate.REAL): 1} and not diff.clean()
    assert diff.n_months == 1 and diff.n_months_digest_mismatch == 1
    assert diff.samples[0]["kind"] == "value" and diff.samples[0]["class"] == "real"


def test_row_level_diff_only_runs_for_a_differing_month():
    jan = datetime(2026, 1, 12, 14, 30, tzinfo=UTC)
    canonical = _canonical(_day(jan, IBKR), _day(DAY1, IBKR))
    raw = _raw(_day(jan, IBKR), _day(DAY1, IBKR))
    raw[4] = _cand(raw[4].timestamp, IBKR, close=11.0)  # October only
    selected, _ = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER)
    diff = gate.compare_series("SPY", "5m", canonical, selected, gate.Evidence())
    assert (diff.n_months, diff.n_months_digest_mismatch) == (2, 1)
    assert sum(diff.kinds.values()) == 1


def test_value_difference_with_a_revision_holding_the_canonical_value_is_self_restatement():
    canonical = _canonical(_day(DAY1, IBKR))
    raw = _raw(_day(DAY1, IBKR))
    raw[0] = _cand(raw[0].timestamp, IBKR, close=10.9)
    selected, _ = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER)
    evidence = gate.Evidence(revisions={(raw[0].timestamp, "ibkr", "named"): {_vals(10.0)}})
    diff = gate.compare_series("SPY", "5m", canonical, selected, evidence)
    assert diff.kinds == {(gate.VALUE, gate.SELF_RESTATEMENT): 1}
    assert diff.n_real == 0 and diff.n_explained == 1 and diff.clean()
    assert diff.class_counts() == {gate.SELF_RESTATEMENT: 1}


def test_a_revision_for_another_value_or_key_does_not_explain_a_difference():
    ts = DAY1
    canonical = {ts: (IBKR, _vals(10.0))}
    selected = {ts: (IBKR, _vals(10.9))}
    other_value = gate.Evidence(revisions={(ts, "ibkr", "named"): {_vals(9.9)}})
    other_key = gate.Evidence(revisions={(ts, "alpaca", "sip_rth"): {_vals(10.0)}})
    assert gate.classify(ts, canonical[ts], selected[ts], other_value) == (gate.VALUE, gate.REAL)
    assert gate.classify(ts, canonical[ts], selected[ts], other_key) == (gate.VALUE, gate.REAL)


def test_cross_vendor_and_new_rows_inside_a_refused_window_are_counted_not_folded_in():
    window = {"ibkr": [(date(2026, 10, 9), date(2026, 10, 13))]}
    evidence = gate.Evidence(refused_windows=window)
    ts = DAY1
    # canonical Alpaca, selection ibkr (raw holds IBKR's refused rows)
    assert gate.classify(ts, (ALPACA, _vals()), (IBKR, _vals(10.2)), evidence) == (
        gate.VENDOR_KIND,
        gate.CROSS_VENDOR,
    )
    # raw holds a row canonical lacks
    assert gate.classify(ts, None, (IBKR, _vals()), evidence) == (
        gate.ONLY_SELECTED,
        gate.CROSS_VENDOR,
    )
    # outside the window, or a refusal of a different vendor: real
    outside = gate.Evidence(refused_windows={"ibkr": [(date(2026, 9, 1), date(2026, 9, 30))]})
    assert gate.classify(ts, None, (IBKR, _vals()), outside)[1] == gate.REAL
    other = gate.Evidence(refused_windows={"alpaca": window["ibkr"]})
    assert gate.classify(ts, None, (IBKR, _vals()), other)[1] == gate.REAL


def test_rows_only_in_canonical_are_never_explained_by_a_refusal():
    evidence = gate.Evidence(refused_windows={"ibkr": [(date(2026, 1, 1), date(2026, 12, 31))]})
    assert gate.classify(DAY1, (IBKR, _vals()), None, evidence) == (gate.ONLY_CANONICAL, gate.REAL)


def test_refused_values_must_appear_in_neither_canonical_nor_selection():
    ts = DAY1
    offered = _vals(10.77)
    pending = gate.Evidence(pending={(ts, "ibkr", "named"): {offered}})
    clean = gate.compare_series("SPY", "5m", {ts: (IBKR, _vals())}, {ts: (IBKR, _vals())}, pending)
    assert clean.pending_rows == 1 and clean.clean()
    promoted = gate.compare_series(
        "SPY", "5m", {ts: (IBKR, offered)}, {ts: (IBKR, offered)}, pending
    )
    assert promoted.refused_value_in_canonical == 1 and promoted.refused_value_selected == 1
    assert not promoted.clean()


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


def _plan(canonical, raw, evidence=None, default=("ibkr",)):
    return gate.derive_spans(
        "SPY", "5m", canonical, raw, KIND_ORDER, evidence or gate.Evidence(), default
    )


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
    diff = gate.compare_series("SPY", "5m", canonical, selected, gate.Evidence())
    assert diff.clean() and not diff.kinds


def test_a_day_mixing_both_vendors_while_both_hold_it_is_a_blocker():
    mixed = _day(DAY1, IBKR, n=2) + [(DAY1 + timedelta(minutes=10), ALPACA, 10.0)]
    canonical = _canonical(mixed)
    raw = _raw(_day(DAY1, IBKR, n=3), _day(DAY1, ALPACA, n=3, close=10.1))
    plan = _plan(canonical, raw)
    assert plan.blocker_dates == [date(2026, 10, 12)]


def test_the_same_mixed_day_is_explained_not_blocking_inside_a_refused_window():
    mixed = _day(DAY1, IBKR, n=2) + [(DAY1 + timedelta(minutes=10), ALPACA, 10.0)]
    canonical = _canonical(mixed)
    raw = _raw(_day(DAY1, IBKR, n=3), _day(DAY1, ALPACA, n=3, close=10.1))
    evidence = gate.Evidence(refused_windows={"ibkr": [(date(2026, 10, 12), date(2026, 10, 12))]})
    plan = _plan(canonical, raw, evidence)
    assert plan.blocker_dates == []
    assert [(s.primary_source, s.fallback_source) for s in plan.spans] == [("ibkr", "alpaca")]


def test_span_row_json_round_trip_and_reason():
    canonical = _canonical(_day(DAY1, IBKR), _day(DAY2, ALPACA))
    raw = _raw(_day(DAY1, IBKR), _day(DAY2, ALPACA))
    (span,) = _plan(canonical, raw).spans
    payload = json.loads(json.dumps(span.to_json()))
    assert payload["reason"] == "reproduces canonical (selection gate, plan 191-07)"
    assert payload["evidence"]["canonical_rows"] == 6 and payload["evidence"]["first_bar"]
    assert gate.SpanRow.from_json(payload) == span


# --- report totals, merge, verdict ---------------------------------------------------------


def _report(real, explained=0):
    kinds = {}
    if real:
        kinds[(gate.VALUE, gate.REAL)] = real
    if explained:
        kinds[(gate.VENDOR_KIND, gate.CROSS_VENDOR)] = explained
    diff = gate.SeriesDiff("SPY", "5m", n_canonical=10, n_selected=10, kinds=gate.Counter(kinds))
    return gate.build_report([diff], {})


def test_report_totals_zero_only_when_clean_and_explained_classes_sit_beside_the_zero():
    clean = _report(0, explained=3)
    assert clean["totals"]["real_differences"] == 0
    assert clean["totals"]["explained"] == {gate.CROSS_VENDOR: 3}
    assert gate.verdict(clean["totals"]) == 0
    assert gate.verdict(_report(2)["totals"]) == 1


def test_merge_sums_shards():
    merged = gate.merge_reports([_report(1), _report(0, explained=2), _report(0)])
    assert merged["totals"]["series"] == 3 and merged["totals"]["real_differences"] == 1
    assert merged["totals"]["explained"] == {gate.CROSS_VENDOR: 2}
    assert merged["totals"]["by_timeframe"]["5m"]["n_canonical"] == 30


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
