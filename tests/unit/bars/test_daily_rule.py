"""The unified daily rule d2-v2 (plan 185-36; data layer integrity design sections 2 and 4).

Pure-function tests: synthetic observations for the mechanics, and real read-only D1 extracts
(tests/fixtures/bars/d2v2_known_cases.json) for the cases that motivated the rule: RJF's IBKR
pre-split step, REX's Tradier seam under an IBKR exception row, DAL's 2007 head, ETHA's reverse
split and INDA's 2012 interior IBKR bars.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.intelligence.bars.daily_rule import (
    FLAG_FALLBACK_SEAM,
    FLAG_NO_VOLUME,
    FLAG_PRE_SPLIT,
    RULE_VERSION,
    PolicyRow,
    derive_daily_v2,
    resolve_policy,
)
from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.sources import SOURCE_IBKR_FALLBACK

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "bars" / "d2v2_known_cases.json"
_WINDOW = 20
_TOL_BP = 10.0
_DEFAULT = PolicyRow(
    timeframe="1d",
    symbol=None,
    valid_from=date(1990, 1, 1),
    valid_to=None,
    ingress_mode="observed",
    primary_source="tradier",
    fallback_source="ibkr",
)
_T0 = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)


def _obs(
    route: str,
    day: date,
    close: float,
    *,
    fetched_at: datetime = _T0,
    request_id: str | None = None,
    volume: int | None = 100,
    what_to_show: str = "TRADES",
) -> Observation:
    return Observation(
        request_id=request_id or f"{route}-{fetched_at.isoformat()}",
        route=route,
        bar_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        fetched_at=fetched_at,
        legacy=route == "LEGACY_IMPORT",
        what_to_show=what_to_show,
    )


def _sessions(start: date, n: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _derive(observations, policy=(_DEFAULT,), splits=(), symbol="TEST"):
    return derive_daily_v2(
        observations,
        list(policy),
        list(splits),
        symbol=symbol,
        basis_window_sessions=_WINDOW,
        basis_tolerance_bp=_TOL_BP,
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


def _latest(observations: list[Observation], route: str) -> dict[date, Observation]:
    out: dict[date, Observation] = {}
    for o in sorted(observations, key=lambda o: (o.fetched_at, o.request_id)):
        if o.route == route:
            out[o.bar_date] = o
    return out


# --- fixture ---------------------------------------------------------------------------------


def test_known_case_fixture_is_present_and_documented():
    cases = json.loads(_FIXTURE.read_text())["cases"]
    assert set(cases) == {"RJF", "REX", "DAL", "ETHA", "INDA"}
    assert all(case["observations"] for case in cases.values())
    readme = (_FIXTURE.parent / "README.md").read_text()
    assert "## d2v2_known_cases.json" in readme


# --- mechanics -------------------------------------------------------------------------------


def test_rule_version():
    # d2-v3 (plan 185-52, todo 517): a stale-only primary yields to a basis-tested current
    # fallback answer.
    assert RULE_VERSION == "d2-v3"


def test_tradier_date_takes_the_latest_tradier_observation():
    day = date(2024, 5, 1)
    older = _obs("TRADIER", day, 10.0, fetched_at=_T0, request_id="t-old")
    newer = _obs("TRADIER", day, 10.5, fetched_at=_T0 + timedelta(days=1), request_id="t-new")
    smart = _obs("SMART", day, 9.0, fetched_at=_T0 + timedelta(days=2), request_id="s")
    result = _derive([newer, smart, older])
    (bar,) = result.bars
    assert (bar.close, bar.source, bar.request_ids, bar.flags) == (10.5, "tradier", ("t-new",), ())
    assert result.flags == [] and result.refused_interior == []


def test_head_is_admitted_as_fallback_with_a_seam_flag_on_the_first_tradier_bar():
    days = _sessions(date(2024, 1, 2), 30)
    head, rest = days[:3], days[3:]
    observations = [_obs("SMART", d, 10.0, request_id=f"s{d}") for d in days]
    # IBKR sits 8 bp above Tradier over the overlap (inside the 10 bp head gate): the seam
    # records it.
    observations += [_obs("TRADIER", d, 10.0 / 1.0008, request_id=f"t{d}") for d in rest]
    result = _derive(observations)
    by_day = {b.bar_date: b for b in result.bars}
    assert [by_day[d].source for d in head] == [SOURCE_IBKR_FALLBACK] * 3
    assert all(by_day[d].source == "tradier" for d in rest)
    (seam,) = result.flags
    assert (seam.bar_date, seam.rule) == (rest[0], FLAG_FALLBACK_SEAM)
    assert seam.detail["n_common"] == _WINDOW
    assert seam.detail["window_sessions"] == _WINDOW
    assert seam.detail["median_ratio"] == pytest.approx(1.0008)
    assert seam.detail["n_head_bars"] == 3
    assert seam.detail["head_first"] == head[0].isoformat()
    assert FLAG_FALLBACK_SEAM in by_day[rest[0]].flags
    assert result.head == head and result.refused_interior == []


def _interior(offset_bp: float):
    days = _sessions(date(2024, 1, 2), 41)
    hole = days[20]
    observations = [_obs("TRADIER", d, 100.0, request_id=f"t{d}") for d in days if d != hole]
    observations += [
        _obs("SMART", d, 100.0 * (1 + offset_bp / 1e4), request_id=f"s{d}") for d in days
    ]
    return hole, _derive(observations)


def test_interior_hole_within_tolerance_is_admitted():
    hole, result = _interior(5.0)
    bar = next(b for b in result.bars if b.bar_date == hole)
    assert bar.source == SOURCE_IBKR_FALLBACK and bar.request_ids == (f"s{hole}",)
    assert result.refused_interior == [] and result.admitted_interior == [hole]
    assert result.flags == []


def test_interior_hole_outside_tolerance_has_no_bar():
    hole, result = _interior(15.0)
    assert hole not in {b.bar_date for b in result.bars}
    assert result.refused_interior == [hole] and result.admitted_interior == []
    assert len(result.bars) == 40


def test_nearest_window_ties_go_to_the_earlier_session():
    # Window 1: the neighbours one session either side tie on distance; the earlier one wins,
    # and its ratio (0 bp) admits the hole where the later one (100 bp) would refuse it.
    days = _sessions(date(2024, 1, 2), 5)
    hole = days[2]
    observations = [_obs("TRADIER", d, 100.0, request_id=f"t{d}") for d in days if d != hole]
    ratios = {days[0]: 1.0, days[1]: 1.0, days[2]: 1.0, days[3]: 1.01, days[4]: 1.01}
    observations += [_obs("SMART", d, 100.0 * r, request_id=f"s{d}") for d, r in ratios.items()]
    result = derive_daily_v2(
        observations,
        [_DEFAULT],
        [],
        symbol="TEST",
        basis_window_sessions=1,
        basis_tolerance_bp=_TOL_BP,
    )
    assert result.admitted_interior == [hole]


def test_stale_scale_observations_are_never_chosen_when_a_current_one_exists():
    day = date(2024, 5, 1)
    split = SplitRecord(
        effective_date=date(2024, 6, 3),
        recorded_at=_T0 + timedelta(hours=1),
        factor=2.0,
        evidence_request_ids=("t-evidence",),
    )
    stale = _obs("TRADIER", day, 20.0, fetched_at=_T0, request_id="t-stale")
    # Fetched before recorded_at but named as the split's evidence: on the new scale.
    evidence = _obs(
        "TRADIER", day, 10.0, fetched_at=_T0 - timedelta(seconds=1), request_id="t-evidence"
    )
    result = _derive([stale, evidence], splits=[split])
    (bar,) = result.bars
    assert (bar.close, bar.request_ids, bar.flags) == (10.0, ("t-evidence",), ())


def test_stale_only_primary_is_flagged_pre_split():
    day = date(2024, 5, 1)
    split = SplitRecord(date(2024, 6, 3), _T0 + timedelta(hours=1), 2.0)
    result = _derive([_obs("TRADIER", day, 20.0, request_id="t")], splits=[split])
    (bar,) = result.bars
    assert bar.flags == (FLAG_PRE_SPLIT,)
    assert [(f.bar_date, f.rule) for f in result.flags] == [(day, FLAG_PRE_SPLIT)]


def test_stale_fallback_is_never_admitted():
    day = date(2024, 5, 1)
    split = SplitRecord(date(2024, 6, 3), _T0 + timedelta(hours=1), 2.0)
    result = _derive([_obs("SMART", day, 20.0, request_id="s")], splits=[split])
    assert result.bars == [] and result.stale_only == [day]


def test_missing_provider_volume_is_flagged():
    result = _derive([_obs("TRADIER", date(2024, 5, 1), 10.0, volume=None)])
    assert result.bars[0].flags == (FLAG_NO_VOLUME,)
    assert result.flags[0].rule == FLAG_NO_VOLUME


def test_venue_routes_are_ignored():
    result = _derive([_obs("NYSE", date(2024, 5, 1), 10.0)])
    assert result.bars == []


def test_non_trades_observation_raises():
    with pytest.raises(ValueError, match="TRADES"):
        _derive([_obs("SMART", date(2024, 5, 1), 10.0, what_to_show="ADJUSTED_LAST")])


def test_a_date_no_policy_row_covers_raises():
    late = PolicyRow("1d", None, date(2025, 1, 1), None, "observed", "tradier", "ibkr")
    with pytest.raises(LookupError, match="no bar_source_policy row"):
        _derive([_obs("TRADIER", date(2024, 5, 1), 10.0)], policy=[late])


def test_resolve_policy_prefers_the_symbol_row_and_refuses_overlap():
    rex = PolicyRow("1d", "REX", date(2025, 1, 1), date(2025, 9, 9), "observed", "ibkr", None)
    other_tf = PolicyRow("5m", None, date(1990, 1, 1), None, "direct", "ibkr", None)
    rows = [_DEFAULT, rex, other_tf]
    assert resolve_policy(rows, "REX", date(2025, 9, 8)) == rex
    assert resolve_policy(rows, "REX", date(2025, 9, 9)) == _DEFAULT
    assert resolve_policy(rows, "SPY", date(2025, 9, 8)) == _DEFAULT
    with pytest.raises(LookupError):
        resolve_policy([other_tf], "SPY", date(2025, 9, 8))
    with pytest.raises(LookupError, match="overlap"):
        resolve_policy([_DEFAULT, rex, rex], "REX", date(2025, 9, 8))


def test_a_1d_policy_must_be_observed():
    direct = PolicyRow("1d", None, date(1990, 1, 1), None, "direct", "ibkr", None)
    with pytest.raises(ValueError, match="observed"):
        _derive([_obs("SMART", date(2024, 5, 1), 10.0)], policy=[direct])


def test_output_is_deterministic_under_input_shuffling():
    observations, splits = _case("DAL")
    expected = _derive(observations, splits=splits, symbol="DAL")
    for seed in range(5):
        shuffled = list(observations)
        random.Random(seed).shuffle(shuffled)
        assert _derive(shuffled, splits=splits, symbol="DAL") == expected
    assert [b.bar_date for b in expected.bars] == sorted(b.bar_date for b in expected.bars)


# --- known cases on real D1 extracts ---------------------------------------------------------


def test_rjf_series_is_tradier_and_the_ibkr_pre_split_step_is_refused_as_interior():
    observations, splits = _case("RJF")
    tradier = _latest(observations, "TRADIER")
    untouched = _derive(observations, splits=splits, symbol="RJF")
    assert {b.bar_date: (b.source, b.close) for b in untouched.bars} == {
        d: ("tradier", o.close) for d, o in tradier.items()
    }
    # IBKR's own series steps +52% at 2021-09-22 (57.27 then 86.92); Tradier is continuous.
    assert _latest(observations, "SMART")[date(2021, 9, 21)].close == 57.27
    for hole in (date(2021, 8, 16), date(2021, 9, 21)):
        holed = [o for o in observations if not (o.route == "TRADIER" and o.bar_date == hole)]
        result = _derive(holed, splits=splits, symbol="RJF")
        assert result.refused_interior == [hole]
        assert hole not in {b.bar_date for b in result.bars}
        assert all(b.source == "tradier" for b in result.bars)


def test_rex_follows_ibkr_under_its_exception_row():
    observations, splits = _case("REX")
    rex = PolicyRow("1d", "REX", date(2004, 1, 1), date(2025, 9, 9), "observed", "ibkr", None)
    result = _derive(observations, policy=[_DEFAULT, rex], splits=splits, symbol="REX")
    smart = _latest(observations, "SMART")
    inside = [b for b in result.bars if b.bar_date < date(2025, 9, 9)]
    assert inside and all(b.source == "ibkr_named" for b in inside)
    assert all(b.close == smart[b.bar_date].close for b in inside)
    after = [b for b in result.bars if b.bar_date >= date(2025, 9, 9)]
    assert after and all(b.source == "tradier" for b in after)
    # No step across the range boundary (Tradier's own series halves before 2025-09-09).
    by_day = {b.bar_date: b.close for b in result.bars}
    assert abs(by_day[date(2025, 9, 9)] / by_day[date(2025, 9, 8)] - 1) < 0.05
    # Without the exception row the Tradier seam is what d2-v2 serves.
    default = {b.bar_date: b.close for b in _derive(observations, splits=splits).bars}
    assert default[date(2025, 9, 8)] == 15.5


def test_dal_head_is_ibkr_fallback_until_tradier_starts_with_one_seam():
    observations, splits = _case("DAL")
    result = _derive(observations, splits=splits, symbol="DAL")
    by_day = {b.bar_date: b for b in result.bars}
    head = [
        date(2007, 4, 26),
        date(2007, 4, 27),
        date(2007, 4, 30),
        date(2007, 5, 1),
        date(2007, 5, 2),
    ]
    assert [by_day[d].source for d in head] == [SOURCE_IBKR_FALLBACK] * 5
    assert by_day[date(2007, 4, 26)].close == 22.79  # the SMART answer
    assert by_day[date(2007, 4, 27)].close == 20.91  # the stored corpus (LEGACY_IMPORT)
    assert all(b.source == "tradier" for d, b in by_day.items() if d >= date(2007, 5, 3))
    (seam,) = [f for f in result.flags if f.rule == FLAG_FALLBACK_SEAM]
    assert seam.bar_date == date(2007, 5, 3)
    assert seam.detail["n_head_bars"] == 5 and seam.detail["n_common"] == _WINDOW
    assert 0.99 < seam.detail["median_ratio"] < 1.01
    assert result.head == head and result.refused_interior == []


def test_etha_serves_the_post_recording_scale_only():
    observations, splits = _case("ETHA")
    (split,) = splits
    assert split.factor == pytest.approx(1 / 3)
    result = _derive(observations, splits=splits, symbol="ETHA")
    evidence = set(split.evidence_request_ids)
    for bar in result.bars:
        assert bar.source == "tradier" and bar.flags == ()
        if bar.bar_date < split.effective_date:
            # Rescaled answers only: the refetch named as the split's evidence.
            assert set(bar.request_ids) <= evidence
            assert bar.close > 50
    assert result.stale_only == [] and result.refused_interior == []


def test_inda_interior_ibkr_bars_agree_with_tradier_and_are_admitted():
    observations, splits = _case("INDA")
    result = _derive(observations, splits=splits, symbol="INDA")
    tradier_days = set(_latest(observations, "TRADIER"))
    holes = sorted({o.bar_date for o in observations} - tradier_days)
    assert len(holes) == 12
    assert result.admitted_interior == holes and result.refused_interior == []
    by_day = {b.bar_date: b for b in result.bars}
    assert all(by_day[d].source == SOURCE_IBKR_FALLBACK for d in holes)
    # IBKR answered these sessions with no trades; the tradeable view hides volume 0.
    assert all(by_day[d].volume == 0 for d in holes)


def test_a_non_positive_tradier_close_measures_no_basis():
    days = _sessions(date(2024, 1, 2), 3)
    observations = [
        _obs("TRADIER", days[0], 0.0, request_id="t0"),
        _obs("SMART", days[0], 10.0, request_id="s0"),
        _obs("SMART", days[1], 10.0, request_id="s1"),
        _obs("TRADIER", days[2], 10.0, request_id="t2"),
    ]
    result = _derive(observations)
    # The only common session with a usable ratio is none: the interior hole is refused.
    assert result.refused_interior == [days[1]]


def _headed(ratio: float):
    days = _sessions(date(2024, 1, 2), 30)
    head, rest = days[:3], days[3:]
    observations = [_obs("SMART", d, 10.0 * ratio, request_id=f"s{d}") for d in days]
    observations += [_obs("TRADIER", d, 10.0, request_id=f"t{d}") for d in rest]
    return head, rest, _derive(observations)


def test_head_with_a_seam_beyond_tolerance_is_refused():
    # XLY-like: IBKR sits at twice Tradier over the overlap, a 2:1 basis (185-36 finding 2).
    head, rest, result = _headed(2.0)
    assert result.head == [] and result.refused_head == head
    assert {b.bar_date for b in result.bars} == set(rest)
    assert all(b.source == "tradier" for b in result.bars)
    assert result.flags == []


def test_head_with_a_seam_within_tolerance_is_admitted_with_its_seam_flag():
    head, rest, result = _headed(1.0005)
    assert result.head == head and result.refused_head == []
    assert [f.rule for f in result.flags] == [FLAG_FALLBACK_SEAM]
    assert result.flags[0].bar_date == rest[0]
    assert result.flags[0].detail["deviation_bp"] == pytest.approx(5.0)


def test_head_with_no_common_session_is_refused():
    days = _sessions(date(2024, 1, 2), 10)
    observations = [_obs("SMART", d, 10.0, request_id=f"s{d}") for d in days[:5]]
    observations += [_obs("TRADIER", d, 10.0, request_id=f"t{d}") for d in days[5:]]
    result = _derive(observations)
    assert result.refused_head == days[:5] and result.head == []


def test_dal_head_seam_is_within_tolerance_and_stays_admitted():
    observations, splits = _case("DAL")
    result = _derive(observations, splits=splits, symbol="DAL")
    assert result.refused_head == [] and len(result.head) == 5


# --- d2-v3: a stale-only primary yields to the restated fallback (plan 185-52, todo 517) ------
#
# Tradier stopped answering on 2026-10-06, so after a later split every pre-split Tradier
# observation is stale for good. IBKR's in-process split re-fetch answers on the new scale. The
# fallback bar replaces the flagged stale bar only where the basis (IBKR over the stale Tradier
# close brought to the new scale by the recorded factors; measurement only, never served) over
# the nearest common sessions is within the interior tolerance.

_SPLIT_FETCH = _T0 + timedelta(hours=1)  # the split's recorded_at
_REFETCH = _T0 + timedelta(hours=2)  # IBKR's re-fetch after the split was recorded


def _split_after(days: list[date], factor: float = 2.0) -> SplitRecord:
    """A forward split effective after the last test session, recorded after Tradier's fetch."""
    return SplitRecord(days[-1] + timedelta(days=7), _SPLIT_FETCH, factor)


