"""D7 nightly reconciliation audit: every check is a pure function tested on fixtures (plan 185-23).

No database, no clock: datetimes and dates arrive as data. The IO layer of
services/bar_reconciliation_audit.py only loads these inputs and reports the results.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from services import bar_reconciliation_audit as audit
from services.bar_reconciliation_audit import (
    aggregate_sessions,
    bucket_fine_volume,
    check_adjusted_vs_trades,
    check_completeness,
    check_daily_vs_intraday,
    check_dividend_freshness,
    check_late_heads,
    check_listing_venue_coverage,
    check_masked_slots,
    check_nightly_skipped,
    check_partial_daily,
    check_route_disagreement,
    check_stray_sources,
    check_switches,
    check_unconfirmed_empty,
    check_unexplained_seams,
    completeness_cells,
    confirmed_spans_from_requests,
    session_slots,
)
from src.intelligence.bars.daily_rule import RULE_VERSION
from src.intelligence.bars.gap_plan import AnsweredWindows
from src.intelligence.bars.sessions import nyse_sessions
from tests.unit._source_grep_helpers import read_source

D0 = date(2026, 9, 21)
D1 = date(2026, 9, 22)


# ---------------------------------------------------------------------------
# SMART vs venue
# ---------------------------------------------------------------------------


class TestRouteDisagreement:
    def test_venue_close_within_tolerance_passes_beyond_fails(self):
        rows = [
            ("ABC", D0, "SMART", 100.0),
            ("ABC", D0, "NYSE", 100.03),  # 3 bp
            ("ABC", D1, "SMART", 100.0),
            ("ABC", D1, "ARCA", 100.10),  # 10 bp
        ]
        result = check_route_disagreement(rows, 0.0005)
        assert result.n_findings == 1
        assert result.samples == ("ABC|2026-09-22|ARCA",)

    def test_with_listing_only_the_listing_venue_is_judged(self):
        rows = [
            ("ABC", D0, "SMART", 100.0),
            ("ABC", D0, "NYSE", 101.0),  # listing venue: judged, differs
            ("ABC", D0, "ARCA", 101.0),  # non-listing: expected to differ, not judged
            ("XYZ", D0, "SMART", 50.0),
            ("XYZ", D0, "ISLAND", 51.0),  # ISLAND is the NASDAQ listing route
        ]
        result = check_route_disagreement(rows, 0.0005, listing={"ABC": "NYSE", "XYZ": "NASDAQ"})
        assert result.samples == ("ABC|2026-09-21|NYSE", "XYZ|2026-09-21|ISLAND")

    def test_venue_row_without_a_smart_answer_is_not_judged(self):
        assert check_route_disagreement([("ABC", D0, "NYSE", 1.0)], 0.0005).n_findings == 0


# ---------------------------------------------------------------------------
# TRADES vs ADJUSTED_LAST
# ---------------------------------------------------------------------------


class TestAdjustedVsTrades:
    @staticmethod
    def _pairs(step_on: date):
        days = [date(2026, 9, d) for d in (14, 15, 16, 17, 18)]
        # A 3% dividend on step_on: adjusted closes before it are scaled by 0.97.
        return {
            "ABC": [(d, 100.0, 100.0 * (0.97 if d < step_on else 1.0)) for d in days],
        }

    def test_ratio_step_on_a_recorded_dividend_date_passes(self):
        step = date(2026, 9, 16)
        assert check_adjusted_vs_trades(self._pairs(step), {("ABC", step)}, 0.02).n_findings == 0

    def test_unexplained_ratio_step_fails(self):
        step = date(2026, 9, 16)
        result = check_adjusted_vs_trades(self._pairs(step), set(), 0.02)
        assert result.n_findings == 1
        assert result.samples == ("ABC|2026-09-16",)

    def test_split_recorded_on_the_last_old_scale_day_explains_the_next_days_step(self):
        step = date(2026, 9, 16)
        old_scale_last = date(2026, 9, 15)
        pairs = self._pairs(step)
        assert check_adjusted_vs_trades(pairs, {("ABC", old_scale_last)}, 0.02).n_findings == 0

    def test_step_below_the_threshold_is_not_a_finding(self):
        days = [date(2026, 9, 14), date(2026, 9, 15)]
        pairs = {"ABC": [(days[0], 100.0, 99.5), (days[1], 100.0, 100.0)]}
        assert check_adjusted_vs_trades(pairs, set(), 0.02).n_findings == 0


# ---------------------------------------------------------------------------
# Daily vs aggregated intraday
# ---------------------------------------------------------------------------


class TestDailyVsIntraday:
    @staticmethod
    def _run(daily_bar, agg_bar, volume_tol=0.0):
        return check_daily_vs_intraday(
            {("ABC", D0): daily_bar}, {("ABC", D0): agg_bar}, 15.0, volume_tol
        )

    def test_ten_bp_auction_difference_passes(self):
        assert self._run((50.0, 100.10, 1000), (50.0, 100.0, 1000)).n_findings == 0

    def test_thirty_bp_close_difference_fails(self):
        result = self._run((50.0, 100.30, 1000), (50.0, 100.0, 1000))
        assert result.n_findings == 1
        assert result.samples == ("ABC|2026-09-21|close",)

    def test_open_mismatch_fails(self):
        assert self._run((50.01, 100.0, 1000), (50.0, 100.0, 1000)).n_findings == 1

    def test_volume_mismatch_by_one_fails_at_zero_tolerance(self):
        assert self._run((50.0, 100.0, 1001), (50.0, 100.0, 1000)).n_findings == 1

    def test_volume_within_measured_tolerance_passes(self):
        # 185-12 measured the official daily volume above the intraday sum by up to ~0.26%.
        assert self._run((50.0, 100.0, 1002), (50.0, 100.0, 1000), 0.005).n_findings == 0

    def test_null_daily_volume_is_not_judged(self):
        assert self._run((50.0, 100.0, None), (50.0, 100.0, 1000)).n_findings == 0

    def test_session_missing_on_one_side_is_not_judged(self):
        result = check_daily_vs_intraday({("ABC", D0): (1.0, 1.0, 1)}, {}, 15.0, 0.0)
        assert result.n_findings == 0


# ---------------------------------------------------------------------------
# Unexplained seams
# ---------------------------------------------------------------------------


class TestUnexplainedSeams:
    @staticmethod
    def _closes(jump_sigmas: float):
        # Alternating +-1% log returns, then one jump of jump_sigmas robust scales. The
        # median absolute deviation of those returns is 0.01, so the scale is 1.4826 * 0.01.
        start = date(2026, 6, 1)
        closes = [100.0]
        for i in range(59):
            closes.append(closes[-1] * math.exp(0.01 if i % 2 == 0 else -0.01))
        closes.append(closes[-1] * math.exp(1.4826 * 0.01 * jump_sigmas))
        days = [start + timedelta(days=i) for i in range(len(closes))]
        return {"ABC": list(zip(days, closes, strict=True))}, days[-1]

    def test_twelve_sigma_jump_without_corporate_action_fails(self):
        closes, jump_day = self._closes(12.0)
        result = check_unexplained_seams(closes, set(), set(), 8.0, judge_from=jump_day)
        assert result.n_findings == 1
        assert result.samples == (f"ABC|{jump_day.isoformat()}",)

    def test_twelve_sigma_jump_with_corporate_action_passes(self):
        closes, jump_day = self._closes(12.0)
        result = check_unexplained_seams(
            closes, {("ABC", jump_day)}, set(), 8.0, judge_from=jump_day
        )
        assert result.n_findings == 0

    def test_twelve_sigma_jump_with_quarantine_flag_passes(self):
        closes, jump_day = self._closes(12.0)
        result = check_unexplained_seams(
            closes, set(), {("ABC", jump_day)}, 8.0, judge_from=jump_day
        )
        assert result.n_findings == 0

    def test_split_effective_date_is_the_last_old_scale_day(self):
        closes, jump_day = self._closes(12.0)
        prev_day = closes["ABC"][-2][0]
        result = check_unexplained_seams(
            closes, {("ABC", prev_day)}, set(), 8.0, judge_from=jump_day
        )
        assert result.n_findings == 0

    def test_quarantined_bar_dropped_between_the_pair_explains_the_jump(self):
        closes, jump_day = self._closes(12.0)
        # The tradeable view drops a quarantined bar, so the pair spans its day.
        gap_day = jump_day - timedelta(days=1)
        series = closes["ABC"][:-2] + [closes["ABC"][-1]]
        result = check_unexplained_seams(
            {"ABC": series}, set(), {("ABC", gap_day)}, 8.0, judge_from=jump_day
        )
        assert result.n_findings == 0

    def test_ordinary_move_passes(self):
        closes, jump_day = self._closes(3.0)
        assert (
            check_unexplained_seams(closes, set(), set(), 8.0, judge_from=jump_day).n_findings == 0
        )

    def test_returns_before_the_judged_window_are_not_judged(self):
        closes, jump_day = self._closes(12.0)
        later = jump_day + timedelta(days=1)
        assert check_unexplained_seams(closes, set(), set(), 8.0, judge_from=later).n_findings == 0


# ---------------------------------------------------------------------------
# Heads and empty history
# ---------------------------------------------------------------------------


class TestLateHeads:
    def test_head_later_than_first_known_trade_fails(self):
        inventory = {"AMD": date(2006, 10, 2), "PEP": date(2006, 10, 2)}
        lineage = {"AMD": date(2015, 1, 2), "PEP": date(2006, 10, 2)}
        result = check_late_heads(inventory, lineage)
        assert result.n_findings == 1
        assert result.samples == ("AMD|first_trade=2006-10-02|head=2015-01-02",)

    def test_inventory_name_without_canonical_rows_fails(self):
        assert check_late_heads({"XYZ": D0}, {}).n_findings == 1


class TestListingVenueCoverage:
    def test_moved_names_without_rows_or_without_a_closed_span_are_findings(self):
        inventory = ["AMD", "CSX", "TLT", "PEP"]
        stored = {
            "AMD": (2, 1),  # closed former span + open current span
            "CSX": (1, 0),  # one open span: the former venue never got recorded
            "PEP": (3, 2),
        }
        result = check_listing_venue_coverage(inventory, stored)
        assert result.n_findings == 2
        assert result.samples == ("CSX|no_closed_span", "TLT|no_rows")

    def test_empty_inventory_is_clean(self):
        assert check_listing_venue_coverage([], {}).n_findings == 0


class TestUnconfirmedEmpty:
    def test_row_covered_by_a_confirmed_span_passes_uncovered_fails(self):
        t = datetime(2010, 1, 1, tzinfo=UTC)
        rows = [("ABC", t, t + timedelta(days=100)), ("XYZ", t, t + timedelta(days=100))]
        confirmed = {"ABC": [(t - timedelta(days=1), t + timedelta(days=100))]}
        result = check_unconfirmed_empty(rows, confirmed, slack=timedelta(days=1))
        assert result.n_findings == 1
        assert result.samples == ("XYZ|2010-01-01",)


class TestConfirmedSpansFromRequests:
    T = datetime(2010, 1, 1, tzinfo=UTC)
    SLACK = timedelta(days=2)

    def _rows(self, routes, primary="NYSE"):
        end = self.T + timedelta(days=100)
        rows = [("run", "SMART", primary, self.T, end)]
        rows += [("run", route, None, self.T, end) for route in routes]
        return rows

    def test_span_confirmed_when_every_non_primary_venue_answered_no_data(self):
        venues = ["NYSE", "ARCA", "ISLAND"]
        (span,) = confirmed_spans_from_requests(
            self._rows(["ARCA", "ISLAND"]), venues, slack=self.SLACK
        )
        assert span == (self.T, self.T + timedelta(days=100))

    def test_span_unconfirmed_when_a_required_venue_is_silent(self):
        venues = ["NYSE", "ARCA", "ISLAND"]
        assert confirmed_spans_from_requests(self._rows(["ARCA"]), venues, slack=self.SLACK) == []

    def test_island_is_the_nasdaq_primary(self):
        venues = ["NYSE", "ISLAND"]
        rows = self._rows(["NYSE"], primary="NASDAQ")
        assert len(confirmed_spans_from_requests(rows, venues, slack=self.SLACK)) == 1


class TestAggregateSessions:
    def test_first_open_last_close_summed_volume_inside_the_session(self):
        sessions = nyse_sessions(D0, D0)
        fine = [
            ("ABC", OPEN - FIVE, 9.0, 9.0, 999),  # pre-market: dropped
            ("ABC", OPEN, 10.0, 10.5, 100),
            ("ABC", OPEN + FIVE, 10.5, 11.0, 50),
            ("ABC", OPEN + FIVE * 77, 11.0, 12.0, 25),  # 15:55 ET, the last bar
        ]
        assert aggregate_sessions(fine, sessions, FIVE) == {("ABC", D0): (10.0, 12.0, 175)}

    def test_session_whose_feed_stops_before_the_final_slot_is_dropped(self):
        sessions = nyse_sessions(D0, D0)
        fine = [("ABC", OPEN, 10.0, 10.5, 100), ("ABC", OPEN + FIVE * 60, 10.5, 11.0, 50)]
        assert aggregate_sessions(fine, sessions, FIVE) == {}


class TestPartialDaily:
    def test_latest_answer_fetched_before_the_close_is_partial(self):
        sessions = nyse_sessions(D0, D1)
        close_d0 = sessions[D0][1]
        latest = [
            ("NVR", D0, close_d0 - timedelta(minutes=51)),  # fetched 19:09 UTC: partial
            ("LLY", D0, close_d0 + timedelta(hours=12)),  # re-fetched next morning: final
        ]
        result = check_partial_daily(latest, sessions)
        assert result.n_findings == 1
        assert result.samples[0].startswith("NVR|2026-09-21|")


# ---------------------------------------------------------------------------
# Dividend freshness, stray sources, switches, nightly
# ---------------------------------------------------------------------------


class TestDividendFreshness:
    def test_coverage_more_than_max_sessions_behind_fails_missing_fails(self):
        sessions = [date(2026, 9, d) for d in (21, 22, 23, 24, 25, 28, 29, 30)]
        coverage = {"FRESH": date(2026, 9, 28), "STALE": date(2026, 9, 22), "NONE": None}
        result = check_dividend_freshness(coverage, date(2026, 9, 30), 3, session_dates=sessions)
        assert result.n_findings == 2
        assert set(result.samples) == {"STALE|covered_to=2026-09-22", "NONE|no_coverage"}

    def test_exactly_max_sessions_behind_passes(self):
        sessions = [date(2026, 9, d) for d in (24, 25, 28, 29)]
        result = check_dividend_freshness(
            {"A": date(2026, 9, 24)}, date(2026, 9, 29), 3, session_dates=sessions
        )
        assert result.n_findings == 0


class TestStraySources:
    def test_pairs_the_derivation_does_not_write_count(self):
        counts = {
            ("1d", ("ibkr", "named")): 10,
            ("1d", ("ibkr", "venue")): 1,
            ("1d", ("ibkr", "fallback")): 4,
            ("1d", ("yahoo", "consolidated")): 2,
            ("15m", ("derived", "5m_grid")): 100,
            ("15m", ("ibkr", "named")): 7,
            ("5m", ("ibkr", "named")): 999,  # 5m is not a derived timeframe: not judged
        }
        result = check_stray_sources(counts)
        assert result.n_findings == 2 + 7
        assert set(result.samples) == {"1d:yahoo/consolidated=2", "15m:ibkr/named=7"}

    def test_the_retired_vendor_is_a_stray_daily_pair(self):
        assert check_stray_sources({("1d", ("tradier", "consolidated")): 5}).n_findings == 5


class TestSwitches:
    def test_venue_switch_true_while_the_verdict_failed_counts(self):
        apr = {
            "venue_bars_1d": True,
            "venue_bars_intraday": False,
            "intraday_recovery_unlocked": False,
        }
        result = check_switches(apr, {"1d": False, "5m": False})
        assert result.n_findings == 1
        assert result.samples == ("venue_bars_1d=true|verdict_passed=false",)

    def test_switches_matching_the_verdict_pass(self):
        apr = {
            "venue_bars_1d": False,
            "venue_bars_intraday": False,
            "intraday_recovery_unlocked": False,
        }
        assert check_switches(apr, {"1d": False, "5m": False}) == audit.CheckResult(0, ())

    def test_recovery_unlocked_is_reported_but_not_counted(self):
        apr = {
            "venue_bars_1d": False,
            "venue_bars_intraday": False,
            "intraday_recovery_unlocked": True,
        }
        result = check_switches(apr, {"1d": False, "5m": False})
        assert result.n_findings == 0
        assert result.samples == ("intraday_recovery_unlocked=true (informational)",)


class TestNightlySkipped:
    NOW = datetime(2026, 10, 3, 6, 0, tzinfo=UTC)

    def _status(self, status, hours_ago=2.0, **extra):
        finished = self.NOW - timedelta(hours=hours_ago)
        return {"status": status, "finished_at": finished.isoformat(), **extra}

    def test_success_within_age_passes(self):
        assert (
            check_nightly_skipped(
                self._status("success"), now=self.NOW, max_age_hours=26
            ).n_findings
            == 0
        )

    def test_lease_timeout_fails(self):
        status = self._status("failed_lease_timeout", lease_timeout_legs=["compute"])
        result = check_nightly_skipped(status, now=self.NOW, max_age_hours=26)
        assert result.n_findings == 1
        assert result.samples == ("status=failed_lease_timeout|legs=compute",)

    def test_missing_status_fails(self):
        assert check_nightly_skipped(None, now=self.NOW, max_age_hours=26).samples == ("no_status",)

    def test_stale_success_is_a_skipped_night(self):
        result = check_nightly_skipped(
            self._status("success", hours_ago=30), now=self.NOW, max_age_hours=26
        )
        assert result.n_findings == 1
        assert result.samples[0].startswith("stale|finished_at=")

    def test_run_that_never_finished_fails(self):
        status = {"status": "started", "started_at": self.NOW.isoformat(), "finished_at": None}
        assert check_nightly_skipped(status, now=self.NOW, max_age_hours=26).n_findings == 1


# ---------------------------------------------------------------------------
# Completeness and masked slots (todo 462)
# ---------------------------------------------------------------------------

# 2026-09-21 (Monday) is a full NYSE session: 13:30-20:00 UTC.
OPEN = datetime(2026, 9, 21, 13, 30, tzinfo=UTC)
FIVE = timedelta(minutes=5)


class TestSessionGrid:
    def test_slots_are_session_anchored(self):
        sessions = nyse_sessions(D0, D0)
        hours = session_slots(sessions, 60, OPEN, OPEN + timedelta(hours=8))
        assert hours[0] == OPEN
        assert hours[1] == OPEN + timedelta(hours=1)
        assert len(hours) == 7  # 09:30, 10:30, ... 15:30
        assert len(session_slots(sessions, 5, OPEN, OPEN + timedelta(hours=8))) == 78

    def test_fine_volume_buckets_to_the_session_anchored_slot(self):
        sessions = nyse_sessions(D0, D0)
        fine = [(OPEN + FIVE * i, 10) for i in range(14)]  # 09:30 .. 10:35
        by_hour = bucket_fine_volume(fine, sessions, 60)
        assert by_hour == {OPEN: 120, OPEN + timedelta(hours=1): 20}
        by_15 = bucket_fine_volume(fine, sessions, 15)
        assert by_15[OPEN] == 30 and len(by_15) == 5


class TestCompleteness:
    def test_real_bar_or_answered_window_counts_complete_unanswered_hole_does_not(self):
        slots = [OPEN + FIVE * i for i in range(4)]
        stored = [slots[0]]
        answered = AnsweredWindows.from_rows([(slots[1], slots[2] + FIVE)])
        (cell,) = completeness_cells("ABC", "5m", slots, stored, answered, FIVE)
        assert (cell.year, cell.n_expected, cell.n_complete) == (2026, 4, 3)
        assert cell.share == pytest.approx(0.75)

    def test_last_1h_slot_ends_at_the_close_so_an_answered_window_to_the_close_covers_it(self):
        sessions = nyse_sessions(D0, D0)
        close = sessions[D0][1]
        last_hour = close - timedelta(minutes=30)  # 15:30 ET, a 30-minute slot
        answered = AnsweredWindows.from_rows([(OPEN, close)])
        (cell,) = completeness_cells(
            "ABC", "1h", [last_hour], [], answered, timedelta(hours=1), sessions
        )
        assert cell.n_complete == 1
        (no_sessions,) = completeness_cells(
            "ABC", "1h", [last_hour], [], answered, timedelta(hours=1)
        )
        assert no_sessions.n_complete == 0

    def test_a_full_unanswered_year_is_reported_by_symbol_and_year_metric_by_timeframe(self):
        year_2025 = [datetime(2025, 3, 3, 14, 30, tzinfo=UTC) + FIVE * i for i in range(10)]
        year_2026 = [OPEN + FIVE * i for i in range(10)]
        cells = completeness_cells(
            "ABC", "5m", year_2025 + year_2026, year_2026, AnsweredWindows(), FIVE
        ) + completeness_cells("XYZ", "5m", year_2026, year_2026, AnsweredWindows(), FIVE)
        result, pooled = check_completeness(cells, 0.996)
        assert result.n_findings == 1
        assert result.samples == ("ABC|5m|2025|share=0.0000",)
        # The metric side carries the timeframe only: one pooled share per timeframe.
        assert pooled == {"5m": pytest.approx(20 / 30)}


class TestMaskedSlots:
    SLOT = OPEN

    def test_placeholder_over_real_fine_volume_counts(self):
        result = check_masked_slots({self.SLOT: "placeholder"}, {self.SLOT: 500})
        assert result.n_findings == 1

    def test_missing_coarse_row_over_real_fine_volume_counts(self):
        assert check_masked_slots({}, {self.SLOT: 500}).n_findings == 1

    def test_real_coarse_bar_over_the_same_slot_counts_zero(self):
        assert check_masked_slots({self.SLOT: "real"}, {self.SLOT: 500}).n_findings == 0

    def test_placeholder_with_no_fine_volume_counts_zero(self):
        assert check_masked_slots({self.SLOT: "placeholder"}, {self.SLOT: 0}).n_findings == 0
        assert check_masked_slots({self.SLOT: "placeholder"}, {}).n_findings == 0

    def test_partial_constituents_bar_is_not_masked(self):
        # It carries the real volume of the constituents that exist; reported separately.
        assert check_masked_slots({self.SLOT: "partial"}, {self.SLOT: 500}).n_findings == 0

    def test_twelve_consecutive_masked_slots_for_one_name_and_day_count_twelve(self):
        slots = [OPEN + timedelta(minutes=15) * i for i in range(12)]
        coarse = dict.fromkeys(slots, "placeholder")
        fine = dict.fromkeys(slots, 100)
        assert check_masked_slots(coarse, fine).n_findings == 12


# ---------------------------------------------------------------------------
# Metric labels (T-185-23-04)
# ---------------------------------------------------------------------------


def test_metrics_are_never_labeled_by_symbol():
    source = read_source("services", "bar_reconciliation_audit.py")
    metric_names = ("FINDINGS_TOTAL", "COMPLETENESS_SHARE", "VENDOR_")
    emits = [
        line
        for line in source.splitlines()
        if any(name in line for name in metric_names) and (".add(" in line or ".set(" in line)
    ]
    assert emits, "no metric emission found"
    for line in emits:
        assert "symbol" not in line, line
    # The plan's acceptance grep: no line naming a symbol calls add(.
    assert not [line for line in source.splitlines() if "symbol" in line and "add(" in line.lower()]


# ---------------------------------------------------------------------------
# The 1d verdict report (plan 185-33 Task 2): loaders on a fake connection, never the live DB
# ---------------------------------------------------------------------------


class _FakeConn:
    """Answers the report's reads by SQL constant and records the writes (todo 494)."""

    def __init__(self, names: dict[str, dict]):
        self.names = names
        self.facts: list[tuple] = []
        self.written_floor = None

    async def fetch(self, sql, *args):
        if sql == audit._SELECT_POLICY_1D_SQL:
            return [
                {
                    "timeframe": "1d",
                    "symbol": None,
                    "valid_from": date(2000, 1, 1),
                    "valid_to": None,
                    "ingress_mode": "observed",
                    "primary_source": "alpaca",
                    "fallback_source": "ibkr",
                }
            ]
        if sql == audit._LINEAGE_MISSING_SQL:
            return [
                {"symbol": s, "bar_date": d, "visible": v}
                for s, n in self.names.items()
                for d, v in n.get("lineage", [])
            ]
        if sql in (audit._EMPTY_SESSIONS_SQL,):
            return [
                {"symbol": s, "span_start": start, "span_end": end}
                for s, n in self.names.items()
                for start, end in n.get("empty", ())
            ]
        if sql == audit._ANSWERED_1D_REQUESTS_SQL:
            sources, routes, shows, outcome = args
            wanted = set(zip(sources, routes, shows, strict=True))
            return [  # the SQL's own filter, driven by the arguments the loader passes
                {
                    "symbol": s,
                    "vendor": q["source"],
                    "window_start": q["start"],
                    "window_end": q["end"],
                }
                for s, n in self.names.items()
                for q in n.get("requests", ())
                if (q["source"], q["route"], q["what"]) in wanted and q["outcome"] == outcome
            ]
        if sql == audit._ANSWERED_1D_LOADS_SQL:
            sources, outcomes, destinations = args
            return [
                {
                    "symbol": s,
                    "vendor": load["source"],
                    "requested_start": load["start"],
                    "requested_end": load["end"],
                }
                for s, n in self.names.items()
                for load in n.get("loads", ())
                if load["source"] in sources
                and load["outcome"] in outcomes
                and load["destination"] in destinations
            ]
        if sql == audit._LATEST_1D_LOAD_SQL:
            return []
        if sql == audit._LISTING_END_SQL:
            return [
                {"symbol": s, "last_session": n["listing_end"]}
                for s, n in self.names.items()
                if "listing_end" in n
            ]
        symbol = args[0]
        data = self.names[symbol]
        if sql == audit._SELECT_DAILY_RAW_SQL:
            return data["observations"]
        if sql == audit._SELECT_STORED_1D_SQL:
            return data["stored"]
        if sql == audit._SELECT_CURRENT_1D_DIGESTS_SQL:
            return data.get("digests", [])
        return []  # splits, flags

    async def fetchval(self, sql, *args):
        if sql == audit._FIRST_1D_BAR_SQL:
            return datetime(2024, 1, 2, tzinfo=UTC)
        return len(self.facts)  # the read-back count in _write_verdicts

    async def executemany(self, sql, facts):
        self.facts.extend(facts)


