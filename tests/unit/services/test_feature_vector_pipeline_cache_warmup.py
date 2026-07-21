"""Regression test for todo 159 — FeatureCache not warmed from seeded bar history.

_get_cache() used to create a brand-new, fully-cold FeatureCache() on first access even
when self._bar_history already had real buffered history (from _seed_bar_history_from_db()
at startup, or simply prior bars appended earlier in the process). above_wk_vwap started
from its dataclass default instead of reflecting the true week-to-date volume-weighted
price, silently wrong for up to ~7 days per restart (until the next ISO week boundary).

hmm_duration is deliberately NOT warmed the same way (see _get_cache()'s docstring) --
replaying its unconditional += 1.0 across buffered history would fabricate a plausibly-large
duration instead of a real bars-since-last-regime-change count, which isn't recoverable
without re-running HMM classification retroactively. It stays cold (0.0), matching the
already-documented, self-correcting-at-next-regime-change behavior.
"""

from datetime import UTC, datetime

from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.schemas.bar_message import BarMessage, SessionType
from tests.unit.pipeline.pipeline_helpers import make_agent


def _bar(ts: datetime, *, high: float, low: float, close: float, volume: int = 1000) -> BarMessage:
    return BarMessage(
        ts=ts,
        symbol="SPY",
        tf="1m",
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=SOURCE_IBKR_NAMED,
        session_type=SessionType.RTH,
    )


def test_get_cache_warms_above_wk_vwap_from_seeded_history():
    """A newly created cache must reflect already-buffered history, not start cold."""
    agent = make_agent()

    # Monday 2026-03-23, same ISO week. Two seeded bars with a clear upward typical-price
    # drift so a warmed cache's above_wk_vwap differs from a cold cache's dataclass default.
    ts1 = datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC)
    ts2 = datetime(2026, 3, 23, 14, 31, 0, tzinfo=UTC)
    ts3 = datetime(2026, 3, 23, 14, 32, 0, tzinfo=UTC)

    bar1 = _bar(ts1, high=100.0, low=98.0, close=98.5)  # typical 98.83 -> below
    bar2 = _bar(ts2, high=101.0, low=99.0, close=99.5)  # typical 99.83 -> below
    bar3 = _bar(ts3, high=105.0, low=103.0, close=104.9)  # the "current" bar, not warmed from

    agent._bar_history.append(bar1)
    agent._bar_history.append(bar2)
    agent._bar_history.append(bar3)

    cache = agent._get_cache("SPY", "1m")

    # Warmed from bar1 + bar2 only (bar3 excluded -- it's the bar currently being
    # processed and gets its own advance_bar() call elsewhere). above_wk_vwap is set on
    # the LAST warm-up call (bar2): cumulative wk_vwap after bar1+bar2 is
    # (98.833*1000 + 99.833*1000) / 2000 = 99.333, and bar2's own close (99.5) > that,
    # so above_wk_vwap ends warm-up at 1.0. bar3's close (104.9) plays no part here.
    assert cache.above_wk_vwap == 1.0, (
        "above_wk_vwap must reflect the seeded bar1/bar2 history immediately on cache "
        "creation, not the dataclass default (todo 159) -- got the cold-cache value, "
        "meaning warm-up did not run"
    )


def test_get_cache_does_not_warm_hmm_duration():
    """hmm_duration must stay cold (0.0) -- see module docstring for why."""
    agent = make_agent()

    ts1 = datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC)
    ts2 = datetime(2026, 3, 23, 14, 31, 0, tzinfo=UTC)
    bar1 = _bar(ts1, high=100.0, low=98.0, close=99.0)
    bar2 = _bar(ts2, high=101.0, low=99.0, close=100.0)

    agent._bar_history.append(bar1)
    agent._bar_history.append(bar2)

    cache = agent._get_cache("SPY", "1m")

    assert cache.hmm_duration == 0.0, (
        "hmm_duration must NOT be warmed from buffered history -- replaying its "
        "unconditional increment would fabricate a duration instead of a real "
        "bars-since-last-regime-change count"
    )


def test_get_cache_warmup_resets_at_iso_week_boundary():
    """Bars from a prior ISO week in the buffer must not leak into the current week's sum."""
    agent = make_agent()

    # Sunday 2026-03-22 23:59 UTC (ISO week 12) vs Monday 2026-03-23 14:30 UTC (ISO week 13).
    prior_week_bar = _bar(
        datetime(2026, 3, 22, 23, 59, 0, tzinfo=UTC), high=500.0, low=490.0, close=495.0
    )
    this_week_bar = _bar(
        datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC), high=100.0, low=98.0, close=99.5
    )
    current_bar = _bar(
        datetime(2026, 3, 23, 14, 31, 0, tzinfo=UTC), high=101.0, low=99.0, close=100.0
    )

    agent._bar_history.append(prior_week_bar)
    agent._bar_history.append(this_week_bar)
    agent._bar_history.append(current_bar)

    cache = agent._get_cache("SPY", "1m")

    # If the prior week's bar (typical ~495) leaked in, above_wk_vwap comparisons would be
    # dominated by it. Confirm the accumulator reset by checking the internal sum only
    # reflects this_week_bar's magnitude, not a blend including the ~495 level.
    assert cache._wk_year_week == (2026, 13), "warm-up must land on the current ISO week"
    typical_this_week = (100.0 + 98.0 + 99.5) / 3.0
    assert (
        abs(cache._wk_tp_vol_sum / cache._wk_vol_sum - typical_this_week) < 1e-6
    ), "the prior ISO week's bar must not contribute to the warmed accumulator"
