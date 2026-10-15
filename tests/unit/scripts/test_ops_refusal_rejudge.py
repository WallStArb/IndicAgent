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
    stamps = _slots(10)
    canon = {s: (IBKR, _v()) for s in stamps}
    canon[stamps[3]] = (IBKR, _v(10.0, 900))  # stored before the refusal, less volume
    offer = {s: _v(10.1) for s in stamps}
    offer[stamps[3]] = _v(10.0, 1000)
    decision = _decide(_inputs(offer, canon))
    assert decision.judgements[0].outcome == rj.HELD
    reasons = {r["timestamp"]: r["reason"] for r in decision.reserve}
    assert "incomplete" in reasons[stamps[3].isoformat()]


def test_a_key_a_later_load_first_wrote_is_not_stored_at_the_refusal():
    # ADM 898c4a50 (2026-10-12 23:23) was judged against 48 values f40ff724 first wrote at
    # 04:27 the next morning (third review of plan 191-07, finding 1)
    day = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)
    early = _slots(20)
    late = [day + timedelta(minutes=5 * i) for i in range(10)]
    canon = {ts: (IBKR, _v()) for ts in early + late}
    offer = {ts: _v() for ts in early}
    offer.update({ts: _v(10.3) for ts in late})  # would be 10 changed of 30 stored
    inserted = REFUSED_AT + timedelta(hours=5)
    later = _load("A", "applied", inserted)
    inputs = _inputs(
        offer,
        canon,
        loads=[_load("R", "refused", REFUSED_AT), later],
        requests={"R": _request(REFUSED_AT), "A": _request(inserted, end=inserted)},
    )
    inputs.first_written = {ts: inserted for ts in late}
    inputs.ranges = {"A": (late[0], late[-1] + timedelta(minutes=5))}
    decision = _decide(inputs)
    (judgement,) = decision.judgements
    assert (judgement.n_stored, judgement.n_changed, judgement.n_new) == (20, 0, 10)
    assert judgement.outcome == rj.ACCEPTED


def test_a_later_serve_answers_the_keys_it_served_before_its_request_window_start():
    # ADM af8b35f1 persisted 20:10 to 00:05 (trading-second duration) and served 16:00 to 19:55:
    # the served range, not the window, decides; the held offer is answered again and released
    day = datetime(2026, 10, 12, 16, 0, tzinfo=UTC)
    early = _slots(20)
    late = [day + timedelta(minutes=5 * i) for i in range(10)]
    canon = {ts: (IBKR, _v()) for ts in early}
    canon.update({ts: (IBKR, _v(10.2)) for ts in late})
    offer = {ts: _v(10.5) for ts in early + late}
    at = REFUSED_AT + timedelta(hours=5)
    window = gate.RequestFact(
        "ibkr", datetime(2026, 10, 12, 20, 10, tzinfo=UTC), at, at - timedelta(seconds=1)
    )
    inputs = _inputs(
        offer,
        canon,
        loads=[_load("R", "refused", REFUSED_AT), _load("A", "applied", at)],
        requests={"R": _request(REFUSED_AT), "A": window},
    )
    inputs.first_written = {ts: at for ts in late}
    inputs.ranges = {"A": (late[0], late[-1] + timedelta(minutes=5))}
    decision = _decide(inputs)
    assert decision.judgements[0].outcome == rj.HELD
    assert set(decision.pending["R"]) == set(early)
    assert all(decision.target[ts].source == "serve A" for ts in late)
    assert not {r["timestamp"] for r in decision.reserve} & {ts.isoformat() for ts in late}


def test_a_later_serve_of_the_exact_key_supersedes_a_held_offer_and_dates_do_not():
    stamps = _slots(20)
    canon = {ts: (IBKR, _v()) for ts in stamps}
    offer = {ts: _v(10.5) for ts in stamps}
    later = _load("A", "applied", REFUSED_AT + timedelta(minutes=1))
    # the request window claims the whole day; only its served range counts
    window = gate.RequestFact("ibkr", stamps[0], stamps[-1] + timedelta(minutes=5), later.loaded_at)
    inputs = _inputs(
        offer,
        canon,
        loads=[_load("R", "refused", REFUSED_AT), later],
        requests={"R": _request(REFUSED_AT), "A": window},
    )
    inputs.ranges = {"A": (stamps[0], stamps[9] + timedelta(minutes=5))}
    decision = _decide(inputs)
    # the first ten were answered again (served range holds them): no hold; the rest stay held
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


def test_the_stored_basis_falls_back_to_the_vendors_raw_row_when_canonical_moved():
    # session-level selection took ADM 2026-09-23 whole from Alpaca without a revision row:
    # the vendor's stored value is its raw row, unless a re-judge load wrote or withdrew it
    ts = DAY
    raw = {ts: (_v(), None, None)}
    canon_now = {ts: (ALPACA, _v(11.0))}
    assert rj._stored_basis(ts, {}, canon_now, raw, set()) == (IBKR, _v())
    assert rj._stored_basis(ts, {}, canon_now, raw, {ts}) == (ALPACA, _v(11.0))
    assert rj._stored_basis(ts, {}, {ts: (IBKR, _v(9.5))}, raw, set()) == (IBKR, _v(9.5))
    assert rj._stored_basis(ts, {ts: None}, canon_now, raw, set()) is None
