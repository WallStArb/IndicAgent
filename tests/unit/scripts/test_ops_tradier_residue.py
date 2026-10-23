"""Tests for ops_tradier_residue (phase 191 plan 19): readiness, residue measurement, the
fallback-path proof and the harness digest self-check.

The proof harness must run the unchanged d2-v3 rule over the d2v2_known_cases fixture shapes
with the Tradier candidates removed: a head case (DAL), an interior-hole case (INDA) and the
no-Tradier-at-all case (ETHA), where the honest characterization is that the rule serves
nothing (every IBKR observation is stale for the recorded split, so every session lands in
stale_only and no canonical bar exists).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.ops.bars import ops_tradier_residue as residue
from src.intelligence.bars.daily_rule import (
    FLAG_FALLBACK_SEAM,
    FLAG_PRE_SPLIT,
    PolicyRow,
    derive_daily_v2,
)
from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.vendor_kind import VENUE_ROUTE_KINDS

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "bars" / "d2v2_known_cases.json"
_D = date(2026, 10, 7)
_DEPTH_AT = datetime(2026, 10, 12, 10, 45, 49, tzinfo=UTC)
_TODAY = date(2026, 10, 22)
_DEFAULT = PolicyRow(
    timeframe="1d",
    symbol=None,
    valid_from=date(1990, 1, 1),
    valid_to=None,
    ingress_mode="observed",
    primary_source="tradier",
    fallback_source="ibkr",
)


def _case(symbol: str) -> tuple[list[Observation], list[SplitRecord]]:
    case = json.loads(_FIXTURE.read_text())["cases"][symbol]
    observations = [
        Observation(
            request_id=o["request_id"],
            route=o["route"],
            bar_date=date.fromisoformat(o["bar_date"]),
            open=o["open"],
            high=o["high"],
            low=o["low"],
            close=o["close"],
            volume=o["volume"],
            fetched_at=datetime.fromisoformat(o["fetched_at"]),
            legacy=o["route"] == "LEGACY_IMPORT",
            what_to_show=o["what_to_show"],
        )
        for o in case["observations"]
    ]
    splits = [
        SplitRecord(
            effective_date=date.fromisoformat(s["effective_date"]),
            recorded_at=datetime.fromisoformat(s["recorded_at"]),
            factor=s["factor"],
            evidence_request_ids=tuple(s["evidence_request_ids"]),
        )
        for s in case["splits"]
    ]
    return observations, splits


def _derive_without_tradier(symbol: str):
    """The proof harness's core: the unchanged rule over the case with Tradier removed."""
    observations, splits = _case(symbol)
    kept = [o for o in observations if o.route != "TRADIER"]
    return derive_daily_v2(
        kept,
        [_DEFAULT],
        splits,
        symbol=symbol,
        basis_window_sessions=20,
        basis_tolerance_bp=10.0,
    )


# --- readiness ---------------------------------------------------------------------------------


def test_readiness_threshold_is_the_deeper_of_first_tradier_and_the_depth_horizon():
    horizon = _TODAY - timedelta(days=9800)
    # A 2000 Tradier head is deeper than the 9800-day horizon: IBKR must have been asked to it.
    assert residue.readiness_threshold(date(2000, 1, 3), _TODAY) == date(2000, 1, 3)
    assert residue.readiness_threshold(date(2000, 1, 3), _TODAY) > horizon
    # A recent listing is shallower: the horizon bounds the ask.
    assert residue.readiness_threshold(date(2020, 12, 10), _TODAY) == horizon


def test_readiness_needs_a_post_depth_change_ask_reaching_the_threshold():
    first = date(2013, 9, 26)
    deep_late = (first, _DEPTH_AT + timedelta(days=5))
    assert residue.readiness_answered(first, [deep_late], _DEPTH_AT, _TODAY)
    # An ask answered before the depth change does not count (it used the shallower depth).
    deep_early = (first, _DEPTH_AT - timedelta(minutes=1))
    assert not residue.readiness_answered(first, [deep_early], _DEPTH_AT, _TODAY)
    # A post-change ask that only reaches above the first Tradier bar does not count.
    shallow_late = (date(2014, 1, 15), _DEPTH_AT + timedelta(days=5))
    assert not residue.readiness_answered(first, [shallow_late], _DEPTH_AT, _TODAY)
    # The exact threshold date and the exact depth-change instant count.
    on_the_line = (first, _DEPTH_AT + timedelta(microseconds=1))
    assert residue.readiness_answered(first, [on_the_line], _DEPTH_AT, _TODAY)


