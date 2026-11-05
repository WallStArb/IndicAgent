"""The corpus rerun data gate (186-32): continuity per name-year on the exchange calendar.

The fetch layer is replaced by in-memory fakes that answer from a fixture of bars, policy rows and
empty-history spans; everything between the fetches (calendar, eras, tallies, holds, evaluate)
runs as in production on the real NYSE calendar. The SQL itself is exercised by the live dry run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

import services.corpus_rerun_data_gate as gate
from services.corpus_rerun_apr import CorpusRerunApr
from src.core.market_calendar import get_market_calendar
from src.intelligence.bars.daily_rule import PolicyRow

NYSE = get_market_calendar()
ERA = date(2016, 1, 4)
HORIZON = datetime(2016, 3, 1, tzinfo=UTC)
APR = CorpusRerunApr(
    max_disk_fraction=0.7,
    disk_reserve_bytes=0,
    bytes_per_row_uncompressed=1379,
    compression_ratio=6.0,
    stored_bytes_per_spool_byte=0.37,
    max_missing_session_fraction=0.01,
    max_missing_1d_session_fraction=0.01,
    min_session_bar_fraction=0.9,
    blocking_timers=(),
)


def _policy(tf: str, lo: date, hi: date | None, primary: str, symbol: str | None = None):
    return PolicyRow(tf, symbol, lo, hi, "batch", primary, None)


def _default_policy(era: date = ERA) -> list[PolicyRow]:
    return [
        _policy("5m", date(1990, 1, 1), era, "ibkr"),
        _policy("5m", era, None, "alpaca"),
        _policy("1d", date(1990, 1, 1), era, "ibkr"),
        _policy("1d", era, None, "alpaca"),
    ]


def _sessions(lo: date, hi: date) -> list[date]:
    return [
        lo + timedelta(days=i)
        for i in range((hi - lo).days)
        if NYSE.is_trading_day("NYSE", lo + timedelta(days=i))
    ]


def _full(day: date) -> int:
    open_ts, close_ts = NYSE.session_bounds("NYSE", day)
    return int((close_ts - open_ts) / timedelta(minutes=5))


def _span(symbol: str, tf: str, provider: str, lo: date, hi: date) -> gate.EmptySpan:
    return gate.EmptySpan(symbol, tf, provider, lo, lo, hi)


@dataclass
class Fixture:
    """One gate world: names with proven starts, 1d bars, 5m bars per (vendor, kind)."""

    starts: dict[str, date] = field(default_factory=dict)
    names: list[str] = field(default_factory=list)
    policy: list[PolicyRow] = field(default_factory=_default_policy)
    days_1d: dict[str, set[date]] = field(default_factory=dict)
    bars_5m: dict[tuple[str, str, str, date], int] = field(default_factory=dict)
    spans: list[gate.EmptySpan] = field(default_factory=list)
    session_ids: dict[str, str] = field(default_factory=dict)

    def add_name(self, symbol: str, start: date, *, full: bool = True) -> None:
        """A name whose every session from start to the horizon has its 1d bar and, when full,
        all its 5m bars from the era's primary."""
        self.names.append(symbol)
        self.starts[symbol] = start
        days = _sessions(start, HORIZON.date())
        self.days_1d[symbol] = set(days)
        if full:
            for day in days:
                vendor, kind = ("ibkr", "named") if day < ERA else ("alpaca", "sip_rth")
                self.bars_5m[(symbol, vendor, kind, day)] = _full(day)

    def drop_5m(self, symbol: str, lo: date, hi: date) -> None:
        for key in [k for k in self.bars_5m if k[0] == symbol and lo <= k[3] < hi]:
            del self.bars_5m[key]

    def run(self, monkeypatch, apr: CorpusRerunApr = APR) -> gate.DataGateResult:
        universe = [
            SimpleNamespace(
                symbol=s,
                session_id=self.session_ids.get(s, "nyse"),
                exchange="SMART",
                asset_class="etf",
            )
            for s in self.names
        ]
        monkeypatch.setattr(gate, "get_active_contracts", lambda settings, dimension: universe)
        monkeypatch.setattr(
            gate,
            "proven_starts",
            lambda conn, names: {
                s: datetime.combine(d, datetime.min.time(), tzinfo=UTC)
                for s, d in self.starts.items()
                if s in names
            },
        )
        monkeypatch.setattr(
            gate, "fetch_policy", lambda conn, tf: [r for r in self.policy if r.timeframe == tf]
        )

        def spans(conn, tf):
            out: dict = {}
            for s in self.spans:
                if s.timeframe == tf:
                    out.setdefault((s.symbol, s.provider), ())
                    out[(s.symbol, s.provider)] += (s,)
            return out

        monkeypatch.setattr(gate, "fetch_empty_spans", spans)

        def counts_1d(conn, segments, days, horizon):
            calendar = set(days)
            out: dict = {}
            for symbol, segs in segments.items():
                for seg in segs:
                    for day in self.days_1d.get(symbol, ()):
                        if day in calendar and seg.lo <= day < seg.hi:
                            key = (symbol, day.year, seg.era)
                            out[key] = out.get(key, 0) + 1
            return out

        monkeypatch.setattr(gate, "fetch_1d_counts", counts_1d)
        monkeypatch.setattr(
            gate,
            "fetch_pre_calendar_1d",
            lambda conn, names, first: {
                s: sum(d < first for d in self.days_1d.get(s, ())) for s in names
            },
        )

        def bars(conn, vendor, kind, segments, sessions):
            days = {x.day for x in sessions}
            for (symbol, v, k, day), n in sorted(self.bars_5m.items()):
                if (v, k) != (vendor, kind) or day not in days:
                    continue
                if any(
                    (seg.vendor, seg.kind) == (vendor, kind) and seg.lo <= day < seg.hi
                    for seg in segments.get(symbol, ())
                ):
                    yield symbol, day, n

        monkeypatch.setattr(gate, "iter_5m_session_bars", bars)
        return gate.run_data_gate(None, None, apr, horizon=HORIZON)


