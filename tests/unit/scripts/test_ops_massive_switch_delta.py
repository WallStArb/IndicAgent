"""The Massive switch expected delta and loss classifier (todo 600 step 7): pure tests."""

from __future__ import annotations

from datetime import date

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