def _restated_case(
    *,
    ibkr_fetched: datetime = _REFETCH,
    ibkr_offset_bp: float = 0.0,
    ibkr_days: list[date] | None = None,
    n: int = 30,
):
    """Tradier on the old scale (close 20), IBKR on the new scale (close 10 at factor 2)."""
    days = _sessions(date(2024, 1, 2), n)
    observations = [_obs("TRADIER", d, 20.0, request_id=f"t{d}", volume=500) for d in days]
    observations += [
        _obs(
            "SMART",
            d,
            10.0 * (1 + ibkr_offset_bp / 1e4),
            fetched_at=ibkr_fetched,
            request_id=f"s{d}",
            volume=300,
        )
        for d in (days if ibkr_days is None else ibkr_days)
    ]
    return days, observations, _split_after(days)


def test_restated_fallback_replaces_a_stale_only_primary():
    # Case (a): split recorded after Tradier's fetch, IBKR fetched after recorded_at.
    days, observations, split = _restated_case()
    result = _derive(observations, splits=[split])
    assert [b.bar_date for b in result.bars] == days
    assert all(b.source == SOURCE_IBKR_FALLBACK for b in result.bars)
    assert all(b.close == 10.0 and b.flags == () for b in result.bars)
    # The fallback bar keeps its own volume; the tradeable view reads it as NULL (migration 446).
    assert {b.volume for b in result.bars} == {300}
    assert [b.request_ids for b in result.bars] == [(f"s{d}",) for d in days]
    assert result.flags == [] and result.restated == days
    assert result.stale_only == [] and result.refused_interior == []