def _obs_row(day, close):
    return {
        "request_id": f"r-{day}",
        "vendor": "alpaca",
        "kind": "sip_rth",
        "bar_date": day,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000,
        "served_at": datetime(2024, 1, 20, tzinfo=UTC),
        "legacy": False,
    }


def _stored_row(day, close, vendor="alpaca", kind="sip_rth"):
    return {
        "timestamp": datetime(day.year, day.month, day.day, tzinfo=UTC),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000.0,
        "vendor": vendor,
        "kind": kind,
        "base": None,
    }


_REPORT_DAYS = [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]


def _good_name():
    from src.intelligence.bars.integrity_checks import StoredBar, month_digests

    stored = [_stored_row(d, 100.0 + i) for i, d in enumerate(_REPORT_DAYS)]
    digests = month_digests(
        [
            StoredBar(
                r["timestamp"],
                r["open"],
                r["high"],
                r["low"],
                r["close"],
                r["volume"],
                r["vendor"],
                r["kind"],
            )
            for r in stored
        ],
        [],
    )
    return {
        "observations": [_obs_row(d, 100.0 + i) for i, d in enumerate(_REPORT_DAYS)],
        "stored": stored,
        "digests": [
            {"range_start": s, "digest": g, "rule_version": RULE_VERSION}
            for s, g in digests.items()
        ],
    }