def test_classify_readiness_splits_names():
    rows = [
        residue.NameReadiness("AAA", date(2000, 1, 3), True),
        residue.NameReadiness("BBB", date(2004, 2, 5), False),
    ]
    answered, unanswered = residue.classify_readiness(rows)
    assert answered == ["AAA"] and unanswered == ["BBB"]


# --- measure -----------------------------------------------------------------------------------


def _measure(symbol="TEST", tradier=(), ibkr=(), empty=(), stored_first=None):
    return residue.measure_name(
        symbol,
        list(tradier),
        list(ibkr),
        list(empty),
        stored_first,
    )


def test_residue_is_a_tradier_session_ibkr_never_answered():
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)]
    tradier = [(d, 100.0, 1000) for d in days]
    ibkr = [
        (days[1], "smart_trades", 100.1, 500),
        (days[2], "venue_nyse", 100.0, 400),
    ]
    empty = [(datetime(days[3], tzinfo=UTC), datetime(days[3], tzinfo=UTC))]
    row = _measure(tradier=tradier, ibkr=ibkr, empty=empty, stored_first=days[0])
    # Only Jan 2 is answered by Tradier alone: smart and venue rows cover, the empty span covers.
    assert row.n_tradier == 4 and row.n_residue == 1
    assert row.residue_first == days[0] and row.residue_last == days[0]
    assert row.residue_dates == [days[0]]


def test_smart_adjusted_is_not_ibkr_coverage_and_venue_sessions_are_counted():
    days = [date(2024, 1, 2), date(2024, 1, 3)]
    tradier = [(d, 100.0, 1000) for d in days]
    ibkr = [(days[0], "smart_adjusted", 99.0, 10), (days[1], "venue_amex", 100.0, 400)]
    row = _measure(tradier=tradier, ibkr=ibkr)
    assert row.n_residue == 1 and row.residue_dates == [days[0]]
    assert row.n_venue_sessions == 1


def test_first_bar_change_uses_the_smart_series_the_rule_can_serve():
    tradier = [(date(2000, 1, 3), 10.0, 100), (date(2000, 1, 4), 10.0, 100)]
    ibkr = [
        (date(2006, 10, 9), "venue_nyse", 20.0, 5),
        (date(2006, 10, 10), "smart_trades", 20.0, 9),
    ]
    row = _measure(tradier=tradier, ibkr=ibkr, stored_first=date(2000, 1, 3))
    # A venue row is never a rule input: the post-deletion first bar is the first smart bar.
    assert row.first_bar_current == date(2000, 1, 3)
    assert row.first_bar_after == date(2006, 10, 10)
    gone = _measure(tradier=tradier, ibkr=[], stored_first=date(2000, 1, 3))
    assert gone.first_bar_after is None  # the name loses its whole 1d history


def test_value_difference_distribution_at_common_smart_sessions():
    days = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    tradier = [(d, 100.0, 1000) for d in days]
    ibkr = [
        (days[0], "smart_trades", 100.01, 500),
        (days[1], "smart_trades", 100.02, 520),
        (days[2], "smart_trades", 99.97, 540),
        (date(2024, 1, 8), "smart_trades", 100.0, 500),  # no Tradier row: not common
    ]
    row = _measure(tradier=tradier, ibkr=ibkr, stored_first=days[0])
    assert row.n_common == 3
    assert row.close_bp_median == pytest.approx(1.0)  # median of [1, 2, -3] bp
    assert row.close_bp_p10 == pytest.approx(-2.2)  # numpy linear interpolation of [-3, 1, 2]
    assert row.close_bp_p90 == pytest.approx(1.8)
    assert row.volume_ratio_median == pytest.approx(0.52)


def test_distribution_is_none_without_common_volume_or_sessions():
    tradier = [(date(2024, 1, 2), 100.0, 0)]
    ibkr = [(date(2024, 1, 2), "smart_trades", 100.0, 0)]
    row = _measure(tradier=tradier, ibkr=ibkr)
    assert row.n_common == 1
    assert row.close_bp_median == pytest.approx(0.0)
    assert row.volume_ratio_median is None
    assert _measure(tradier=[], ibkr=[]).close_bp_median is None


