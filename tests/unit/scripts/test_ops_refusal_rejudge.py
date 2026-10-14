"""ops_refusal_rejudge.py: one outcome per retired-path refused load, judged on the vendor's own
values (second review of plan 191-07, finding 2). Fakes only, no database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from scripts.ops.bars import ops_refusal_rejudge as rj
from scripts.ops.bars import ops_selection_gate as gate

IBKR = ("ibkr", "named")
ALPACA = ("alpaca", "sip_rth")
DAY = datetime(2026, 9, 23, 13, 30, tzinfo=UTC)
REFUSED_AT = datetime(2026, 10, 12, 23, 23, tzinfo=UTC)
SETTLE = timedelta(minutes=30)


def _v(close=10.0, volume=100):
    return (9.0, 11.0, 8.5, close, volume)


def _load(load_id, outcome, at):
    return gate.LoadFact(
        load_id,
        "ibkr",
        date(2026, 9, 1),
        date(2026, 10, 13),
        outcome,
        at,
        "market_data_ohlcv",
        "ibkr-history-fetch",
    )


def _request(at, end=None):
    return gate.RequestFact("ibkr", DAY - timedelta(days=1), end or at, at - timedelta(seconds=1))


def _inputs(offer, canon, *, loads=None, requests=None, revisions=None, slot_loads=None, ends=()):
    loads = loads or [_load("R", "refused", REFUSED_AT)]
    return rj.SeriesInputs(
        "ADM",
        loads,
        requests if requests is not None else {"R": _request(REFUSED_AT)},
        {},
        {"R": offer},
        revisions or {},
        canon,
        slot_loads or {},
        sorted(ends),
    )


def _slots(n):
    return [DAY + timedelta(minutes=5 * i) for i in range(n)]


def _decide(inputs, min_stored=10):
    return rj.decide_series(inputs, max_ratio=0.02, min_stored=min_stored, settle=SETTLE)


def test_a_load_the_retired_path_refused_against_alpaca_is_accepted_on_the_vendors_own_values():
    stamps = _slots(60)
    # canonical held Alpaca on 50 slots (not IBKR's own) and IBKR on 10, all equal to the offer
    canon = {ts: (ALPACA, _v(11.0)) for ts in stamps[:50]}
    canon.update({ts: (IBKR, _v()) for ts in stamps[50:]})
    decision = _decide(_inputs({ts: _v() for ts in stamps}, canon))
    (judgement,) = decision.judgements
    assert (judgement.outcome, judgement.n_stored, judgement.n_new) == (rj.ACCEPTED, 10, 50)
    assert all(decision.target[ts].values == _v() for ts in stamps) and not decision.pending


def test_a_refused_load_holds_every_differing_offer_new_bars_included():
    stamps = _slots(20)
    canon = {ts: (IBKR, _v()) for ts in stamps[:10]}
    offer = {ts: _v() for ts in stamps}
    offer[stamps[0]] = _v(10.5)  # one own restatement of ten stored: 10 % > 2 %
    decision = _decide(_inputs(offer, canon))
    assert decision.judgements[0].outcome == rj.HELD
    # raw keeps the stored value and nothing where the vendor stored nothing of its own
    assert decision.target[stamps[0]].values == _v()
    assert all(decision.target[ts] is None for ts in stamps[10:])
    assert set(decision.pending["R"]) == {stamps[0], *stamps[10:]}
    assert {r["reason"] for r in decision.reserve} == {"no raw row: the vendor's offer is held"}


def test_a_held_offer_with_more_volume_than_raw_is_listed_for_a_re_serve():
    ts = datetime(2026, 10, 12, 19, 55, tzinfo=UTC)  # ADM: 380,459 kept, 380,759 held
    stamps = [ts - timedelta(minutes=5 * i) for i in range(10)]
    canon = {s: (IBKR, _v()) for s in stamps}
    canon[ts] = (IBKR, _v(80.43, 380459))
    offer = {s: _v(10.1) for s in stamps}
    offer[ts] = _v(80.43, 380759)
    decision = _decide(_inputs(offer, canon))
    assert decision.judgements[0].outcome == rj.HELD
    reasons = {r["timestamp"]: r["reason"] for r in decision.reserve}
    assert "incomplete" in reasons[ts.isoformat()]


def test_a_later_serve_of_the_exact_key_supersedes_a_held_offer_and_dates_do_not():
    stamps = _slots(20)
    canon = {ts: (IBKR, _v()) for ts in stamps}
    offer = {ts: _v(10.5) for ts in stamps}
    later = _load("A", "applied", REFUSED_AT + timedelta(minutes=1))
    window = gate.RequestFact("ibkr", stamps[0], stamps[9] + timedelta(minutes=5), later.loaded_at)
    inputs = _inputs(
        offer,
        canon,
        loads=[_load("R", "refused", REFUSED_AT), later],
        requests={"R": _request(REFUSED_AT), "A": window},
    )
    decision = _decide(inputs)
    # the first ten were answered again (window holds them): no hold; the rest stay held
    assert set(decision.pending["R"]) == set(stamps[10:])
    assert decision.target[stamps[0]].source == "serve A"


def test_an_offered_bar_that_straddles_its_request_end_is_never_stored_or_held():
    stamps = _slots(12)
    canon = {ts: (IBKR, _v()) for ts in stamps[:11]}
    end = stamps[11] + timedelta(minutes=2)  # the request ended inside the last bar
    inputs = _inputs(
        {ts: _v() for ts in stamps},
        canon,
        requests={"R": gate.RequestFact("ibkr", DAY, end, REFUSED_AT - timedelta(seconds=1))},
    )
    decision = _decide(inputs)
    assert decision.partial["R"] == [stamps[11]]
    assert decision.target[stamps[11]] is None and decision.judgements[0].n_partial == 1


def test_plan_writes_withdraws_restores_restamps_and_releases():
    a, b, c = _slots(3)
    decision = rj.SeriesDecision("ADM")
    decision.target = {
        a: None,
        b: rj.Event(REFUSED_AT, _v(), "offer R", REFUSED_AT),
        c: rj.Event(REFUSED_AT, _v(), "offer R", REFUSED_AT),
    }
    raw = {a: (_v(1.0), None, None), b: (_v(2.0), None, None), c: (_v(), REFUSED_AT, None)}
    plan = rj.plan_writes(decision, raw, {"R": {a}}, set(), {c: "R"})
    assert plan.withdraw == {a: _v(1.0)} and set(plan.write) == {b}
    assert plan.restamp == {c: REFUSED_AT} and plan.release == {"R": [a]}
