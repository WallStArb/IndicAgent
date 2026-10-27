"""The daily rule d2-v4 (D-191-Q, todo 545 step 3): Alpaca SIP as a raw daily input and policy
primary from 2016-01-04 with IBKR fallback, IBKR alone before.

Synthetic observations for the mechanics (session-date matching, the zero-volume guard, the
listing guard, the policy checks), and golden digests of the d2-v3 rule over the known-case
fixture (tests/fixtures/bars/d2v2_known_cases.json), taken at the d2-v3 commit before the bump:
where no policy row names Alpaca, every output stays bit-identical, with or without Alpaca rows
in the inputs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.intelligence.bars.daily_rule import (
    FLAG_FALLBACK_SEAM,
    PRIMARY_PAIR,
    RAW_DAILY_SERIES,
    RAW_DAILY_SESSION_ZONE,
    RULE_VERSION,
    PolicyRow,
    derive_daily_v2,
    observation_from_raw,
    raw_session_date,
    servable_primary_dates,
)
from src.intelligence.bars.derivation import Observation, SplitRecord
from src.intelligence.bars.sources import CANONICAL_1D_SOURCES
from src.intelligence.bars.vendor_kind import canonical_kind_for_raw

ALPACA = ("alpaca", "sip_rth")
IBKR_NAMED = ("ibkr", "named")
IBKR_FALLBACK = ("ibkr", "fallback")

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "bars" / "d2v2_known_cases.json"
_WINDOW = 5
_TOL_BP = 10.0
_SEAM = date(2016, 1, 4)
_T0 = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)
_ALPACA_DEFAULT = PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "alpaca", "ibkr")
# The D-191-Q shape: IBKR alone before 2016-01-04, Alpaca primary with IBKR fallback from it.
_D191Q = (
    PolicyRow("1d", None, date(1990, 1, 1), _SEAM, "observed", "ibkr", None),
    PolicyRow("1d", None, _SEAM, None, "observed", "alpaca", "ibkr"),
)


def _obs(
    route: str,
    day: date,
    close: float,
    *,
    volume: int | None = 100,
    fetched_at: datetime = _T0,
    request_id: str | None = None,
) -> Observation:
    return Observation(
        request_id=request_id or f"{route}-{day.isoformat()}",
        route=route,
        bar_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        fetched_at=fetched_at,
        legacy=route == "LEGACY_IMPORT",
    )


def _sessions(start: date, n: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _derive(observations, policy=(_ALPACA_DEFAULT,), splits=(), window=_WINDOW):
    return derive_daily_v2(
        observations,
        list(policy),
        list(splits),
        symbol="TEST",
        basis_window_sessions=window,
        basis_tolerance_bp=_TOL_BP,
    )


def _pairs(result) -> dict[date, tuple[str, str]]:
    return {b.bar_date: (b.vendor, b.kind) for b in result.bars}


# --- identity ----------------------------------------------------------------------------------


def test_rule_version_and_alpaca_identity():
    assert RULE_VERSION == "d2-v4"
    assert PRIMARY_PAIR["alpaca"] == ALPACA
    # The canonical kind is the raw kind, as canonical 5m carries Alpaca rows (D-191-B).
    assert canonical_kind_for_raw("alpaca", "sip_rth") == "sip_rth"
    assert ALPACA in CANONICAL_1D_SOURCES
    assert ("alpaca", "sip_rth") in RAW_DAILY_SERIES
    # iex_rth is raw only, never selected (D-191-A follow-up).
    assert ("alpaca", "iex_rth") not in RAW_DAILY_SERIES


def test_tradier_and_ibkr_series_stay_inputs():
    assert ("tradier", "consolidated") in RAW_DAILY_SERIES
    assert ("ibkr", "smart_trades") in RAW_DAILY_SERIES
    assert set(RAW_DAILY_SESSION_ZONE) == set(RAW_DAILY_SERIES)


# --- session date ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        (datetime(2024, 3, 8, 5, 0, tzinfo=UTC), date(2024, 3, 8)),  # EST midnight
        (datetime(2024, 3, 11, 4, 0, tzinfo=UTC), date(2024, 3, 11)),  # EDT midnight
        (datetime(2024, 11, 4, 5, 0, tzinfo=UTC), date(2024, 11, 4)),  # back on EST
    ],
)
def test_alpaca_stamps_map_to_the_new_york_session_date(stamp, expected):
    assert raw_session_date("alpaca", "sip_rth", stamp) == expected


def test_ibkr_and_tradier_stamps_keep_the_utc_date():
    stamp = datetime(2024, 3, 8, 0, 0, tzinfo=UTC)
    assert raw_session_date("ibkr", "smart_trades", stamp) == date(2024, 3, 8)
    assert raw_session_date("tradier", "consolidated", stamp) == date(2024, 3, 8)


def test_session_date_refuses_a_series_the_rule_does_not_read():
    with pytest.raises(ValueError, match="not a d2-v4 input"):
        raw_session_date("alpaca", "iex_rth", datetime(2024, 3, 8, 5, tzinfo=UTC))


def test_observation_from_raw_maps_alpaca_sip_rth():
    obs = observation_from_raw(
        request_id="a1",
        vendor="alpaca",
        kind="sip_rth",
        bar_date=date(2024, 3, 8),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=10,
        served_at=_T0,
        legacy=False,
    )
    assert obs.route == "ALPACA" and not obs.legacy and obs.bar_date == date(2024, 3, 8)
    with pytest.raises(ValueError):
        observation_from_raw(
            request_id="a1",
            vendor="alpaca",
            kind="iex_rth",
            bar_date=date(2024, 3, 8),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=10,
            served_at=_T0,
            legacy=False,
        )


def test_one_canonical_bar_per_session_when_both_vendors_answer():
    days = _sessions(date(2024, 3, 4), 10)
    observations = [_obs("SMART", d, 100.0) for d in days] + [
        _obs("ALPACA", d, 100.0, volume=150) for d in days
    ]
    result = _derive(observations)
    assert [b.bar_date for b in result.bars] == days
    assert set(_pairs(result).values()) == {ALPACA}
    assert {b.volume for b in result.bars} == {150}


# --- policy ------------------------------------------------------------------------------------


def test_d191q_policy_serves_ibkr_before_2016_and_alpaca_from_it():
    before = _sessions(date(2015, 12, 1), 20)
    after = _sessions(_SEAM, 20)
    observations = [_obs("SMART", d, 50.0) for d in before + after] + [
        _obs("ALPACA", d, 50.0) for d in after
    ]
    pairs = _pairs(_derive(observations, policy=_D191Q))
    assert all(pairs[d] == IBKR_NAMED for d in before)
    assert all(pairs[d] == ALPACA for d in after)


def test_alpaca_policy_admits_only_ibkr_as_fallback():
    day = date(2024, 3, 8)
    bad = PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "alpaca", "tradier")
    with pytest.raises(ValueError, match="fallback"):
        _derive([_obs("ALPACA", day, 1.0)], policy=[bad])
    ibkr_over_alpaca = PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "ibkr", "alpaca")
    with pytest.raises(ValueError, match="fallback"):
        _derive([_obs("SMART", day, 1.0)], policy=[ibkr_over_alpaca])


def test_alpaca_primary_without_fallback_serves_alpaca_only():
    days = _sessions(date(2024, 3, 4), 10)
    alone = PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "alpaca", None)
    observations = [_obs("SMART", d, 10.0) for d in days] + [
        _obs("ALPACA", d, 10.0) for d in days if d != days[5]
    ]
    pairs = _pairs(_derive(observations, policy=[alone]))
    assert days[5] not in pairs
    assert set(pairs.values()) == {ALPACA}


def test_an_interior_alpaca_hole_takes_the_ibkr_fallback_within_tolerance():
    days = _sessions(date(2024, 3, 4), 20)
    hole = days[10]
    observations = [_obs("SMART", d, 10.0) for d in days] + [
        _obs("ALPACA", d, 10.0) for d in days if d != hole
    ]
    result = _derive(observations)
    assert _pairs(result)[hole] == IBKR_FALLBACK
    assert result.admitted_interior == [hole]


def test_an_interior_alpaca_hole_is_refused_outside_the_basis_tolerance():
    days = _sessions(date(2024, 3, 4), 20)
    hole = days[10]
    # The vendors agree at the head (the Alpaca span is anchored), then IBKR steps 1% above
    # Alpaca around the hole: no splice across it.
    observations = [_obs("SMART", d, 10.1 if d >= days[7] else 10.0) for d in days] + [
        _obs("ALPACA", d, 10.0) for d in days if d != hole
    ]
    result = _derive(observations, policy=[_ALPACA_DEFAULT])
    assert result.alpaca_start == days[0]
    assert hole not in _pairs(result)
    assert result.refused_interior == [hole]


def test_a_name_whose_vendors_never_agree_has_no_alpaca_span():
    # A persistent basis outside the tolerance is no evidence of one instrument: Alpaca never
    # anchors, and the IBKR fallback is the series (no splice exists to test).
    days = _sessions(date(2024, 3, 4), 20)
    observations = [_obs("SMART", d, 10.1) for d in days] + [_obs("ALPACA", d, 10.0) for d in days]
    result = _derive(observations)
    assert result.alpaca_start is None and result.pre_listing == days
    assert set(_pairs(result).values()) == {IBKR_FALLBACK}


# --- guard 1: a zero-volume Alpaca bar never serves --------------------------------------------


def test_a_zero_volume_alpaca_bar_falls_through_to_ibkr():
    days = _sessions(date(2024, 3, 4), 20)
    dead = days[10]
    observations = [_obs("SMART", d, 10.0) for d in days] + [
        _obs("ALPACA", d, 10.0, volume=0 if d == dead else 100) for d in days
    ]
    result = _derive(observations)
    assert _pairs(result)[dead] == IBKR_FALLBACK
    assert result.zero_volume == [dead]
    assert all(b.volume != 0 for b in result.bars if (b.vendor, b.kind) == ALPACA)


def test_a_zero_volume_alpaca_bar_with_no_ibkr_bar_leaves_the_session_missing():
    days = _sessions(date(2024, 3, 4), 20)
    dead = days[10]
    observations = [_obs("SMART", d, 10.0) for d in days if d != dead] + [
        _obs("ALPACA", d, 10.0, volume=0 if d == dead else 100) for d in days
    ]
    result = _derive(observations)
    assert dead not in _pairs(result)
    assert result.zero_volume == [dead]


def test_a_missing_alpaca_volume_is_no_trade_bar_either():
    days = _sessions(date(2024, 3, 4), 20)
    dead = days[10]
    observations = [_obs("SMART", d, 10.0) for d in days] + [
        _obs("ALPACA", d, 10.0, volume=None if d == dead else 100) for d in days
    ]
    result = _derive(observations)
    assert _pairs(result)[dead] == IBKR_FALLBACK


def test_zero_volume_placeholders_never_anchor_the_alpaca_span():
    # Carry-forward placeholders across a dead-ticker gap at the head are no measurement.
    days = _sessions(date(2024, 3, 4), 30)
    observations = [_obs("SMART", d, 10.0) for d in days[10:]] + [
        _obs("ALPACA", d, 10.0, volume=0 if d < days[10] else 100) for d in days
    ]
    result = _derive(observations)
    assert result.alpaca_start == days[10]
    assert result.zero_volume == days[:10]
    assert all(d not in _pairs(result) for d in days[:10])


# --- guard 2: the Alpaca span starts at the name's listing -------------------------------------


def test_alpaca_bars_before_ibkr_history_never_serve():
    # A reused ticker: Alpaca answers sessions IBKR's contract never traded.
    days = _sessions(date(2024, 3, 4), 40)
    listing = days[15]
    observations = [_obs("SMART", d, 10.0) for d in days if d >= listing] + [
        _obs("ALPACA", d, 10.0) for d in days
    ]
    result = _derive(observations)
    pairs = _pairs(result)
    assert result.alpaca_start == listing
    assert result.pre_listing == days[:15]
    assert all(d not in pairs for d in days[:15])
    assert all(pairs[d] == ALPACA for d in days[15:])


def test_a_predecessor_splice_after_ibkr_head_is_cut_at_agreement():
    # AA 2016: IBKR's contract trades when-issued from 10-18 while Alpaca's ticker still prints
    # the predecessor at about five times the price until 11-01.
    days = _sessions(date(2016, 10, 3), 40)
    ibkr_head, regular_way = days[11], days[21]
    observations = [_obs("SMART", d, 16.0 if d < regular_way else 23.0) for d in days[11:]] + [
        _obs("ALPACA", d, 80.0 if d < regular_way else 23.0) for d in days
    ]
    result = _derive(observations, policy=_D191Q)
    pairs = _pairs(result)
    assert result.alpaca_start == regular_way
    assert result.pre_listing == [d for d in days if d < regular_way]
    assert all(pairs[d] == ALPACA for d in days if d >= regular_way)
    # The contract's own pre-regular-way sessions are the IBKR head, recorded at the seam.
    assert all(pairs[d] == IBKR_FALLBACK for d in days if ibkr_head <= d < regular_way)
    assert all(b.close != 80.0 for b in result.bars)
    seam = [f for f in result.flags if f.rule == FLAG_FALLBACK_SEAM]
    assert [f.bar_date for f in seam] == [regular_way]


def test_alpaca_with_no_ibkr_history_at_all_never_serves():
    days = _sessions(date(2024, 3, 4), 10)
    result = _derive([_obs("ALPACA", d, 10.0) for d in days])
    assert result.bars == []
    assert result.alpaca_start is None
    assert result.pre_listing == days


def test_one_disagreeing_session_after_the_anchor_does_not_cut_the_span():
    days = _sessions(date(2024, 3, 4), 40)
    odd = days[25]
    observations = [_obs("SMART", d, 10.5 if d == odd else 10.0) for d in days] + [
        _obs("ALPACA", d, 10.0) for d in days
    ]
    result = _derive(observations)
    assert result.alpaca_start == days[0]
    assert result.pre_listing == []
    assert set(_pairs(result).values()) == {ALPACA}


# --- scale -------------------------------------------------------------------------------------


def test_a_stale_alpaca_answer_takes_the_current_ibkr_answer_within_tolerance():
    days = _sessions(date(2024, 3, 4), 20)
    split = SplitRecord(days[-1] + timedelta(days=30), _T0 + timedelta(days=1), 2.0)
    later = _T0 + timedelta(days=2)
    stale_day = days[10]
    observations = [_obs("SMART", d, 10.0, fetched_at=later) for d in days] + [
        _obs(
            "ALPACA",
            d,
            20.0 if d == stale_day else 10.0,
            fetched_at=(_T0 if d == stale_day else later),
        )
        for d in days
    ]
    result = _derive(observations, splits=[split])
    assert _pairs(result)[stale_day] == IBKR_FALLBACK
    assert result.restated == [stale_day]


# --- servable primary dates (policy conformance's basis) ---------------------------------------


def test_servable_primary_dates_apply_both_alpaca_guards():
    days = _sessions(date(2024, 3, 4), 30)
    observations = [_obs("SMART", d, 10.0) for d in days[5:]] + [
        _obs("ALPACA", d, 10.0, volume=0 if d == days[20] else 100) for d in days
    ]
    dates = servable_primary_dates(
        observations, [], basis_window_sessions=_WINDOW, basis_tolerance_bp=_TOL_BP
    )
    assert dates["alpaca"] == frozenset(d for d in days[5:] if d != days[20])
    assert dates["tradier"] == frozenset()


# --- d2-v3 bit identity where Alpaca is absent ---------------------------------------------------

# sha256 of each d2-v3 result over the fixture, taken at commit 1e88ae9aa (the d2-v3 rule)
# with _result_digest below; the switch date is each case's median observation date.
_D2V3_GOLDEN = {
    "DAL/ibkr_default": "99292c9cb474ea820ed594eb6098d587dec68c1d1a58ca0c5b477103d043caab",
    "DAL/ibkr_symbol_exception": "e230c32d71814644fb79760c9cc0c06ad869f8af893102b2846dbee18c7d7f84",
    "DAL/tradier_default": "0dbc0d67cf318089811f2c18dda3fc08893f21f7dfd102848ef6915ccd49b449",
    "DAL/tradier_then_ibkr": "b0664331660a79940ee1825322b92e603a121c1e85e0af29cf11106770b36c36",
    "ETHA/ibkr_default": "21dc2312cbd2cba5f363bf5e2f50038f1be6fda2891167b33e845e3741b485fd",
    "ETHA/ibkr_symbol_exception": "cf900c30e9ab947e44ac115b18edfce22d24efc2689b787e987f4c597e7d24b1",
    "ETHA/tradier_default": "d1f1f2ea40eb735573435367e27bcbf5898d6c5f6815bc98dfec3564ee7ff021",
    "ETHA/tradier_then_ibkr": "39ba87353be92d7021db6d98f008e4516596aecbae60aa6949e43789f831a267",
    "INDA/ibkr_default": "8da6588343e05f04fd5430fcb4da4d717ccefd05835c9d87f3e0c793aa1f5505",
    "INDA/ibkr_symbol_exception": "06ca85e14640397c94d90f55e6dad5899e0499fe7b18c169a47b4283b5111bf5",
    "INDA/tradier_default": "664524921536cb2d2fc81d7d464ca5af2f850c0f4a01c10859d2f7423f58f50d",
    "INDA/tradier_then_ibkr": "fd8cb90f678412a58b4000dcdc38987440eacec586255b5325a390aae88b55d7",
    "REX/ibkr_default": "447a956823653bb9fa619bf1098c0091a2454a46f40c69a2c3ebdd63fed78c2b",
    "REX/ibkr_symbol_exception": "97859af68b76c0363b8d01ad7f2c0ba879827ec648c0973bdf95e3ffca38a9e4",
    "REX/tradier_default": "713536e2d87ba1c3be26a8f1d7a4999c9bee848131b8395e8ebad35ac849d4a7",
    "REX/tradier_then_ibkr": "5ddc98cf31bc618e2ed032b593243a3cff144b9cee805e1f58171a821572fccf",
    "RJF/ibkr_default": "050882be42842d30992d3c39fa83fefea488c75a24473c3a5f0b0c37cc59b637",
    "RJF/ibkr_symbol_exception": "ef1353c989e5cb40d72a7b593741aa75fea8064cefdd9e4cf296df3e0531eb34",
    "RJF/tradier_default": "4e8153e1a0f992a5b14a3a8a2ee7d12ab3bb13877a228abcb3cec4cbf1040d16",
    "RJF/tradier_then_ibkr": "5e16be8ebdae5cef5145c0e0240040a24cb1ceb755d3c5a16fb9078fb304359b",
}
_D2V3_FIELDS = (
    "refused_interior",
    "head",
    "admitted_interior",
    "stale_only",
    "refused_head",
    "restated",
)


def _result_digest(result) -> str:
    """sha256 over the d2-v3 result fields (bars, flags and the six date lists)."""
    payload = {
        "bars": [
            [
                b.bar_date.isoformat(),
                repr(b.open),
                repr(b.high),
                repr(b.low),
                repr(b.close),
                b.volume,
                b.vendor,
                b.kind,
                list(b.request_ids),
                list(b.flags),
            ]
            for b in result.bars
        ],
        "flags": [
            [f.bar_date.isoformat(), f.rule, list(f.fields), json.dumps(f.detail, sort_keys=True)]
            for f in result.flags
        ],
        **{name: [d.isoformat() for d in getattr(result, name)] for name in _D2V3_FIELDS},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


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


def _golden_policies(symbol: str, switch: date) -> dict[str, list[PolicyRow]]:
    return {
        "tradier_default": [
            PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "tradier", "ibkr")
        ],
        "ibkr_default": [PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "ibkr", None)],
        "tradier_then_ibkr": [
            PolicyRow("1d", None, date(1990, 1, 1), switch, "observed", "tradier", "ibkr"),
            PolicyRow("1d", None, switch, None, "observed", "ibkr", None),
        ],
        "ibkr_symbol_exception": [
            PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "tradier", "ibkr"),
            PolicyRow("1d", symbol, date(1990, 1, 1), switch, "observed", "ibkr", None),
        ],
    }


def _golden_runs(with_alpaca: bool):
    for symbol in ("DAL", "ETHA", "INDA", "REX", "RJF"):
        observations, splits = _case(symbol)
        dates = sorted({o.bar_date for o in observations})
        switch = dates[len(dates) // 2]
        if with_alpaca:
            # Alpaca answers every fixture session plus sessions nobody else answered, on a
            # different level: under a policy that never names Alpaca none of it may matter.
            extra = [d + timedelta(days=1) for d in dates if (d + timedelta(days=1)) not in dates]
            observations = observations + [
                _obs("ALPACA", d, 1.0 + i % 7, volume=0 if i % 5 == 0 else 1000)
                for i, d in enumerate(sorted(set(dates) | set(extra)))
            ]
        for name, rows in _golden_policies(symbol, switch).items():
            result = derive_daily_v2(
                observations,
                rows,
                splits,
                symbol=symbol,
                basis_window_sessions=20,
                basis_tolerance_bp=10.0,
            )
            yield f"{symbol}/{name}", result


def test_d2v3_fixture_outputs_are_bit_identical_without_alpaca():
    assert {key: _result_digest(r) for key, r in _golden_runs(False)} == _D2V3_GOLDEN


def test_alpaca_rows_change_nothing_under_a_policy_that_never_names_alpaca():
    assert {key: _result_digest(r) for key, r in _golden_runs(True)} == _D2V3_GOLDEN