def test_an_evidence_request_counts_as_a_restated_fallback_answer():
    # A re-fetch that revealed the split is fetched before recorded_at and is on the new scale.
    days, observations, _ = _restated_case(ibkr_fetched=_T0 + timedelta(minutes=30))
    split = SplitRecord(
        days[-1] + timedelta(days=7),
        _SPLIT_FETCH,
        2.0,
        evidence_request_ids=tuple(f"s{d}" for d in days),
    )
    result = _derive(observations, splits=[split])
    assert result.restated == days and result.flags == []


def test_a_stale_fallback_keeps_the_flagged_stale_primary():
    # Case (b): IBKR also fetched before recorded_at: today's d2-v2 behavior.
    days, observations, split = _restated_case(ibkr_fetched=_T0)
    result = _derive(observations, splits=[split])
    assert all(b.source == "tradier" and b.close == 20.0 for b in result.bars)
    assert all(b.flags == (FLAG_PRE_SPLIT,) for b in result.bars)
    assert {f.rule for f in result.flags} == {FLAG_PRE_SPLIT}
    assert result.restated == []


def test_an_absent_fallback_keeps_the_flagged_stale_primary():
    # Cases (b) and (e): no IBKR answer at all, or none on some dates.
    days, observations, split = _restated_case(ibkr_days=[])
    result = _derive(observations, splits=[split])
    assert all(b.source == "tradier" and b.flags == (FLAG_PRE_SPLIT,) for b in result.bars)
    assert result.restated == []
    gap = days[10:13]
    days, observations, split = _restated_case(ibkr_days=[d for d in days if d not in gap])
    result = _derive(observations, splits=[split])
    by_day = {b.bar_date: b for b in result.bars}
    assert [b.bar_date for b in result.bars] == days
    assert all(by_day[d].source == "tradier" and by_day[d].flags == (FLAG_PRE_SPLIT,) for d in gap)
    assert result.restated == [d for d in days if d not in gap]


