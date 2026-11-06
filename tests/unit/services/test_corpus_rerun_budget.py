"""The corpus rerun's disk budget (186-31): span planner, peak terms, re-projection, unit guard.

Synthetic counts: 12,000 5m rows a year over 2010-2019 (1,000 a month) in symbol chunk 0, one
stored byte per row, so a span's uncompressed intraday bytes equal its rows. Each test switches
one term on and shows it moves the answer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from services.corpus_rerun_budget import (
    STAGE_1D,
    BudgetInputs,
    DiskGuardRefused,
    RowCounts,
    SpanPlanRefused,
    UnitDiskGuard,
    chunk_floor,
    format_peaks,
    overflowing,
    plan_spans,
    project,
    split_years,
)

_DAY = timedelta(days=1)
_YEARS = range(2010, 2020)


def _counts(per_month: int = 1000, daily: int = 0, chunks: int = 1) -> RowCounts:
    cells = {}
    for chunk in range(chunks):
        for year in _YEARS:
            for month in range(1, 13):
                cells[("5m", chunk, date(year, month, 1))] = per_month
                if daily:
                    cells[("1d", chunk, date(year, month, 1))] = daily
    return RowCounts(cells)


def _inputs(**overrides) -> BudgetInputs:
    """Limit 30,000 bytes; compressed bytes, the WAL, spools and straddles all near zero."""
    values = {
        "free_bytes_at_launch": 100_000,
        "max_disk_fraction": 0.3,
        "bytes_per_row": 1.0,
        "compression_ratio": 1e12,
        "stored_bytes_per_spool_byte": 1e12,
        "wal_bytes": 0,
        "chunk_interval": _DAY,  # Jan 1 is day aligned: no straddling chunk
    }
    values.update(overrides)
    return BudgetInputs(**values)


def _jan1(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


def test_plan_spans_returns_the_smallest_fitting_span_count():
    plan = plan_spans(_counts(), _inputs())
    # four spans need a three-year span (36,000 > 30,000); five two-year spans fit (24,000)
    assert len(plan.spans) == 5
    assert plan.spans[0] == (_jan1(2010), _jan1(2012)) and plan.spans[-1][1] == _jan1(2020)
    assert all(a[1] == b[0] for a, b in zip(plan.spans, plan.spans[1:]))  # a partition
    assert max(p.total for p in plan.peaks) <= plan.limit_bytes
    four = split_years(_counts(), 4)
    assert overflowing(project(four, _counts(), _inputs()), _inputs())


def test_plan_spans_refuses_when_no_count_fits_and_names_the_candidates():
    with pytest.raises(SpanPlanRefused, match="no span count fits") as refused:
        plan_spans(_counts(), _inputs(max_disk_fraction=0.11))  # 11,000 < one year's 12,000
    assert "n=10" in str(refused.value)


def test_the_wal_term_moves_the_span_count():
    # 24,000 + 7,000 > 30,000: every span must be a single year (12,000 + 7,000)
    plan = plan_spans(_counts(), _inputs(wal_bytes=7_000))
    assert len(plan.spans) == 10
    assert {p.wal for p in plan.peaks} == {7_000}


def test_the_straddling_chunk_moves_the_span_count():
    """360-day chunks: the chunk crossing a span's start carries the previous span's rows
    uncompressed into the next span's peak."""
    base = _inputs(max_disk_fraction=0.25)  # 25,000: five two-year spans fit without straddle
    assert len(plan_spans(_counts(), base).spans) == 5
    straddling = _inputs(max_disk_fraction=0.25, chunk_interval=timedelta(days=360))
    plan = plan_spans(_counts(), straddling)
    assert len(plan.spans) > 5
    later = [p for p in plan.peaks if p.step not in (STAGE_1D, "s1")]
    assert later and all(p.straddle > 0 for p in later)
    # the straddle is exactly the previous span's rows inside the chunk holding the start
    start = plan.spans[1][0]
    floor = chunk_floor(start, timedelta(days=360))
    assert plan.peaks[2].straddle == pytest.approx(_counts().rows(floor, start, ("5m",)))