# --- the unchanged rule over the fixture shapes with Tradier removed ---------------------------


def test_dal_head_case_without_tradier_serves_every_ibkr_session_as_fallback_head():
    result = _derive_without_tradier("DAL")
    observations, _ = _case("DAL")
    ibkr_days = sorted({o.bar_date for o in observations if o.route != "TRADIER"})
    assert [b.bar_date for b in result.bars] == ibkr_days
    assert all((b.vendor, b.kind) == ("ibkr", "fallback") for b in result.bars)
    # With no Tradier answer at all the fallback is the series: every session is head, and
    # there is no Tradier bar to carry the seam flag.
    assert result.head == ibkr_days and result.refused_head == []
    assert all(f.rule != FLAG_FALLBACK_SEAM for f in result.flags)
    assert result.refused_interior == [] and result.restated == []
    # The head dates the real (Tradier-present) run serves are a subset, values unchanged.
    by_day = {b.bar_date: b.close for b in result.bars}
    assert by_day[date(2007, 4, 26)] == 22.79 and by_day[date(2007, 4, 27)] == 20.91


def test_inda_interior_case_without_tradier_serves_all_smart_sessions_with_their_volumes():
    result = _derive_without_tradier("INDA")
    observations, _ = _case("INDA")
    smart = {o.bar_date: o for o in observations if o.route == "SMART"}
    assert {b.bar_date for b in result.bars} == set(smart)
    assert all((b.vendor, b.kind) == ("ibkr", "fallback") for b in result.bars)
    by_day = {b.bar_date: b.volume for b in result.bars}
    assert all(by_day[d] == smart[d].volume for d in smart)
    assert result.refused_interior == [] and result.refused_head == []


def test_etha_without_tradier_serves_nothing_every_ibkr_observation_is_stale():
    # The honest characterization of the no-primary-bars-at-all case: the recorded reverse
    # split stales every IBKR observation (fetched before recorded_at, none of them the
    # split's evidence), so the rule serves no bar at all and lists every session stale_only.
    result = _derive_without_tradier("ETHA")
    observations, _ = _case("ETHA")
    ibkr_days = sorted({o.bar_date for o in observations if o.route != "TRADIER"})
    assert result.bars == []
    assert result.stale_only == ibkr_days
    assert result.head == [] and result.refused_head == [] and result.refused_interior == []


# --- proof classification ----------------------------------------------------------------------


def test_classify_proof_marks_a_name_proven_when_every_required_session_is_served():
    smart = {date(2024, 1, 2), date(2024, 1, 3)}
    venue = {date(2024, 1, 4)}
    bars = [b for b in _derive_without_tradier("DAL").bars]  # real bars, kinds counted
    proof = residue.classify_proof(
        "TEST",
        smart_dates=smart | {b.bar_date for b in bars},
        venue_dates=venue,
        bars=bars,
    )
    assert proof.proven and proof.unserved == [] and proof.exception is None
    assert proof.n_required == len(smart | venue | {b.bar_date for b in bars})
    assert proof.served_fallback == len(bars) and proof.served_named == 0


def test_classify_proof_splits_unserved_sessions_and_flags_venue_moved():
    d1, d2, d3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)
    served = [b for b in _derive_without_tradier("DAL").bars]
    proof = residue.classify_proof("TEST", smart_dates={d1, d2}, venue_dates={d3}, bars=served)
    assert not proof.proven
    assert proof.unserved == [d1, d2, d3]  # none of TEST's sessions is among DAL's bars
    assert proof.unserved_smart == 2 and proof.unserved_venue_only == 1
    assert not proof.venue_moved
    venue_only = residue.classify_proof("TEST", smart_dates=set(), venue_dates={d3}, bars=served)
    assert venue_only.venue_moved and venue_only.unserved_venue_only == 1