def _failing(result: gate.DataGateResult) -> set[tuple[str, int]]:
    return {(f.symbol, f.year) for f in result.failing_name_years}


# --------------------------------------------------------------------------- continuity


def test_complete_history_passes_with_the_survivorship_caveat(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2015, 11, 2))
    result = world.run(monkeypatch)
    assert result.ok
    assert result.caveat["code"] == "survivorship_pre2016_ibkr_5m"
    assert result.caveat["source"] == "todo 534 owner decision 2026-11-04"
    assert "survivorship-biased" in result.caveat["text"]
    pre_era = len(_sessions(date(2015, 11, 2), ERA))
    assert result.caveat["counts"] == {
        "names_with_1d_before_alpaca_era": 1,
        "names_pre_era_all_5m": 1,
        "names_pre_era_partly_empty_history": 0,
        "pre_era_sessions_by_5m": pre_era,
        "pre_era_sessions_by_empty_history": 0,
    }
    assert result.eras["ibkr/named"].sessions == pre_era
    assert result.eras["alpaca/sip_rth"].names_at_depth == 1
    record = result.as_record()
    assert record["horizon"] == "2016-03-01T00:00:00+00:00"
    assert record["eras"]["ibkr/named"]["covered_5m"] == pre_era


def test_mid_history_hole_fails_though_the_first_5m_bar_is_at_the_1d_start(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2015, 11, 2))
    world.drop_5m("AAA", date(2015, 12, 7), date(2015, 12, 12))  # five sessions
    result = world.run(monkeypatch)
    assert not result.ok
    assert result.caveat is None
    assert _failing(result) == {("AAA", 2015)}
    failing = result.failing_name_years[0]
    assert (failing.missing_5m, failing.partial_5m, failing.missing_1d) == (5, 0, 0)
    assert result.eras["ibkr/named"].missing_sessions == 5


def test_hole_inside_an_empty_history_span_of_the_era_vendor_passes(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2015, 11, 2))
    world.drop_5m("AAA", date(2015, 12, 7), date(2015, 12, 12))
    # The span also covers Dec 3 and 4, which hold their bars: those count as covered by 5m.
    world.spans.append(_span("AAA", "5m", "ibkr", date(2015, 12, 3), date(2015, 12, 11)))
    result = world.run(monkeypatch)
    assert result.ok
    counts = result.eras["ibkr/named"]
    assert (counts.covered_empty, counts.missing_sessions, counts.partial_sessions) == (5, 0, 0)
    assert counts.covered_5m == counts.sessions - 5
    assert result.caveat["counts"]["names_pre_era_partly_empty_history"] == 1
    assert result.caveat["counts"]["pre_era_sessions_by_empty_history"] == 5


def test_span_of_another_vendor_does_not_cover_a_hole(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2015, 11, 2))
    world.drop_5m("AAA", date(2016, 2, 1), date(2016, 2, 6))
    world.spans.append(_span("AAA", "5m", "ibkr", date(2016, 2, 1), date(2016, 2, 5)))
    result = world.run(monkeypatch)
    assert _failing(result) == {("AAA", 2016)}
    assert result.eras["alpaca/sip_rth"].missing_sessions == 5


