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
from services.corpus_rerun_apr import CorpusRerunApr, HeldName, HeldNameYear
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
    max_null_fraction=0.05,
)


def _policy(tf: str, lo: date, hi: date | None, primary: str, symbol: str | None = None):
    return PolicyRow(tf, symbol, lo, hi, "batch", primary, None)


def _default_policy(era: date = ERA, pre: str = "ibkr") -> list[PolicyRow]:
    return [
        _policy("5m", date(1990, 1, 1), era, pre),
        _policy("5m", era, None, "alpaca"),
        _policy("1d", date(1990, 1, 1), era, pre),
        _policy("1d", era, None, "alpaca"),
    ]


def _post_step7_policy() -> list[PolicyRow]:
    """After step 7 the 5m primary before the Alpaca era is Massive, not IBKR."""
    return _default_policy(pre="massive")


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
    # (vendor, ask, complete, has_partial_bars): the rows of ohlcv_ask_current
    asks: list[tuple[str, gate.CompletedAsk, bool, bool]] = field(default_factory=list)
    pre_pair: tuple[str, str] = ("ibkr", "named")  # the (vendor, kind) serving before ERA
    tier: set[str] | None = None  # the 5m tier; None puts every name in it
    # symbol -> (as_of, tier_5m) month-end rows of universe_membership; a name without an entry
    # is a member at every month-end from its start's month to the horizon (tier per `tier`).
    members: dict[str, list[tuple[date, bool]]] = field(default_factory=dict)
    scope: str = "all"

    def add_name(self, symbol: str, start: date, *, full: bool = True) -> None:
        """A name whose every session from start to the horizon has its 1d bar and, when full,
        all its 5m bars from the era's primary."""
        self.names.append(symbol)
        self.starts[symbol] = start
        days = _sessions(start, HORIZON.date())
        self.days_1d[symbol] = set(days)
        if full:
            for day in days:
                vendor, kind = self.pre_pair if day < ERA else ("alpaca", "sip_rth")
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
        monkeypatch.setattr(
            gate,
            "corpus_universe",
            lambda conn, intraday=False: [
                c for c in universe if not intraday or self.tier is None or c.symbol in self.tier
            ],
        )
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

        def answers(conn, pairs, names, horizon):
            # The view filter of _COMPLETED_ASKS_SQL (complete, no partial bars), per pair.
            out = {}
            for vendor, kind in pairs:
                asks = [
                    a
                    for v, a, complete, partial in self.asks
                    if v == vendor and complete and not partial
                ]
                for symbol, found in gate.merge_answers(asks).items():
                    out[(symbol, gate.era_label(vendor, kind))] = found
            return out

        monkeypatch.setattr(gate, "fetch_answers", answers)

        def membership(conn):
            rows = []
            for symbol in self.names:
                months = self.members.get(symbol)
                if months is None:
                    in_tier = self.tier is None or symbol in self.tier
                    months = [
                        (d, in_tier)
                        for d in _month_ends(
                            self.starts.get(symbol, date(2015, 11, 2)), HORIZON.date()
                        )
                    ]
                by_year: dict[int, list[tuple[date, bool]]] = {}
                for as_of, tier in months:
                    by_year.setdefault(as_of.year, []).append((as_of, tier))
                for year, parts in by_year.items():
                    dates = [d for d, _ in parts]
                    rows.append((symbol, year, any(t for _, t in parts), min(dates), max(dates)))
            return gate.name_scopes(rows)

        monkeypatch.setattr(gate, "fetch_membership", membership)
        return gate.run_data_gate(None, None, apr, scope=self.scope, horizon=HORIZON)


def _month_ends(lo: date, hi: date) -> list[date]:
    """Month-ends from lo's month up to (excluding) hi."""
    out, year, month = [], lo.year, lo.month
    while True:
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        end = nxt - timedelta(days=1)
        if end >= hi:
            return out
        out.append(end)
        year, month = nxt.year, nxt.month


def _failing(result: gate.DataGateResult) -> set[tuple[str, int]]:
    return {(f.symbol, f.year) for f in result.failing_name_years}


# --------------------------------------------------------------------------- continuity


