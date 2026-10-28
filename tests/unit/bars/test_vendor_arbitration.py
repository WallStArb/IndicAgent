"""The D-191-Q three-vendor 1d arbitration (todo 545): which vendor is right where Alpaca and IBKR
disagree on a 1d close, decided by Tradier while Tradier still exists. A hold means Alpaca does
not serve (second review H1): every hold span gets an interim IBKR row."""

from __future__ import annotations

from dataclasses import replace
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
    NameArbitration,
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
_DEFAULT_IDS = ("id-default-tradier", "id-default-ibkr")
_FINGERPRINT = {
    "through": "2026-10-06",
    "series": {"alpaca/sip_rth": {"rows": 1, "max_served_at": "2026-10-27T00:00:00+00:00"}},
}


def _sessions(start: date, n: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


_CALENDAR = _sessions(date(2015, 1, 1), 3200)


def _arb(symbol, alpaca, ibkr, tradier, params=_PARAMS, **kw):
    return arbitrate(symbol, alpaca, ibkr, tradier, params, sessions=_CALENDAR, **kw)


def _only(result, cls):
    return [s for s in result.spans if s.cls == cls]


def _plan(results, live=(), params=_PARAMS):
    return build_plan(
        results,
        list(live),
        params,
        evidence={"run": "test"},
        live_default_ids=_DEFAULT_IDS,
        raw_fingerprint=_FINGERPRINT,
    )


def test_agreement_has_no_span():
    days = _sessions(date(2020, 1, 2), 30)
    closes = dict.fromkeys(days, 10.0)
    result = _arb("X", closes, closes, closes)
    assert result.spans == () and result.n_common == 30


# --- IBKR wrong: evidence, Alpaca serves --------------------------------------------------------


def test_oke_drift_is_ibkr_defective_evidence_and_no_row():
    days = _sessions(date(2018, 1, 2), 80)
    alpaca = dict.fromkeys(days, 10.0)
    ibkr = {d: 10.0 * (0.76 + 0.0084 * i) for i, d in enumerate(days)}
    result = _arb("OKE", alpaca, ibkr, dict(alpaca))
    assert result.spans and {s.cls for s in result.spans} == {IBKR_DEFECTIVE}
    assert {span_action(s, _PARAMS) for s in result.spans} == {"evidence"}


def test_rjf_two_thirds_is_ibkr_defective():
    days = _sessions(date(2020, 1, 2), 60)
    alpaca = dict.fromkeys(days, 30.0)
    (span,) = _arb("RJF", alpaca, dict.fromkeys(days, 20.0), dict(alpaca)).spans
    assert span.cls == IBKR_DEFECTIVE and span.n_sessions == 60
    assert span.median_ibkr_over_alpaca == pytest.approx(2 / 3)


# --- IBKR right: a row ----------------------------------------------------------------------------


def test_a_spin_off_adjusted_span_is_alpaca_differs_and_gets_an_ibkr_row():
    days = _sessions(date(2024, 1, 2), 100)
    spin = days[70]
    alpaca = {d: 49.0 if d >= spin else 68.8 for d in days}
    ibkr = {d: 49.0 if d >= spin else 52.0 for d in days}
    (span,) = _arb("WDC", alpaca, ibkr, dict(ibkr)).spans
    assert span.cls == ALPACA_DIFFERS and (span.start, span.end) == (days[0], days[69])
    assert span_action(span, _PARAMS) == "row"


def test_a_ticker_reuse_span_is_alpaca_differs():
    days = _sessions(date(2016, 10, 3), 40)
    regular_way = days[21]
    alpaca = {d: 80.0 if d < regular_way else 23.0 for d in days}
    ibkr = {d: 16.0 if d < regular_way else 23.0 for d in days[11:]}
    span = _only(_arb("AA", alpaca, ibkr, dict(ibkr)), ALPACA_DIFFERS)[0]
    assert span.end == days[20] and span_action(span, _PARAMS) == "row"


def test_a_three_way_span_where_ibkr_and_tradier_both_adjusted_gets_a_row():
    # HON: IBKR/Tradier 33 bp apart and steady, both far from Alpaca's unadjusted level.
    days = _sessions(date(2016, 1, 4), 60)
    alpaca = dict.fromkeys(days, 10.0)
    tradier = dict.fromkeys(days, 4.95)
    ibkr = {d: 4.95 * (1 - 0.0033) for d in days}
    (span,) = _arb("HON", alpaca, ibkr, tradier).spans
    assert span.cls == THREE_WAY and span_action(span, _PARAMS) == "row"


def test_a_three_way_span_failing_the_log_share_stays_held():
    # DHC: IBKR/Tradier 47 bp against IBKR/Alpaca 359 bp, more than a tenth of it.
    days = _sessions(date(2016, 7, 1), 60)
    alpaca = dict.fromkeys(days, 10.0)
    ibkr = dict.fromkeys(days, 10.0 * 0.96466)
    tradier = {d: ibkr[d] / 0.99531 for d in days}
    (span,) = _arb("DHC", alpaca, ibkr, tradier).spans
    assert span.cls == THREE_WAY and span_action(span, _PARAMS) == "hold"


def test_a_three_way_span_with_ibkr_far_from_tradier_stays_held():
    days = _sessions(date(2016, 1, 4), 60)
    alpaca = dict.fromkeys(days, 10.0)
    tradier = dict.fromkeys(days, 6.0)
    ibkr = dict.fromkeys(days, 6.0 * 1.0374)  # LEN: 374 bp
    (span,) = _arb("LEN", alpaca, ibkr, tradier).spans
    assert span_action(span, _PARAMS) == "hold"


def test_an_unsteady_ibkr_tradier_spread_stays_held():
    days = _sessions(date(2016, 1, 4), 60)
    alpaca = dict.fromkeys(days, 10.0)
    tradier = dict.fromkeys(days, 5.0)
    ibkr = {d: 5.0 * (1.003 if i % 2 else 0.997) for i, d in enumerate(days)}
    (span,) = _arb("X", alpaca, ibkr, tradier).spans
    assert span.cls == THREE_WAY and span_action(span, _PARAMS) == "hold"


# --- holds, noise and quarantine ------------------------------------------------------------------


def test_two_vendors_disagreeing_without_tradier_go_to_the_hold_list():
    days = _sessions(date(2020, 1, 2), 30)
    (span,) = _arb("QBTS", dict.fromkeys(days, 10.0), dict.fromkeys(days, 12.0), {}).spans
    assert span.cls == TWO_VENDOR and span_action(span, _PARAMS) == "hold"


def test_an_alpaca_differs_span_open_at_tradier_s_end_is_held():
    days = _sessions(date(2026, 8, 3), 40)
    window = replace(_PARAMS, window_end=days[-1])
    (span,) = _arb(
        "X", dict.fromkeys(days, 10.0), dict.fromkeys(days, 12.0), dict.fromkeys(days, 12.0), window
    ).spans
    assert span.touches_window_end and span_action(span, window) == "hold"


def test_a_short_disagreement_is_noise():
    days = _sessions(date(2020, 1, 2), 30)
    ibkr = {d: 12.0 if d in days[10:12] else 10.0 for d in days}
    (span,) = _arb("X", dict.fromkeys(days, 10.0), ibkr, dict.fromkeys(days, 14.0)).spans
    assert span.n_sessions == 2 and span_action(span, _PARAMS) == "noise"


def test_a_short_alpaca_print_far_from_ibkr_and_tradier_is_quarantined():
    # GDX March 2020: IBKR equals Tradier, Alpaca's close more than 200 bp off for two sessions.
    days = _sessions(date(2020, 3, 2), 30)
    alpaca = {d: 10.3 if d in days[10:12] else (10.05 if d == days[20] else 10.0) for d in days}
    closes = dict.fromkeys(days, 10.0)
    result = _arb("GDX", alpaca, closes, dict(closes))
    assert [q["session"] for q in result.quarantine] == [days[10].isoformat(), days[11].isoformat()]
    plan = _plan([result])
    assert [(q["symbol"], q["session"]) for q in plan["quarantine"]] == [
        ("GDX", days[10].isoformat()),
        ("GDX", days[11].isoformat()),
    ]


def test_sessions_outside_the_window_are_not_arbitrated():
    days = _sessions(date(2015, 12, 1), 40)
    (span,) = _arb(
        "X", dict.fromkeys(days, 10.0), dict.fromkeys(days, 12.0), dict.fromkeys(days, 12.0)
    ).spans
    assert span.start == date(2016, 1, 4)


# --- Alpaca before IBKR's first bar: the continuity test -----------------------------------------


def test_an_ipo_day_bar_continuous_with_ibkr_s_head_serves_alpaca():
    # FCFS: Alpaca's two sessions run into IBKR's first bar, and both agree on that session.
    days = _sessions(date(2016, 8, 29), 20)
    alpaca = {d: 10.0 + 0.4 * i for i, d in enumerate(days)}
    ibkr = {d: alpaca[d] for d in days[2:]}
    (pre,) = _only(
        _arb("FCFS", alpaca, ibkr, dict(ibkr), ibkr_head_verified=days[2]), PRE_IBKR_HISTORY
    )
    assert pre.continuous and span_action(pre, _PARAMS) == "info"


def test_a_level_break_at_ibkr_s_head_is_no_bar_until_the_head():
    # AA: Alpaca prints the old Alcoa at 80 the session before IBKR's contract trades at 16.
    days = _sessions(date(2016, 10, 3), 30)
    alpaca = dict.fromkeys(days, 80.0)
    ibkr = dict.fromkeys(days[11:], 16.0)
    result = _arb("AA", alpaca, ibkr, {}, ibkr_head_verified=days[11])
    (pre,) = _only(result, PRE_IBKR_HISTORY)
    assert not pre.continuous and span_action(pre, _PARAMS) == "row"
    rows = [r for r in _plan([result])["symbol_rows"] if r["evidence"]["class"] == PRE_IBKR_HISTORY]
    assert [(r["valid_from"], r["valid_to"], r["primary"]) for r in rows] == [
        (days[0].isoformat(), days[11].isoformat(), "ibkr")
    ]


def test_a_gap_before_ibkr_s_head_is_no_bar():
    # DOW: Alpaca's ticker stops in 2017, IBKR's contract starts in 2019.
    days = _sessions(date(2017, 6, 1), 60)
    alpaca = {d: 10.0 for d in days[:20]} | {d: 10.0 for d in days[40:]}
    ibkr = {d: 10.0 for d in days[40:]}
    (pre,) = _only(_arb("DOW", alpaca, ibkr, {}), PRE_IBKR_HISTORY)
    assert pre.end == days[19] and not pre.continuous and span_action(pre, _PARAMS) == "row"


def test_ibkr_wrong_at_its_head_but_alpaca_equal_to_tradier_is_continuous():
    # MOD: on IBKR's first session Alpaca equals Tradier and IBKR is the one that is off.
    days = _sessions(date(2026, 8, 3), 30)
    alpaca = dict.fromkeys(days, 10.0)
    ibkr = dict.fromkeys(days[20:], 10.9)
    (pre,) = _only(_arb("MOD", alpaca, ibkr, dict(alpaca)), PRE_IBKR_HISTORY)
    assert pre.continuous and span_action(pre, _PARAMS) == "info"


def test_alpaca_with_no_ibkr_bar_at_all_is_held():
    days = _sessions(date(2020, 1, 2), 30)
    (pre,) = _arb("QRVO", dict.fromkeys(days, 10.0), {}, {}).spans
    assert pre.cls == PRE_IBKR_HISTORY and span_action(pre, _PARAMS) == "hold"


# --- the plan --------------------------------------------------------------------------------------


def _wdc():
    days = _sessions(date(2024, 1, 2), 100)
    spin = days[70]
    alpaca = {d: 49.0 if d >= spin else 68.8 for d in days}
    ibkr = {d: 49.0 if d >= spin else 52.0 for d in days}
    return _arb("WDC", alpaca, ibkr, dict(ibkr)), days


def test_every_hold_gets_an_interim_ibkr_row():
    days = _sessions(date(2018, 1, 2), 30)
    held = _arb(
        "SSP", dict.fromkeys(days, 10.0), dict.fromkeys(days, 12.0), dict.fromkeys(days, 14.0)
    )
    plan = _plan([held])
    (hold,) = plan["hold"]
    (row,) = plan["symbol_rows"]
    assert row["symbol"] == "SSP" and row["primary"] == "ibkr" and row["fallback"] is None
    assert row["evidence"]["interim"] is True
    assert row["valid_from"] <= hold["start"] and row["valid_to"] > hold["end"]


def test_the_plan_writes_rows_and_disposes_every_live_symbol_row():
    wdc, days = _wdc()
    oke_days = _sessions(date(2018, 1, 2), 30)
    oke = _arb(
        "OKE",
        dict.fromkeys(oke_days, 10.0),
        dict.fromkeys(oke_days, 7.6),
        dict.fromkeys(oke_days, 10.0),
    )
    live = [
        LiveSymbolRow("id-wdc", "WDC", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None),
        LiveSymbolRow("id-oke", "OKE", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None),
        LiveSymbolRow("id-zzz", "ZZZ", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None),
    ]
    plan = _plan([wdc, oke], live)
    assert plan["timeframe"] == "1d" and plan["retire_defaults"] is True
    assert plan["retire_default_ids"] == list(_DEFAULT_IDS)
    assert plan["raw_fingerprint"] == _FINGERPRINT
    assert [
        (d["valid_from"], d.get("valid_to"), d["primary"], d.get("fallback"))
        for d in plan["defaults"]
    ] == [("1990-01-01", "2016-01-04", "ibkr", None), ("2016-01-04", None, "alpaca", "ibkr")]
    (row,) = plan["symbol_rows"]
    assert (row["symbol"], row["valid_from"], row["valid_to"]) == (
        "WDC",
        days[0].isoformat(),
        (days[69] + timedelta(days=1)).isoformat(),
    )
    retired = {r["policy_id"]: r["disposition"] for r in plan["retire_symbol_rows"]}
    assert retired == {"id-wdc": "replaced", "id-oke": "superseded_by_default"}
    (kept,) = plan["keep_symbol_rows"]
    assert kept["policy_id"] == "id-zzz" and kept["valid_from"] == "1990-01-01"
    assert kept["valid_to"] == "2026-10-07"
    assert [e["symbol"] for e in plan["ibkr_defective"]] == ["OKE"]


def test_a_name_with_a_live_row_and_holds_retires_it_for_the_interim_rows():
    days = _sessions(date(2018, 1, 2), 30)
    held = _arb(
        "SSP", dict.fromkeys(days, 10.0), dict.fromkeys(days, 12.0), dict.fromkeys(days, 14.0)
    )
    live = [LiveSymbolRow("id-ssp", "SSP", date(2000, 1, 3), None, "tradier", "ibkr")]
    plan = _plan([held], live)
    assert plan["keep_symbol_rows"] == []
    assert plan["retire_symbol_rows"][0]["disposition"] == "replaced"


def test_the_plan_parses_as_an_ops_source_policy_plan():
    from scripts.ops.bars.ops_source_policy import parse_plan

    wdc, _ = _wdc()
    days = _sessions(date(2018, 1, 2), 30)
    held = _arb(
        "SSP", dict.fromkeys(days, 10.0), dict.fromkeys(days, 12.0), dict.fromkeys(days, 14.0)
    )
    live = [LiveSymbolRow("id-wdc", "WDC", date(1990, 1, 1), date(2026, 10, 7), "ibkr", None)]
    plan = parse_plan(_plan([wdc, held], live))
    assert plan.retire_defaults and sorted({r["symbol"] for r in plan.symbol_rows}) == [
        "SSP",
        "WDC",
    ]


def test_name_arbitration_defaults_to_no_quarantine():
    assert NameArbitration("X", 0, ()).quarantine == ()


# --- third review: a long pre-IBKR span needs Tradier's word or an ordinary gap -----------------


def _handover(n_pre: int, *, alpaca_last: float, tradier_pre: float | None):
    """Alpaca answers n_pre sessions before IBKR's first bar, then both agree from it on. IBKR's
    own daily moves alternate +-1% (median absolute move about 100 bp)."""
    days = _sessions(date(2020, 1, 2), n_pre + 40)
    pre, post = days[:n_pre], days[n_pre:]
    ibkr = {d: 10.0 * (1.01 if i % 2 else 1.0) for i, d in enumerate(post)}
    alpaca = {d: alpaca_last for d in pre} | dict(ibkr)
    tradier = {} if tradier_pre is None else {d: tradier_pre for d in pre}
    return days, alpaca, ibkr, tradier


def test_a_long_span_tradier_contradicts_with_a_large_gap_is_held():
    # SW: WestRock under the reused ticker; Tradier disagrees, the gap is 8 daily moves.
    days, alpaca, ibkr, tradier = _handover(60, alpaca_last=10.8, tradier_pre=13.0)
    (pre,) = _only(_arb("SW", alpaca, ibkr, tradier), PRE_IBKR_HISTORY)
    assert pre.continuous and span_action(pre, _PARAMS) == "hold"
    rows = _plan([_arb("SW", alpaca, ibkr, tradier)])["symbol_rows"]
    assert [(r["valid_from"], r["evidence"]["interim"]) for r in rows] == [
        (days[0].isoformat(), True)
    ]


def test_a_long_span_without_tradier_and_a_large_gap_is_held():
    # GRNT: no Tradier inside the span, the gap is about 7 daily moves.
    _days, alpaca, ibkr, tradier = _handover(60, alpaca_last=10.7, tradier_pre=None)
    (pre,) = _only(_arb("GRNT", alpaca, ibkr, tradier), PRE_IBKR_HISTORY)
    assert span_action(pre, _PARAMS) == "hold"


def test_a_long_span_tradier_corroborates_is_admitted_whatever_the_gap():
    # RKT: Tradier agrees with Alpaca across the span; the gap is a real move.
    _days, alpaca, ibkr, tradier = _handover(60, alpaca_last=10.5, tradier_pre=10.5)
    (pre,) = _only(_arb("RKT", alpaca, ibkr, tradier), PRE_IBKR_HISTORY)
    assert span_action(pre, _PARAMS) == "info"


def test_a_long_span_with_an_ordinary_gap_is_admitted_without_tradier():
    _days, alpaca, ibkr, tradier = _handover(60, alpaca_last=9.8, tradier_pre=None)
    (pre,) = _only(_arb("X", alpaca, ibkr, tradier), PRE_IBKR_HISTORY)
    assert span_action(pre, _PARAMS) == "info"


def test_a_short_span_keeps_the_same_session_test_alone():
    # An IPO-day bar (20 sessions or fewer): a large first-day gap is an ordinary IPO move.
    _days, alpaca, ibkr, tradier = _handover(5, alpaca_last=13.0, tradier_pre=None)
    (pre,) = _only(
        _arb("IPO", alpaca, ibkr, tradier, replace(_PARAMS, min_sessions=20)), PRE_IBKR_HISTORY
    )
    assert span_action(pre, replace(_PARAMS, min_sessions=20)) == "info"


def test_the_gap_bound_is_a_parameter():
    _days, alpaca, ibkr, tradier = _handover(60, alpaca_last=10.7, tradier_pre=None)
    loose = replace(_PARAMS, gap_max_moves=10.0)
    (pre,) = _only(_arb("GRNT", alpaca, ibkr, tradier, loose), PRE_IBKR_HISTORY)
    assert span_action(pre, loose) == "info"
