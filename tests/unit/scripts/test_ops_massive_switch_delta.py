"""The Massive switch expected delta and loss classifier (todo 600 step 7): pure tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from scripts.ops.bars.ops_massive_policy_plan import GapRow
from scripts.ops.bars.ops_massive_switch_delta import (
    DELTA_FIELDS,
    Group,
    Identity,
    classify_loss,
    month_bounds,
    summarize,
    tally,
)

END = date(2026, 11, 10)
IDENTITY = Identity(
    gaps={"GAP": [GapRow("GAP", "span", "before_first_event", date(2003, 9, 10), None)]},
    spans={"OK": [(date(2003, 9, 10), None)], "OLD": [(date(2003, 9, 10), None)]},
    listing_end={"OLD": date(2010, 6, 30)},
)


def test_a_lost_slot_takes_the_first_cause_in_the_declared_order():
    assert classify_loss(IDENTITY, "GAP", date(2010, 1, 4), zero=True) == "gap_list"
    assert classify_loss(IDENTITY, "OLD", date(2011, 1, 3), zero=True) == "after_listing_end"
    assert classify_loss(IDENTITY, "OK", date(2011, 1, 3), zero=True) == "zero_volume"
    assert classify_loss(IDENTITY, "NOSPAN", date(2011, 1, 3), zero=False) == "no_ticker_span"
    assert classify_loss(IDENTITY, "OK", date(2011, 1, 3), zero=False) == "unexplained"


def test_the_tally_counts_every_slot_once_under_the_switch_policy():
    groups = [
        Group("OK", date(2002, 5, 1), "ibkr", False, True, False, 7),  # pre-start: leaves
        Group("OK", date(2010, 5, 3), "ibkr", False, True, True, 10),  # moves to Massive
        Group("OK", date(2020, 5, 4), "alpaca", False, True, True, 20),  # moves to Massive
        Group("OK", date(2020, 5, 5), None, False, False, True, 3),  # Massive gains
        Group("OK", date(2020, 5, 6), "alpaca", False, True, False, 2),  # lost: unexplained
        Group("NOSPAN", date(2010, 5, 3), "ibkr", False, True, False, 4),  # lost: mapping hole
        Group("GAP", date(2010, 5, 3), "ibkr", False, True, False, 5),  # gap before 2016: lost
        Group("GAP", date(2020, 5, 4), "alpaca", False, True, False, 6),  # Alpaca gap row keeps
        Group("GAP", date(2020, 5, 5), "ibkr", False, True, False, 1),  # gap row, no fallback
        Group("OK", date(2026, 11, 11), "alpaca", False, True, False, 8),  # after the end: kept
        Group("OK", date(2026, 11, 12), "ibkr", False, True, False, 9),  # after the end: leaves
    ]
    row, losses = tally(groups, "1d", date(2020, 5, 1), END, IDENTITY)
    assert row["before"] == 7 + 10 + 20 + 2 + 4 + 5 + 6 + 1 + 8 + 9
    assert (row["pre_start"], row["massive"], row["gained"]) == (7, 33, 3)
    assert (row["moved_ibkr"], row["moved_alpaca"]) == (10, 20)
    assert (row["lost_alpaca"], row["lost_ibkr"]) == (2, 9)
    assert (row["gap_alpaca"], row["gap_other"]) == (6, 1)
    assert (row["after_end_alpaca"], row["after_end_other"]) == (8, 9)
    assert row["expected_after"] == 33 + 6 + 8
    every = sum(
        row[k]
        for k in (
            "pre_start",
            "moved_ibkr",
            "moved_alpaca",
            "lost_alpaca",
            "lost_ibkr",
            "gap_alpaca",
            "gap_other",
            "after_end_alpaca",
            "after_end_other",
        )
    )
    assert every == row["before"]  # each canonical slot lands in exactly one bucket
    assert sorted((r["symbol"], r["cause"], r["slots"]) for r in losses) == [
        ("GAP", "gap_list", 5),
        ("NOSPAN", "no_ticker_span", 4),
        ("OK", "unexplained", 2),
    ]
    assert set(row) == set(DELTA_FIELDS)


def test_summarize_counts_slots_sessions_and_names_per_cause():
    losses = [
        {"timeframe": "5m", "symbol": "A", "cause": "gap_list", "slots": 78},
        {"timeframe": "5m", "symbol": "A", "cause": "gap_list", "slots": 77},
        {"timeframe": "5m", "symbol": "B", "cause": "zero_volume", "slots": 1},
    ]
    assert summarize(losses) == {
        "5m": {
            "gap_list": {"slots": 155, "name_sessions": 2, "names": 1},
            "zero_volume": {"slots": 1, "name_sessions": 1, "names": 1},
        }
    }


def test_month_bounds_roll_over_the_year():
    lo, hi = month_bounds(date(2025, 12, 1))
    assert (lo.date(), hi.date()) == (date(2025, 12, 1), date(2026, 1, 1))


def test_verify_checks_counts_ibkr_and_the_gap_row_alpaca_groups():
    from scripts.ops.bars.ops_massive_switch_delta import verify

    def card(tf, sym, vendor, month, n, digest="d"):
        return {"timeframe": tf, "symbol": sym, "vendor": vendor, "kind": "k", "month": month,
                "n": n, "digest": digest}  # fmt: skip

    before = [
        card("1d", "GAP", "alpaca", "2020-05-01", 21),
        card("1d", "GAP", "ibkr", "2020-05-01", 2),
    ]
    deltas = [{"timeframe": "1d", "month": "2020-05-01", "expected_after": "121"}]
    good = [
        card("1d", "GAP", "alpaca", "2020-05-01", 21),
        card("1d", "OK", "massive", "2020-05-01", 100),
    ]
    assert verify(before, good, deltas, IDENTITY, END)["ok"]
    bad = [
        card("1d", "GAP", "alpaca", "2020-05-01", 21, "x"),
        card("1d", "OK", "ibkr", "2020-05-01", 100),
    ]
    report = verify(before, bad, deltas, IDENTITY, END)
    assert not report["ok"] and report["ibkr_rows_left"] == ["1d:OK"]
    assert len(report["gap_row_groups_changed"]) == 1
    short = verify(before, good[:1], deltas, IDENTITY, END)
    assert short["count_failures"] == [
        {"timeframe": "1d", "month": "2020-05-01", "expected": 121, "got": 21}
    ]


def test_verify_wants_every_before_card_month_and_fails_an_unpredicted_one():
    # The months wanted are the union of the before card's months and the delta rows': a month
    # canonical never held but the rebuild fills is a delta row and passes at its expectation;
    # a month the after card holds that delta skipped fails as expected-zero, never silently.
    from scripts.ops.bars.ops_massive_switch_delta import verify

    def card(tf, sym, month, n, digest="d"):
        return {"timeframe": tf, "symbol": sym, "vendor": "massive", "kind": "k",
                "month": month, "n": n, "digest": digest}  # fmt: skip

    filled = [card("1d", "OK", "2010-05-01", 30)]
    deltas = [{"timeframe": "1d", "month": "2010-05-01", "expected_after": "30"}]
    assert verify([], filled, deltas, IDENTITY, END)["ok"]
    unpredicted = filled + [card("1d", "NEW", "2011-06-01", 5)]
    report = verify([], unpredicted, deltas, IDENTITY, END)
    assert not report["ok"]
    assert {
        "timeframe": "1d",
        "month": "2011-06-01",
        "expected": 0,
        "got": 5,
    } in report["count_failures"]
    skipped = [card("1d", "OLD", "2020-05-01", 4)]
    report = verify(skipped, filled, deltas, IDENTITY, END)
    assert not report["ok"]


def test_an_out_of_session_stamp_cannot_inflate_expected_after():
    # 5m keeps only the regular-hours grid stamps selection can take (the same filter
    # selection applies to sip_flat_agg); 08:30 New York is off grid, 09:35 is on it. 1d has
    # no stamp grid.
    from scripts.ops.bars.ops_massive_switch_delta import month_params, month_sql

    grid = month_params("5m", date(2016, 1, 1))["grid"]
    assert datetime(2016, 1, 4, 13, 30, tzinfo=UTC) not in grid  # 08:30 New York
    assert datetime(2016, 1, 4, 14, 35, tzinfo=UTC) in grid  # 09:35 New York
    assert "ANY(%(grid)s)" in month_sql("5m")
    assert "grid" not in month_params("1d", date(2016, 1, 1))
    assert "ANY(%(grid)s)" not in month_sql("1d")


def test_a_stamp_just_after_utc_midnight_buckets_by_its_utc_month_not_its_new_york_session():
    # 2016-07-01 00:15 UTC is the June 30 late session in New York: the card buckets by UTC
    # month, so both join sides are scoped by the stamp and nothing re-filters by the session
    # date (a 1d New York midnight stamp shares its stamp's UTC date).
    from scripts.ops.bars.ops_massive_switch_delta import month_params, month_sql

    stamp = datetime(2016, 7, 1, 0, 15, tzinfo=UTC)
    for month, inside in ((date(2016, 6, 1), False), (date(2016, 7, 1), True)):
        params = month_params("5m", month)
        assert (params["lo"] <= stamp < params["hi"]) is inside
        sql = month_sql("5m")
        assert "lo_day" not in sql and "hi_day" not in sql and "raw_lo" not in sql
        midnight = datetime(2016, 7, 1, 4, 0, tzinfo=UTC)
        params = month_params("1d", month)
        assert (params["lo"] <= midnight < params["hi"]) is inside
        sql = month_sql("1d")
        assert "lo_day" not in sql and "hi_day" not in sql and "raw_lo" not in sql
