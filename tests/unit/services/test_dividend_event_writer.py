"""Dividend derivation from TRADES / ADJUSTED_LAST ratio steps (todo 428).

Synthetic series are built the way IBKR builds ADJUSTED_LAST: TRADES close times a cumulative
factor that multiplies in (1 - amount / prior close) for every ex-date after the day, then
rounded to the cent.
"""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

import services.dividend_event_writer as dividend_event_writer
from services.dividend_event_writer import (
    SOURCE_IBKR,
    Derivation,
    DividendEvent,
    derive_ibkr_events,
    derive_yahoo_events,
    disagreeing_yields,
    join_adjustment_pairs,
    pair_d1_series,
    reconcile,
    require_cvr_codes,
    vanished_ex_dates,
)
from src.core.models import AssetClass
from src.intelligence.research.dividends import DisputeRule

MARGIN = 1.25
STABLE = 3
RULE = DisputeRule(rel_tolerance=0.1, noise_margin=MARGIN)


def _series(closes, dividends):
    """dividends: {row index of ex-date: amount}. Returns (day, close, adjusted) rows."""
    n = len(closes)
    factor = np.ones(n)
    for i, amount in dividends.items():
        factor[:i] *= 1.0 - amount / closes[i - 1]
    start = date(2010, 1, 4)
    return [
        (start + timedelta(days=k), float(closes[k]), round(float(closes[k] * factor[k]), 2))
        for k in range(n)
    ]


def _walk(n, start_price, seed):
    rng = np.random.default_rng(seed)
    return np.round(start_price * np.exp(np.cumsum(rng.normal(0, 0.012, n))), 2)


def test_quarterly_dividends_recovered_within_rounding():
    closes = _walk(400, 470.0, seed=1)
    dividends = {60: 1.91, 123: 1.60, 186: 1.76, 249: 1.74, 312: 1.97}
    d = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    assert [e.ex_date for e in d.events] == [
        date(2010, 1, 4) + timedelta(days=i) for i in dividends
    ]
    for e, amount in zip(d.events, dividends.values(), strict=True):
        assert abs(e.dividend_yield - amount / e.prev_close) <= e.yield_tolerance
    assert (d.n_downward_steps, d.n_unstable_steps) == (0, 0)


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("price", [4.0, 75.0, 600.0])
def test_rounding_alone_never_produces_an_event(seed, price):
    # A deep cumulative factor (0.3) makes the adjusted prices small, the hardest case.
    closes = _walk(1500, price, seed)
    series = [(d, c, round(c * 0.3, 2)) for d, c, _ in _series(closes, {})]
    d = derive_ibkr_events(series, 1.0, STABLE)
    assert d.events == [] and d.n_downward_steps == 0 and d.n_unstable_steps == 0


def test_monthly_high_yield_payer_fully_recovered():
    closes = _walk(2000, 75.0, seed=7)
    dividends = {i: 0.38 for i in range(21, 1990, 21)}
    d = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    assert len(d.events) == len(dividends)
    assert all(abs(e.dividend_yield - 0.38 / e.prev_close) <= e.yield_tolerance for e in d.events)


def test_downward_step_is_an_anomaly_not_a_dividend():
    closes = _walk(50, 100.0, seed=3)
    series = _series(closes, {})
    series = series[:25] + [(day, c, round(a * 0.99, 2)) for day, c, a in series[25:]]
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == [] and d.n_downward_steps == 1


def test_one_day_excursion_is_unstable():
    closes = _walk(50, 100.0, seed=4)
    series = _series(closes, {})
    day, c, a = series[25]
    series[25] = (day, c, round(a * 1.01, 2))
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == [] and d.n_unstable_steps == 1 and d.n_downward_steps == 1


def test_newest_step_waits_for_the_next_run():
    closes = _walk(30, 100.0, seed=5)
    series = _series(closes, {29: 1.0})
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == []
    assert (d.covered_from, d.covered_to) == (series[1 + STABLE][0], series[-1 - STABLE][0])


