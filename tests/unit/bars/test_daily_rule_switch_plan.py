"""A8, the step 7 hard blocker: d2-v6 under the switch policy (runbook
docs/operations/massive-step7-runbook.md A8; owner ruling 2026-11-13, todo 600: IBKR removed).

The switch plan's row shapes (one stage): a Massive default [1990-01-01, archive_end) with no
fallback, Alpaca symbol rows over the identity gap spans clipped to [2016-01-04, archive_end)
with no fallback, and the Alpaca default [archive_end, open). The rule must read alpaca_era_start
from the archive end (never Alpaca's first day), never fall a gap row back to IBKR, fire the
zero-volume guard on Alpaca only, and serve nothing before Massive's archive start or on a
session its policy cannot answer."""

from __future__ import annotations

from datetime import UTC, date, datetime

from scripts.ops.bars.ops_massive_policy_plan import GapRow, defaults_for, gap_rows
from src.intelligence.bars.daily_rule import (
    PRIMARY_PAIR,
    PolicyRow,
    alpaca_era_start,
    derive_daily,
)
from src.intelligence.bars.derivation import Observation
from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START

ARCHIVE_END = date(2026, 11, 10)
_FETCHED = datetime(2026, 11, 12, 2, 0, tzinfo=UTC)


def _switch_policy(gap_spans: tuple[str, date, date] = ()) -> tuple[PolicyRow, ...]:
    """The one-stage switch rows, built through the plan module's own shape functions (the rows
    step 7b actually writes): defaults then gap rows clipped to [2016-01-04, archive_end), a
    span that clips to nothing making no row. Every row names no fallback."""
    gaps = [
        GapRow(symbol, "instrument", "gap_reason", start, stop) for symbol, start, stop in gap_spans
    ]
    dicts = [*defaults_for("1d", ARCHIVE_END), *gap_rows(gaps, ARCHIVE_END, {})]
    return tuple(
        PolicyRow(
            "1d",
            d.get("symbol"),
            date.fromisoformat(d["valid_from"]),
            date.fromisoformat(d["valid_to"]) if d["valid_to"] else None,
            "observed",
            d["primary"],
            d.get("fallback"),
        )
        for d in dicts
    )


def _obs(day: date, close: float, route: str, volume: int = 1000) -> Observation:
    return Observation(
        f"{route}-{day.isoformat()}",
        route,
        day,
        close,
        close,
        close,
        close,
        volume,
        _FETCHED,
        False,
    )


def _derive(observations, policy, symbol: str = "TEST"):
    return derive_daily(
        observations,
        list(policy),
        [],
        symbol=symbol,
        basis_window_sessions=1,
        basis_tolerance_bp=10.0,
    )


def test_alpaca_era_start_is_the_archive_end_even_with_gap_rows_present():
    # Risk 11: the era rule reads the first Alpaca default row, never the symbol rows; moving it
    # to Alpaca's first day (2016-01-04, where the gap rows start) would relabel every IBKR
    # fallback-era bar and misread the volume basis.
    rows = _switch_policy((("GAPX", date(2016, 1, 4), date(2016, 3, 31)),))
    assert alpaca_era_start(rows) == ARCHIVE_END
    assert [r.valid_from for r in rows if r.symbol is not None] == [date(2016, 1, 4)]
    assert alpaca_era_start(rows) != date(2016, 1, 4)


def test_each_era_serves_its_primary_identity_across_the_moved_era_start():
    cases = [
        (date(2026, 11, 9), "MASSIVE", PRIMARY_PAIR["massive"]),
        (date(2026, 11, 6), "MASSIVE", PRIMARY_PAIR["massive"]),
        (ARCHIVE_END, "ALPACA", PRIMARY_PAIR["alpaca"]),
        (date(2026, 11, 11), "ALPACA", PRIMARY_PAIR["alpaca"]),
    ]
    policy = _switch_policy()
    for day, route, identity in cases:
        result = _derive([_obs(day, 10.0, route)], policy)
        assert [(b.bar_date, b.vendor, b.kind) for b in result.bars] == [(day, *identity)]