def test_a_restated_basis_outside_tolerance_keeps_the_flagged_stale_primary():
    # IBKR sits 15 bp off the restated Tradier close: no splice across a basis difference.
    days, observations, split = _restated_case(ibkr_offset_bp=15.0)
    result = _derive(observations, splits=[split])
    assert all(b.source == "tradier" and b.flags == (FLAG_PRE_SPLIT,) for b in result.bars)
    assert result.restated == []
    _, inside, split = _restated_case(ibkr_offset_bp=8.0)
    assert len(_derive(inside, splits=[split]).restated) == len(days)


def test_a_wrong_factor_measures_a_basis_break_and_restates_nothing():
    days, observations, _ = _restated_case()
    result = _derive(observations, splits=[_split_after(days, factor=3.0)])
    assert result.restated == [] and all(b.source == "tradier" for b in result.bars)


def test_no_split_leaves_the_rule_unchanged():
    # Case (c): no recorded split, Tradier and IBKR agree: Tradier is served as before.
    days = _sessions(date(2024, 1, 2), 10)
    observations = [_obs("TRADIER", d, 10.0, request_id=f"t{d}") for d in days]
    observations += [_obs("SMART", d, 10.0, fetched_at=_REFETCH, request_id=f"s{d}") for d in days]
    result = _derive(observations)
    assert all(b.source == "tradier" and b.flags == () for b in result.bars)
    assert result.restated == [] and result.flags == []


