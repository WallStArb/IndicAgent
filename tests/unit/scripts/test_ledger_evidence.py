"""scripts/ops/bars/_ledger_evidence.py and the release decision of ops_pending_release.py
(third review of plan 191-07, finding 1; D-191-N). Fakes only, no database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from scripts.ops.bars import _ledger_evidence as ev
from scripts.ops.bars import ops_pending_release as rel

_AT = datetime(2026, 10, 12, 12, 14, 31, tzinfo=UTC)


def _load(outcome, at, load_id):
    return ev.LoadFact(
        load_id,
        "ibkr",
        date(2026, 10, 1),
        date(2026, 10, 31),
        outcome,
        at,
        "market_data_ohlcv",
        "ibkr-history-fetch",
    )


def test_a_load_takes_the_request_answered_just_before_it():
    at = datetime(2026, 10, 12, 12, 15, 17, 192000, tzinfo=UTC)
    load = _load("applied", at, load_id="G")
    late = _load("applied", at + timedelta(minutes=5), load_id="H")
    first = ev.RequestFact(
        "ibkr", at - timedelta(days=150), at - timedelta(days=1), at - timedelta(seconds=40)
    )
    near = ev.RequestFact(
        "ibkr", at - timedelta(days=300), at - timedelta(days=151), at - timedelta(milliseconds=46)
    )
    requests = [first, near, ev.RequestFact("alpaca", at, at, at)]
    assert ev.match_requests([load, late], requests, match_s=5) == {"G": near}


def _served_load(load_id, at, first, last, n_bars, n_new=0, outcome="applied"):
    return ev.LoadFact(
        load_id,
        "ibkr",
        first,
        last,
        outcome,
        at,
        "market_data_ohlcv",
        "ibkr-history-fetch",
        n_bars,
        n_new,
    )


def test_the_served_range_is_the_loads_own_bars_not_its_request_window():
    # ADM af8b35f1 / f40ff724 (third review of plan 191-07, finding 1): the request persisted
    # 20:10 to 00:05 (IBKR counts a seconds duration in trading seconds); its 48 bars are 16:00
    # to 19:55, the last 48 vendor keys before the asked end
    day = date(2026, 10, 12)
    keys = [datetime(2026, 9, 30, 19, 55, tzinfo=UTC)] + [
        datetime(2026, 10, 12, 16, 0, tzinfo=UTC) + timedelta(minutes=5 * i) for i in range(48)
    ]
    at = datetime(2026, 10, 13, 4, 27, 1, tzinfo=UTC)
    load = _served_load("F", at, day, day, 48, 48)
    request = ev.RequestFact(
        "ibkr",
        datetime(2026, 10, 12, 20, 10, tzinfo=UTC),
        datetime(2026, 10, 13, 0, 5, tzinfo=UTC),
        at - timedelta(milliseconds=1),
    )
    ranges = ev.served_ranges([load], [request], {"ibkr": keys}, 5)
    assert ranges == {"F": (keys[1], keys[-1] + timedelta(minutes=5))}
    # the keys do not end on the load's dates: no range is claimed
    wrong = _served_load("W", at, date(2026, 10, 11), day, 48, 48)
    assert ev.served_ranges([wrong], [request], {"ibkr": keys}, 5) == {}
    # fewer keys than the load's bars: no range
    assert ev.served_ranges([load], [request], {"ibkr": keys[:20]}, 5) == {}
    # no matched request: a single-date load whose bar count equals the date's keys
    assert ev.served_ranges([load], [], {"ibkr": keys}, 5) == ranges
    # per-row evidence wins over the reconstruction; refused loads never get a range
    rows = {"F": [keys[5], keys[9]]}
    assert ev.served_ranges([load], [request], {"ibkr": keys}, 5, row_stamps=rows) == {
        "F": (keys[5], keys[9] + timedelta(minutes=5))
    }
    refused = _served_load("R", at, day, day, 48, 0, outcome="refused")
    assert ev.served_ranges([refused], [request], {"ibkr": keys}, 5) == {}


def test_the_latest_answer_wins_and_an_older_offer_is_superseded():
    ts = datetime(2026, 10, 12, 19, 55, tzinfo=UTC)
    refused = datetime(2026, 10, 12, 23, 23, tzinfo=UTC)
    later = datetime(2026, 10, 13, 4, 27, tzinfo=UTC)
    offer = rel.Offer(ts, (1, 2, 0.5, 1.5, 380759), "R", refused)
    # ADM 19:55: raw holds the 04:27 answer; the 23:23 offer is superseded
    (d,) = rel.decide([offer], {ts: (1, 2, 0.5, 1.5, 380459)}, {ts: later})
    assert not d.release
    # a raw value older than the offer, of unknown age, or no raw row: the offer wins
    for raw, served in (
        ({ts: (1, 2, 0.5, 1.5, 1)}, {ts: refused - timedelta(days=1)}),
        ({ts: (1, 2, 0.5, 1.5, 1)}, {ts: None}),
        ({}, {}),
    ):
        (d,) = rel.decide([offer], raw, served)
        assert d.release
    # two offers at one key: only the latest can win
    older = rel.Offer(ts, (9, 9, 9, 9, 9), "Q", refused - timedelta(hours=1))
    first, second = rel.decide([older, offer], {}, {})
    assert (first.release, second.release) == (False, True)
