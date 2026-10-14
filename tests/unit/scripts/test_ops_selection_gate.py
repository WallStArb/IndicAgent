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


REFUSED_AT = datetime(2026, 10, 12, 12, 14, 31, tzinfo=UTC)


def _load(
    outcome="refused",
    at=REFUSED_AT,
    first=date(2026, 10, 1),
    last=date(2026, 10, 31),
    vendor="ibkr",
    destination="market_data_ohlcv",
    caller="ibkr-history-fetch",
    load_id=None,
):
    return gate.LoadFact(
        load_id or f"{outcome}-{at.isoformat()}",
        vendor,
        first,
        last,
        outcome,
        at,
        destination,
        caller,
    )


def _refused_evidence(raw_rows, *, revisions=None):
    """Evidence whose listed raw rows were served by one refused IBKR load."""
    load = _load()
    raw = {(ts, *vk): values for ts, vk, values in raw_rows}
    return gate.Evidence(
        raw=raw,
        refused_serves={key: load for key in raw if key[1] == "ibkr"},
        revisions=revisions or {},
    )


def _refused_on(raw, day):
    """Evidence: every raw row, and IBKR's rows of session `day` served by a refused load."""
    load = _load()
    return gate.Evidence(
        raw={
            (c.timestamp, c.vendor, c.kind): (c.open, c.high, c.low, c.close, c.volume) for c in raw
        },
        refused_serves={
            (c.timestamp, c.vendor, c.kind): load
            for c in raw
            if c.vendor == "ibkr" and c.timestamp.date() == day
        },
    )


def test_a_value_difference_on_a_refused_serve_is_self_restatement():
    canonical = _canonical(_day(DAY1, IBKR))
    raw = _raw(_day(DAY1, IBKR))
    raw[0] = _cand(raw[0].timestamp, IBKR, close=10.9)
    selected, _ = gate.selected_rows(raw, [DEFAULT_I], KIND_ORDER)
    evidence = _refused_evidence([(raw[0].timestamp, IBKR, _vals(10.9))])
    diff = gate.compare_series("SPY", "5m", canonical, selected, evidence)
    assert diff.kinds == {(gate.VALUE, gate.SELF_RESTATEMENT): 1}
    assert diff.n_real == 0 and diff.n_explained == 1
    # explained is not clean: the held refused serve would be selected (D-191-I)
    assert diff.refused_value_selected == 1 and not diff.clean()
    assert diff.class_counts() == {gate.SELF_RESTATEMENT: 1}


def test_a_logged_canonical_value_without_a_refused_serve_explains_nothing():
    # review finding 3: logging alone (17 TMUS slots had no refused load) is not a refusal
    ts = DAY1
    evidence = gate.Evidence(revisions={(ts, "ibkr", "named"): [(REFUSED_AT, _vals(10.0))]})
    assert gate.classify(ts, (IBKR, _vals(10.0)), (IBKR, _vals(10.9)), evidence) == (
        gate.VALUE,
        gate.REAL,
    )


def test_a_revision_holding_the_raw_value_means_canonical_was_restated_after_the_copy():
    ts = DAY1
    canonical = (IBKR, _vals(10.4))  # the vendor's later serve
    selected = (IBKR, _vals(10.0))  # raw still holds the value canonical displaced
    key = (ts, "ibkr", "named")
    evidence = gate.Evidence(revisions={key: [(REFUSED_AT, _vals(10.0))]})
    assert gate.classify(ts, canonical, selected, evidence) == (
        gate.VALUE,
        gate.RESTATED_AFTER_COPY,
    )


def test_when_both_values_are_logged_the_latest_revision_decides():
    ts = DAY1
    key = (ts, "ibkr", "named")
    earlier, later = REFUSED_AT, REFUSED_AT + timedelta(days=1)
    canonical, selected = (IBKR, _vals(10.4)), (IBKR, _vals(10.0))
    # TMUS: full V1 displaced by truncated V2 (raw copied V2), then V2 displaced by V1 again
    raw_last = gate.Evidence(revisions={key: [(earlier, _vals(10.4)), (later, _vals(10.0))]})
    assert gate.classify(ts, canonical, selected, raw_last)[1] == gate.RESTATED_AFTER_COPY
    # canonical's value displaced last and no refused serve: nothing explains raw
    canon_last = gate.Evidence(revisions={key: [(earlier, _vals(10.0)), (later, _vals(10.4))]})
    assert gate.classify(ts, canonical, selected, canon_last)[1] == gate.REAL
    # a refused serve wins over the order: raw is the refused value
    refused = gate.Evidence(
        revisions=raw_last.revisions,
        refused_serves={key: _load()},
        raw={key: _vals(10.0)},
    )
    assert gate.classify(ts, canonical, selected, refused)[1] == gate.SELF_RESTATEMENT