def test_short_and_invalid_input():
    with pytest.raises(ValueError, match="too few"):
        derive_ibkr_events([], MARGIN, STABLE)
    with pytest.raises(ValueError, match="too few"):
        derive_yahoo_events([(date(2020, 1, 1), 10.0, 0.0)])
    with pytest.raises(ValueError, match="non-positive"):
        derive_ibkr_events([(date(2020, 1, 1), 0.0, 1.0)] * 10, MARGIN, STABLE)
    nan = float("nan")
    with pytest.raises(ValueError, match="unusable close"):
        derive_yahoo_events([(date(2020, 1, 1), 10.0, 0.0), (date(2020, 1, 2), nan, 0.2)])
    with pytest.raises(ValueError, match="unusable close"):  # the close a yield is taken from
        derive_yahoo_events(
            [(D, 10.0, 0), (D + timedelta(1), nan, 0), (D + timedelta(2), 9.0, 0.2)]
        )
    with pytest.raises(ValueError, match="unusable close"):
        derive_yahoo_events([(D, 10.0, 0.0), (D + timedelta(1), -1.0, 0.0)])
    # An untraded day away from any dividend is dropped, not fatal.
    d = derive_yahoo_events(
        [
            (D, 10.0, 0),
            (D + timedelta(1), nan, 0),
            (D + timedelta(2), 9.0, 0),
            (D + timedelta(3), 9.5, 0.2),
        ]
    )
    assert [(e.ex_date, e.prev_close) for e in d.events] == [(D + timedelta(3), 9.0)]
    with pytest.raises(ValueError, match="negative dividend"):
        derive_yahoo_events([(date(2020, 1, 1), 10.0, 0.0), (date(2020, 1, 2), 10.0, -0.1)])


def test_yahoo_events_use_the_prior_close_and_skip_row_zero():
    d0 = date(2020, 1, 2)
    rows = [(d0, 100.0, 0.5), (d0 + timedelta(1), 101.0, 0.0), (d0 + timedelta(2), 99.0, 0.8)]
    d = derive_yahoo_events(rows)
    assert [(e.ex_date, e.amount, e.prev_close) for e in d.events] == [(rows[2][0], 0.8, 101.0)]
    assert (d.covered_from, d.covered_to) == (rows[1][0], rows[2][0])


def test_rederived_yield_is_split_invariant():
    event = DividendEvent(date(2020, 3, 20), amount=1.80, prev_close=600.0, yield_tolerance=1e-5)
    derivation = Derivation([event], event.ex_date, event.ex_date)
    # Stored before a 2:1 split: amount 3.60 on a 1200 close, same yield.
    assert disagreeing_yields({event.ex_date: 3.60 / 1200.0}, derivation) == []
    assert disagreeing_yields({event.ex_date: 2.00 / 600.0}, derivation) == [event.ex_date]


D = date(2012, 10, 1)
_PC = {D: 1000.0}  # a high prior close: the rounding bound is negligible, the relative one rules


def test_reconcile_flags_one_dividend_on_two_dates():
    rec = reconcile(
        {D: 0.005}, {D + timedelta(1): 0.005}, (D, D), (D, D + timedelta(9)), 5, RULE, _PC
    )
    assert rec.near_misses == [(D, D + timedelta(1))]
    assert rec.ibkr_holes == [] and rec.yahoo_holes == []


def test_reconcile_holes_count_only_inside_the_other_sources_span():
    later = D + timedelta(31)
    span = (D, later)
    rec = reconcile({D: 0.005}, {later: 0.005}, span, span, 5, RULE, _PC)
    assert rec.near_misses == [] and rec.ibkr_holes == [later] and rec.yahoo_holes == [D]
    rec = reconcile({}, {later: 0.005}, (D, D), span, 5, RULE, _PC)
    assert rec.ibkr_holes == []  # IBKR never examined that date


def test_reconcile_yield_disagreement_is_relative():
    assert reconcile({D: 0.0052}, {D: 0.005}, None, None, 5, RULE, _PC).yield_disagreements == []
    assert reconcile({D: 0.0060}, {D: 0.005}, None, None, 5, RULE, _PC).yield_disagreements == [D]