def test_a_voided_split_is_not_an_input_and_changes_nothing():
    # Case (d): corporate_action_current hides void rows (migration 461), so a voided split
    # never reaches the rule; the daily stage reads that view (test_bar_derivation_daily).
    days, observations, split = _restated_case()
    voided = _derive(observations, splits=[])
    assert all(b.source == "tradier" and b.close == 20.0 for b in voided.bars)
    assert voided.restated == [] and voided.flags == []
    assert _derive(observations, splits=[split]).restated == days


def test_only_dates_before_the_split_are_restated():
    # Effective inside the span: Tradier answers on or after it are current and stay primary.
    days, observations, _ = _restated_case()
    split = SplitRecord(days[14], _SPLIT_FETCH, 2.0)
    after = [o for o in observations if not (o.route == "TRADIER" and o.bar_date >= days[14])]
    after += [_obs("TRADIER", d, 10.0, request_id=f"t2{d}") for d in days[14:]]
    result = _derive(after, splits=[split])
    by_day = {b.bar_date: b for b in result.bars}
    assert result.restated == days[:14]
    assert all(by_day[d].source == "tradier" and by_day[d].flags == () for d in days[14:])


def test_an_ibkr_primary_with_no_fallback_still_flags_a_stale_only_answer():
    # Under the post-D default (IBKR primary, no fallback) nothing else may answer.
    ibkr_default = PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "ibkr", None)
    day = date(2026, 10, 8)
    split = SplitRecord(date(2026, 10, 20), _SPLIT_FETCH, 2.0)
    observations = [
        _obs("SMART", day, 20.0, request_id="s-old"),
        _obs("TRADIER", day, 10.0, fetched_at=_REFETCH, request_id="t-new"),
    ]
    result = _derive(observations, policy=[ibkr_default], splits=[split])
    (bar,) = result.bars
    assert (bar.source, bar.flags) == ("ibkr_named", (FLAG_PRE_SPLIT,))
    assert result.restated == []