def test_a_gap_span_serves_alpaca_only_and_never_falls_back():
    # Alpaca answers where it can inside the span; a silent session inside the span and a silent
    # session under the post-archive Alpaca default both record unserved_primary and never
    # invent an (ibkr, fallback) bar, though the IBKR witness answered both.
    alpaca_days = [date(2016, 1, 4), date(2016, 1, 5)]
    silent_in_span, silent_after = date(2016, 1, 6), date(2026, 11, 11)
    observations = [_obs(d, 10.0, "ALPACA") for d in alpaca_days] + [
        _obs(silent_in_span, 10.0, "SMART"),
        _obs(silent_after, 10.0, "SMART"),
    ]
    result = _derive(
        observations,
        _switch_policy((("GAPX", date(2016, 1, 4), date(2016, 3, 31)),)),
        symbol="GAPX",
    )
    assert [(b.bar_date, b.vendor, b.kind) for b in result.bars] == [
        (d, *PRIMARY_PAIR["alpaca"]) for d in alpaca_days
    ]
    assert result.unserved_primary == [silent_in_span, silent_after]
    assert result.zero_volume == [] and result.zero_volume_fallback == []
    assert not any(b.vendor == "ibkr" for b in result.bars)


def test_a_gap_span_ending_before_alpacas_first_day_makes_no_row_and_serves_nothing():
    # The clipping drops the span entirely (start >= stop): those sessions are a gap, the IBKR
    # witness is never admitted, and the session records unserved under the Massive default.
    policy = _switch_policy((("OLDY", date(2005, 1, 1), date(2010, 12, 31)),))
    assert [r.symbol for r in policy] == [None, None]
    result = _derive([_obs(date(2008, 6, 5), 10.0, "SMART")], policy, symbol="OLDY")
    assert result.bars == []
    assert result.unserved_primary == [date(2008, 6, 5)]


def test_nothing_is_served_before_massives_archive_start():
    # Massive answers only from its archive start; an IBKR witness answer in 1998 is recorded
    # unserved, never served, and the first canonical bar is the archive start itself.
    first_sessions = [MASSIVE_ARCHIVE_START, date(2003, 9, 11)]
    observations = [_obs(d, 10.0, "MASSIVE") for d in first_sessions]
    observations.append(_obs(date(1998, 6, 5), 10.0, "SMART"))
    result = _derive(observations, _switch_policy())
    assert [b.bar_date for b in result.bars] == first_sessions
    assert result.unserved_primary == [date(1998, 6, 5)]
    assert not any(b.vendor == "ibkr" for b in result.bars)


def test_the_zero_volume_guard_fires_only_on_alpaca():
    # A zero-volume Massive bar is served (the guard is Alpaca-only); a zero-volume Alpaca bar
    # is dropped and, the switch policy naming no fallback, no bar reaches the session and no
    # IBKR fallback is invented. (A session whose only answer was the dropped placeholder also
    # leaves the axis, so unserved_primary does not record it: pre-existing d2-v6 behavior,
    # raised for the lead's ruling, not pinned here either way.)
    massive_day, alpaca_day = date(2026, 11, 9), ARCHIVE_END
    result = _derive(
        [
            _obs(massive_day, 10.0, "MASSIVE", volume=0),
            _obs(alpaca_day, 10.0, "ALPACA", volume=0),
        ],
        _switch_policy(),
    )
    assert [(b.bar_date, b.vendor, b.kind) for b in result.bars] == [
        (massive_day, *PRIMARY_PAIR["massive"])
    ]
    assert result.zero_volume == [alpaca_day]
    assert alpaca_day not in {b.bar_date for b in result.bars}
    assert result.zero_volume_fallback == []