def test_join_refuses_a_day_missing_from_one_series():
    d = [date(2020, 1, k) for k in range(2, 7)]
    trades = {x: 10.0 for x in d}
    adjusted = {x: 9.0 for x in d}
    assert len(join_adjustment_pairs(trades, adjusted)) == 5
    # Different history depths are fine; only the overlap must match.
    assert len(join_adjustment_pairs(trades, {x: 9.0 for x in d[1:]})) == 4
    del adjusted[d[2]]
    with pytest.raises(ValueError, match="disagree on 1 days"):
        join_adjustment_pairs(trades, adjusted)


def test_vanished_ex_dates_only_inside_the_examined_span():
    event = DividendEvent(D + timedelta(1), 0.5, 100.0, 1e-6)
    derivation = Derivation([event], D, D + timedelta(20))
    stored = {D, D + timedelta(1), D + timedelta(40)}
    assert vanished_ex_dates(stored, derivation) == [D]


def test_yahoo_tolerance_absorbs_split_rerounding():
    # A 10:1 split re-scales and re-rounds: 0.52 on 41.37 becomes 0.052 on 4.14 (cents).
    event = derive_yahoo_events([(D, 41.40, 0.0), (D + timedelta(1), 41.37, 0.52)]).events[0]
    assert abs(0.052 / 4.14 - event.dividend_yield) <= event.yield_tolerance


@pytest.mark.parametrize("seed", range(10))
def test_series_on_different_closes_produce_no_events(seed):
    """NVR 2004: IBKR's two series used different closing prices, so the ratio wandered about
    0.3% a day, up to 150x the rounding bound. No step is stable; none may become a dividend."""
    rng = np.random.default_rng(seed)
    closes = _walk(500, 450.0, seed)
    other = closes * (1 + rng.uniform(-0.003, 0.003, len(closes)))
    series = [
        (d, c, round(float(a), 2)) for (d, c, _), a in zip(_series(closes, {}), other, strict=True)
    ]
    d = derive_ibkr_events(series, MARGIN, STABLE)
    assert d.events == [] and d.n_unstable_steps > 0


def test_weekly_payer_is_still_detected():
    closes = _walk(300, 25.0, seed=11)
    dividends = {i: 0.05 for i in range(10, 290, 5)}
    d = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    assert [e.ex_date for e in d.events] == [
        date(2010, 1, 4) + timedelta(days=i) for i in dividends
    ]


def test_a_disagreement_inside_ibkr_rounding_is_not_reported():
    """MRVL: a $0.06 dividend on a $15 close. IBKR's cent rounding alone moves the implied
    yield by up to about 17%, so a 15% gap is noise; a gap beyond both bounds is reported."""
    yahoo_y = 0.06 / 15.0
    pc = {D: 15.0}
    assert not reconcile(
        {D: yahoo_y * 1.15}, {D: yahoo_y}, None, None, 5, RULE, pc
    ).yield_disagreements
    assert reconcile({D: yahoo_y * 1.6}, {D: yahoo_y}, None, None, 5, RULE, pc).yield_disagreements


# ---------------------------------------------------------------------------
# D1 route (phase 185 plan 21; raw since plan 191-10): the IBKR branch pairs the TRADES and
# ADJUSTED_LAST raw series for one fetch_run_id (pair_d1_series, D-191-D) instead of
# fetching them, and near misses become dividend_date_dispute rows inside the
# per-symbol transaction instead of rolling the symbol back.
# ---------------------------------------------------------------------------

_RUN = uuid.UUID("33333333-3333-3333-3333-333333333333")
_RUN_OTHER = uuid.UUID("44444444-4444-4444-4444-444444444444")
_START = date(2010, 1, 4)


def _d1_fixture(closes, dividends):
    """(TRADES, ADJUSTED_LAST) D1 row lists for _RUN, built from _series output."""
    rows = _series(closes, dividends)
    return [(_RUN, d, c) for d, c, _ in rows], [(_RUN, d, a) for d, _, a in rows]


def _equity(symbol):
    return SimpleNamespace(symbol=symbol, asset_class=AssetClass.EQUITY)