def test_an_admitted_head_stays_admitted_after_a_split():
    # The head seam is measured on the restated Tradier closes when all of Tradier is stale.
    days = _sessions(date(2024, 1, 2), 30)
    head = days[:3]
    observations = [_obs("SMART", d, 10.0, fetched_at=_REFETCH, request_id=f"s{d}") for d in days]
    observations += [_obs("TRADIER", d, 20.0, request_id=f"t{d}") for d in days[3:]]
    result = _derive(observations, splits=[_split_after(days)])
    assert result.head == head and result.refused_head == []
    assert result.restated == days[3:]
    assert all(b.source == SOURCE_IBKR_FALLBACK for b in result.bars)
    # No Tradier bar is served, so there is no vendor seam to flag.
    assert result.flags == []


def test_rjf_after_a_hypothetical_split_restates_only_where_ibkr_agrees():
    # RJF's real extract, with a hypothetical 2:1 split recorded after every stored fetch and
    # IBKR re-answering the same history on the new scale. IBKR's own series steps +52% at
    # 2021-09-22 (its pre-split stale basis): before it the restated basis is off by a third and
    # the dates keep the flagged stale Tradier bar; after it IBKR agrees and is served.
    observations, _ = _case("RJF")
    last_fetch = max(o.fetched_at for o in observations)
    split = SplitRecord(date(2026, 11, 2), last_fetch + timedelta(hours=1), 2.0)
    refetch = last_fetch + timedelta(hours=2)
    smart = _latest(observations, "SMART")
    reanswered = [
        _obs("SMART", d, o.close / 2, fetched_at=refetch, request_id=f"re-{d}")
        for d, o in smart.items()
    ]
    result = _derive(observations + reanswered, splits=[split], symbol="RJF")
    by_day = {b.bar_date: b for b in result.bars}
    step = date(2021, 9, 22)
    restated = set(result.restated)
    assert restated and all(d >= step for d in restated)
    early = [d for d in by_day if d < date(2021, 9, 10)]
    assert early and all(
        by_day[d].source == "tradier" and by_day[d].flags == (FLAG_PRE_SPLIT,) for d in early
    )
    assert all(by_day[d].source == SOURCE_IBKR_FALLBACK for d in restated)
