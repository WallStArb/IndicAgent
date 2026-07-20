"""Unit tests for price-sanity classification and cross-symbol corroboration (todo 149/151).

Pure-function tests for CandidateVerdict, classify_candidate_bar,
apply_cross_symbol_downgrade, and build_subject_key -- no DB, no asyncpg connection.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.intelligence.statistics.price_sanity import (
    CandidateVerdict,
    apply_cross_symbol_downgrade,
    build_subject_key,
    classify_candidate_bar,
    count_corroborating_symbols_batch,
)


class TestClassifyCandidateBar:
    def test_uup_corrupt_print_confirmed(self) -> None:
        # The exact UUP 2007-06-20 19:00 row from todo 148/151: open/high corrupted
        # to 1000, low/close still consistent with neighbors (~25-29), neighbors
        # agree closely with each other (25.07 vs 24.08).
        verdict = classify_candidate_bar(
            open_=1000.0,
            high=1000.0,
            low=28.97,
            close=28.97,
            prev_close=25.07,
            next_open=24.08,
        )
        assert verdict.verdict == "CONFIRMED_CORRUPT"
        assert "open" in verdict.implausible_fields
        assert "high" in verdict.implausible_fields
        assert "low" not in verdict.implausible_fields
        assert "close" not in verdict.implausible_fields
        assert verdict.reason == "isolated_spike_neighbors_agree"

    def test_plausible_bar_ruled_plausible(self) -> None:
        verdict = classify_candidate_bar(
            open_=25.0,
            high=25.5,
            low=24.8,
            close=25.2,
            prev_close=25.0,
            next_open=25.3,
        )
        assert verdict.verdict == "PLAUSIBLE"
        assert verdict.implausible_fields == ()

    def test_no_prev_close_is_ambiguous(self) -> None:
        verdict = classify_candidate_bar(
            open_=1000.0,
            high=1000.0,
            low=28.97,
            close=28.97,
            prev_close=None,
            next_open=24.08,
        )
        assert verdict.verdict == "AMBIGUOUS"
        assert verdict.reason == "insufficient_neighbor_data"
        assert verdict.neighbor_ratio is None

    def test_no_next_open_is_ambiguous(self) -> None:
        verdict = classify_candidate_bar(
            open_=1000.0,
            high=1000.0,
            low=28.97,
            close=28.97,
            prev_close=25.07,
            next_open=None,
        )
        assert verdict.verdict == "AMBIGUOUS"
        assert verdict.reason == "insufficient_neighbor_data"

    def test_implausible_but_neighbors_disagree_is_ambiguous(self) -> None:
        # Neighbors themselves are 10x apart (untrustworthy reference) -- even
        # though the bar is implausible relative to the average, we cannot
        # confidently call it corrupt vs. a genuine continuation of a already-
        # volatile move.
        verdict = classify_candidate_bar(
            open_=500.0,
            high=520.0,
            low=490.0,
            close=495.0,
            prev_close=5.0,
            next_open=50.0,
        )
        assert verdict.verdict == "AMBIGUOUS"
        assert verdict.reason == "implausible_but_neighbors_disagree"
        assert verdict.implausible_fields != ()

    def test_boundary_magnitude_exactly_at_threshold_counts_as_implausible(self) -> None:
        # reference = (10 + 10) / 2 = 10; open = 100 -> ratio exactly 10.0 (the
        # default magnitude_threshold) -- >= is inclusive.
        verdict = classify_candidate_bar(
            open_=100.0,
            high=10.0,
            low=10.0,
            close=10.0,
            prev_close=10.0,
            next_open=10.0,
            magnitude_threshold=10.0,
        )
        assert verdict.verdict == "CONFIRMED_CORRUPT"
        assert "open" in verdict.implausible_fields

    def test_custom_thresholds_respected(self) -> None:
        # Same bar as the boundary test, but a stricter (lower) magnitude
        # threshold of 5.0 -- ratio 10.0 clears it easily.
        verdict = classify_candidate_bar(
            open_=100.0,
            high=10.0,
            low=10.0,
            close=10.0,
            prev_close=10.0,
            next_open=10.0,
            magnitude_threshold=5.0,
        )
        assert verdict.verdict == "CONFIRMED_CORRUPT"

        # With a looser (higher) threshold of 20.0, ratio 10.0 no longer counts.
        verdict_loose = classify_candidate_bar(
            open_=100.0,
            high=10.0,
            low=10.0,
            close=10.0,
            prev_close=10.0,
            next_open=10.0,
            magnitude_threshold=20.0,
        )
        assert verdict_loose.verdict == "PLAUSIBLE"


def test_apply_cross_symbol_downgrade_leaves_non_confirmed_verdicts_unchanged():
    ambiguous = CandidateVerdict(
        verdict="AMBIGUOUS",
        implausible_fields=("open",),
        max_ratio=15.0,
        neighbor_ratio=3.0,
        reason="implausible_but_neighbors_disagree",
    )
    result = apply_cross_symbol_downgrade(ambiguous, n_corroborating_symbols=10, min_symbols=4)
    assert result is ambiguous


def test_apply_cross_symbol_downgrade_below_threshold_stays_confirmed_corrupt():
    confirmed = CandidateVerdict(
        verdict="CONFIRMED_CORRUPT",
        implausible_fields=("open", "high"),
        max_ratio=40.0,
        neighbor_ratio=1.02,
        reason="isolated_spike_neighbors_agree",
    )
    # n_corroborating_symbols=2 other symbols + self = 3, min_symbols=4 -> not enough
    result = apply_cross_symbol_downgrade(confirmed, n_corroborating_symbols=2, min_symbols=4)
    assert result.verdict == "CONFIRMED_CORRUPT"
    assert result is confirmed


def test_apply_cross_symbol_downgrade_at_threshold_becomes_market_event():
    confirmed = CandidateVerdict(
        verdict="CONFIRMED_CORRUPT",
        implausible_fields=("open", "high", "low", "close"),
        max_ratio=142.0,
        neighbor_ratio=1.01,
        reason="isolated_spike_neighbors_agree",
    )
    # n_corroborating_symbols=3 other symbols + self = 4, min_symbols=4 -> corroborated
    result = apply_cross_symbol_downgrade(confirmed, n_corroborating_symbols=3, min_symbols=4)
    assert result.verdict == "MARKET_EVENT"
    assert result.implausible_fields == confirmed.implausible_fields
    assert result.max_ratio == confirmed.max_ratio
    assert "cross_symbol_corroborated_n=4" in result.reason


class TestBuildSubjectKey:
    def test_format(self) -> None:
        key = build_subject_key("UUP", "5m", "2007-06-20T19:00:00Z")
        assert key == "symbol=UUP|tf=5m|ts=2007-06-20T19:00:00Z"


def _mock_pool_with_rows(rows: list[dict]) -> AsyncMock:
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=rows)
    return pool


def test_count_corroborating_symbols_batch_window_mode_not_implemented():
    """match_mode is a required, explicit parameter with no default -- 'window' is not
    implemented in this plan (forward_return_writer.py's existing window-mode
    corroboration pass is not refactored onto this primitive here, see the plan's
    Global Constraints). Calling with 'window' must fail loudly, not silently no-op
    or silently fall back to 'exact' -- a silent mode substitution is exactly how
    both prior corroboration bugs happened."""
    pool = _mock_pool_with_rows([])
    with pytest.raises(NotImplementedError, match="window"):
        asyncio.run(
            count_corroborating_symbols_batch(
                pool,
                candidates=[("UUP", "5m", "2007-06-20T19:05:00+00:00")],
                match_mode="window",
                magnitude_threshold=10.0,
                neighbor_agreement_threshold=2.0,
                window_minutes=60,
            )
        )


def test_count_corroborating_symbols_batch_flash_crash_cluster():
    """Reproduces the live 2010-05-06 Flash Crash cluster shape (6 symbols, exact
    shared timestamp for raw bars -- todo 151's own established precedent for why
    raw-bar corroboration uses exact match, unlike forward_returns' derived,
    staggered scales) -- all 6 must corroborate each other, batched in ONE query
    regardless of candidate count."""
    ts = "2010-05-06T18:45:00+00:00"
    crash_symbols = ["CWB", "ITA", "RSP", "VTV", "VUG", "VYM"]
    rows = [
        {
            "symbol": s,
            "tf": "5m",
            "bar_ts": ts,
            "open": 10.0,
            "high": 10.5,
            "low": 0.05,  # implausible low on every symbol -- the crash's shape
            "close": 10.2,
            "prev_close": 10.3,
            "next_open": 10.25,
        }
        for s in crash_symbols
    ]
    pool = _mock_pool_with_rows(rows)
    candidates = [(s, "5m", ts) for s in crash_symbols]

    result = asyncio.run(
        count_corroborating_symbols_batch(
            pool,
            candidates=candidates,
            match_mode="exact",
            magnitude_threshold=10.0,
            neighbor_agreement_threshold=2.0,
        )
    )

    assert pool.fetch.call_count == 1  # one batched query, not one per candidate
    for symbol in crash_symbols:
        # 6 symbols total, each corroborated by the OTHER 5 (excludes itself)
        assert result[(symbol, "5m", ts)] == 5


def test_count_corroborating_symbols_batch_isolated_corruption_excludes_self():
    """A single isolated corrupt print (no other symbol implausible nearby) must
    corroborate to 0, not 1 -- the subject's own row must be excluded from its own
    count."""
    ts = "2007-06-20T19:05:00+00:00"
    rows = [
        {
            "symbol": "UUP",
            "tf": "5m",
            "bar_ts": ts,
            "open": 1000.0,
            "high": 1000.0,
            "low": 1000.0,
            "close": 1000.0,
            "prev_close": 28.97,
            "next_open": 24.08,
        }
    ]
    pool = _mock_pool_with_rows(rows)

    result = asyncio.run(
        count_corroborating_symbols_batch(
            pool,
            candidates=[("UUP", "5m", ts)],
            match_mode="exact",
            magnitude_threshold=10.0,
            neighbor_agreement_threshold=2.0,
        )
    )

    assert result[("UUP", "5m", ts)] == 0