class FakeDividendConn:
    """asyncpg.Connection-shaped fake over D1 rows and in-memory dividend stores.

    Applies the same first-derivation-wins and ON CONFLICT DO NOTHING semantics
    the live tables carry, so a test can assert what a run leaves behind.
    """

    def __init__(self, d1, latest_run=None, apr_extra=None):
        self.d1 = d1  # symbol -> {(what_to_show, run_id): [(run_id, bar_date, close)]}
        self.latest_run = latest_run
        self.apr_extra = apr_extra or {}  # extra config_state rows the test needs read
        self.events = {}  # (symbol, source) -> {ex_date: (amount, prev_close)}
        self.coverage = {}  # (symbol, source) -> (covered_from, covered_to)
        self.disputes = []  # dividend_date_dispute rows as executemany received them
        self.dispute_sql = ""

    class _Txn:
        def __init__(self, outer):
            self.outer = outer

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    def transaction(self):
        return FakeDividendConn._Txn(self)

    async def fetch(self, sql, *args):
        if "config_state" in sql:  # load_apr_dict_async: the writer's APR keys
            return [
                {"config_key": key, "config_value": value}
                for key, value in {
                    "threshold.dividend_event.noise_margin": "1.25",
                    "threshold.dividend_event.stable_sessions": "3",
                    "threshold.dividend_event.ex_date_match_days": "5",
                    "threshold.dividend_event.source_yield_rel_tolerance": "0.10",
                    **self.apr_extra,
                }.items()
            ]
        if "controlled_vocabulary" in sql:
            return [
                {"namespace": "bar_vendor", "code": "ibkr"},
                {"namespace": "bar_kind", "code": "smart_trades"},
                {"namespace": "bar_kind", "code": "smart_adjusted"},
            ]
        if "ohlcv_raw" in sql:  # the raw series as current rows, one serve after every bar
            symbol, _vendor, kind = args
            what = {"smart_trades": "TRADES", "smart_adjusted": "ADJUSTED_LAST"}[kind]
            return [
                _answer(d, c, run)
                for (w, _run_key), rows in self.d1.get(symbol, {}).items()
                if w == what
                for run, d, c in rows
            ]
        if "AS dividend_yield" in sql:  # _write: this source's stored events
            symbol, source = args
            return [
                {"ex_date": ex, "dividend_yield": amount / prev_close}
                for ex, (amount, prev_close) in sorted(
                    self.events.get((symbol, source), {}).items()
                )
            ]
        if " AS y" in sql:  # _reconcile: every stored event for the symbol
            (symbol,) = args
            return [
                {
                    "source": source,
                    "ex_date": ex,
                    "y": amount / prev_close,
                    "prev_close": prev_close,
                }
                for (sym, source), events in sorted(self.events.items())
                if sym == symbol
                for ex, (amount, prev_close) in sorted(events.items())
            ]
        if "covered_from, covered_to FROM dividend_event_coverage" in sql:
            (symbol,) = args
            return [
                {"source": source, "covered_from": lo, "covered_to": hi}
                for (sym, source), (lo, hi) in sorted(self.coverage.items())
                if sym == symbol
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql, *args):
        if "GROUP BY" in sql:  # _resolve_fetch_run: latest run with both series
            return {"fetch_run_id": self.latest_run} if self.latest_run else None
        if "dividend_event_coverage" in sql:  # _write: this source's stored span
            span = self.coverage.get((args[0], args[1]))
            return {"covered_from": span[0], "covered_to": span[1]} if span is not None else None
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql, *args):
        if "dividend_event_coverage" in sql:
            symbol, source, lo, hi, _checked = args
            old = self.coverage.get((symbol, source), (lo, hi))
            self.coverage[(symbol, source)] = (min(old[0], lo), max(old[1], hi))
            return "INSERT 0 1"
        raise AssertionError(f"unexpected execute: {sql}")

    async def executemany(self, sql, args_seq):
        if "INSERT INTO dividend_events" in sql:
            for symbol, ex_date, source, amount, prev_close, _version in args_seq:
                self.events.setdefault((symbol, source), {}).setdefault(
                    ex_date, (amount, prev_close)
                )
            return "INSERT 0 0"
        if "dividend_date_dispute" in sql:
            self.dispute_sql = sql
            for symbol, first, last, dates_json, run_id in args_seq:
                if not any(
                    r[0] == symbol and r[1] == first and r[2] == last for r in self.disputes
                ):
                    self.disputes.append((symbol, first, last, dates_json, run_id))
            return "INSERT 0 0"
        raise AssertionError(f"unexpected executemany: {sql}")


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    class _Acquire:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, *exc):
            return False

    def acquire(self):
        return FakePool._Acquire(self.conn)