def test_complete_history_passes_with_the_survivorship_caveat(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2015, 11, 2))
    result = world.run(monkeypatch)
    assert result.ok
    assert result.caveat["code"] == "survivorship_pre_alpaca_era_5m"
    assert result.caveat["source"] == "todo 534 owner decision 2026-11-04"
    assert "survivorship-biased" in result.caveat["text"]
    assert "IBKR" not in result.caveat["text"]
    pre_era = len(_sessions(date(2015, 11, 2), ERA))
    assert result.caveat["counts"] == {
        "names_with_1d_before_alpaca_era": 1,
        "names_pre_era_all_5m": 1,
        "names_pre_era_partly_empty_history": 0,
        "pre_era_sessions_by_5m": pre_era,
        "pre_era_sessions_by_completed_answer": 0,
        "pre_era_sessions_by_empty_history": 0,
    }
    assert result.eras["ibkr/named"].sessions == pre_era
    assert result.eras["alpaca/sip_rth"].names_at_depth == 1
    record = result.as_record()
    assert record["horizon"] == "2016-03-01T00:00:00+00:00"
    assert record["eras"]["ibkr/named"]["bar_complete"] == pre_era


def test_caveat_counts_follow_the_policy_in_force_after_step_7(monkeypatch):
    world = Fixture(policy=_post_step7_policy(), pre_pair=("massive", "sip_flat_adj"))
    world.add_name("AAA", date(2015, 11, 2))
    result = world.run(monkeypatch)
    assert result.ok
    pre_era = len(_sessions(date(2015, 11, 2), ERA))
    assert pre_era > 0
    assert result.caveat["code"] == "survivorship_pre_alpaca_era_5m"
    assert "IBKR" not in result.caveat["text"]
    assert result.caveat["counts"]["names_with_1d_before_alpaca_era"] == 1
    assert result.caveat["counts"]["names_pre_era_all_5m"] == 1
    assert result.caveat["counts"]["pre_era_sessions_by_5m"] == pre_era
    assert "ibkr/named" not in result.eras
    assert result.eras["massive/sip_flat_adj"].sessions == pre_era


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
    assert counts.bar_complete == counts.sessions - 5
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
    assert result.eras["alpaca/sip_rth"].bar_complete == len(
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
    assert gate.classify_session(3, 78, 0.9, in_span=False, answered=False) == gate.PARTIAL
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


def _held_names(*symbols: str) -> CorpusRerunApr:
    return CorpusRerunApr(
        **{**APR.__dict__, "held_names": tuple(HeldName(s, f"evidence {s}") for s in symbols)}
    )


def test_a_listed_name_without_a_proven_start_is_held_not_refused(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.names.append("BBB")
    result = world.run(monkeypatch, _held_names("BBB"))
    assert result.ok
    assert result.names_without_proven_start == ("BBB",)
    assert result.held_names_by_list == {"BBB": "evidence BBB"}
    assert result.as_record()["held_names_by_list"] == {"BBB": "evidence BBB"}


def test_a_name_hold_excuses_only_the_listed_name_and_only_a_missing_start(monkeypatch):
    world = Fixture()
    world.add_name("AAA", date(2016, 1, 4))
    world.names.append("BBB")
    other = world.run(monkeypatch, _held_names("CCC"))
    assert not other.ok and not other.held_names_by_list
    zero = Fixture()
    zero.add_name("AAA", date(2016, 1, 4))
    zero.names.append("BBB")
    zero.starts["BBB"] = HORIZON.date()  # a start with no sessions: not excusable by this list
    result = zero.run(monkeypatch, _held_names("BBB"))
    assert not result.ok and not result.held_names_by_list


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


# --------------------------------------------------------------------------- completed answers

_THIN = (date(2015, 6, 8), date(2015, 6, 13))  # five IBKR-era sessions
_WEEK = (datetime(2015, 6, 8, tzinfo=UTC), datetime(2015, 6, 13, tzinfo=UTC))


def _ask(n_bars: int = 15, *, complete: bool = True, partial: bool = False):
    return ("ibkr", gate.CompletedAsk("AAA", *_WEEK, n_bars), complete, partial)


def _thin_world(*asks) -> Fixture:
    """AAA from 2015-01-02 with five thin IBKR-era sessions (3 bars each)."""
    world = Fixture()
    world.add_name("AAA", date(2015, 1, 2))
    for day in _sessions(*_THIN):
        world.bars_5m[("AAA", "ibkr", "named", day)] = 3
    world.asks = list(asks)
    return world


def test_thin_session_inside_a_complete_ask_counts(monkeypatch):
    result = _thin_world(_ask()).run(monkeypatch)
    assert result.ok
    counts = result.eras["ibkr/named"]
    assert (counts.answer_complete, counts.partial_sessions) == (5, 0)
    assert counts.names_at_depth == 1 and counts.names_at_depth_by_bars == 0


def test_thin_session_inside_an_incomplete_ask_does_not_count(monkeypatch):
    """No terminal page, a page gap, or a failed or timeout page: the view says incomplete."""
    result = _thin_world(_ask(complete=False)).run(monkeypatch)
    assert not result.ok
    assert result.eras["ibkr/named"].partial_sessions == 5


def test_thin_session_with_no_ask_does_not_count(monkeypatch):
    result = _thin_world().run(monkeypatch)
    assert result.eras["ibkr/named"].partial_sessions == 5
    assert result.eras["ibkr/named"].answer_complete == 0


def test_ask_with_partial_bars_does_not_count(monkeypatch):
    result = _thin_world(_ask(partial=True)).run(monkeypatch)
    assert result.eras["ibkr/named"].partial_sessions == 5


def test_ask_of_another_vendor_does_not_count(monkeypatch):
    ask = ("alpaca", gate.CompletedAsk("AAA", *_WEEK, 15), True, False)
    result = _thin_world(ask).run(monkeypatch)
    assert result.eras["ibkr/named"].partial_sessions == 5


def test_merge_joins_touching_windows_and_drops_empty_ones():
    start, end = _WEEK
    mid = datetime(2015, 6, 10, tzinfo=UTC)
    merged = gate.merge_answers(
        [
            gate.CompletedAsk("AAA", start, mid, 4),
            gate.CompletedAsk("AAA", mid, end, 0),
            gate.CompletedAsk("BBB", end, start, 0),  # empty window: ignored
        ]
    )
    assert set(merged) == {"AAA"}
    assert (merged["AAA"].starts, merged["AAA"].ends) == ((start,), (end,))


def test_zero_bar_session_inside_a_complete_ask_is_no_trades(monkeypatch):
    world = _thin_world(_ask(n_bars=0))
    world.drop_5m("AAA", *_THIN)
    result = world.run(monkeypatch)
    assert result.ok
    counts = result.eras["ibkr/named"]
    assert (counts.no_trades, counts.missing_sessions) == (5, 0)


_TWO_DAYS = (datetime(2015, 6, 8, tzinfo=UTC), datetime(2015, 6, 10, tzinfo=UTC))


@pytest.mark.parametrize(("complete", "day_two"), [(True, "no_trades"), (False, "missing")])
def test_ask_serving_bars_on_day_one_and_none_on_day_two(monkeypatch, complete, day_two):
    """Lead ruling 2026-11-05: a 581 page commits with its bars, so a complete ask has no lost
    insert; its zero-bar day is no_trades whatever it served on other days. An incomplete ask
    of the same shape proves nothing: day two is missing."""
    world = Fixture()
    world.add_name("AAA", date(2015, 1, 2))
    world.drop_5m("AAA", date(2015, 6, 8), date(2015, 6, 10))
    world.bars_5m[("AAA", "ibkr", "named", date(2015, 6, 8))] = 5
    world.asks = [("ibkr", gate.CompletedAsk("AAA", *_TWO_DAYS, 5), complete, False)]
    counts = world.run(monkeypatch).eras["ibkr/named"]
    assert counts.answer_complete == (1 if complete else 0)
    assert counts.partial_sessions == (0 if complete else 1)
    assert counts.no_trades == (1 if day_two == "no_trades" else 0)
    assert counts.missing_sessions == (1 if day_two == "missing" else 0)


def test_planned_post_step7_policy_with_alpaca_gap_rows_is_not_refused():
    """Massive default to the era start, Alpaca from it, an Alpaca gap row before 2016: the label
    alpaca/sip_rth serves on both sides, in different years, so the split is exact."""
    seg = gate.Segment
    era = date(2026, 11, 11)
    segments = {
        "AAA": [
            seg(date(2015, 1, 2), date(2016, 1, 4), "alpaca", "sip_rth"),
            seg(date(2016, 1, 4), era, "massive", "sip_flat_adj"),
            seg(era, date(2026, 12, 1), "alpaca", "sip_rth"),
        ]
    }
    keys = gate.pre_era_keys(segments, era)
    assert ("AAA", 2015, "alpaca/sip_rth") in keys
    assert ("AAA", 2026, "massive/sip_flat_adj") in keys
    assert ("AAA", 2026, "alpaca/sip_rth") not in keys


def test_one_tally_shared_by_both_sides_of_the_era_start_refuses():
    seg = gate.Segment
    era = date(2026, 11, 11)
    segments = {
        "AAA": [
            seg(date(2026, 1, 2), era, "massive", "sip_flat_adj"),
            seg(era, date(2026, 12, 1), "massive", "sip_flat_adj"),
        ]
    }
    with pytest.raises(LookupError, match="cannot split"):
        gate.pre_era_keys(segments, era)


def test_a_name_outside_the_5m_tier_is_judged_on_1d_alone(monkeypatch):
    """A 1d-only name with no 5m bars passes; the tier name beside it is still judged on 5m."""
    world = Fixture(tier={"AAA"})
    world.add_name("AAA", date(2016, 1, 4))
    world.add_name("ONLY1D", date(2016, 1, 4), full=False)
    result = world.run(monkeypatch)
    assert result.ok and result.intraday_names == 1 and result.names_checked == 2
    only = result.eras[gate.ONE_D_ONLY_ERA]
    assert only.names == 1 and only.sessions == only.sessions_with_1d > 0
    assert only.names_at_depth == 0 and only.missing_sessions == 0
    assert result.eras["alpaca/sip_rth"].names == 1


def test_a_1d_hole_fails_a_name_outside_the_5m_tier(monkeypatch):
    world = Fixture(tier=set())
    world.add_name("ONLY1D", date(2016, 1, 4), full=False)
    world.days_1d["ONLY1D"] -= set(_sessions(date(2016, 2, 8), date(2016, 2, 13)))
    assert _failing(world.run(monkeypatch)) == {("ONLY1D", 2016)}


def test_a_5m_hole_still_fails_a_tier_name_beside_1d_only_names(monkeypatch):
    world = Fixture(tier={"AAA"})
    world.add_name("AAA", date(2016, 1, 4))
    world.add_name("ONLY1D", date(2016, 1, 4), full=False)
    world.drop_5m("AAA", date(2016, 2, 8), date(2016, 2, 13))
    assert _failing(world.run(monkeypatch)) == {("AAA", 2016)}


def test_1d_only_names_stay_out_of_the_survivorship_caveat(monkeypatch):
    world = Fixture(tier={"AAA"})
    world.add_name("AAA", date(2015, 6, 1))
    world.add_name("ONLY1D", date(2015, 6, 1), full=False)
    result = world.run(monkeypatch)
    assert result.ok and result.caveat["counts"]["names_with_1d_before_alpaca_era"] == 1


class _StreamConn:
    """Records the parameters of the one streamed 5m query; yields no rows."""

    def __init__(self) -> None:
        self.params: dict = {}

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, sql, params):
        self.params = params
        return iter(())


@pytest.mark.parametrize(
    ("vendor", "canonical_kind", "raw_kind"),
    [
        ("massive", "sip_flat_adj", "sip_flat_agg"),  # canonical label, raw stores sip_flat_agg
        ("alpaca", "sip_rth", "sip_rth"),
        ("ibkr", "named", "named"),
    ],
)
def test_the_5m_query_asks_raw_for_its_raw_kind(vendor, canonical_kind, raw_kind):
    day = date(2010, 1, 4)
    session = gate.Session(
        day, datetime(2010, 1, 4, 14, 30, tzinfo=UTC), datetime(2010, 1, 4, 21, 0, tzinfo=UTC)
    )
    segments = {"AAA": [gate.Segment(day, day + timedelta(days=1), vendor, canonical_kind)]}
    conn = _StreamConn()
    list(gate.iter_5m_session_bars(conn, vendor, canonical_kind, segments, [session]))
    assert conn.params["vendor"] == vendor and conn.params["kind"] == raw_kind


class _ChunkConn:
    """Records the names of every read query; the 1d counts answer one row per name."""

    def __init__(self) -> None:
        self.names: list[list[str]] = []
        self.params: list[dict] = []
        self._rows: list[tuple] = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.names.append(list(params["names"]))
        self.params.append(params)
        if "source" in params:  # the completed-asks read: no asks
            self._rows = []
        elif "symbols" in params:  # the 1d counts: one session per segment name
            self._rows = [(s, 2020, "none/1d_only", 1) for s in sorted(set(params["symbols"]))]
        else:  # the pre-calendar count
            self._rows = [(n, 5) for n in params["names"]]

    def fetchall(self):
        return self._rows


def test_the_name_reads_are_chunked_and_the_chunks_join_back_to_the_whole():
    names = [f"N{i:04d}" for i in range(gate._NAME_CHUNK * 2 + 7)]
    day = date(2020, 1, 2)
    segments = {s: [gate.Segment(day, day + timedelta(days=1), "none", "1d_only")] for s in names}
    conn = _ChunkConn()
    counts = gate.fetch_1d_counts(conn, segments, [day], datetime(2021, 1, 1, tzinfo=UTC))
    assert [len(c) for c in conn.names] == [gate._NAME_CHUNK, gate._NAME_CHUNK, 7]
    assert [n for chunk in conn.names for n in chunk] == names
    assert {key[0] for key in counts} == set(names)
    assert all(set(p["symbols"]) == set(p["names"]) for p in conn.params)

    conn = _ChunkConn()
    pre = gate.fetch_pre_calendar_1d(conn, names, day)
    assert [len(c) for c in conn.names] == [gate._NAME_CHUNK, gate._NAME_CHUNK, 7]
    assert set(pre) == set(names)


def test_the_5m_and_ask_reads_are_chunked_with_chunk_local_segments():
    names = [f"N{i:04d}" for i in range(gate._NAME_CHUNK + 3)]
    day = date(2010, 1, 4)
    session = gate.Session(
        day, datetime(2010, 1, 4, 14, 30, tzinfo=UTC), datetime(2010, 1, 4, 21, 0, tzinfo=UTC)
    )
    segments = {s: [gate.Segment(day, day + timedelta(days=1), "alpaca", "sip_rth")] for s in names}
    streams: list[dict] = []

    class _Conn(_StreamConn):
        def stream(self, sql, params):
            streams.append(params)
            return iter(((params["symbols"][0], day, 3),))

    rows = list(gate.iter_5m_session_bars(_Conn(), "alpaca", "sip_rth", segments, [session]))
    assert [len(p["names"]) for p in streams] == [gate._NAME_CHUNK, 3]
    assert all(set(p["symbols"]) == set(p["names"]) for p in streams)
    assert [r[0] for r in rows] == [names[0], names[gate._NAME_CHUNK]]

    conn = _ChunkConn()
    gate.fetch_answers(conn, [("alpaca", "sip_rth")], names, datetime(2021, 1, 1, tzinfo=UTC))
    assert [len(c) for c in conn.names] == [gate._NAME_CHUNK, 3]


# --------------------------------------------------------------------------- scope (materiality)

START = date(2014, 3, 3)


def _cut(world: Fixture, symbol: str, lo: date, hi: date) -> None:
    """Remove a name's 1d and 5m bars on the sessions in [lo, hi)."""
    world.days_1d[symbol] -= set(_sessions(lo, hi))
    world.drop_5m(symbol, lo, hi)


def _members(lo: date, hi: date, tier: bool = True) -> list[tuple[date, bool]]:
    """Month-end rows for the months from lo's month up to (excluding) hi's month-end."""
    return [(d, tier) for d in _month_ends(lo, hi)]


def test_dead_name_passes_without_the_years_after_its_death(monkeypatch):
    """AMZ-shaped: bars and membership end in 2014; every later year is out of scope."""
    world = Fixture()
    world.add_name("DEAD", START)
    _cut(world, "DEAD", date(2014, 12, 13), HORIZON.date())
    world.members["DEAD"] = _members(START, date(2014, 12, 1))  # 2014-03 .. 2014-11
    result = world.run(monkeypatch)
    assert result.ok and not result.failing_name_years
    assert result.eras["ibkr/named"].sessions == len(_sessions(START, date(2014, 12, 1)))
    assert result.scope == "all"


def test_the_same_name_with_membership_through_the_horizon_fails_in_later_years(monkeypatch):
    world = Fixture()
    world.add_name("DEAD", START)
    _cut(world, "DEAD", date(2014, 12, 13), HORIZON.date())
    result = world.run(monkeypatch)
    assert _failing(result) == {("DEAD", 2014), ("DEAD", 2015), ("DEAD", 2016)}


def test_entry_year_is_judged_only_from_the_first_membership_month(monkeypatch):
    world = Fixture()
    world.add_name("NEW", date(2015, 6, 1))
    _cut(world, "NEW", date(2015, 6, 1), date(2015, 11, 1))  # before the first member month
    world.members["NEW"] = _members(date(2015, 11, 1), HORIZON.date())
    result = world.run(monkeypatch)
    assert result.ok
    assert result.eras["ibkr/named"].sessions == len(_sessions(date(2015, 11, 1), ERA))
    # a hole inside the member months of the entry year still fails it
    world2 = Fixture()
    world2.add_name("NEW", date(2015, 6, 1))
    _cut(world2, "NEW", date(2015, 11, 9), date(2015, 11, 14))
    world2.members["NEW"] = _members(date(2015, 11, 1), HORIZON.date())
    assert _failing(world2.run(monkeypatch)) == {("NEW", 2015)}


def test_re_entry_judges_the_years_with_a_row_over_the_whole_span(monkeypatch):
    rows = _members(date(2014, 3, 1), date(2015, 1, 1)) + _members(date(2016, 1, 1), HORIZON.date())
    world = Fixture()
    world.add_name("BACK", START)
    _cut(world, "BACK", date(2015, 1, 5), date(2015, 12, 20))  # the gap year: no row, no bars
    world.members["BACK"] = rows
    assert world.run(monkeypatch).ok
    world2 = Fixture()
    world2.add_name("BACK", START)
    _cut(world2, "BACK", date(2015, 1, 5), date(2015, 12, 20))
    _cut(world2, "BACK", date(2016, 2, 8), date(2016, 2, 13))  # a hole in a member year
    world2.members["BACK"] = rows
    assert _failing(world2.run(monkeypatch)) == {("BACK", 2016)}


def test_5m_is_judged_only_in_tier_years(monkeypatch):
    rows = _members(date(2015, 1, 1), date(2016, 1, 1), tier=False) + _members(
        date(2016, 1, 1), HORIZON.date(), tier=True
    )
    world = Fixture()
    world.add_name("T", date(2015, 1, 5))
    world.drop_5m("T", date(2015, 3, 2), date(2015, 3, 9))  # 5m hole in a non-tier member year
    world.members["T"] = rows
    result = world.run(monkeypatch)
    assert result.ok and not result.failing_5m_not_gating
    world2 = Fixture()
    world2.add_name("T", date(2015, 1, 5))
    world2.drop_5m("T", date(2016, 2, 8), date(2016, 2, 13))  # in the tier year
    world2.members["T"] = rows
    assert _failing(world2.run(monkeypatch)) == {("T", 2016)}


def test_a_1d_hole_in_a_non_tier_member_year_still_fails(monkeypatch):
    rows = _members(date(2015, 1, 1), date(2016, 1, 1), tier=False) + _members(
        date(2016, 1, 1), HORIZON.date(), tier=True
    )
    world = Fixture()
    world.add_name("T", date(2015, 1, 5))
    world.days_1d["T"] -= set(_sessions(date(2015, 3, 2), date(2015, 3, 24)))  # 16 of 252
    world.members["T"] = rows
    assert _failing(world.run(monkeypatch)) == {("T", 2015)}


def test_a_name_without_a_membership_row_is_refused_with_no_judged_years(monkeypatch):
    world = Fixture()
    world.add_name("GHOST", START)
    world.members["GHOST"] = []
    result = world.run(monkeypatch)
    assert not result.ok
    assert result.names_with_zero_sessions == ("GHOST",)
    assert not result.failing_name_years


def test_scope_1d_reports_the_5m_term_without_gating_on_it(monkeypatch):
    world = Fixture(scope="1d")
    world.add_name("AAA", date(2015, 11, 2))
    world.drop_5m("AAA", date(2015, 12, 7), date(2015, 12, 12))
    result = world.run(monkeypatch)
    assert result.ok and result.scope == "1d"
    assert [(f.symbol, f.year, f.missing_5m) for f in result.failing_5m_not_gating] == [
        ("AAA", 2015, 5)
    ]
    assert result.as_record()["scope"] == "1d"
    assert not result.failing_name_years
    world.scope = "all"
    all_result = world.run(monkeypatch)
    assert not all_result.ok and _failing(all_result) == {("AAA", 2015)}
    assert not all_result.failing_5m_not_gating


def test_scope_1d_still_fails_a_1d_hole(monkeypatch):
    world = Fixture(scope="1d")
    world.add_name("AAA", date(2015, 11, 2))
    world.days_1d["AAA"] -= set(_sessions(date(2015, 12, 7), date(2015, 12, 12)))
    assert _failing(world.run(monkeypatch)) == {("AAA", 2015)}


def test_an_unknown_scope_raises(monkeypatch):
    world = Fixture(scope="both")
    world.add_name("AAA", date(2015, 11, 2))
    with pytest.raises(ValueError, match="scope"):
        world.run(monkeypatch)


def test_name_scopes_and_clip_segments():
    scope = gate.name_scopes(
        [
            ("A", 2014, False, date(2014, 3, 31), date(2014, 12, 31)),
            ("A", 2016, True, date(2016, 1, 31), date(2016, 2, 29)),
        ]
    )["A"]
    assert scope.years_1d == {2014, 2016} and scope.years_5m == {2016}
    assert (scope.first, scope.last) == (date(2014, 3, 1), date(2016, 2, 29))
    seg = gate.Segment(date(2013, 1, 1), date(2020, 1, 1), "v", "k")
    assert gate.clip_segments({"A": [seg]}, {"A": scope}) == {
        "A": [gate.Segment(date(2014, 3, 1), date(2016, 3, 1), "v", "k")]
    }
    assert gate.clip_segments({"B": [seg]}, {"A": scope}) == {}


def test_a_member_whose_proven_start_follows_its_membership_is_disclosed_not_refused(monkeypatch):
    world = Fixture()
    world.add_name("LATE", date(2015, 11, 2))
    world.members["LATE"] = _members(date(2014, 3, 1), date(2014, 12, 1))
    result = world.run(monkeypatch)
    assert result.ok and not result.names_with_zero_sessions
    assert result.names_member_before_proven_start == ("LATE",)
    assert not result.failing_name_years


# --------------------------------------------------------------------------- residual tolerance and holds
# The 1d name-year of these tests is 2015 of a name that starts on 2015-01-02: 252 sessions, so the
# residual constant (5 percent) is 12.6 sessions and the APR tolerance (1 percent) is 2.52.


def _year_2015_world(missing_1d: int, scope: str = "1d", symbol: str = "AAA") -> Fixture:
    world = Fixture(scope=scope)
    world.add_name(symbol, date(2015, 1, 2))
    gap = _sessions(date(2015, 3, 2), date(2015, 12, 1))[:missing_1d]
    world.days_1d[symbol] -= set(gap)
    return world


def test_1d_residual_between_the_apr_tolerance_and_five_percent_is_disclosed_not_gating(
    monkeypatch,
):
    result = _year_2015_world(12).run(monkeypatch)  # 12 of 252 = 4.8 percent, over the 1 percent
    assert result.ok and not result.failing_name_years
    assert [
        (f.symbol, f.year, f.sessions, f.missing_1d) for f in result.residual_1d_name_years
    ] == [("AAA", 2015, 252, 12)]
    assert result.thresholds["residual_1d_missing_fraction"] == 0.05
    assert result.as_record()["residual_1d_name_years"][0]["missing_1d"] == 12


def test_1d_name_year_above_five_percent_still_fails(monkeypatch):
    result = _year_2015_world(13).run(monkeypatch)  # 13 of 252 = 5.2 percent
    assert _failing(result) == {("AAA", 2015)}
    assert not result.residual_1d_name_years


def test_1d_within_the_apr_tolerance_is_neither_failing_nor_residual(monkeypatch):
    result = _year_2015_world(2).run(monkeypatch)  # 2 of 252 = 0.8 percent
    assert result.ok and not result.residual_1d_name_years


def test_an_apr_tolerance_above_five_percent_is_the_stricter_gate_that_stays_in_force(monkeypatch):
    loose = CorpusRerunApr(**{**APR.__dict__, "max_missing_1d_session_fraction": 0.10})
    assert _year_2015_world(20).run(monkeypatch, loose).ok  # 7.9 percent, under the APR 10
    assert not _year_2015_world(26).run(monkeypatch, loose).ok  # 10.3 percent


def test_the_residual_never_relaxes_the_5m_term(monkeypatch):
    world = Fixture(scope="all")
    world.add_name("AAA", date(2015, 1, 2))
    world.drop_5m("AAA", date(2015, 3, 2), date(2015, 3, 12))  # 8 sessions, 3.2 percent
    result = world.run(monkeypatch)
    assert _failing(result) == {("AAA", 2015)}
    assert not result.residual_1d_name_years


def _held(*pairs: tuple[str, int]) -> CorpusRerunApr:
    return CorpusRerunApr(
        **{
            **APR.__dict__,
            "held_name_years": tuple(HeldNameYear(s, y, f"evidence {s} {y}") for s, y in pairs),
        }
    )


def test_a_held_name_year_does_not_gate_and_is_reported_with_its_evidence(monkeypatch):
    world = _year_2015_world(70)
    result = world.run(monkeypatch, _held(("AAA", 2015)))
    assert result.ok and not result.failing_name_years
    [held] = result.held_name_years
    assert (held.symbol, held.year, held.missing_1d, held.evidence) == (
        "AAA",
        2015,
        70,
        "evidence AAA 2015",
    )
    assert result.eras["ibkr/named"].failing_name_years == 0
    assert result.as_record()["held_name_years"][0]["evidence"] == "evidence AAA 2015"


def test_a_held_name_year_is_excused_on_the_5m_term_too(monkeypatch):
    world = _year_2015_world(70, scope="all")
    world.drop_5m("AAA", date(2015, 3, 2), date(2015, 12, 1))
    result = world.run(monkeypatch, _held(("AAA", 2015)))
    assert result.ok and len(result.held_name_years) == 1


def test_a_hold_excuses_only_its_own_name_and_year(monkeypatch):
    world = _year_2015_world(70)
    other_name = world.run(monkeypatch, _held(("BBB", 2015)))
    assert _failing(other_name) == {("AAA", 2015)} and not other_name.held_name_years
    other_year = world.run(monkeypatch, _held(("AAA", 2016)))
    assert _failing(other_year) == {("AAA", 2015)} and not other_year.held_name_years


def test_the_proven_start_disclosure_counts_names_and_member_months():
    months = {"RSX": (10, False), "BFX": (5, True), "AAA": (100, True)}
    assert gate.proven_start_disclosure(["RSX", "BFX", "GONE"], months) == {
        "names": 2,
        "names_in_5m_tier": 1,
        "member_months": 15,
        "member_months_total": 115,
    }
    assert gate.proven_start_disclosure([], months)["names"] == 0


def test_a_hold_on_a_name_year_that_does_not_fail_reports_nothing(monkeypatch):
    result = _year_2015_world(0).run(monkeypatch, _held(("AAA", 2015)))
    assert result.ok and not result.held_name_years