def test_the_compressed_rest_and_the_1d_rows_count_in_every_peak():
    inputs = _inputs(compression_ratio=4.0, max_disk_fraction=0.9)
    counts = _counts(daily=10)
    spans = split_years(counts, 5)
    peaks = project(spans, counts, inputs)
    assert peaks[0].step == STAGE_1D
    assert peaks[0].daily_uncompressed == pytest.approx(10 * 12 * 10)  # every 1d row, uncompressed
    # span 3 sits on the compressed rows of spans 1 and 2 (48,000 rows / 4) and their 1d rows
    assert peaks[3].compressed_rest == pytest.approx(48_000 / 4)
    assert peaks[3].daily_compressed == pytest.approx(10 * 12 * 4 / 4)
    assert peaks[3].daily_uncompressed == pytest.approx(10 * 12 * 6)


def test_the_largest_group_spool_is_one_symbol_chunk_of_one_tf():
    inputs = _inputs(stored_bytes_per_spool_byte=0.5, max_disk_fraction=0.99)
    counts = _counts(chunks=2)
    spans = split_years(counts, 10)
    peaks = project(spans, counts, inputs)
    # one chunk's year of 5m (12,000 rows) at 2 spool bytes per row
    assert peaks[1].spool == pytest.approx(24_000)
    assert peaks[1].intraday == pytest.approx(24_000)


def test_reprojecting_fixed_spans_with_a_larger_bytes_per_row_names_the_overflowing_span():
    plan = plan_spans(_counts(), _inputs())
    heavier = _inputs(bytes_per_row=1.3)  # 24,000 rows x 1.3 = 31,200 > 30,000
    over = overflowing(project(plan.spans, _counts(), heavier), heavier)
    assert [p.step for p in over] == ["s1", "s2", "s3", "s4", "s5"]
    assert "OVER" in format_peaks(project(plan.spans, _counts(), heavier), heavier.limit_bytes)


def test_month_counts_are_pro_rated_by_days_when_a_bound_cuts_them():
    counts = RowCounts({("5m", 0, date(2020, 1, 1)): 31_000})
    lo, hi = datetime(2020, 1, 17, tzinfo=UTC), datetime(2020, 3, 1, tzinfo=UTC)
    assert counts.rows(lo, hi, ("5m",)) == pytest.approx(15_000)
    assert counts.rows(lo, hi, ("1h",)) == 0


def test_chunk_floor_is_epoch_aligned_like_timescaledb():
    interval = timedelta(days=360)
    floor = chunk_floor(_jan1(2020), interval)
    assert floor <= _jan1(2020) < floor + interval
    assert (floor - datetime(1970, 1, 1, tzinfo=UTC)) % interval == timedelta(0)


def test_split_years_refuses_more_spans_than_years():
    assert split_years(_counts(), 11) is None
    assert split_years(RowCounts({}), 1) is None


# ---------------------------------------------------------------------------
# UnitDiskGuard
# ---------------------------------------------------------------------------


def _guard(free_now: int, **overrides) -> UnitDiskGuard:
    values = {
        "free_bytes_at_launch": 1000,
        "max_disk_fraction": 0.7,
        "reserve_bytes": 100,
        "wal_bytes": 50,
        "stored_bytes_per_spool_byte": 0.5,
        "free_bytes": lambda: free_now,
    }
    values.update(overrides)
    return UnitDiskGuard(**values)


def test_the_guard_passes_a_unit_inside_both_limits():
    _guard(free_now=700).check(spool_bytes=200)  # growth 300 + 100 + 50 <= 700; 700-150 >= 100


def test_the_guard_refuses_growth_past_the_fraction_limit_with_the_numbers():
    with pytest.raises(DiskGuardRefused) as refused:
        _guard(free_now=400).check(spool_bytes=200)  # growth 600 + 100 + 50 > 700
    detail = refused.value.detail
    assert detail["breached"] == "fraction_limit"
    assert detail["growth_since_launch_bytes"] == 600 and detail["projected_unit_bytes"] == 100


def test_the_guard_refuses_a_unit_that_would_cut_into_the_reserve():
    with pytest.raises(DiskGuardRefused) as refused:
        _guard(free_now=900, reserve_bytes=800).check(spool_bytes=200)  # 900 - 150 < 800
    assert refused.value.detail["breached"] == "reserve"


def test_the_guard_uses_the_largest_ratio_measured_so_far():
    guard = _guard(free_now=700)
    guard.observe(0.2)
    assert guard.stored_bytes_per_spool_byte == 0.5  # never below the seed
    guard.observe(2.0)
    with pytest.raises(DiskGuardRefused):
        guard.check(spool_bytes=200)  # now 400 projected: growth 300 + 400 + 50 > 700