class _Window:
    last_session = date(2024, 1, 4)
    training_window_end = datetime(2024, 1, 4, tzinfo=UTC)


_NOW = datetime(2024, 1, 5, 6, tzinfo=UTC)


def _run(names, seam_samples=()):
    import asyncio

    conn = _FakeConn(names)
    params = audit._IntegrityParams.from_apr({})
    run = asyncio.run(
        audit.BarReconciliationAudit._verdict_report_1d(
            conn, params, _Window(), sorted(names), list(seam_samples), _NOW
        )
    )
    return conn, run


def _request(source, route, what, outcome, start, end):
    return {
        "source": source,
        "route": route,
        "what": what,
        "outcome": outcome,
        "start": datetime(start.year, start.month, start.day, tzinfo=UTC),
        "end": datetime(end.year, end.month, end.day, tzinfo=UTC),
    }


def _ibkr_gap_name(requests):
    """A name on IBKR SMART bars (routes the observations carry) with the middle session of three
    absent, plus the given ohlcv_request rows."""
    name = _good_name()
    gap = _REPORT_DAYS[1]
    name["stored"] = [
        _stored_row(d, 100.0 + i, "ibkr", "named") for i, d in enumerate(_REPORT_DAYS) if d != gap
    ]
    name["observations"] = [
        {**_obs_row(d, 100.0 + i), "vendor": "ibkr", "kind": "smart_trades"}
        for i, d in enumerate(_REPORT_DAYS)
        if d != gap
    ]
    name["digests"] = []
    name["requests"] = requests
    return name


def _coverage_1d(requests):
    _, run = _run({"AAA": _ibkr_gap_name(requests)})
    return next(f for f in run.facts if f[2] == "session_coverage")


_WINDOW = (_REPORT_DAYS[0], _REPORT_DAYS[-1] + timedelta(days=1))


def test_a_session_inside_a_successful_canonical_request_window_is_answered():
    assert _coverage_1d([_request("ibkr", "SMART", "TRADES", "bars", *_WINDOW)])[5] is True
    assert _coverage_1d([])[5] is False


def test_a_tradier_request_or_a_non_canonical_route_answers_nothing():
    for source, route, what in (
        ("tradier", "TRADIER", "TRADES"),
        ("ibkr", "NYSE", "TRADES"),
        ("ibkr", "SMART", "ADJUSTED_LAST"),
        ("alpaca", "IEX", "1Day"),
    ):
        assert _coverage_1d([_request(source, route, what, "bars", *_WINDOW)])[5] is False


def test_a_refused_failed_or_partial_request_answers_nothing():
    for outcome in ("failed", "timeout", "legacy_import", "no_data"):
        assert _coverage_1d([_request("ibkr", "SMART", "TRADES", outcome, *_WINDOW)])[5] is False


