"""d2-v6 (todo 600 step 4): the Massive route and what each split source does.

A massive_reference split records a market split the incumbents carry adjusted as served: it
neither stales nor rescales them. Massive's served day bar is unadjusted: it is never stale and is
divided by every market split, never by an incumbent route correction (a todo 592 operator row).
The daily read refuses a split source it does not know."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from services.bar_derivation import split_record
from src.intelligence.bars.daily_rule import (
    FLAG_PRE_SPLIT,
    PRIMARY_PAIR,
    RAW_DAILY_SERIES,
    RAW_DAILY_SESSION_ZONE,
    PolicyRow,
    derive_daily,
    observation_from_raw,
    raw_session_date,
)
from src.intelligence.bars.derivation import Observation

_FETCHED = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)
_RECORDED = datetime(2026, 11, 10, 16, 43, tzinfo=UTC)  # after every fetch: stale-eligible
_IBKR = (PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "ibkr", None),)
_MASSIVE = (PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "massive", None),)
# NVDA 2024: the 10:1 split's last old-scale session is 2024-06-07.
_OLD = date(2024, 6, 7)
_DAYS = [date(2024, 6, 5), date(2024, 6, 6), date(2024, 6, 7), date(2024, 6, 10), date(2024, 6, 11)]


def _obs(day: date, close: float, route: str) -> Observation:
    return Observation(
        f"{route}-{day}", route, day, close, close, close, close, 1000, _FETCHED, False
    )


def _derive(observations, policy, splits):
    return derive_daily(
        observations,
        list(policy),
        list(splits),
        symbol="NVDA",
        basis_window_sessions=5,
        basis_tolerance_bp=10.0,
    )


def _record(inferred_by: str, factor: float = 10.0, *, rows_file: bool = False, routes=None):
    return split_record(
        {
            "effective_date": _OLD,
            "recorded_at": _RECORDED,
            "factor": factor,
            "evidence_request_ids": [],
            "inferred_by": inferred_by,
            "unadjusted_routes": routes,
            "calendar_adjusted_step": 0.0 if routes else None,
            "operator_rows_file": rows_file,
        }
    )


def test_a_massive_reference_split_never_stales_the_incumbent_history():
    # IBKR served NVDA adjusted for the 10:1 before the reference row was recorded. Read as a
    # restatement split (d2-v5's reading of any non-calendar row) every pre-split bar would be
    # stale and quarantined as pre_split_unrefetched.
    adjusted = [_obs(d, 120.0, "SMART") for d in _DAYS]
    reference = _record("massive_reference")
    assert (reference.stales, reference.market_fact, reference.rescale_routes) == (
        False,
        True,
        frozenset(),
    )
    result = _derive(adjusted, _IBKR, [reference])
    assert [b.close for b in result.bars] == [120.0] * 5
    assert not any(FLAG_PRE_SPLIT in b.flags for b in result.bars)
    # The same split from the nightly overlap does stale it (D-21 is unchanged).
    overlap = _derive(adjusted, _IBKR, [_record("nightly_overlap")])
    assert sum(FLAG_PRE_SPLIT in b.flags for b in overlap.bars) == 3


def test_a_massive_day_bar_is_divided_by_every_market_split_and_served_adjusted():
    unadjusted = [_obs(d, 1200.0 if d <= _OLD else 120.0, "MASSIVE") for d in _DAYS]
    result = _derive(unadjusted, _MASSIVE, [_record("massive_reference")])
    assert [b.close for b in result.bars] == [120.0] * 5
    assert {(b.vendor, b.kind) for b in result.bars} == {("massive", "sip_flat_adj")}
    assert result.bars[0].volume == 10000  # a share count on the adjusted basis
    # A calendar-confirmed split is a market split too (its routes name the incumbents only).
    calendar = _record("calendar_audit", routes=[{"vendor": "ibkr", "kind": "smart_trades"}])
    assert [b.close for b in _derive(unadjusted, _MASSIVE, [calendar]).bars] == [120.0] * 5


@pytest.mark.parametrize("factor", [0.4, 0.5, 4.4963], ids=["PATK", "IJR", "MTCH"])
def test_an_incumbent_route_correction_never_divides_the_massive_route(factor):
    unadjusted = [_obs(d, 120.0, "MASSIVE") for d in _DAYS]
    correction = _record(
        "calendar_audit",
        factor,
        rows_file=True,
        routes=[{"vendor": "ibkr", "kind": "smart_trades"}],
    )
    assert correction.market_fact is False
    assert [b.close for b in _derive(unadjusted, _MASSIVE, [correction]).bars] == [120.0] * 5


def test_a_massive_observation_is_never_stale():
    # A restatement split recorded after the file was served: the file is as served, never a
    # vendor's stale adjusted history, so it is rescaled, not quarantined.
    unadjusted = [_obs(d, 1200.0 if d <= _OLD else 120.0, "MASSIVE") for d in _DAYS]
    result = _derive(unadjusted, _MASSIVE, [_record("nightly_overlap")])
    assert [b.close for b in result.bars] == [120.0] * 5
    assert not any(FLAG_PRE_SPLIT in b.flags for b in result.bars)


def test_the_daily_read_refuses_a_split_source_it_does_not_know():
    with pytest.raises(ValueError, match="no known meaning"):
        _record("new_vendor_reference")


def test_the_massive_series_is_read_and_dated_by_new_york_midnight():
    assert ("massive", "sip_flat") in RAW_DAILY_SERIES
    assert RAW_DAILY_SESSION_ZONE[("massive", "sip_flat")] == "America/New_York"
    assert PRIMARY_PAIR["massive"] == ("massive", "sip_flat_adj")
    # window_start of the 2024-06-07 day file: midnight New York, 04:00 UTC in summer.
    stamp = datetime(2024, 6, 7, 4, 0, tzinfo=UTC)
    assert raw_session_date("massive", "sip_flat", stamp) == date(2024, 6, 7)
    assert raw_session_date("massive", "sip_flat", stamp - timedelta(seconds=1)) == date(2024, 6, 6)
    obs = observation_from_raw(
        request_id=None,
        vendor="massive",
        kind="sip_flat",
        bar_date=_OLD,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1,
        served_at=_FETCHED,
        legacy=False,
    )
    assert (obs.route, obs.legacy) == ("MASSIVE", False)


def test_a_massive_answer_on_a_session_no_policy_routes_to_massive_is_no_unserved_session():
    # Raw Massive lands (step 5) before the policy names it (step 7b): its sessions must not read
    # as by-design silences of the IBKR primary.
    incumbent = [_obs(d, 120.0, "SMART") for d in _DAYS[2:]]
    massive = [_obs(d, 1200.0 if d <= _OLD else 120.0, "MASSIVE") for d in _DAYS]
    result = _derive(incumbent + massive, _IBKR, [_record("massive_reference")])
    assert result.unserved_primary == []
    assert [b.bar_date for b in result.bars] == _DAYS[2:]


def test_a_session_no_policy_covers_still_fails_loudly_with_massive_present():
    # The axis keeps every incumbent's dates, so a missing policy row is never silent.
    late = (PolicyRow("1d", None, date(2024, 6, 10), None, "observed", "ibkr", None),)
    incumbent = [_obs(d, 120.0, "SMART") for d in _DAYS]
    massive = [_obs(d, 120.0, "MASSIVE") for d in _DAYS]
    with pytest.raises(LookupError, match="no bar_source_policy row"):
        _derive(incumbent + massive, late, [])
