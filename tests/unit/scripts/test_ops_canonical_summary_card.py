"""The canonical summary card's file half (todo 600 step 7): pure, no database."""

from __future__ import annotations

import argparse

import pytest

from scripts.ops.bars.ops_canonical_summary_card import (
    _month_start,
    compare_cards,
    main,
    read_card,
    totals,
    write_csv_gz,
)


def _row(month, n=10, digest="7", tf="5m", symbol="AAA", vendor="alpaca", kind="sip_rth"):
    return {
        "timeframe": tf,
        "symbol": symbol,
        "vendor": vendor,
        "kind": kind,
        "month": month,
        "n": n,
        "digest": digest,
    }


def test_identical_cards_inside_the_window_compare_clean():
    rows = [_row("2015-12-01", vendor="ibkr", kind="named"), _row("2016-01-01")]
    changed_before_window = [_row("2015-12-01", vendor="massive", kind="sip_flat_adj"), rows[1]]
    report = compare_cards(rows, changed_before_window, "2016-01-01", None)
    assert report["n_differences"] == 0
    assert report["groups_before"] == report["groups_after"] == 1


def test_a_digest_count_or_vendor_change_inside_the_window_is_listed():
    before = [_row("2016-01-01"), _row("2016-02-01"), _row("2016-03-01")]
    after = [
        _row("2016-01-01", digest="8"),
        _row("2016-02-01", n=11),
        _row("2016-03-01", vendor="massive", kind="sip_flat_adj"),
    ]
    report = compare_cards(before, after, "2016-01-01", None)
    assert report["n_differences"] == 4  # the vendor move is a missing plus an extra group
    assert report["differences_by_timeframe"] == {"5m": 4}
    keys = {tuple(d["key"]) for d in report["differences"]}
    assert ("5m", "AAA", "alpaca", "sip_rth", "2016-03-01") in keys
    assert ("5m", "AAA", "massive", "sip_flat_adj", "2016-03-01") in keys


def test_the_window_end_is_exclusive():
    report = compare_cards(
        [_row("2026-11-01")], [_row("2026-11-01", digest="9")], "2016-01-01", "2026-11-01"
    )
    assert report["n_differences"] == 0


def test_round_trip_and_deterministic_bytes(tmp_path):
    rows = [_row("2016-01-01"), _row("2016-01-01", tf="1d", n=21)]
    first = write_csv_gz(tmp_path / "canonical_5m.csv.gz", rows[:1])
    again = write_csv_gz(tmp_path / "again.csv.gz", rows[:1])
    assert first == again
    write_csv_gz(tmp_path / "canonical_1d.csv.gz", rows[1:])
    read = read_card(tmp_path)
    assert sorted(r["timeframe"] for r in read) == ["1d", "5m"]
    assert totals(read) == {"1d|alpaca|sip_rth": 21, "5m|alpaca|sip_rth": 10}


def test_compare_cli_exits_nonzero_on_a_difference(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    write_csv_gz(tmp_path / "b" / "canonical_5m.csv.gz", [_row("2016-01-01")])
    write_csv_gz(tmp_path / "a" / "canonical_5m.csv.gz", [_row("2016-01-01", digest="1")])
    argv = ["--compare", str(tmp_path / "b"), str(tmp_path / "a"), "--from", "2016-01-01"]
    assert main(argv) == 1
    write_csv_gz(tmp_path / "a" / "canonical_5m.csv.gz", [_row("2016-01-01")])
    assert main(argv) == 0


def test_window_bounds_must_be_month_starts():
    assert _month_start("2016-01-01") == "2016-01-01"
    with pytest.raises(argparse.ArgumentTypeError):
        _month_start("2016-01-04")


def test_expected_differences_are_reported_apart_and_do_not_fail():
    before = [_row("2019-05-01", tf="1d", symbol="CTVA"), _row("2019-05-01", tf="1d")]
    after = [
        _row("2019-05-01", tf="1d", symbol="CTVA", digest="x"),
        _row("2019-05-01", tf="1d", digest="y"),
    ]
    report = compare_cards(before, after, "2016-01-01", None, expected=[("1d", "CTVA")])
    assert report["n_differences"] == 1
    assert [d["key"][1] for d in report["expected_differences"]] == ["CTVA"]
    assert [d["key"][1] for d in report["differences"]] == ["AAA"]
