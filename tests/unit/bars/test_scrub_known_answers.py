"""D-10 known-answer tests for the price_sanity scrub rule (pure, no database).

Every dry-run row (the 2026-09-26 report of
scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --tf 1d) and every legacy
confirmed_corrupt 1d row (price_sanity_status_rows.csv) is rebuilt as a three-bar
window and run through run_rules. These tests are the gate that must pass before
plan 10 runs the rules over research data. Known disagreements are asserted by
symbol and timestamp, never silently skipped.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.intelligence.bars.scrub_rules import (
    RULE_VERSION,
    ScrubParams,
    SymbolBars,
    is_quarantine,
    run_rules,
)
from tests.unit.bars._builders import load_dry_run_report, seeded_apr, three_bar_window

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "fixtures" / "bars"

# The one recorded known disagreement (tests/fixtures/bars/README.md): FXY's legacy
# confirmed_corrupt status predates the current classifier; with its live neighbors
# its max_ratio is 9.94, just under the 10.0 magnitude threshold, so the current
# price_sanity rule says PLAUSIBLE. It stays quarantined through the
# legacy_price_sanity_status flag migration 381 copied in (plan 04).
_FXY_2008_09_24 = ("FXY", "2008-09-24T00:00:00Z")


def _params(tf: str = "1d") -> ScrubParams:
    return ScrubParams.from_apr(seeded_apr(), tf)


def _run(row: dict, *, tf: str = "1d"):
    window, middle = three_bar_window(row)
    bars = SymbolBars(symbol=row["symbol"], tf=tf, **window)
    return run_rules(bars, _params(tf)), middle


def _quarantine_flags(result, middle: int, params: ScrubParams):
    return [f for f in result.flags if f.index == middle and is_quarantine(f, params)]


def test_rule_version_is_pinned():
    assert RULE_VERSION == "scrub-v1"


def test_all_45_confirmed_corrupt_rows_quarantined():
    rows = load_dry_run_report("CONFIRMED_CORRUPT")
    assert len(rows) == 45
    quarantined = 0
    for row in rows:
        result, middle = _run(row)
        params = _params()
        ps_flags = [f for f in result.flags if f.rule == "price_sanity" and f.index == middle]
        assert len(ps_flags) == 1, (row["symbol"], row["timestamp"], result.flags)
        expected_fields = tuple(row["implausible_fields"].split(","))
        assert ps_flags[0].fields == expected_fields, row["symbol"]
        assert is_quarantine(ps_flags[0], params)
        if _quarantine_flags(result, middle, params):
            quarantined += 1
        # The synthetic flat neighbors must never themselves be quarantined.
        for flag in result.flags:
            if flag.index != middle:
                assert not is_quarantine(flag, params), (row["symbol"], flag)
    assert quarantined == 45


def test_none_of_the_1864_ambiguous_rows_quarantined():
    rows = load_dry_run_report("AMBIGUOUS")
    assert len(rows) == 1864
    params = _params()
    for row in rows:
        result, middle = _run(row)
        assert not _quarantine_flags(result, middle, params), (
            row["symbol"],
            row["timestamp"],
        )
        # AMBIGUOUS is not a flag, but it is a recorded candidate (non-PLAUSIBLE).
        assert middle in {i for i, _ in result.price_sanity_candidates}


def _load_legacy_confirmed_1d() -> list[dict]:
    with (_FIXTURE_DIR / "price_sanity_status_rows.csv").open(newline="") as handle:
        rows = []
        for raw in csv.DictReader(handle):
            if raw["price_sanity_status"] != "confirmed_corrupt":
                continue
            if raw["timeframe"] != "1d":
                continue
            rows.append(
                {
                    "symbol": raw["symbol"],
                    "timestamp": raw["timestamp"],
                    "open": float(raw["open"]),
                    "high": float(raw["high"]),
                    "low": float(raw["low"]),
                    "close": float(raw["close"]),
                    "volume": float(raw["volume"]),
                    "prev_close": float(raw["prev_close"]) if raw["prev_close"] else None,
                    "next_open": float(raw["next_open"]) if raw["next_open"] else None,
                }
            )
    return rows


def test_all_15_legacy_confirmed_corrupt_1d_rows_quarantined_or_recorded():
    rows = _load_legacy_confirmed_1d()
    assert len(rows) == 15
    skipped: list[tuple[str, str, str]] = []
    disagreements: list[tuple[str, str]] = []
    quarantined = 0
    for row in rows:
        if row["prev_close"] is None or row["next_open"] is None:
            skipped.append((row["symbol"], row["timestamp"], "missing neighbor column"))
            continue
        result, middle = _run(row)
        params = _params()
        if _quarantine_flags(result, middle, params):
            quarantined += 1
        else:
            disagreements.append((row["symbol"], row["timestamp"]))
    assert skipped == []  # zero silent skips
    assert quarantined == 14
    assert disagreements == [_FXY_2008_09_24]