def _run_writer(conn, instruments, sources=("ibkr",), fetch_run_id=_RUN):
    writer = dividend_event_writer.DividendEventWriter(
        "postgresql://unused",
        None,
        [dividend_event_writer._CLI_SOURCES[s] for s in sources],
        fetch_run_id,
        [i.symbol for i in instruments],
    )
    original = dividend_event_writer.get_active_contracts
    dividend_event_writer.get_active_contracts = lambda settings, dimension: list(instruments)
    try:
        asyncio.run(writer.execute(FakePool(conn)))
    finally:
        dividend_event_writer.get_active_contracts = original


_SERVED = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)


def _answer(day, close, run, *, served=_SERVED, current=True, origin=None, route="SMART"):
    return {
        "bar_date": day,
        "close": close,
        "served_at": served,
        "fetch_run_id": run,
        "route": route,
        "current": current,
        "origin": origin,
    }


def test_pair_d1_series_takes_the_runs_own_answers():
    days = [_START, _START + timedelta(1)]
    trades = [_answer(d, c, _RUN) for d, c in zip(days, (10.0, 11.0), strict=True)]
    adjusted = [_answer(d, c, _RUN) for d, c in zip(days, (9.0, 9.9), strict=True)]
    assert pair_d1_series(trades, adjusted, _RUN) == (
        {days[0]: 10.0, days[1]: 11.0},
        {days[0]: 9.0, days[1]: 9.9},
    )
    with pytest.raises(ValueError, match="twice with different closes"):
        pair_d1_series(trades + [_answer(days[0], 10.5, _RUN)], adjusted, _RUN)
    with pytest.raises(ValueError, match="no ADJUSTED_LAST answers"):
        pair_d1_series(trades, adjusted, _RUN_OTHER)


def test_trades_restated_after_the_adjusted_serve_never_pairs_by_ordering():
    """D-191-D (a): the current TRADES row was restated after the adjusted serve. It must not
    pair; the run's own answer (same fetch_run_id) does, and without one the value stored at
    the adjusted serve (now in the revision log) does."""
    day = _START
    a_served = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    adjusted = [_answer(day, 9.0, _RUN, served=a_served)]
    restated = _answer(day, 30.0, _RUN_OTHER, served=a_served + timedelta(days=8))
    same_run = _answer(day, 10.0, _RUN, served=a_served, current=False, origin="raw")
    trades, _ = pair_d1_series([restated, same_run], adjusted, _RUN)
    assert trades == {day: 10.0}
    earlier = uuid.UUID("55555555-5555-5555-5555-555555555555")
    displaced = _answer(
        day, 10.0, earlier, served=a_served - timedelta(days=1), current=False, origin="raw"
    )
    trades, _ = pair_d1_series([restated, displaced], adjusted, _RUN)
    assert trades == {day: 10.0}
    trades_only_restated, _ = pair_d1_series(
        [restated, _answer(day + timedelta(1), 1.0, _RUN)], adjusted, _RUN
    )
    assert day not in trades_only_restated


def test_trades_unchanged_for_the_date_pairs_by_ordering_although_the_name_split_later():
    """D-191-D (b): TRADES for this date was served before the adjusted answer by another run
    and never changed (the split restated other dates). The ordering pair is accepted."""
    day = _START
    a_served = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    adjusted = [_answer(day, 9.0, _RUN, served=a_served)]
    unchanged = _answer(day, 10.0, _RUN_OTHER, served=a_served - timedelta(days=30))
    later_split = _answer(day + timedelta(1), 5.0, _RUN_OTHER, served=a_served + timedelta(days=8))
    trades, _ = pair_d1_series([unchanged, later_split], adjusted, _RUN)
    assert trades[day] == 10.0


