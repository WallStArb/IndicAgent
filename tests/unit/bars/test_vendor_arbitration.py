"""The D-191-Q three-vendor arbitration (todo 545 step 3 rework): which vendor is right where
Alpaca and IBKR disagree on a 1d close, decided by Tradier while Tradier still exists."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.intelligence.bars.vendor_arbitration import (
    ALPACA_DIFFERS,
    IBKR_DEFECTIVE,
    PRE_IBKR_HISTORY,
    THREE_WAY,
    TWO_VENDOR,
    ArbitrationParams,
    LiveSymbolRow,
    arbitrate,
    build_plan,
    span_action,
)

_PARAMS = ArbitrationParams(
    window_start=date(2016, 1, 4),
    window_end=date(2026, 10, 6),
    tolerance_bp=10.0,
    min_sessions=5,
    min_class_share=0.9,
)


def _sessions(start: date, n: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _only(result, cls):
    return [s for s in result.spans if s.cls == cls]


def test_agreement_has_no_span():
    days = _sessions(date(2020, 1, 2), 30)
    closes = dict.fromkeys(days, 10.0)
    result = arbitrate("X", closes, closes, closes, _PARAMS)
    assert result.spans == () and result.n_common == 30


def test_oke_drift_is_ibkr_defective_evidence_and_no_row():
    days = _sessions(date(2018, 1, 2), 80)
    alpaca = dict.fromkeys(days, 10.0)
    ibkr = {d: 10.0 * (0.76 + 0.0084 * i) for i, d in enumerate(days)}
    result = arbitrate("OKE", alpaca, ibkr, dict(alpaca), _PARAMS)
    assert result.spans and {s.cls for s in result.spans} == {IBKR_DEFECTIVE}
    assert {span_action(s, _PARAMS) for s in result.spans} == {"evidence"}


def test_rjf_two_thirds_is_ibkr_defective():
    days = _sessions(date(2020, 1, 2), 60)
    alpaca = dict.fromkeys(days, 30.0)
    (span,) = arbitrate("RJF", alpaca, dict.fromkeys(days, 20.0), dict(alpaca), _PARAMS).spans
    assert span.cls == IBKR_DEFECTIVE and span.n_sessions == 60
    assert span.median_ibkr_over_alpaca == pytest.approx(2 / 3)


def test_a_spin_off_adjusted_span_is_alpaca_differs_and_gets_an_ibkr_row():
    days = _sessions(date(2024, 1, 2), 100)
    spin = days[70]
    alpaca = {d: 49.0 if d >= spin else 68.8 for d in days}
    ibkr = {d: 49.0 if d >= spin else 52.0 for d in days}
    (span,) = arbitrate("WDC", alpaca, ibkr, dict(ibkr), _PARAMS).spans
    assert span.cls == ALPACA_DIFFERS and (span.start, span.end) == (days[0], days[69])
    assert span_action(span, _PARAMS) == "row"


def test_a_ticker_reuse_span_is_alpaca_differs():
    days = _sessions(date(2016, 10, 3), 40)
    regular_way = days[21]
    alpaca = {d: 80.0 if d < regular_way else 23.0 for d in days}
    ibkr = {d: 16.0 if d < regular_way else 23.0 for d in days[11:]}
    (span,) = arbitrate("AA", alpaca, ibkr, dict(ibkr), _PARAMS).spans[-1:]
    assert span.cls == ALPACA_DIFFERS and span.end == days[20]


def test_three_way_disagreement_goes_to_the_hold_list():
    days = _sessions(date(2020, 1, 2), 30)
    (span,) = arbitrate(
        "SSP",
        dict.fromkeys(days, 10.0),
        dict.fromkeys(days, 12.0),
        dict.fromkeys(days, 14.0),
        _PARAMS,
    ).spans
    assert span.cls == THREE_WAY and span_action(span, _PARAMS) == "hold"


def test_two_vendors_disagreeing_without_tradier_go_to_the_hold_list():
    days = _sessions(date(2020, 1, 2), 30)
    (span,) = arbitrate(
        "X", dict.fromkeys(days, 10.0), dict.fromkeys(days, 12.0), {}, _PARAMS
    ).spans
    assert span.cls == TWO_VENDOR and span_action(span, _PARAMS) == "hold"


def test_a_short_disagreement_is_noise():
    days = _sessions(date(2020, 1, 2), 30)
    ibkr = {d: 12.0 if d in days[10:12] else 10.0 for d in days}
    (span,) = arbitrate(
        "X", dict.fromkeys(days, 10.0), ibkr, dict.fromkeys(days, 14.0), _PARAMS
    ).spans
    assert span.n_sessions == 2 and span_action(span, _PARAMS) == "noise"


def test_an_alpaca_differs_span_open_at_tradier_s_end_is_held_not_written():
    days = _sessions(date(2026, 8, 3), 40)
    window = ArbitrationParams(**{**_PARAMS.__dict__, "window_end": days[-1]})
    (span,) = arbitrate(
        "X",
        dict.fromkeys(days, 10.0),
        dict.fromkeys(days, 12.0),
        dict.fromkeys(days, 12.0),
        window,
    ).spans
    assert span.cls == ALPACA_DIFFERS and span.touches_window_end
    assert span_action(span, window) == "hold"


def test_sessions_outside_the_window_are_not_arbitrated():
    days = _sessions(date(2015, 12, 1), 40)
    (span,) = arbitrate(
        "X",
        dict.fromkeys(days, 10.0),
        dict.fromkeys(days, 12.0),
        dict.fromkeys(days, 12.0),
        _PARAMS,
    ).spans
    assert span.start == date(2016, 1, 4)


def test_alpaca_before_ibkr_history_is_held_only_when_ibkr_verified_its_head():
    days = _sessions(date(2020, 1, 2), 40)
    alpaca = dict.fromkeys(days, 10.0)
    ibkr = dict.fromkeys(days[20:], 10.0)
    unverified = arbitrate("MOD", alpaca, ibkr, dict(alpaca), _PARAMS)
    (pre,) = _only(unverified, PRE_IBKR_HISTORY)
    assert (pre.start, pre.end, pre.n_sessions) == (days[0], days[19], 20)
    assert span_action(pre, _PARAMS) == "info"
    verified = arbitrate("PINS", alpaca, ibkr, dict(alpaca), _PARAMS, ibkr_head_verified=days[20])
    assert span_action(_only(verified, PRE_IBKR_HISTORY)[0], _PARAMS) == "hold"


# --- the plan -------------------------------------------------------------------------------------


def _wdc():
    days = _sessions(date(2024, 1, 2), 100)
    spin = days[70]
    alpaca = {d: 49.0 if d >= spin else 68.8 for d in days}
    ibkr = {d: 49.0 if d >= spin else 52.0 for d in days}
    return arbitrate("WDC", alpaca, ibkr, dict(ibkr), _PARAMS), days


def test_the_plan_writes_the_alpaca_differs_row_and_disposes_every_live_symbol_row():
    wdc, days = _wdc()
    oke_days = _sessions(date(2018, 1, 2), 30)
    oke = arbitrate(
        "OKE",
        dict.fromkeys(oke_days, 10.0),
        dict.fromkeys(oke_days, 7.6),
        dict.fromkeys(oke_days, 10.0),
        _PARAMS,
    )
    ssp = arbitrate(
        "SSP",
        dict.fromkeys(oke_days, 10.0),
        dict.fromkeys(oke_days, 12.0),
        dict.fromkeys(oke_days, 14.0),
        _PARAMS,
    )
    live = [
        LiveSymbolRow("id-wdc", "WDC", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None),
        LiveSymbolRow("id-oke", "OKE", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None),
        LiveSymbolRow("id-ssp", "SSP", date(2000, 1, 3), None, "tradier", "ibkr"),
        LiveSymbolRow("id-zzz", "ZZZ", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None),
    ]
    plan = build_plan([wdc, oke, ssp], live, _PARAMS, evidence={"run": "test"})
    assert plan["timeframe"] == "1d" and plan["retire_defaults"] is True
    assert plan["seam"] == "2016-01-04"
    assert [
        (d["valid_from"], d.get("valid_to"), d["primary"], d.get("fallback"))
        for d in plan["defaults"]
    ] == [
        ("1990-01-01", "2016-01-04", "ibkr", None),
        ("2016-01-04", None, "alpaca", "ibkr"),
    ]
    (row,) = plan["symbol_rows"]
    assert (row["symbol"], row["valid_from"], row["valid_to"], row["primary"]) == (
        "WDC",
        days[0].isoformat(),
        (days[69] + timedelta(days=1)).isoformat(),
        "ibkr",
    )
    assert row["fallback"] is None and row["evidence"]["class"] == ALPACA_DIFFERS
    retired = {r["policy_id"]: r["disposition"] for r in plan["retire_symbol_rows"]}
    assert retired == {"id-wdc": "replaced", "id-oke": "confirmed"}
    kept = {r["policy_id"]: r["reason"] for r in plan["keep_symbol_rows"]}
    assert set(kept) == {"id-ssp", "id-zzz"}
    assert "hold" in kept["id-ssp"] and "no common" in kept["id-zzz"]
    assert [h["symbol"] for h in plan["hold"]] == ["SSP"]
    assert [e["symbol"] for e in plan["ibkr_defective"]] == ["OKE"]


def test_a_kept_row_turns_the_name_s_rows_into_holds():
    wdc, _ = _wdc()
    days = _sessions(date(2018, 1, 2), 30)
    three = arbitrate(
        "WDC",
        dict.fromkeys(days, 10.0),
        dict.fromkeys(days, 12.0),
        dict.fromkeys(days, 14.0),
        _PARAMS,
    )
    both = type(wdc)(symbol="WDC", n_common=wdc.n_common + 30, spans=three.spans + wdc.spans)
    live = [LiveSymbolRow("id-wdc", "WDC", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None)]
    plan = build_plan([both], live, _PARAMS, evidence={"run": "test"})
    assert plan["symbol_rows"] == []
    assert [r["policy_id"] for r in plan["keep_symbol_rows"]] == ["id-wdc"]
    assert {h["class"] for h in plan["hold"]} == {THREE_WAY, ALPACA_DIFFERS}


def test_the_plan_parses_as_an_ops_source_policy_plan():
    from scripts.ops.bars.ops_source_policy import parse_plan

    wdc, _ = _wdc()
    live = [LiveSymbolRow("id-wdc", "WDC", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None)]
    plan = parse_plan(build_plan([wdc], live, _PARAMS, evidence={"run": "test"}))
    assert plan.retire_defaults and [r["symbol"] for r in plan.symbol_rows] == ["WDC"]