def _load_1d(source="ibkr", outcome="applied", destination="raw", days=_REPORT_DAYS):
    return {
        "source": source,
        "outcome": outcome,
        "destination": destination,
        "start": days[0],
        "end": days[-1],
    }


def test_an_applied_raw_load_of_a_canonical_vendor_answers_its_range_end_inclusive():
    name = _ibkr_gap_name([])
    name["loads"] = [_load_1d()]
    assert next(f for f in _run({"AAA": name})[1].facts if f[2] == "session_coverage")[5] is True
    # the range's last day holds the bar that corroborates the gap; end one day short and the
    # window holds a single bar, so nothing is corroborated on its far side
    name["loads"] = [_load_1d(days=_REPORT_DAYS[:2])]
    assert next(f for f in _run({"AAA": name})[1].facts if f[2] == "session_coverage")[5] is False


def test_a_refused_derived_or_archive_load_answers_nothing():
    for load in (
        _load_1d(outcome="refused"),
        _load_1d(outcome="failed"),
        _load_1d(source="tradier"),
        _load_1d(source="derived", destination="market_data_ohlcv"),
        _load_1d(destination="archive"),
    ):
        name = _ibkr_gap_name([])
        name["loads"] = [load]
        assert (
            next(f for f in _run({"AAA": name})[1].facts if f[2] == "session_coverage")[5] is False
        )


def test_a_window_with_no_stored_bar_inside_it_answers_nothing():
    later = (_REPORT_DAYS[-1] + timedelta(days=5), _REPORT_DAYS[-1] + timedelta(days=9))
    assert _coverage_1d([_request("ibkr", "SMART", "TRADES", "bars", *later)])[5] is False


def test_the_existing_empty_history_rule_is_unchanged():
    name = _ibkr_gap_name([])
    name["empty"] = [(_REPORT_DAYS[1], _REPORT_DAYS[1])]
    _, run = _run({"AAA": name})
    assert next(f for f in run.facts if f[2] == "session_coverage")[5] is True
    assert "ohlcv_request" not in audit._EMPTY_SESSIONS_SQL


def test_each_name_gets_nine_verdict_rows_and_two_informational_rows():
    conn, run = _run({"AAA": _good_name(), "BBB": _good_name()})
    rows = [f for f in run.facts if f[1] == "AAA|1d"]
    assert len(rows) == 11
    assert {f[0] for f in run.facts} == {"bar_integrity"}
    assert [f[2] for f in rows][:9] == list(audit.CHECKS_1D)
    assert "freshness_1d" in audit.CHECKS_1D
    assert [f[2] for f in rows][9:] == ["refused_head_1d", "held_1d"]
    assert all(f[5] for f in run.facts)
    assert run.failing_by_check == {}


def test_a_failing_check_is_recorded_not_raised_and_other_names_still_judged():
    bad = _good_name()
    bad["stored"][0] = _stored_row(_REPORT_DAYS[0], 150.0)  # recompute differs and digest stale
    _, run = _run({"AAA": bad, "BBB": _good_name()}, seam_samples=["AAA|2024-01-03"])
    assert run.failing_by_check["canonical_recompute"] == 1
    assert run.failing_by_check["digest_fresh"] == 1
    assert run.failing_by_check["unexplained_seam"] == 1
    assert run.passing_by_check["canonical_recompute"] == 1


def test_lineage_missing_counts_visible_and_quarantined_untraced_go_to_the_fact():
    name = _good_name()
    name["lineage"] = [(_REPORT_DAYS[0], True), (_REPORT_DAYS[1], False)]
    _, run = _run({"AAA": name})
    verdict = {f[2]: f for f in run.facts}["lineage_missing"]
    assert verdict[3] == 1.0 and verdict[5] is False
    assert run.untraced_hidden.result.n_findings == 1
    assert run.untraced_hidden.result.samples == ("AAA=1",)


def test_write_verdicts_reads_back_and_raises_on_a_short_write():
    import asyncio

    conn, run = _run({"AAA": _good_name()})
    asyncio.run(audit.BarReconciliationAudit._write_verdicts(conn, run, _NOW))
    assert len(conn.facts) == len(run.facts)

    class _Short(_FakeConn):
        async def fetchval(self, sql, *args):
            return 0

    with pytest.raises(RuntimeError, match="wrote 0 of"):
        asyncio.run(audit.BarReconciliationAudit._write_verdicts(_Short({}), run, _NOW))


def test_findings_by_symbol_groups_seam_samples():
    assert audit.findings_by_symbol(["AAA|2024-01-03", "AAA|2024-01-04", "BBB|2024-01-03"]) == {
        "AAA": 2,
        "BBB": 1,
    }


def test_ibkr_fallback_is_an_allowed_1d_pair():
    assert check_stray_sources({("1d", ("ibkr", "fallback")): 4}).n_findings == 0
    assert check_stray_sources({("1d", ("mystery", "x")): 4}).n_findings == 4


def test_integrity_keys_are_loaded_by_the_audit():
    assert "threshold.bar_integrity.%" in audit._APR_PATTERNS
    params = audit._IntegrityParams.from_apr({"threshold.bar_integrity.report_max_age_hours": 12})
    assert params.report_max_age_hours == 12 and params.session_coverage_min == 0.999
    assert params.freshness_max_lag_sessions_1d == 2
    params = audit._IntegrityParams.from_apr(
        {"threshold.bar_integrity.freshness_max_lag_sessions_1d": "5"}
    )
    assert params.freshness_max_lag_sessions_1d == 5


def test_a_stale_name_fails_freshness_1d_and_is_counted():
    stale = _good_name()
    stale["stored"] = stale["stored"][:1]  # latest bar 2024-01-02; 01-03 and 01-04 behind
    stale["observations"] = stale["observations"][:1]
    stale["digests"] = []

    class _Late(_Window):
        last_session = date(2024, 1, 9)  # 01-03 .. 01-09: 5 sessions behind

    import asyncio

    conn = _FakeConn({"AAA": stale, "BBB": _good_name()})
    run = asyncio.run(
        audit.BarReconciliationAudit._verdict_report_1d(
            conn, audit._IntegrityParams.from_apr({}), _Late(), ["AAA", "BBB"], [], _NOW
        )
    )
    verdicts = {(f[1], f[2]): f for f in run.facts}
    assert verdicts[("AAA|1d", "freshness_1d")][3:6] == (5.0, 2.0, False)
    assert verdicts[("BBB|1d", "freshness_1d")][5] is False  # BBB ends 01-04 too
    assert run.failing_by_check["freshness_1d"] == 2


def test_alert_gauges_carry_freshness_1d_and_record_zero_when_it_clears(monkeypatch):
    gauges = _patched_gauges(monkeypatch)
    now = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    audit.record_alert_gauges(
        failing_by_check=audit.merge_failing_by_check(
            audit.zero_for_judged({"freshness_1d": 1500, "session_coverage": 1262}),
            {"session_coverage": 240},
        ),
        previous_verdict_at=None,
        run_start=now,
        max_age_hours=30,
        refused_by_source={},
    )
    points = sorted(gauges["BAR_INTEGRITY_FAILING_NAMES"].points, key=lambda p: p[1]["check"])
    assert points == [(0, {"check": "freshness_1d"}), (240, {"check": "session_coverage"})]
    assert {key for _, attributes in points for key in attributes} == {"check"}


# ---------------------------------------------------------------------------
# The intraday verdicts (plan 185-40 Task 2): fakes only, never the live DB (todo 494)
# ---------------------------------------------------------------------------

_I_DAYS = (date(2025, 6, 2), date(2025, 6, 3))
_I_END_DAY = _I_DAYS[-1]


def _intraday_series(days=_I_DAYS):
    """Five-minute rows over whole regular sessions, one price step per bar."""
    from src.intelligence.bars.sessions import nyse_sessions

    sessions = nyse_sessions(days[0], days[-1])
    slots = audit.session_slots(
        sessions,
        5,
        datetime(days[0].year, days[0].month, days[0].day, tzinfo=UTC),
        datetime(days[-1].year, days[-1].month, days[-1].day, tzinfo=UTC) + timedelta(days=1),
    )
    rows = [
        {
            "timestamp": slot,
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 99.0 + i,
            "close": 101.0 + i,
            "volume": 10.0,
            "base": None,
            "vendor": "ibkr",
        }
        for i, slot in enumerate(slots)
    ]
    return sessions, rows