def test_a_revision_for_another_value_or_key_does_not_explain_a_difference():
    ts = DAY1
    canonical = {ts: (IBKR, _vals(10.0))}
    selected = {ts: (IBKR, _vals(10.9))}
    other_value = gate.Evidence(revisions={(ts, "ibkr", "named"): [(REFUSED_AT, _vals(9.9))]})
    other_key = gate.Evidence(revisions={(ts, "alpaca", "sip_rth"): [(REFUSED_AT, _vals(10.0))]})
    assert gate.classify(ts, canonical[ts], selected[ts], other_value) == (gate.VALUE, gate.REAL)
    assert gate.classify(ts, canonical[ts], selected[ts], other_key) == (gate.VALUE, gate.REAL)


def test_cross_vendor_needs_the_refused_serve_of_that_key_and_canonical_own_row_equal():
    ts = DAY1
    ibkr_row = (IBKR, _vals(10.2))
    alpaca_row = (ALPACA, _vals())
    evidence = _refused_evidence([(ts, IBKR, _vals(10.2)), (ts, ALPACA, _vals())])
    # canonical Alpaca (its raw row equal), selection IBKR's refused, unheld serve
    assert gate.classify(ts, alpaca_row, ibkr_row, evidence) == (
        gate.VENDOR_KIND,
        gate.CROSS_VENDOR,
    )
    # raw holds a row canonical lacks
    assert gate.classify(ts, None, ibkr_row, evidence) == (gate.ONLY_SELECTED, gate.CROSS_VENDOR)
    # canonical's own Alpaca raw row differs: the Alpaca divergence is not hidden (finding 5)
    drift = _refused_evidence([(ts, IBKR, _vals(10.2)), (ts, ALPACA, _vals(10.7))])
    assert gate.classify(ts, alpaca_row, ibkr_row, drift)[1] == gate.REAL
    # the selected row was not served by a refused load: real, whatever the window says
    plain = gate.Evidence(raw=evidence.raw)
    assert gate.classify(ts, None, ibkr_row, plain)[1] == gate.REAL
    # same vendor, different kind is never explained by a refusal
    venue = (("ibkr", "venue"), _vals())
    same_vendor = _refused_evidence([(ts, IBKR, _vals(10.2)), (ts, ("ibkr", "venue"), _vals())])
    assert gate.classify(ts, venue, ibkr_row, same_vendor)[1] == gate.REAL


def test_a_refused_serve_that_displaced_the_vendor_own_value_is_held_not_cross_vendor():
    ts = DAY1
    key = (ts, "ibkr", "named")
    evidence = _refused_evidence(
        [(ts, IBKR, _vals(10.2))], revisions={key: [(REFUSED_AT, _vals(10.0))]}
    )
    assert evidence.held(key, None)
    assert gate.classify(ts, None, (IBKR, _vals(10.2)), evidence)[1] == gate.REAL
    diff = gate.compare_series("SPY", "5m", {}, {ts: (IBKR, _vals(10.2))}, evidence)
    assert diff.refused_value_selected == 1


def test_rows_only_in_canonical_are_never_explained_by_a_refusal():
    evidence = _refused_evidence([(DAY1, IBKR, _vals())])
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
    # canonical's Alpaca row equals Alpaca's own raw row (otherwise the slot is real, finding 5)
    raw = _raw(_day(DAY1, IBKR, n=3), _day(DAY1, ALPACA, n=3))
    plan = _plan(canonical, raw, _refused_on(raw, date(2026, 10, 12)))
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


def _report(real, explained=0, shard=None, symbol="SPY", **counts):
    kinds = {}
    if real:
        kinds[(gate.VALUE, gate.REAL)] = real
    if explained:
        kinds[(gate.VENDOR_KIND, gate.CROSS_VENDOR)] = explained
    diff = gate.SeriesDiff(symbol, "5m", n_canonical=10, n_selected=10, kinds=gate.Counter(kinds))
    for name, value in counts.items():
        setattr(diff, name, value)
    meta = {"target": "market_data_ohlcv", "timeframes": ["5m"], "with_spans": []}
    if shard:
        meta["shard"] = shard
    return gate.build_report([diff], meta)


def test_verdict_is_clean_only_when_canonical_equals_the_selection_exactly():
    assert gate.verdict(_report(0)["totals"]) == gate.EXIT_CLEAN
    explained = _report(0, explained=3)
    assert explained["totals"]["real_differences"] == 0
    assert explained["totals"]["explained"] == {gate.CROSS_VENDOR: 3}
    # finding 1: explained residue is not clean (it was exit 0)
    assert gate.verdict(explained["totals"]) == gate.EXIT_RESIDUE == 3
    assert gate.verdict(_report(0, refused_value_selected=1)["totals"]) == gate.EXIT_RESIDUE
    assert gate.verdict(_report(2)["totals"]) == gate.EXIT_REAL
    assert gate.verdict(_report(0, refused_value_in_canonical=1)["totals"]) == gate.EXIT_REAL
    assert gate.verdict(_report(0, unmapped_canonical=4)["totals"]) == gate.EXIT_REAL
    assert _report(0, unmapped_canonical=4)["totals"]["unmapped_canonical_rows"] == 4


