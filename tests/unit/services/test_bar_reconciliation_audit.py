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
    VendorAgreementAccumulator,
    aggregate_sessions,
    bucket_fine_volume,
    check_adjusted_vs_trades,
    check_completeness,
    check_daily_vs_intraday,
    check_dividend_freshness,
    check_late_heads,
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
    def test_sources_the_derivation_does_not_write_count(self):
        counts = {
            ("1d", "ibkr_named"): 10,
            ("1d", "ibkr_venue"): 1,
            ("1d", "tradier"): 50,
            ("1d", "synthetic_fill"): 4,
            ("1d", "yahoo"): 2,
            ("15m", "derived_5m"): 100,
            ("15m", "synthetic_fill"): 3,
            ("15m", "ibkr_named"): 7,
            ("1h", None): 1,
            ("5m", "ibkr_named"): 999,  # 5m is not a derived timeframe: not judged
        }
        result = check_stray_sources(counts)
        assert result.n_findings == 2 + 7 + 1
        assert set(result.samples) == {"1d:yahoo=2", "15m:ibkr_named=7", "1h:NULL=1"}

    def test_tradier_is_an_admitted_daily_source(self):
        assert check_stray_sources({("1d", "tradier"): 5}).n_findings == 0


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
# Vendor agreement (Tradier vs IBKR SMART TRADES, migration 438)
# ---------------------------------------------------------------------------


class TestVendorAgreement:
    def test_share_differing_and_median_volume_ratio_per_year(self):
        acc = VendorAgreementAccumulator(15.0)
        acc.add(
            [
                (2006, 100.0, 100.0, 90, 100),
                (2006, 100.0, 100.5, 100, 100),  # 50 bp: differs
                (2006, 100.0, 100.1, 80, 100),  # 10 bp: agrees
                (2026, 10.0, 10.0, 55, 100),
            ]
        )
        acc.add([(2026, 10.0, 10.0, 60, 0)])  # zero Tradier volume: no ratio, close still counts
        years = acc.result()
        assert set(years) == {2006, 2026}
        assert years[2006].n_both == 3
        assert years[2006].n_differ == 1
        assert years[2006].share_differ == pytest.approx(1 / 3)
        assert years[2006].median_volume_ratio == pytest.approx(0.9)
        assert years[2026].n_both == 2
        assert years[2026].median_volume_ratio == pytest.approx(0.55)


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