def test_classify_proof_post_d_sessions_are_not_required_and_exceptions_fail_the_name():
    post = date(2026, 10, 8)
    proof = residue.classify_proof("TEST", smart_dates={post}, venue_dates=set(), bars=[])
    assert proof.n_required == 0 and proof.proven
    failed = residue.classify_proof(
        "TEST",
        smart_dates={date(2024, 1, 2)},
        venue_dates=set(),
        bars=[],
        error=LookupError("no bar_source_policy row covers (1d, TEST) on 1980-01-02"),
    )
    assert not failed.proven and failed.exception is not None and failed.unserved == []


# --- harness digest self-check -----------------------------------------------------------------


def _bar(day: date, close: float, volume: int = 100):
    from src.intelligence.bars.derivation import CanonicalBar

    return CanonicalBar(
        bar_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        vendor="ibkr",
        kind="named",
        request_ids=("r",),
        flags=(),
    )


def _stored(day: date, close: float, volume: int = 100, kind="named"):
    return (datetime(day, tzinfo=UTC), "ibkr", kind, close, close, close, close, volume)


def _self_check(harness_bars, stored_rows, harness_flags=None, stored_rules=None):
    return residue.digest_self_check(
        "TEST",
        harness_bars,
        harness_flags or {},
        stored_rows,
        stored_rules or {},
    )


def test_self_check_digests_match_when_values_and_rule_overlay_match():
    days = [date(2026, 10, 8), date(2026, 10, 9)]
    bars = [_bar(d, 100.0) for d in days]
    stored = [_stored(d, 100.0) for d in days]
    rules = {int(datetime(d, tzinfo=UTC).timestamp()): {"scrub_rule"} for d in days}
    # A scrub rule rides both sides identically; the daily-stage rules are the harness's own.
    flags = {days[0]: {FLAG_PRE_SPLIT}}
    rules[int(datetime(days[0], tzinfo=UTC).timestamp())] = {"scrub_rule", FLAG_PRE_SPLIT}
    check = _self_check(bars, stored, harness_flags=flags, stored_rules=rules)
    assert check.equal and check.n_harness == check.n_stored == 2
    assert check.harness_digest == check.stored_digest and check.harness_digest


def test_self_check_catches_a_value_difference():
    days = [date(2026, 10, 8)]
    check = _self_check([_bar(days[0], 100.0)], [_stored(days[0], 100.5)])
    assert not check.equal


def test_self_check_catches_a_flag_difference_and_an_extra_stored_row():
    days = [date(2026, 10, 8)]
    flags = {days[0]: {FLAG_PRE_SPLIT}}
    check = _self_check([_bar(days[0], 100.0)], [_stored(days[0], 100.0)], harness_flags=flags)
    assert not check.equal
    # A stored venue row the rule never writes is a difference, surfaced by the kind counts.
    extra = _self_check(
        [_bar(days[0], 100.0)], [_stored(days[0], 100.0), _stored(days[0], 1.0, kind="venue")]
    )
    assert not extra.equal and extra.n_stored == 2


def test_self_check_over_daily_flag_overlay_matches_write_1d_digests_semantics():
    # stored rules {scrub, pre_split} on a bar the harness flags pre_split: the overlay keeps
    # scrub and replaces the daily-stage rules with the harness's own, so identical inputs digest equal.
    day = date(2026, 10, 8)
    ts = int(datetime(day, tzinfo=UTC).timestamp())
    check = residue.digest_self_check(
        "TEST",
        [_bar(day, 100.0)],
        {day: {FLAG_PRE_SPLIT}},
        [_stored(day, 100.0)],
        {ts: {"scrub_rule", FLAG_PRE_SPLIT}},
    )
    assert check.equal


# --- read-only guard and the raw kind vocabulary ------------------------------------------------


def test_the_module_contains_no_write_statements():
    source = Path(residue.__file__).read_text()
    for line in source.splitlines():
        if line.strip().startswith("#"):
            continue
        assert not re.search(r"\b(?:INSERT|UPDATE|DELETE)\b", line), line


def test_ibkr_raw_kinds_are_the_route_kinds_never_the_bare_venue_kind():
    kinds = residue.IBKR_RAW_KINDS
    assert kinds[0] == "smart_trades"
    assert set(kinds[1:]) == set(VENUE_ROUTE_KINDS)
    assert all(k.startswith("venue_") for k in kinds[1:])
    assert "venue" not in kinds and "smart_adjusted" not in kinds
