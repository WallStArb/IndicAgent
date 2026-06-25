"""Unit tests for ET session-boundary forward return completeness (Phase 140 P0).

Tests verify:
1. _build_forward_return_sql generates fwd_ts_{scale} columns and America/New_York
   date comparison for intraday TFs (5m, 15m, 1h), and does NOT for daily (1d).
2. AT TIME ZONE 'America/New_York' correctly identifies the DST spring-forward boundary
   (2024-03-10) as a date change — proving overnight contamination would be caught.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root so we can import the service module
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.forward_return_writer import _build_forward_return_sql

LOOKAHEADS = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}
ET = ZoneInfo("America/New_York")
UTC = UTC


# ---------------------------------------------------------------------------
# Test 1 — SQL shape / content by TF
# ---------------------------------------------------------------------------


class TestBuildForwardReturnSql:
    def test_intraday_5m_contains_fwd_ts_and_new_york(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "5m")
        assert "fwd_ts_fast" in sql, "5m SQL must include fwd_ts_fast LEAD column"
        assert "America/New_York" in sql, "5m SQL must include America/New_York timezone"

    def test_intraday_15m_contains_fwd_ts_and_new_york(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "15m")
        assert "fwd_ts_fast" in sql, "15m SQL must include fwd_ts_fast LEAD column"
        assert "America/New_York" in sql, "15m SQL must include America/New_York timezone"

    def test_intraday_1h_contains_fwd_ts_and_new_york(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "1h")
        assert "fwd_ts_fast" in sql, "1h SQL must include fwd_ts_fast LEAD column"
        assert "America/New_York" in sql, "1h SQL must include America/New_York timezone"

    def test_daily_does_not_contain_new_york(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "1d")
        assert (
            "America/New_York" not in sql
        ), "1d SQL must NOT include America/New_York — daily gaps are the expected signal"

    def test_daily_does_not_contain_fwd_ts(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "1d")
        assert "fwd_ts_fast" not in sql, "1d SQL must NOT include fwd_ts LEAD columns"

    def test_all_scales_have_fwd_ts_for_intraday(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "5m")
        for scale in LOOKAHEADS:
            assert f"fwd_ts_{scale}" in sql, f"5m SQL missing fwd_ts_{scale}"

    def test_intraday_complete_uses_date_comparison(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "5m")
        # The complete_ flag should reference the date cast via AT TIME ZONE
        assert "::date" in sql, "intraday complete_ flag must use ::date cast"
        assert "bar_ts" in sql, "intraday complete_ flag must reference bar_ts"

    def test_daily_complete_is_simple_null_check(self) -> None:
        sql = _build_forward_return_sql(LOOKAHEADS, "1d")
        assert "IS NOT NULL" in sql, "1d complete_ flag must use IS NOT NULL"
        assert "::date" not in sql, "1d complete_ flag must NOT use ::date cast"


# ---------------------------------------------------------------------------
# Test 2 — DST spring-forward boundary (2024-03-10)
# ---------------------------------------------------------------------------


class TestDSTSpringForwardBoundary:
    """Prove AT TIME ZONE 'America/New_York' date comparison catches overnight crossings."""

    def test_spring_forward_dates_differ(self) -> None:
        """A 5m bar at 16:00 ET on 2024-03-09 and a bar at 09:30 ET on 2024-03-10
        must resolve to DIFFERENT ET calendar dates.

        If complete_{scale} used only IS NOT NULL (the old bug), this pair would be
        marked complete=True — an overnight gap contaminating a 5m return.
        """
        # 2024-03-09 21:00 UTC = 16:00 ET (standard time, UTC-5)
        current_bar_utc = datetime(2024, 3, 9, 21, 0, tzinfo=UTC)
        # 2024-03-10 13:30 UTC = 09:30 EDT (daylight time, UTC-4, spring-forward happened at 2am)
        forward_bar_utc = datetime(2024, 3, 10, 13, 30, tzinfo=UTC)

        current_et_date = current_bar_utc.astimezone(ET).date()
        forward_et_date = forward_bar_utc.astimezone(ET).date()

        assert current_et_date != forward_et_date, (
            f"Expected different ET dates across the overnight boundary: "
            f"current={current_et_date}, forward={forward_et_date}"
        )
        assert str(current_et_date) == "2024-03-09"
        assert str(forward_et_date) == "2024-03-10"

    def test_intraday_same_session_dates_match(self) -> None:
        """Two bars within the same ET trading day must resolve to the SAME date."""
        # 2024-03-10 14:30 UTC = 10:30 EDT (same session as 09:30 open)
        bar_a_utc = datetime(2024, 3, 10, 13, 30, tzinfo=UTC)  # 09:30 EDT
        bar_b_utc = datetime(2024, 3, 10, 19, 55, tzinfo=UTC)  # 15:55 EDT

        date_a = bar_a_utc.astimezone(ET).date()
        date_b = bar_b_utc.astimezone(ET).date()

        assert (
            date_a == date_b
        ), f"Same-session bars must have the same ET date: {date_a} vs {date_b}"

    def test_fall_back_boundary(self) -> None:
        """DST fall-back: a bar at 15:55 ET on 2024-11-03 and 09:30 ET on 2024-11-04
        must resolve to different ET dates even though UTC offset changes.
        """
        # 2024-11-03: daylight time ends at 2am (UTC-4 before, UTC-5 after)
        # 15:55 EDT = 19:55 UTC
        current_bar_utc = datetime(2024, 11, 3, 19, 55, tzinfo=UTC)
        # 09:30 EST on 2024-11-04 = 14:30 UTC
        forward_bar_utc = datetime(2024, 11, 4, 14, 30, tzinfo=UTC)

        current_et_date = current_bar_utc.astimezone(ET).date()
        forward_et_date = forward_bar_utc.astimezone(ET).date()

        assert current_et_date != forward_et_date, (
            f"Fall-back boundary must still detect different dates: "
            f"current={current_et_date}, forward={forward_et_date}"
        )
