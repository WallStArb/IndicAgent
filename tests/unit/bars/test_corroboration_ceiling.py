"""D-11: cross-symbol corroboration must not clear a print beyond the ceiling.

The 2010-05-06 Flash Crash stub prints (26 bars) and EWW 2006-11-07 were wrongly
cleared to MARKET_EVENT by corroboration that ignored magnitude. corroborated_verdict
closes that defect: a CONFIRMED_CORRUPT verdict whose max_ratio exceeds
threshold.bar_scrub.corroboration_max_clearable_ratio (2.5, seeded below the 10.0
magnitude threshold) can never be cleared, however many symbols corroborate it.
"""

from __future__ import annotations

import re
from dataclasses import replace

import numpy as np

from src.intelligence.bars.scrub_rules import (
    ScrubParams,
    SymbolBars,
    corroborated_verdict,
    count_corroborating,
    run_rules,
)
from src.intelligence.statistics.price_sanity import CandidateVerdict
from tests.unit.bars._builders import load_dry_run_report, seeded_apr, three_bar_window


def _params() -> ScrubParams:
    return ScrubParams.from_apr(seeded_apr(), "1d")


def _confirmed_verdict(row: dict) -> CandidateVerdict:
    """Classify a report row through run_rules and return its raw verdict."""
    window, middle = three_bar_window(row)
    bars = SymbolBars(symbol=row["symbol"], tf="1d", **window)
    result = run_rules(bars, _params())
    verdicts = dict(result.price_sanity_candidates)
    verdict = verdicts.get(middle)
    assert verdict is not None and verdict.verdict == "CONFIRMED_CORRUPT", (
        row["symbol"],
        row["timestamp"],
        verdict,
    )
    return verdict


def test_all_27_market_event_rows_stay_confirmed_corrupt():
    rows = load_dry_run_report("MARKET_EVENT")
    assert len(rows) == 27
    params = _params()
    for row in rows:
        verdict = _confirmed_verdict(row)
        # The report's reason carries the TOTAL corroborated symbol count
        # (subject + others); passing it as n_corroborating is the conservative
        # direction for this assertion and is what the plan prescribes.
        n = int(re.search(r"n=(\d+)", row["reason"]).group(1))
        cleared = corroborated_verdict(
            verdict,
            n,
            min_symbols=params.min_symbols,
            max_clearable_ratio=params.corroboration_max_clearable_ratio,
        )
        assert cleared.verdict == "CONFIRMED_CORRUPT", (row["symbol"], row["timestamp"])


def test_ceiling_still_downgrades_small_prints():
    params = _params()
    base = _confirmed_verdict(load_dry_run_report("CONFIRMED_CORRUPT")[0])
    small = replace(base, max_ratio=2.0)
    cleared = corroborated_verdict(
        small,
        5,
        min_symbols=params.min_symbols,
        max_clearable_ratio=params.corroboration_max_clearable_ratio,
    )
    assert cleared.verdict == "MARKET_EVENT"
    assert cleared.reason == "cross_symbol_corroborated_n=6"

    exactly_at_ceiling = replace(base, max_ratio=params.corroboration_max_clearable_ratio)
    at_limit = corroborated_verdict(
        exactly_at_ceiling,
        5,
        min_symbols=params.min_symbols,
        max_clearable_ratio=params.corroboration_max_clearable_ratio,
    )
    assert at_limit.verdict == "MARKET_EVENT"

    just_above = replace(base, max_ratio=3.0)
    blocked = corroborated_verdict(
        just_above,
        5,
        min_symbols=params.min_symbols,
        max_clearable_ratio=params.corroboration_max_clearable_ratio,
    )
    assert blocked.verdict == "CONFIRMED_CORRUPT"

    too_few_symbols = corroborated_verdict(
        small,
        0,
        min_symbols=params.min_symbols,
        max_clearable_ratio=params.corroboration_max_clearable_ratio,
    )
    assert too_few_symbols.verdict == "CONFIRMED_CORRUPT"


def test_non_confirmed_verdicts_pass_through_unchanged():
    params = _params()
    base = _confirmed_verdict(load_dry_run_report("CONFIRMED_CORRUPT")[0])
    ambiguous = replace(base, verdict="AMBIGUOUS")
    out = corroborated_verdict(
        ambiguous,
        26,
        min_symbols=params.min_symbols,
        max_clearable_ratio=params.corroboration_max_clearable_ratio,
    )
    assert out is ambiguous


def test_count_corroborating_counts_other_symbols_within_window():
    window_seconds = 60 * 60  # alpha.quant.cross_symbol_corroboration.window_minutes
    candidates = {
        "AAA": np.array([1_000_000], dtype=np.int64),
        "BBB": np.array([1_000_000], dtype=np.int64),
        "CCC": np.array([1_000_030], dtype=np.int64),
        "DDD": np.array([1_000_000 + 10 * window_seconds], dtype=np.int64),
    }
    counts = count_corroborating(candidates, window_seconds)
    assert counts[("AAA", 1_000_000)] == 2
    assert counts[("BBB", 1_000_000)] == 2
    assert counts[("CCC", 1_000_030)] == 2  # 30 s away is inside the window
    assert counts[("DDD", 1_000_000 + 10 * window_seconds)] == 0


def test_count_corroborating_counts_symbols_not_bars():
    # Two candidates on ONE other symbol within the window still count once.
    window_seconds = 60
    candidates = {
        "AAA": np.array([1_000], dtype=np.int64),
        "BBB": np.array([1_000, 1_030], dtype=np.int64),
    }
    counts = count_corroborating(candidates, window_seconds)
    assert counts[("AAA", 1_000)] == 1
    assert counts[("BBB", 1_000)] == 1
    assert counts[("BBB", 1_030)] == 1