def test_hole_within_the_tolerance_passes(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2015, 1, 2))
    world.drop_5m("AAA", date(2015, 6, 1), date(2015, 6, 3))  # 2 of 252 sessions
    assert world.run(monkeypatch).ok
    tight = CorpusRerunApr(**{**APR.__dict__, "max_missing_session_fraction": 0.0})
    assert not world.run(monkeypatch, tight).ok


def test_alpaca_era_hole_fails(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.drop_5m("AAA", date(2016, 2, 8), date(2016, 2, 13))
    result = world.run(monkeypatch)
    assert _failing(result) == {("AAA", 2016)}
    assert result.eras["alpaca/sip_rth"].missing_sessions == 5
    assert "ibkr/named" not in result.eras


def test_era_boundary_follows_the_policy_rows(monkeypatch):
    """Moving the Alpaca 5m era to Feb 1 makes January IBKR's (vendor, kind): the fixture's
    Alpaca January bars no longer count, and its absent IBKR January bars are missing."""
    world = Fixture(policy=_default_policy(date(2016, 2, 1)))
    world.add_name("AAA", date(2016, 1, 4))
    result = world.run(monkeypatch)
    assert result.alpaca_5m_era_start == date(2016, 2, 1)
    january = len(_sessions(date(2016, 1, 4), date(2016, 2, 1)))
    assert result.eras["ibkr/named"].missing_sessions == january
    assert result.eras["alpaca/sip_rth"].covered_5m == len(
        _sessions(date(2016, 2, 1), HORIZON.date())
    )


def test_symbol_policy_row_beats_the_default():
    rows = _default_policy() + [_policy("5m", date(2016, 1, 4), None, "ibkr", symbol="AAA")]
    segs = gate.five_minute_segments(
        [r for r in rows if r.timeframe == "5m"], "AAA", date(2015, 6, 1), date(2016, 6, 1), ERA
    )
    # IBKR inside the Alpaca era serves as (ibkr, fallback), so the pair depends on era_start.
    assert [(s.lo, s.hi, s.era) for s in segs] == [
        (date(2015, 6, 1), ERA, "ibkr/named"),
        (ERA, date(2016, 6, 1), "ibkr/fallback"),
    ]


def test_missing_1d_sessions_fail_and_still_count_against_5m(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    gap = set(_sessions(date(2016, 2, 8), date(2016, 2, 13)))
    world.days_1d["AAA"] -= gap
    world.drop_5m("AAA", date(2016, 2, 8), date(2016, 2, 13))
    result = world.run(monkeypatch)
    failing = result.failing_name_years[0]
    assert (failing.missing_1d, failing.missing_5m) == (5, 5)
    assert result.eras["alpaca/sip_rth"].sessions_with_1d == (
        result.eras["alpaca/sip_rth"].sessions - 5
    )


def test_missing_1d_alone_fails_the_name_year(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.days_1d["AAA"] -= set(_sessions(date(2016, 2, 8), date(2016, 2, 13)))
    result = world.run(monkeypatch)
    assert _failing(result) == {("AAA", 2016)}
    assert result.failing_name_years[0].missing_5m == 0


# --------------------------------------------------------------------------- partial sessions


def test_truncated_session_is_partial_not_covered(monkeypatch):
    assert gate.classify_session(3, 78, 0.9, in_span=False) == gate.PARTIAL
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    for day in _sessions(date(2016, 2, 8), date(2016, 2, 13)):
        world.bars_5m[("AAA", "alpaca", "sip_rth", day)] = 3
    result = world.run(monkeypatch)
    counts = result.eras["alpaca/sip_rth"]
    assert (counts.partial_sessions, counts.missing_sessions) == (5, 0)
    failing = result.failing_name_years[0]
    assert (failing.partial_5m, failing.missing_5m) == (5, 0)


def test_half_day_with_all_its_bars_is_covered(monkeypatch):
    half_day = date(2015, 11, 27)  # the day after Thanksgiving closes at 13:00 New York
    assert _full(half_day) == 42
    world = Fixture()
    world.add_name("AAA", date(2015, 11, 23))
    assert world.bars_5m[("AAA", "ibkr", "named", half_day)] == 42
    result = world.run(monkeypatch)
    assert result.ok
    assert result.eras["ibkr/named"].partial_sessions == 0


# --------------------------------------------------------------------------- refusals and holds


def test_name_without_proven_start_is_counted_and_fails(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.names.append("BBB")
    result = world.run(monkeypatch)
    assert not result.ok
    assert result.names_without_proven_start == ("BBB",)
    assert result.held_names == {}


def test_name_with_zero_sessions_is_counted_and_fails(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.names.append("BBB")
    world.starts["BBB"] = HORIZON.date()
    result = world.run(monkeypatch)
    assert not result.ok
    assert result.names_with_zero_sessions == ("BBB",)


def test_name_with_zero_1d_sessions_is_counted_and_fails(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.add_name("BBB", date(2016, 1, 4))
    world.days_1d["BBB"] = set()
    result = world.run(monkeypatch)
    assert not result.ok
    assert result.names_with_zero_1d_sessions == ("BBB",)
    assert all(f.symbol != "BBB" for f in result.failing_name_years)


def _hold_world(alpaca_span_provider: str) -> Fixture:
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.names.append("BBB")
    first = NYSE.first_session("NYSE")
    world.spans.append(_span("BBB", "1d", "ibkr", first, ERA - timedelta(days=1)))
    world.spans.append(
        _span("BBB", "1d", alpaca_span_provider, ERA, HORIZON.date() - timedelta(days=1))
    )
    return world


def test_no_start_name_held_by_1d_spans_of_each_era_primary(monkeypatch):
    world = _hold_world("alpaca")
    result = world.run(monkeypatch)
    assert result.ok
    assert result.names_without_proven_start == ("BBB",)
    assert [s.provider for s in result.held_names["BBB"]] == ["ibkr", "alpaca"]
    assert result.as_record()["held_names"]["BBB"][0]["provider"] == "ibkr"


def test_zero_session_name_held_by_1d_spans(monkeypatch):
    world = _hold_world("alpaca")
    world.starts["BBB"] = HORIZON.date()
    result = world.run(monkeypatch)
    assert result.ok
    assert result.names_with_zero_sessions == ("BBB",)
    assert set(result.held_names) == {"BBB"}


def test_ibkr_span_over_the_alpaca_era_holds_nothing(monkeypatch):
    world = _hold_world("ibkr")
    world.spans = [s for s in world.spans if s.verified_from != ERA] + [
        _span("BBB", "1d", "ibkr", NYSE.first_session("NYSE"), HORIZON.date())
    ]
    result = world.run(monkeypatch)
    assert not result.ok
    assert result.held_names == {}


# --------------------------------------------------------------------------- calendar


def test_real_shaped_row_resolves_to_the_nyse_calendar():
    row = SimpleNamespace(symbol="SPY", session_id="nyse", exchange="SMART")
    key = gate.resolve_calendar_key([row], NYSE)
    assert key == "NYSE"
    sessions = gate.calendar_sessions(NYSE, key, HORIZON)
    assert sessions[0].day == date(2000, 1, 3)
    assert sessions[-1].day == date(2016, 2, 29)
    assert sessions[-1].expected_slots == 78


def test_unsupported_session_id_raises_listing_names_and_session_ids(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.add_name("ESZ6", date(2016, 1, 4))
    world.session_ids["ESZ6"] = "futures_24_5"
    with pytest.raises(ValueError, match=r"ESZ6 \(session_id 'futures_24_5'\)"):
        world.run(monkeypatch)


def test_empty_universe_raises():
    with pytest.raises(ValueError, match="empty"):
        gate.resolve_calendar_key([], NYSE)


def test_pre_calendar_1d_sessions_are_judged_from_the_first_session_and_reported(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2015, 11, 2))
    world.starts["AAA"] = date(1999, 12, 1)
    world.days_1d["AAA"] |= {date(1999, 12, 30), date(1999, 12, 31)}
    result = world.run(monkeypatch)
    assert result.pre_calendar_1d_sessions == {"AAA": 2}
    assert result.pre_calendar_1d_sessions_total == 2
    # Judged from 2000-01-03: the fixture has no bars from 2000 to 2015-11, so those years fail.
    assert min(f.year for f in result.failing_name_years) == 2000


# --------------------------------------------------------------------------- SQL hygiene


def test_sql_reads_the_named_sources_and_holds_no_date_or_kind_literal():
    sql = " ".join(
        getattr(gate, name) for name in dir(gate) if name.endswith("_SQL") and name.startswith("_")
    )
    for source in (
        "market_data_ohlcv_tradeable",
        "ohlcv_raw",
        "ohlcv_empty_history",
        "bar_source_policy_current",
    ):
        assert source in sql, source
    assert not re.search(r"'\d{4}-\d{2}-\d{2}'", sql)
    for literal in ("'named'", "'sip_rth'", "'fallback'", "'ibkr'", "'alpaca'", "'5m'", "'1d'"):
        assert literal not in sql, literal
    assert "FROM market_data_ohlcv " not in sql