def test_a_superseded_offer_or_a_forming_adjusted_bar_never_pairs():
    day = _START
    a_served = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    adjusted = [
        _answer(day, 9.0, _RUN, served=a_served),
        _answer(a_served.date(), 9.5, _RUN, served=a_served),  # forming on its answer date
    ]
    offer = _answer(
        day, 99.0, _RUN_OTHER, served=a_served - timedelta(1), current=False, origin="superseded"
    )
    trades, adj = pair_d1_series([offer, _answer(day + timedelta(1), 1.0, _RUN)], adjusted, _RUN)
    assert day not in trades and a_served.date() not in adj


def test_the_writer_refuses_to_run_without_its_cvr_codes():
    require_cvr_codes(
        [
            {"namespace": "bar_vendor", "code": "ibkr"},
            {"namespace": "bar_kind", "code": "smart_trades"},
            {"namespace": "bar_kind", "code": "smart_adjusted"},
        ]
    )
    with pytest.raises(RuntimeError, match="smart_adjusted"):
        require_cvr_codes([{"namespace": "bar_vendor", "code": "ibkr"}])


@pytest.mark.parametrize(
    "price,seed,dividends",
    [
        (470.0, 1, {60: 1.91, 123: 1.60, 186: 1.76, 249: 1.74, 312: 1.97}),  # JPM-shaped
        (75.0, 7, {i: 0.38 for i in range(21, 480, 21)}),  # KO-shaped high yield
        (25.0, 11, {i: 0.05 for i in range(10, 400, 5)}),  # XLU-shaped low price
    ],
)
def test_d1_route_reproduces_the_interim_derivation(price, seed, dividends):
    closes = _walk(520, price, seed=seed)
    trades, adjusted = _d1_fixture(closes, dividends)
    conn = FakeDividendConn({"JPM": {("TRADES", _RUN): trades, ("ADJUSTED_LAST", _RUN): adjusted}})
    _run_writer(conn, [_equity("JPM")])
    expected = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    stored = conn.events[("JPM", SOURCE_IBKR)]
    assert sorted(stored) == [e.ex_date for e in expected.events]
    for event in expected.events:
        assert stored[event.ex_date] == (event.amount, event.prev_close)
    assert conn.coverage[("JPM", SOURCE_IBKR)] == (expected.covered_from, expected.covered_to)


def test_d1_route_nvr_2004_wander_derives_nothing():
    rng = np.random.default_rng(3)
    closes = _walk(500, 450.0, seed=3)
    other = closes * (1 + rng.uniform(-0.003, 0.003, len(closes)))
    rows = _series(closes, {})
    conn = FakeDividendConn(
        {
            "NVR": {
                ("TRADES", _RUN): [(_RUN, d, c) for d, c, _ in rows],
                ("ADJUSTED_LAST", _RUN): [
                    (_RUN, d, round(float(a), 2)) for (d, _, _), a in zip(rows, other, strict=True)
                ],
            }
        }
    )
    _run_writer(conn, [_equity("NVR")])
    assert conn.events.get(("NVR", SOURCE_IBKR), {}) == {}
    assert conn.disputes == []


def test_d1_route_refuses_series_from_two_fetch_runs():
    closes = _walk(400, 470.0, seed=1)
    trades, _adjusted_other_run = _d1_fixture(closes, {100: 1.90})
    rows = _series(closes, {})
    conn = FakeDividendConn(
        {
            "JPM": {
                ("TRADES", _RUN): trades,
                ("ADJUSTED_LAST", _RUN_OTHER): [(_RUN_OTHER, d, a) for d, _, a in rows],
            }
        }
    )
    with pytest.raises(RuntimeError, match="no ADJUSTED_LAST answers"):
        _run_writer(conn, [_equity("JPM")])
    assert conn.events == {} and conn.disputes == []