def test_merge_sums_a_complete_shard_set():
    merged = gate.merge_reports(
        [
            _report(1, shard="0/3", symbol="A"),
            _report(0, explained=2, shard="1/3", symbol="B"),
            _report(0, shard="2/3", symbol="C"),
        ]
    )
    assert merged["totals"]["series"] == 3 and merged["totals"]["real_differences"] == 1
    assert merged["totals"]["explained"] == {gate.CROSS_VENDOR: 2}
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


def test_refused_serve_map_matches_by_load_id_or_served_at_and_honours_a_later_raw_serve():
    ts = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
    refused = _load(load_id="R")
    by_id = (ts, "ibkr", "named")
    by_time = (ts + timedelta(minutes=5), "ibkr", "named")
    other_vendor = (ts, "alpaca", "sip_rth")
    serves = {by_id: (None, "R"), by_time: (REFUSED_AT, None), other_vendor: (REFUSED_AT, None)}
    assert set(gate.refused_serve_map(serves, [refused])) == {by_id, by_time}
    later = REFUSED_AT + timedelta(hours=1)
    # a later applied raw serve of the same vendor covering the date re-served the slot
    reserved = _load("applied", later, destination="raw", load_id="A")
    assert gate.refused_serve_map(serves, [refused, reserved]) == {}
    # a legacy (canonical-era) serve, a backfill or repair record, or an earlier load does not
    for load in (
        _load("applied", later, load_id="L"),
        _load("applied", later, destination="raw", caller="raw-repair-191", load_id="P"),
        _load("applied", REFUSED_AT - timedelta(hours=1), destination="raw", load_id="E"),
        _load("applied", later, destination="raw", first=date(2026, 10, 6), load_id="W"),
    ):
        assert set(gate.refused_serve_map(serves, [refused, load])) == {by_id, by_time}


def test_later_serve_finds_a_covering_applied_vendor_serve():
    ts = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
    loads = [_load("applied", REFUSED_AT + timedelta(minutes=1), load_id="A")]
    assert gate.later_serve(ts, "ibkr", REFUSED_AT, loads) is loads[0]
    assert gate.later_serve(ts, "ibkr", REFUSED_AT, loads, destination="raw") is None
    assert gate.later_serve(ts, "alpaca", REFUSED_AT, loads) is None


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


def test_a_refusal_explained_day_takes_the_ranking_closest_to_canonical():
    canonical = _canonical(_day(DAY1, ALPACA))
    raw = _raw(_day(DAY1, IBKR, close=10.2), _day(DAY1, ALPACA))
    span, tail = _plan(canonical, raw, _refused_on(raw, date(2026, 10, 12))).spans
    # (ibkr, alpaca) would carry three explained differences; (alpaca, ibkr) carries none
    assert (span.primary_source, span.fallback_source) == ("alpaca", "ibkr")
    assert (tail.primary_source, tail.valid_from, tail.valid_to) == (
        "ibkr",
        date(2026, 10, 13),
        None,
    )


def test_rows_only_raw_holds_never_narrow_a_span_to_one_vendor():
    # canonical stops with Alpaca on day 1; IBKR's refused rows for day 2 sit only in raw
    canonical = _canonical(_day(DAY1, ALPACA))
    raw = _raw(_day(DAY1, ALPACA), _day(DAY2, IBKR))
    (span,) = _plan(canonical, raw, _refused_on(raw, date(2026, 10, 13))).spans
    assert (span.primary_source, span.fallback_source) == ("ibkr", "alpaca")
    assert span.valid_to is None


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


def test_a_refused_value_canonical_took_from_a_later_applied_serve_is_not_held():
    # GE 2021-11-05 19:40: refused at 12:14, then an applied serve at 15:47 put the same value in
    # canonical and logged the 4-decimal value it displaced
    ts = datetime(2021, 11, 5, 19, 40, tzinfo=UTC)
    key = (ts, "ibkr", "named")
    refused = _load(first=date(2021, 9, 1), last=date(2022, 4, 5), load_id="R")
    evidence = gate.Evidence(
        raw={key: _vals(10.0)},
        refused_serves={key: refused},
        revisions={key: [(REFUSED_AT + timedelta(hours=3), _vals(10.0001))]},
        loads=[refused],
    )
    canonical = (IBKR, _vals(10.0))
    assert evidence.held(key, canonical)  # no later serve on record: canonical took a held value
    evidence.loads.append(
        _load(
            "applied",
            REFUSED_AT + timedelta(hours=3),
            first=date(2021, 4, 5),
            last=date(2021, 11, 5),
            load_id="A",
        )
    )
    assert not evidence.held(key, canonical)
    diff = gate.compare_series("SPY", "5m", {ts: canonical}, {ts: canonical}, evidence)
    assert diff.refused_value_in_canonical == 0 and diff.clean()