def _archive_rows(rows, tf):
    """What a vendor archive holds when it agrees with the 5m rows (built by the rebucketing)."""
    from src.intelligence.bars.integrity_checks import rebucket_5m

    five = audit._FiveMinute.from_rows(rows, [])
    width = {"15m": 900, "1h": 3600}[tf]
    starts = sorted({int(r["timestamp"].timestamp()) // width * width for r in rows})
    if tf == "1h":  # the vendor's first bucket of a session is the 09:30 half hour
        starts = sorted({s for s in starts} | {int(r["timestamp"].timestamp()) for r in rows[:1]})
    rebucketed = rebucket_5m(
        five.ts, five.open, five.high, five.low, five.close, five.volume, starts, timeframe=tf
    )
    return {datetime.fromtimestamp(t, tz=UTC): values for t, values in rebucketed.items()}


class _IntradayConn:
    """Answers the intraday report's reads by SQL constant and records nothing it must not."""

    def __init__(self, names, *, previous=None, last_sweep=None, loads=(), stray=None):
        self.names = names  # symbol -> {"rows", "archive": {tf: {ts: values}}, "digests": {tf: {}}}
        self.previous = previous or {}
        self.last_sweep = last_sweep
        self.loads = list(loads)
        self.stray = stray or {}
        self.facts: list[tuple] = []

    async def fetch(self, sql, *args):
        if sql == audit._INTRADAY_NAMES_SQL:
            return [{"symbol": s} for s in sorted(self.names)]
        if sql == audit._PREVIOUS_DIGEST_VERDICT_SQL:
            return [
                {"subject": s, "passed": p, "evaluated_at": at}
                for s, (p, at) in self.previous.items()
            ]
        if sql == audit._CHANGING_LOADS_SQL:
            return self.loads
        if sql == audit._STRAY_VENDOR_SQL:
            return [{"symbol": s, "timeframe": tf, "n": n} for (s, tf), n in self.stray.items()]
        symbol = args[0]
        data = self.names[symbol]
        if sql == audit._SELECT_5M_SQL:
            return data["rows"]
        if sql == audit._RAW_5M_SLOTS_SQL:
            return [{"timestamp": r["timestamp"]} for r in data.get("slots", data["rows"])]
        if sql == audit._LOADED_RANGES_SQL:
            _symbol, _timeframe, sources, outcomes, destinations = args
            return [  # the SQL's own filter, driven by the arguments the loader passes
                {"requested_start": load["start"], "requested_end": load["end"]}
                for load in data.get("loads", ())
                if load["source"] in sources
                and load["outcome"] in outcomes
                and load["destination"] in destinations
            ]
        if sql == audit._ARCHIVE_ROWS_SQL:
            return [
                {
                    "timeframe": tf,
                    "timestamp": ts,
                    **dict(zip(("open", "high", "low", "close", "volume"), v)),
                }
                for tf, by_ts in data["archive"].items()
                for ts, v in by_ts.items()
            ]
        if sql == audit._SELECT_CURRENT_GRID_DIGESTS_SQL:
            return [
                {"timeframe": tf, "range_start": start, "digest": digest}
                for tf, by_month in data["digests"].items()
                for start, digest in by_month.items()
            ]
        return []  # flags, answered windows

    async def fetchval(self, sql, *args):
        if sql == audit._LATEST_SWEEP_SQL:
            return self.last_sweep
        return len(self.facts)


class _IWindow:
    last_session = _I_END_DAY
    training_window_end = datetime(2025, 6, 3, tzinfo=UTC)

    @property
    def end(self):
        from src.intelligence.bars.sessions import nyse_sessions

        return nyse_sessions(_I_END_DAY, _I_END_DAY)[_I_END_DAY][1]


def _agreeing_name(rows=None):
    sessions, base_rows = _intraday_series()
    rows = rows if rows is not None else base_rows
    five = audit._FiveMinute.from_rows(rows, [])
    digests, _ = audit.intraday_month_digests(five, sessions, None)
    return {
        "rows": rows,
        "archive": {tf: _archive_rows(rows, tf) for tf in ("15m", "1h")},
        "digests": digests,
    }


_I_NOW = datetime(2025, 6, 4, 6, tzinfo=UTC)
_I_PARAMS = audit._IntegrityParams.from_apr({})


def _no_drift(names):
    async def drift(_names):
        return {}

    return drift(names)


def _intraday(conn, drift=_no_drift):
    import asyncio

    return asyncio.run(
        audit.BarReconciliationAudit._verdict_report_intraday(
            conn, _I_PARAMS, _IWindow(), _I_NOW, coverage_drift=drift
        )
    )


def _verdict(run, subject, check):
    return next(f for f in run.facts if f[1] == subject and f[2] == check)


def test_an_agreeing_name_passes_every_intraday_check_and_gets_the_whole_row_set():
    run = _intraday(_IntradayConn({"AAA": _agreeing_name()}))
    subjects = {(f[1], f[2]) for f in run.facts if f[1] != "intraday|sweep"}
    assert subjects == {
        ("AAA|5m", "slot_coverage"),
        ("AAA|5m", "digest_fresh"),
        ("AAA|15m", "digest_fresh"),
        ("AAA|1h", "digest_fresh"),
        ("AAA|15m", "grid_parity"),
        ("AAA|1h", "grid_parity"),
        ("AAA|15m", "stray_vendor_rows"),
        ("AAA|1h", "stray_vendor_rows"),
        ("AAA|5m", "coverage_cache"),
    }
    assert {f[0] for f in run.facts} == {"bar_integrity"}
    assert all(f[5] for f in run.facts) and run.failing_by_check == {}
    parity = _verdict(run, "AAA|15m", "grid_parity")
    assert parity[3] == 0.0 and parity[4] == 0.0


def test_missing_unanswered_slots_fail_slot_coverage_with_the_worst_year_as_metric():
    _, rows = _intraday_series()
    kept = [r for i, r in enumerate(rows) if i % 10]  # one slot in ten missing
    name = _agreeing_name(rows)
    name["slots"] = kept
    run = _intraday(_IntradayConn({"AAA": name}))
    verdict = _verdict(run, "AAA|5m", "slot_coverage")
    assert verdict[5] is False
    assert 0.85 < verdict[3] < 0.95
    assert verdict[4] == 0.995


def test_zero_volume_provider_bars_count_as_answered_slots():
    _, rows = _intraday_series()
    name = _agreeing_name(rows)
    name["slots"] = list(rows)  # a zero-volume bar is stored but absent from the tradeable view
    name["rows"] = [r for i, r in enumerate(rows) if i % 10]  # tradeable view hides them
    run = _intraday(_IntradayConn({"AAA": name}))
    assert _verdict(run, "AAA|5m", "slot_coverage")[5] is True


def _load(start, end, *, source="alpaca", outcome="applied", destination="market_data_ohlcv"):
    return {
        "start": start,
        "end": end,
        "source": source,
        "outcome": outcome,
        "destination": destination,
    }


def _thin_name(loads):
    """A name whose stored bars miss one slot in ten (no-trade slots) and which carries `loads`."""
    _, rows = _intraday_series()
    name = _agreeing_name(rows)
    name["slots"] = [r for i, r in enumerate(rows) if i % 10]
    name["rows"] = name["slots"]
    name["loads"] = loads
    return name


def _coverage(name):
    run = _intraday(_IntradayConn({"AAA": name}))
    return _verdict(run, "AAA|5m", "slot_coverage")


def test_a_no_trade_slot_inside_an_applied_load_range_is_answered():
    first, last = _I_DAYS[0], _I_DAYS[-1]
    verdict = _coverage(_thin_name([_load(first - timedelta(days=3), last)]))
    assert verdict[5] is True and verdict[3] == 1.0


def test_a_refused_or_failed_load_answers_nothing():
    first, last = _I_DAYS[0], _I_DAYS[-1]
    for outcome in ("refused", "failed", "no_data", "gated"):
        verdict = _coverage(_thin_name([_load(first, last, outcome=outcome)]))
        assert verdict[5] is False and verdict[3] < 0.95, outcome


def test_a_slot_outside_every_load_range_and_answered_window_stays_missing():
    first, last = _I_DAYS[0], _I_DAYS[-1]
    verdict = _coverage(_thin_name([_load(first, first)]))
    assert verdict[5] is False and verdict[3] < 0.995


def test_the_ibkr_loads_and_the_extended_hours_archive_do_not_answer_slots():
    first, last = _I_DAYS[0], _I_DAYS[-1]
    for load in (_load(first, last, source="ibkr"), _load(first, last, destination="archive")):
        assert _coverage(_thin_name([load]))[5] is False


def test_requested_end_is_inclusive_and_the_day_after_is_not():
    last = _I_DAYS[-1]
    name = _thin_name([_load(_I_DAYS[0] - timedelta(days=3), last - timedelta(days=1))])
    last_day_slots = {r["timestamp"] for r in name["rows"] if r["timestamp"].date() == last}
    inclusive = _coverage(name)
    name["loads"] = [_load(_I_DAYS[0] - timedelta(days=3), last)]
    full = _coverage(name)
    assert full[3] == 1.0 and inclusive[3] < 1.0 and last_day_slots
    name["loads"] = [_load(_I_DAYS[0] - timedelta(days=3), last - timedelta(days=1))]
    assert _coverage(name)[5] is False


def test_a_mismatched_archive_bucket_fails_grid_parity_and_is_named():
    name = _agreeing_name()
    key = next(iter(name["archive"]["15m"]))
    values = list(name["archive"]["15m"][key])
    values[4] += 1.0
    name["archive"]["15m"][key] = tuple(values)
    run = _intraday(_IntradayConn({"AAA": name}))
    verdict = _verdict(run, "AAA|15m", "grid_parity")
    assert verdict[5] is False and verdict[3] == 1.0
    assert run.parity_failing == ["AAA|15m|mismatched=1|compared=52"]
    assert _verdict(run, "AAA|1h", "grid_parity")[5] is True


def test_a_name_without_archive_rows_passes_parity_with_a_null_metric_and_is_counted():
    name = _agreeing_name()
    name["archive"] = {}
    run = _intraday(_IntradayConn({"AAA": name}))
    verdict = _verdict(run, "AAA|15m", "grid_parity")
    assert verdict[5] is True and verdict[3] is None
    assert run.n_without_archive == {"15m": 1, "1h": 1}


def _sip(rows, keep):
    """The rows with those picked by `keep(index)` served by Alpaca SIP at slightly other prices."""
    return [
        (
            {**r, "vendor": "alpaca", "open": r["open"] + 0.01, "close": r["close"] - 0.02}
            if keep(i)
            else r
        )
        for i, r in enumerate(rows)
    ]


def test_ibkr_sourced_five_minute_bars_rebucket_equal_to_the_archive_and_are_counted():
    run = _intraday(_IntradayConn({"AAA": _agreeing_name()}))
    for tf in ("15m", "1h"):
        verdict = _verdict(run, f"AAA|{tf}", "grid_parity")
        assert verdict[5] is True and verdict[3] == 0.0
    assert run.parity_compared["15m"] > 0 and run.parity_compared["1h"] > 0
    assert run.parity_mismatched == {"15m": 0, "1h": 0} and run.n_without_archive == {}


def test_sip_sourced_five_minute_bars_that_differ_from_the_archive_are_not_compared():
    _, rows = _intraday_series()
    name = _agreeing_name(rows)  # the archive is IBKR's: it agrees with the original ibkr bars
    name["rows"] = _sip(rows, lambda i: True)  # canonical 5m is all SIP now, prices differ
    run = _intraday(_IntradayConn({"AAA": name}))
    for tf in ("15m", "1h"):
        verdict = _verdict(run, f"AAA|{tf}", "grid_parity")
        assert verdict[5] is True and verdict[3] is None  # passed, nothing was measured
    assert run.n_without_archive == {"15m": 1, "1h": 1}
    assert run.parity_compared == {} and run.parity_failing == []


def test_an_ibkr_sourced_bucket_that_mismatches_still_fails_beside_sip_buckets():
    _, rows = _intraday_series()
    name = _agreeing_name(rows)
    half = len(rows) // 2
    name["rows"] = _sip(rows, lambda i: i >= half)  # first session ibkr, second session SIP
    key = next(iter(name["archive"]["15m"]))  # a bucket in the ibkr-sourced first session
    values = list(name["archive"]["15m"][key])
    values[4] += 1.0
    name["archive"]["15m"][key] = tuple(values)
    run = _intraday(_IntradayConn({"AAA": name}))
    verdict = _verdict(run, "AAA|15m", "grid_parity")
    assert verdict[5] is False and verdict[3] == 1.0
    assert run.parity_failing[0].startswith("AAA|15m|mismatched=1|compared=")
    assert 1 < run.parity_compared["15m"] < len(name["archive"]["15m"])  # SIP buckets excluded
    assert _verdict(run, "AAA|1h", "grid_parity")[5] is True


def test_a_bucket_with_one_sip_constituent_is_excluded_not_compared_or_failed():
    _, rows = _intraday_series()
    name = _agreeing_name(rows)
    name["rows"] = _sip(rows, lambda i: i == 1)  # one SIP bar inside the first 15m bucket
    run = _intraday(_IntradayConn({"AAA": name}))
    full = len(name["archive"]["15m"])
    verdict = _verdict(run, "AAA|15m", "grid_parity")
    assert verdict[5] is True and verdict[3] == 0.0
    assert run.parity_compared["15m"] == full - 1  # exactly the mixed bucket left out


def test_stray_vendor_rows_fail_per_timeframe():
    run = _intraday(_IntradayConn({"AAA": _agreeing_name()}, stray={("AAA", "15m"): 7}))
    assert _verdict(run, "AAA|15m", "stray_vendor_rows")[3:6] == (7.0, 0.0, False)
    assert _verdict(run, "AAA|1h", "stray_vendor_rows")[5] is True


def test_a_stale_stored_digest_fails_only_its_timeframe():
    name = _agreeing_name()
    month = next(iter(name["digests"]["15m"]))
    name["digests"]["15m"][month] = "0" * 64
    run = _intraday(_IntradayConn({"AAA": name}))
    stale = _verdict(run, "AAA|15m", "digest_fresh")
    assert stale[5] is False and stale[3] == 1.0
    assert _verdict(run, "AAA|5m", "digest_fresh")[5] is True


def test_first_run_is_a_full_sweep_and_writes_the_sweep_fact_once():
    run = _intraday(_IntradayConn({"AAA": _agreeing_name(), "BBB": _agreeing_name()}))
    assert run.full_sweep is True
    sweep = [f for f in run.facts if f[2] == "digest_full_sweep"]
    assert len(sweep) == 1 and sweep[0][1] == "intraday|sweep" and sweep[0][3] == 2.0


def _previous(passed=True, at=datetime(2025, 6, 3, 6, tzinfo=UTC)):
    return {"AAA|5m": (passed, at)}


def test_digest_scope_skips_months_nothing_was_written_in_since_the_previous_report():
    name = _agreeing_name()
    month = next(iter(name["digests"]["5m"]))
    name["digests"]["5m"][month] = "0" * 64  # stale, but no load touched the month
    recent = datetime(2025, 6, 1, 6, tzinfo=UTC)
    run = _intraday(_IntradayConn({"AAA": name}, previous=_previous(), last_sweep=recent))
    assert run.full_sweep is False
    assert _verdict(run, "AAA|5m", "digest_fresh")[5] is True
    assert not [f for f in run.facts if f[2] == "digest_full_sweep"]


def test_a_load_written_since_the_previous_report_brings_its_months_into_scope():
    name = _agreeing_name()
    month = next(iter(name["digests"]["5m"]))
    name["digests"]["5m"][month] = "0" * 64
    load = {
        "symbol": "AAA",
        "loaded_at": datetime(2025, 6, 3, 12, tzinfo=UTC),
        "first_bar": date(2025, 6, 2),
        "last_bar": date(2025, 6, 3),
    }
    run = _intraday(
        _IntradayConn(
            {"AAA": name},
            previous=_previous(),
            last_sweep=datetime(2025, 6, 1, 6, tzinfo=UTC),
            loads=[load],
        )
    )
    assert _verdict(run, "AAA|5m", "digest_fresh")[5] is False


def test_a_sweep_older_than_the_cadence_rechecks_every_month():
    name = _agreeing_name()
    month = next(iter(name["digests"]["5m"]))
    name["digests"]["5m"][month] = "0" * 64
    run = _intraday(
        _IntradayConn(
            {"AAA": name}, previous=_previous(), last_sweep=datetime(2025, 5, 20, 6, tzinfo=UTC)
        )
    )
    assert run.full_sweep is True
    assert _verdict(run, "AAA|5m", "digest_fresh")[5] is False


def test_a_previous_failure_is_rechecked_even_when_nothing_was_written():
    name = _agreeing_name()
    month = next(iter(name["digests"]["5m"]))
    name["digests"]["5m"][month] = "0" * 64
    run = _intraday(
        _IntradayConn(
            {"AAA": name},
            previous=_previous(passed=False),
            last_sweep=datetime(2025, 6, 1, 6, tzinfo=UTC),
        )
    )
    assert _verdict(run, "AAA|5m", "digest_fresh")[5] is False


def test_coverage_cache_drift_names_the_failing_names():
    async def drift(_names):
        return {"BBB": 2}

    run = _intraday(_IntradayConn({"AAA": _agreeing_name(), "BBB": _agreeing_name()}), drift=drift)
    assert _verdict(run, "AAA|5m", "coverage_cache")[5] is True
    bad = _verdict(run, "BBB|5m", "coverage_cache")
    assert bad[5] is False and bad[3] == 2.0
    assert run.failing_by_check["coverage_cache"] == 1


def test_a_held_fetcher_lock_writes_no_coverage_cache_verdict_and_counts_the_skip():
    async def held(_names):
        return None

    run = _intraday(_IntradayConn({"AAA": _agreeing_name(), "BBB": _agreeing_name()}), drift=held)
    assert not [f for f in run.facts if f[2] == "coverage_cache"]
    assert run.coverage_skipped == 2
    assert "coverage_cache" not in run.passing_by_check


class _FakeLock:
    def __init__(self, granted=True):
        self.granted = granted
        self.events: list[str] = []

    def acquire(self):
        self.events.append("acquire")
        return self.granted

    def release(self):
        self.events.append("release")


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        self._last = sql

    def fetchall(self):
        self.conn.reads += 1
        return self.conn.committed if self.conn.reads == 1 else self.conn.rebuilt


class _FakeConnection:
    def __init__(self, committed, rebuilt):
        self.committed, self.rebuilt = committed, rebuilt
        self.reads = 0
        self.executed: list[str] = []
        self.events: list[str] = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.events.append("close")


_LEDGER = (
    "AAA",
    "5m",
    "ibkr",
    datetime(2020, 1, 1, tzinfo=UTC),
    datetime(2025, 1, 1, tzinfo=UTC),
    100,
    "ok",
)


def _drift(lock, conn, rebuild=None):
    calls = []

    def default_rebuild(cur, symbols):
        calls.append(symbols)
        return 0

    result = audit.coverage_cache_drift(
        "dsn",
        ["AAA", "BBB"],
        lock_factory=lambda dsn, holder: lock,
        connect=lambda dsn: conn,
        rebuild=rebuild or default_rebuild,
        lock_wait_seconds=0.0,
        poll_interval_seconds=1.0,
    )
    return result, calls


def test_coverage_cache_rebuild_is_rolled_back_never_committed_and_the_lock_released():
    rebuilt = (*_LEDGER[:5], 101, "ok")  # the rebuild finds one more stored bar than the ledger
    lock, conn = _FakeLock(), _FakeConnection([_LEDGER], [rebuilt])
    result, calls = _drift(lock, conn)
    assert result == {"AAA": 1}
    assert calls == [["AAA", "BBB"]]
    assert "commit" not in conn.events and conn.events == ["rollback", "close"]
    assert any(sql.startswith("SET LOCAL ROLE") for sql in conn.executed)
    assert lock.events == ["acquire", "release"]


def test_coverage_cache_equal_ledger_is_zero_drift_and_a_missing_row_is_drift():
    result, _ = _drift(_FakeLock(), _FakeConnection([_LEDGER], [_LEDGER]))
    assert result == {}
    missing = ("BBB", "15m", "ibkr", None, None, 0, None)
    result, _ = _drift(_FakeLock(), _FakeConnection([_LEDGER], [_LEDGER, missing]))
    assert result == {"BBB": 1}


def test_coverage_cache_keys_rows_by_provider_so_two_vendors_never_collide():
    """One (symbol, timeframe) now carries an ibkr and an alpaca row; keyed without the provider
    the later row would overwrite the earlier and mask or invent drift."""
    alpaca = ("AAA", "5m", "alpaca", _LEDGER[3], _LEDGER[4], 7, None)
    same = _drift(_FakeLock(), _FakeConnection([_LEDGER, alpaca], [alpaca, _LEDGER]))[0]
    assert same == {}
    off = (*alpaca[:5], 8, None)
    result, _ = _drift(_FakeLock(), _FakeConnection([_LEDGER, alpaca], [_LEDGER, off]))
    assert result == {"AAA": 1}


def test_coverage_cache_with_the_lock_held_does_nothing_and_never_connects():
    lock = _FakeLock(granted=False)

    def no_connect(dsn):
        raise AssertionError("connected without the fetcher lock")

    result = audit.coverage_cache_drift(
        "dsn",
        ["AAA"],
        lock_factory=lambda dsn, holder: lock,
        connect=no_connect,
        lock_wait_seconds=0.0,
        poll_interval_seconds=1.0,
    )
    assert result is None and lock.events == ["acquire"]


class _Clock:
    """Injected monotonic clock and sleep: sleeping advances the clock, nothing really waits."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class _LockHeldFor:
    """A lock refused for the first `polls` tries, then granted."""

    def __init__(self, polls):
        self.polls, self.tries, self.events = polls, 0, []

    def acquire(self):
        self.tries += 1
        self.events.append("acquire")
        return self.tries > self.polls

    def release(self):
        self.events.append("release")


def _waiting_drift(lock, clock, *, lock_wait_seconds, poll_interval_seconds=30.0, conn=None):
    calls = []

    def no_connect(dsn):
        raise AssertionError("connected without the fetcher lock")

    result = audit.coverage_cache_drift(
        "dsn",
        ["AAA"],
        lock_factory=lambda dsn, holder: lock,
        connect=(lambda dsn: conn) if conn else no_connect,
        rebuild=lambda cur, symbols: calls.append(symbols) or 0,
        lock_wait_seconds=lock_wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
        sleep_function=clock.sleep,
        clock=clock,
    )
    return result, calls


def test_coverage_cache_waits_for_the_lock_polling_then_runs_the_rebuild():
    lock, clock = _LockHeldFor(3), _Clock()
    conn = _FakeConnection([_LEDGER], [_LEDGER])
    result, calls = _waiting_drift(lock, clock, lock_wait_seconds=600, conn=conn)
    assert result == {}
    assert lock.tries == 4 and clock.sleeps == [30.0, 30.0, 30.0]
    assert calls == [["AAA"]]
    assert lock.events == ["acquire"] * 4 + ["release"]


def test_coverage_cache_held_past_the_bound_returns_none_and_never_connects():
    lock, clock = _LockHeldFor(10**9), _Clock()
    result, calls = _waiting_drift(lock, clock, lock_wait_seconds=100, poll_interval_seconds=30)
    assert result is None and calls == []
    assert sum(clock.sleeps) == 100 and clock.sleeps[-1] == 10  # the last sleep is clipped
    assert lock.events == ["acquire"] * len(lock.events)  # never released: never held


def test_coverage_cache_with_a_free_lock_does_not_wait():
    lock, clock = _LockHeldFor(0), _Clock()
    conn = _FakeConnection([_LEDGER], [_LEDGER])
    result, _ = _waiting_drift(lock, clock, lock_wait_seconds=600, conn=conn)
    assert result == {} and clock.sleeps == [] and lock.tries == 1


def test_coverage_cache_default_is_a_single_try():
    lock, clock = _LockHeldFor(1), _Clock()
    result, _ = _waiting_drift(lock, clock, lock_wait_seconds=0)
    assert result is None and clock.sleeps == [] and lock.tries == 1


def test_the_lock_wait_bounds_are_apr_keys_with_documented_defaults():
    params = audit._IntegrityParams.from_apr(
        {
            "infra.bar_integrity.coverage_cache_lock_wait_s": "7200",
            "infra.bar_integrity.coverage_cache_lock_poll_s": "10",
        }
    )
    assert (params.coverage_cache_lock_wait_seconds, params.coverage_cache_lock_poll_seconds) == (
        7200,
        10,
    )
    default = audit._IntegrityParams.from_apr({})
    assert (default.coverage_cache_lock_wait_seconds, default.coverage_cache_lock_poll_seconds) == (
        21600,
        30,
    )
    assert "infra.bar_integrity.%" in audit._APR_PATTERNS


def test_coverage_cache_releases_the_lock_and_rolls_back_when_the_rebuild_raises():
    lock, conn = _FakeLock(), _FakeConnection([_LEDGER], [_LEDGER])

    def boom(cur, symbols):
        raise RuntimeError("rebuild failed")

    with pytest.raises(RuntimeError, match="rebuild failed"):
        _drift(lock, conn, rebuild=boom)
    assert conn.events == ["rollback", "close"]
    assert lock.events == ["acquire", "release"]


def test_the_lock_holder_names_the_audit_job():
    seen = {}

    def factory(dsn, holder):
        seen["holder"] = holder
        return _FakeLock(granted=False)

    audit.coverage_cache_drift(
        "dsn", ["AAA"], lock_factory=factory, lock_wait_seconds=0.0, poll_interval_seconds=1.0
    )
    assert seen["holder"] == "bar-reconciliation-audit"


def test_intraday_report_is_written_with_a_read_back_that_counts_the_1d_rows_too():
    import asyncio

    conn = _IntradayConn({"AAA": _agreeing_name()})
    run = _intraday(conn)

    class _Count(_IntradayConn):
        async def executemany(self, sql, facts):
            self.facts.extend(facts)

    counting = _Count({})
    asyncio.run(audit.BarReconciliationAudit._write_verdicts(counting, run, _I_NOW, already=0))
    assert len(counting.facts) == len(run.facts)

    class _Short(_Count):
        async def fetchval(self, sql, *args):
            return len(run.facts)  # the 1d rows are missing from the read-back

    with pytest.raises(RuntimeError, match="wrote"):
        asyncio.run(
            audit.BarReconciliationAudit._write_verdicts(_Short({}), run, _I_NOW, already=5)
        )


def test_intraday_keys_are_loaded_by_the_audit():
    assert "infra.bar_integrity.%" in audit._APR_PATTERNS
    params = audit._IntegrityParams.from_apr(
        {
            "threshold.bar_integrity.slot_coverage_min_intraday": 0.99,
            "infra.bar_integrity.intraday_full_sweep_days": 3,
        }
    )
    assert params.slot_coverage_min_intraday == 0.99 and params.intraday_full_sweep_days == 3


# ---------------------------------------------------------------------------
# Alert gauges (plan 185-41; design section 8): failing names per check, the report age and its
# APR maximum, and refused or gated loads by source. No metric carries a job or symbol label
# (todo 498: the collector drops metrics with a job label).
# ---------------------------------------------------------------------------


class _Gauge:
    def __init__(self):
        self.points: list[tuple[float, dict]] = []

    def set(self, value, attributes=None):
        self.points.append((value, dict(attributes or {})))


def _patched_gauges(monkeypatch):
    gauges = {
        name: _Gauge()
        for name in (
            "BAR_INTEGRITY_FAILING_NAMES",
            "BAR_INTEGRITY_REPORT_AGE_SECONDS",
            "BAR_INTEGRITY_REPORT_MAX_AGE_SECONDS",
            "OHLCV_LOAD_REFUSED_24H",
        )
    }
    for name, gauge in gauges.items():
        monkeypatch.setattr(audit, name, gauge)
    return gauges


def test_failing_names_merge_sums_a_check_that_runs_on_both_reports():
    merged = audit.merge_failing_by_check(
        {"session_coverage": 240, "digest_fresh": 0},
        {"digest_fresh": 2, "slot_coverage": 240},
    )
    assert merged == {"session_coverage": 240, "digest_fresh": 2, "slot_coverage": 240}


def test_alert_gauges_record_each_check_the_age_the_max_and_every_load_source(monkeypatch):
    gauges = _patched_gauges(monkeypatch)
    now = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    audit.record_alert_gauges(
        failing_by_check={"session_coverage": 240, "grid_parity": 0},
        previous_verdict_at=now - timedelta(hours=24),
        run_start=now,
        max_age_hours=30,
        refused_by_source={"ibkr": 2},
    )
    assert sorted(gauges["BAR_INTEGRITY_FAILING_NAMES"].points, key=lambda p: p[1]["check"]) == [
        (0, {"check": "grid_parity"}),
        (240, {"check": "session_coverage"}),
    ]
    assert gauges["BAR_INTEGRITY_REPORT_AGE_SECONDS"].points == [(86400.0, {})]
    assert gauges["BAR_INTEGRITY_REPORT_MAX_AGE_SECONDS"].points == [(108000.0, {})]
    # A source with no refusals records zero, so an alert clears when the refusals stop.
    assert sorted(gauges["OHLCV_LOAD_REFUSED_24H"].points, key=lambda p: p[1]["source"]) == [
        (0, {"source": "derived"}),
        (2, {"source": "ibkr"}),
    ]
    attribute_keys = {
        key for gauge in gauges.values() for _, attributes in gauge.points for key in attributes
    }
    assert attribute_keys == {"check", "source"}  # never job, symbol or subject


def test_the_first_ever_report_has_no_age_to_record(monkeypatch):
    gauges = _patched_gauges(monkeypatch)
    now = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    audit.record_alert_gauges(
        failing_by_check={},
        previous_verdict_at=None,
        run_start=now,
        max_age_hours=30,
        refused_by_source={},
    )
    assert gauges["BAR_INTEGRITY_REPORT_AGE_SECONDS"].points == []
    assert gauges["BAR_INTEGRITY_REPORT_MAX_AGE_SECONDS"].points == [(108000.0, {})]


def test_the_load_source_labels_are_the_writers_that_still_load():
    # ohlcv_load.source still admits tradier (history); plan 185-48 deleted its loader, so
    # no tradier load can be refused and the gauge records only the live writers.
    assert set(audit.LOAD_SOURCES) == {"ibkr", "derived"}
    assert "outcome IN ('refused', 'gated')" in audit._REFUSED_LOADS_24H_SQL
    assert "bar_integrity" in audit._MONITOR_TYPE_VERDICT


# --- held names (plan 185-51, todo 515) ----------------------------------------------------


def _ctva_hold(symbol="AAA"):
    from services.bar_hold import Hold

    return Hold(
        hold_id="aaaaaaaa-0000-0000-0000-000000000001",
        symbol=symbol,
        timeframe="1d",
        reason="unclassified_rescale",
        factor=39 / 7,
        first_affected_date=date(2019, 5, 24),
        last_affected_date=date(2026, 9, 30),
        action_id=None,
        detail={},
        recorded_by="ops_split_detect",
        recorded_at=datetime(2026, 10, 8, tzinfo=UTC),
    )


def test_a_held_name_fails_held_1d_and_its_stale_freshness_names_the_cause():
    import asyncio

    stale = _good_name()
    stale["stored"] = stale["stored"][:1]
    stale["observations"] = stale["observations"][:1]
    stale["digests"] = []

    class _Late(_Window):
        last_session = date(2024, 1, 9)

    run = asyncio.run(
        audit.BarReconciliationAudit._verdict_report_1d(
            _FakeConn({"AAA": stale, "BBB": _good_name()}),
            audit._IntegrityParams.from_apr({}),
            _Late(),
            ["AAA", "BBB"],
            [],
            _NOW,
            holds={"AAA": (_ctva_hold(),)},
        )
    )
    verdicts = {(f[1], f[2]): f for f in run.facts}
    assert verdicts[("AAA|1d", "held_1d")][3] == 1.0 and verdicts[("AAA|1d", "held_1d")][5] is False
    assert verdicts[("BBB|1d", "held_1d")][3] == 0.0 and verdicts[("BBB|1d", "held_1d")][5] is True
    assert "held_1d" not in run.failing_by_check  # informational: never a gate check
    (sample,) = run.held_stale
    assert sample.startswith("AAA: freshness_1d 5 sessions behind; held: unclassified_rescale")


def test_the_held_names_check_reports_every_hold_with_its_cause():
    result = audit.check_held_names({"CTVA": (_ctva_hold("CTVA"),)})
    assert result.n_findings == 1
    assert result.samples == (
        "CTVA: unclassified_rescale factor 5.5714 over 2019-05-24..2026-09-30, held since 2026-10-08",
    )
    assert audit.check_held_names({}).n_findings == 0


def test_explained_dates_read_only_current_corporate_actions():
    assert "FROM corporate_action_current" in audit._EXPLAINED_DATES_SQL


def test_d7_has_no_tradier_refused_check():
    """Plan 185-48: the Tradier loader is deleted, so no Tradier load can be refused. The
    generic refusal gauge covers the ibkr and derived writers."""
    from tests.unit._source_grep_helpers import read_source

    source = read_source("services/bar_reconciliation_audit.py")
    assert "tradier_refused" not in source
    assert not hasattr(audit, "check_tradier_refused")
    assert not hasattr(audit, "_TRADIER_LATEST_LOAD_SQL")
    assert "_REFUSED_LOADS_24H_SQL" in source


# ---------------------------------------------------------------------------
# Plan 191-09: D7 reads ohlcv_raw and ohlcv_revision; ADJUSTED_LAST pairs by D-191-D.
# ---------------------------------------------------------------------------


def test_d7_reads_no_retired_store():
    import re

    source = read_source("services", "bar_reconciliation_audit.py")
    assert not re.search(
        r"(FROM|JOIN|INTO|COPY)\s+(ohlcv_observation|ohlcv_intraday_raw_archive)\b", source
    )
    assert "FROM ohlcv_raw" in audit._ARCHIVE_ROWS_SQL and "kind = 'named'" in (
        audit._ARCHIVE_ROWS_SQL
    )
    assert "q.route = 'SMART'" in audit._SMART_OBS_SQL
    assert "FROM ohlcv_venue_head" in audit._VENUE_FIRST_SQL
    assert not hasattr(audit, "_SMART_HEAD_SQL")


_DAY1, _DAY2, _DAY3 = date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9)
_T_OLD = datetime(2026, 10, 10, 1, tzinfo=UTC)  # an earlier run's serve
_T_RUN = datetime(2026, 10, 10, 2, tzinfo=UTC)  # the adjusted run's serves
_T_END = datetime(2026, 10, 10, 2, 5, tzinfo=UTC)  # the adjusted run's last answer
_T_LATER = datetime(2026, 10, 11, 2, tzinfo=UTC)  # a later serve
_RUN = audit.AdjustedRun(
    run_end=_T_END,
    adjusted_from=datetime(2026, 10, 7, tzinfo=UTC),
    adjusted_to=datetime(2026, 10, 10, tzinfo=UTC),
    adjusted_answered=_T_RUN,
)
_T, _A = "smart_trades", "smart_adjusted"
_ADJ = {(_A, d): (9.0, _T_RUN) for d in (_DAY1, _DAY2, _DAY3)}


def test_value_as_of_reads_back_through_the_revision_log():
    # Held then, overwritten later: the displaced value is the one held.
    assert audit.value_as_of((20.0, _T_LATER), [(10.0, _T_LATER)], _T_END) == 10.0
    # Two overwrites after the time: the earliest one displaced the value held.
    later2 = _T_LATER + timedelta(days=1)
    assert audit.value_as_of((30.0, later2), [(20.0, later2), (10.0, _T_LATER)], _T_END) == 10.0
    # An overwrite before the time does not matter; the current value was held.
    assert audit.value_as_of((20.0, _T_OLD), [(10.0, _T_OLD)], _T_END) == 20.0
    # First served after the time: nothing was held.
    assert audit.value_as_of((20.0, _T_LATER), [], _T_END) is None
    assert audit.value_as_of(None, [], _T_END) is None


def test_d7_trades_restated_after_the_adjusted_run_never_pairs_by_ordering():
    # DAY2's TRADES value was restated after the run: the value held when the run ended pairs,
    # the restated one never does.
    current = {
        **_ADJ,
        (_T, _DAY1): (10.0, _T_OLD),
        (_T, _DAY2): (20.0, _T_LATER),
        (_T, _DAY3): (10.0, _T_OLD),
    }
    displaced = {(_T, _DAY2): [(10.0, _T_LATER)]}
    rows = audit.adjusted_pairs(_RUN, current, displaced, _DAY1)
    assert rows == [(_DAY1, 10.0, 9.0), (_DAY2, 10.0, 9.0), (_DAY3, 10.0, 9.0)]


def test_the_runs_own_trades_answer_pairs_even_when_restated_later():
    # The run itself changed DAY2's TRADES value (11.0, displacing 10.0 at the run's serve);
    # a later serve restated it again (20.0). The run's own answer pairs.
    current = {**_ADJ, (_T, _DAY2): (20.0, _T_LATER)}
    displaced = {(_T, _DAY2): [(10.0, _T_RUN), (11.0, _T_LATER)]}
    assert audit.adjusted_pairs(_RUN, current, displaced, _DAY1) == [(_DAY2, 11.0, 9.0)]


def test_d7_trades_unchanged_for_the_date_pairs_although_the_name_split_later():
    # The name split later (DAY3's TRADES restated after the run); DAY1 and DAY2 kept their
    # value, served before the run, so they pair; DAY3 pairs its value held at the run.
    current = {
        **_ADJ,
        (_T, _DAY1): (10.0, _T_OLD),
        (_T, _DAY2): (10.0, _T_OLD),
        (_T, _DAY3): (5.0, _T_LATER),
    }
    displaced = {(_T, _DAY3): [(10.0, _T_LATER)]}
    assert audit.adjusted_pairs(_RUN, current, displaced, _DAY1) == [
        (_DAY1, 10.0, 9.0),
        (_DAY2, 10.0, 9.0),
        (_DAY3, 10.0, 9.0),
    ]


def test_a_whole_history_ask_pairs_from_pair_from_to_the_day_before_its_answer():
    run = audit.AdjustedRun(_T_END, None, None, _T_RUN)
    current = {**_ADJ, **{(_T, d): (10.0, _T_OLD) for d in (_DAY1, _DAY2, _DAY3)}}
    assert [d for d, _, _ in audit.adjusted_pairs(run, current, {}, _DAY2)] == [_DAY2, _DAY3]


def test_pairs_start_at_pair_from_and_stop_before_the_answer_date():
    current = {**_ADJ, **{(_T, d): (10.0, _T_OLD) for d in (_DAY1, _DAY2, _DAY3)}}
    current[(_A, date(2026, 10, 10))] = (9.0, _T_RUN)  # forming: answered on its own date
    current[(_T, date(2026, 10, 10))] = (10.0, _T_RUN)
    assert audit.adjusted_pairs(_RUN, current, {}, _DAY2) == [
        (_DAY2, 10.0, 9.0),
        (_DAY3, 10.0, 9.0),
    ]


class _FakePool:
    def acquire(self):
        class _Ctx:
            async def __aenter__(self):
                return "conn"

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def _coverage_step(monkeypatch, drift):
    """Run the deferred coverage step over a run of two names; returns (run, write calls, seen)."""
    import asyncio

    run = _intraday(_IntradayConn({"AAA": _agreeing_name(), "BBB": _agreeing_name()}), drift=None)
    seen, writes = {}, []

    def fake_drift(dsn, names, **kwargs):
        seen.update(names=names, **kwargs)
        return drift

    async def fake_write(conn, part, run_start, *, already=0):
        writes.append((list(part.facts), already))

    monkeypatch.setattr(audit, "coverage_cache_drift", fake_drift)
    monkeypatch.setattr(audit.BarReconciliationAudit, "_write_verdicts", staticmethod(fake_write))
    step = object.__new__(audit.BarReconciliationAudit)
    step._db_dsn = "dsn"
    integ = audit._IntegrityParams(
        **{
            **_I_PARAMS.__dict__,
            "coverage_cache_lock_wait_seconds": 900,
            "coverage_cache_lock_poll_seconds": 5,
        }
    )
    out = asyncio.run(step._coverage_step(_FakePool(), integ, _IWindow(), _I_NOW, run, already=7))
    return run, out, writes, seen


def test_the_deferred_report_has_no_coverage_cache_rows_and_no_skip():
    run = _intraday(_IntradayConn({"AAA": _agreeing_name()}), drift=None)
    assert not [f for f in run.facts if f[2] == "coverage_cache"]
    assert run.coverage_skipped == 0 and run.names == ("AAA",)


def test_the_coverage_step_waits_with_the_apr_bounds_and_writes_a_second_group(monkeypatch):
    run, out, writes, seen = _coverage_step(monkeypatch, {"BBB": 2})
    assert (seen["names"], seen["lock_wait_seconds"], seen["poll_interval_seconds"]) == (
        ["AAA", "BBB"],
        900,
        5,
    )
    assert len(writes) == 1 and writes[0][1] == 7 + len(run.facts)
    assert {f[1]: f[5] for f in writes[0][0]} == {"AAA|5m": True, "BBB|5m": False}
    assert out.failing_by_check["coverage_cache"] == 1
    assert out.passing_by_check["coverage_cache"] == 1
    assert out.coverage_skipped == 0 and len(out.facts) == len(run.facts) + 2


def test_the_coverage_step_counts_the_skip_when_the_lock_stays_held(monkeypatch):
    _, out, writes, _ = _coverage_step(monkeypatch, None)
    assert writes == [] and out.coverage_skipped == 2
    assert not [f for f in out.facts if f[2] == "coverage_cache"]


def test_a_database_error_while_polling_is_a_missed_try_not_a_failed_audit():
    class _FlakyLock:
        def __init__(self):
            self.tries = 0

        def acquire(self):
            self.tries += 1
            if self.tries == 1:
                raise audit.psycopg.OperationalError("server closed the connection")
            return False

        def release(self):
            raise AssertionError("released a lock never held")

    lock = _FlakyLock()
    clock = _Clock()
    result = audit.coverage_cache_drift(
        "dsn",
        ["AAA"],
        lock_factory=lambda dsn, holder: lock,
        connect=lambda dsn: (_ for _ in ()).throw(AssertionError("connected without the lock")),
        lock_wait_seconds=60.0,
        poll_interval_seconds=30.0,
        sleep_function=clock.sleep,
        clock=clock,
    )
    assert result is None and lock.tries >= 2