def test_near_misses_record_disputes_and_keep_the_events():
    closes = _walk(200, 470.0, seed=2)
    dividends = {100: 1.90}
    trades, adjusted = _d1_fixture(closes, dividends)
    conn = FakeDividendConn({"JPM": {("TRADES", _RUN): trades, ("ADJUSTED_LAST", _RUN): adjusted}})
    ibkr_ex = _START + timedelta(days=100)
    yahoo_ex = ibkr_ex + timedelta(days=2)  # one dividend, two dates: a near miss
    conn.events[("JPM", "yahoo")] = {yahoo_ex: (1.90, closes[99])}
    conn.coverage[("JPM", "yahoo")] = (ibkr_ex - timedelta(days=150), ibkr_ex + timedelta(days=90))
    _run_writer(conn, [_equity("JPM")])
    assert sorted(conn.events[("JPM", SOURCE_IBKR)]) == [ibkr_ex]  # no rollback
    assert conn.disputes == [
        (
            "JPM",
            ibkr_ex,
            yahoo_ex,
            json.dumps(
                {"ibkr_adjusted_last_ratio": ibkr_ex.isoformat(), "yahoo": yahoo_ex.isoformat()}
            ),
            _RUN,
        )
    ]
    assert "ON CONFLICT DO NOTHING" in conn.dispute_sql


def test_dispute_replay_on_a_rerun_writes_nothing_new():
    closes = _walk(200, 470.0, seed=2)
    trades, adjusted = _d1_fixture(closes, {100: 1.90})
    conn = FakeDividendConn({"JPM": {("TRADES", _RUN): trades, ("ADJUSTED_LAST", _RUN): adjusted}})
    ibkr_ex = _START + timedelta(days=100)
    conn.events[("JPM", "yahoo")] = {ibkr_ex + timedelta(days=2): (1.90, closes[99])}
    conn.coverage[("JPM", "yahoo")] = (ibkr_ex - timedelta(days=150), ibkr_ex + timedelta(days=90))
    _run_writer(conn, [_equity("JPM")])
    _run_writer(conn, [_equity("JPM")])  # the same dispute again on a rerun
    assert len(conn.disputes) == 1


def test_default_fetch_run_is_the_latest_paired_run():
    closes = _walk(400, 470.0, seed=1)
    dividends = {100: 1.90, 200: 1.60}
    trades, adjusted = _d1_fixture(closes, dividends)
    conn = FakeDividendConn(
        {"JPM": {("TRADES", _RUN): trades, ("ADJUSTED_LAST", _RUN): adjusted}},
        latest_run=_RUN,
    )
    _run_writer(conn, [_equity("JPM")], fetch_run_id=None)
    expected = derive_ibkr_events(_series(closes, dividends), MARGIN, STABLE)
    assert sorted(conn.events[("JPM", SOURCE_IBKR)]) == [e.ex_date for e in expected.events]


def test_a_runs_superseded_offer_never_pairs_on_either_side_in_any_row_order():
    """Review of 191-10, finding 2: a value the run offered but raw never stored (origin
    superseded) pairs on neither side, and the outcome does not depend on row order."""
    day, other = _START, _START + timedelta(1)
    a_served = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
    offer = {"served": a_served, "current": False, "origin": "superseded"}
    adjusted = [
        _answer(day, 9.0, _RUN, served=a_served),
        _answer(other, 7.7, _RUN, **offer),  # the run's only adjusted answer of `other`
    ]
    trades = [
        _answer(day, 55.0, _RUN, **offer),  # superseded TRADES offer of the run
        _answer(day, 10.0, _RUN, served=a_served),
    ]
    for t_rows in (trades, trades[::-1]):
        paired, adj = pair_d1_series(t_rows, adjusted, _RUN)
        assert adj == {day: 9.0}
        assert paired == {day: 10.0}


# ---------------------------------------------------------------------------
# Per-name isolation (threshold.dividend.max_failure_fraction): one name's
# Yahoo failure never blocks the others, and the failure fraction gates the
# run's end state (partial vs nonzero exit).
# ---------------------------------------------------------------------------

_YAHOO_ROWS = [(date(2026, 1, 2), 10.0, 0.0), (date(2026, 1, 3), 10.0, 0.50)]
_FAILING = ("PSKY", "WBD", "QRVO", "CCO")


class _CaptureLogger:
    def __init__(self):
        self.events = []

    def info(self, event, **kw):
        self.events.append((event, kw))

    def warning(self, event, **kw):
        self.events.append((event, kw))


def _run_yahoo_writer(instruments, failing, threshold, monkeypatch):
    """Run the writer over `instruments` with Yahoo failing for `failing` symbols and
    threshold.dividend.max_failure_fraction read as `threshold`. Returns (writer, conn, logs)."""

    async def fetch(symbol):
        if symbol in failing:
            return [], "too few daily rows"
        return list(_YAHOO_ROWS), None

    monkeypatch.setattr(
        dividend_event_writer, "yahoo", SimpleNamespace(fetch_daily_close_and_dividends=fetch)
    )
    writer = dividend_event_writer.DividendEventWriter(
        "postgresql://unused",
        None,
        [dividend_event_writer.SOURCE_YAHOO],
        None,
        [i.symbol for i in instruments],
    )
    logs = _CaptureLogger()
    writer.logger = logs
    conn = FakeDividendConn(
        {}, apr_extra={"threshold.dividend.max_failure_fraction": str(threshold)}
    )
    monkeypatch.setattr(
        dividend_event_writer,
        "get_active_contracts",
        lambda settings, dimension: list(instruments),
    )
    asyncio.run(writer.execute(FakePool(conn)))
    return writer, conn, logs


def test_minority_symbol_failures_complete_partial(monkeypatch):
    """4 dead/thin names of 1,529 (the 2026-10-16 nightly condition): the pass is kept, the
    run completes with a partial status, and each failed name is logged with its reason."""
    names = [f"N{i:04d}" for i in range(1525)] + list(_FAILING)
    instruments = [_equity(symbol) for symbol in names]
    writer, conn, logs = _run_yahoo_writer(instruments, set(_FAILING), 0.05, monkeypatch)
    assert writer.completion_status == "partial"
    failed_lines = [
        kw for event, kw in logs.events if event == "dividend_event_writer.symbol_failed"
    ]
    assert {kw["symbol"] for kw in failed_lines} == set(_FAILING)
    assert all(kw["reason"] == "too few daily rows" for kw in failed_lines)
    summary = [kw for event, kw in logs.events if event == "dividend_event_writer.partial_run"]
    assert summary == [
        {
            "failed_symbols": 4,
            "symbols": 1529,
            "failure_fraction": round(4 / 1529, 6),
            "max_failure_fraction": 0.05,
        }
    ]
    # The healthy names' events were written, not discarded with the failed pass.
    assert conn.events[("N0000", "yahoo")] == {
        _YAHOO_ROWS[1][0]: (_YAHOO_ROWS[1][2], _YAHOO_ROWS[0][1])
    }


def test_failures_above_the_threshold_exit_nonzero(monkeypatch):
    instruments = [_equity(f"N{i:03d}") for i in range(60)] + [_equity(s) for s in _FAILING]
    with pytest.raises(RuntimeError, match="exceeds"):
        _run_yahoo_writer(instruments, set(_FAILING), 0.05, monkeypatch)


def test_failure_fraction_at_the_threshold_is_partial_not_failure(monkeypatch):
    """4 of 80 is exactly 0.05: the run exits nonzero only when the fraction exceeds it."""
    instruments = [_equity(f"N{i:03d}") for i in range(76)] + [_equity(s) for s in _FAILING]
    writer, _conn, _logs = _run_yahoo_writer(instruments, set(_FAILING), 0.05, monkeypatch)
    assert writer.completion_status == "partial"


def test_threshold_is_read_from_the_apr(monkeypatch):
    """A zero tolerance read from the APR turns a single failed name into a nonzero exit."""
    with pytest.raises(RuntimeError, match="exceeds"):
        _run_yahoo_writer([_equity("JPM"), _equity("PSKY")], {"PSKY"}, 0.0, monkeypatch)
