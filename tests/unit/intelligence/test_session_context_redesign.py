# tests/unit/intelligence/test_session_context_redesign.py
from datetime import UTC, datetime

import pandas as pd

UTC = UTC


def make_df(utc_ts: datetime) -> dict:
    """Minimal frames dict with a single-row DataFrame for test."""
    df = pd.DataFrame(
        [
            {
                "timestamp": utc_ts,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 100,
            }
        ]
    )
    return {"main": df}


def run(utc_ts: datetime) -> dict:
    from src.intelligence.context.session_context import SessionContextPlugin

    p = SessionContextPlugin()
    return p.compute_full(make_df(utc_ts))


def utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


EXPECTED_27_OUTPUTS = {
    # existing 12
    "session_asia",
    "session_london",
    "session_ny",
    "session_london_ny_overlap",
    "session_after_hours",
    "in_london_killzone",
    "in_ny_killzone",
    "minutes_to_ny_open",
    "minutes_to_london_open",
    "bars_since_session_start",
    "is_monday",
    "is_friday",
    # new: exchange active flags (6)
    "session_nyse_active",
    "session_lse_active",
    "session_tse_active",
    "session_hkex_active",
    "session_sse_active",
    "session_asx_active",
    # new: trading break flags (3)
    "session_tse_in_break",
    "session_hkex_in_break",
    "session_sse_in_break",
    # new: overlaps (2)
    "session_tokyo_london_overlap",
    "session_ny_sydney_overlap",
    # new: sub-session (4)
    "session_elapsed_frac",
    "is_opening_range",
    "is_lunch_consolidation",
    "is_power_hour",
}


class TestOutputCount:
    def test_all_27_outputs_present(self):
        result = run(utc(2026, 3, 10, 15, 0))  # Tuesday 15:00 UTC
        assert set(result.keys()) == EXPECTED_27_OUTPUTS

    def test_outputs_frozenset_matches(self):
        from src.intelligence.context.session_context import SessionContextPlugin

        p = SessionContextPlugin()
        assert p.outputs == EXPECTED_27_OUTPUTS


class TestDSTFix:
    """DST transition: 2026-03-08 02:00 US clocks spring forward (EST→EDT).
    After transition: NY open 09:30 EDT = 13:30 UTC (not 14:30 as with hardcoded UTC-5).
    """

    def test_ny_session_open_post_dst_1330_utc(self):
        # 2026-03-09 Monday — first post-DST trading day
        # 09:30 EDT = 13:30 UTC → should be session_ny > 0 (gradient, not binary)
        result = run(utc(2026, 3, 9, 13, 30))
        assert result["session_ny"] > 0.0
        assert 0.0 <= result["session_ny"] <= 1.0

    def test_ny_session_closed_at_1330_pre_dst(self):
        # 2026-03-03 Tuesday — pre-DST
        # 09:30 EST = 14:30 UTC; 13:30 UTC = 08:30 EST → not yet open
        result = run(utc(2026, 3, 3, 13, 30))
        assert result["session_ny"] == 0.0

    def test_session_ny_active_flag_matches_ny_session(self):
        # session_nyse_active should be > 0 when open (gradient)
        result_open = run(utc(2026, 3, 9, 15, 0))  # 11:00 EDT — open
        result_closed = run(utc(2026, 3, 9, 20, 30))  # 16:30 EDT — closed
        assert result_open["session_nyse_active"] > 0.0
        assert result_closed["session_nyse_active"] == 0.0


class TestExchangeActiveFlags:
    def test_lse_open_during_london_morning(self):
        # LSE 08:00-16:30 London time; in March (GMT): 08:00 UTC → open at 09:00 UTC
        result = run(utc(2026, 3, 10, 9, 0))
        assert result["session_lse_active"] > 0.0

    def test_tse_open_during_morning(self):
        # TSE 09:00-15:30 JST; JST = UTC+9; 09:00 JST = 00:00 UTC
        result = run(utc(2026, 3, 10, 0, 30))  # 09:30 JST — open
        assert result["session_tse_active"] > 0.0

    def test_tse_in_break(self):
        # 11:30-12:30 JST = 02:30-03:30 UTC
        result = run(utc(2026, 3, 10, 2, 45))  # 11:45 JST — in break
        assert result["session_tse_active"] > 0.0  # is_open still True
        assert result["session_tse_in_break"] > 0.0

    def test_asx_closed_during_us_hours(self):
        # ASX 10:00-16:00 AEDT (UTC+11 in March) = 23:00-05:00 UTC
        # During US hours 14:30 UTC = 01:30 AEDT next day — after close
        result = run(utc(2026, 3, 10, 14, 30))
        assert result["session_asx_active"] == 0.0

    def test_nyse_not_open_on_weekend(self):
        # Saturday
        result = run(utc(2026, 3, 14, 15, 0))
        assert result["session_nyse_active"] == 0.0


class TestOverlapFlags:
    def test_tokyo_london_overlap(self):
        # TSE and LSE don't overlap in March UTC; check flag is 0.0 when they don't overlap
        result = run(utc(2026, 3, 10, 5, 0))  # 05:00 UTC: TSE open (14:00 JST), LSE closed
        assert result["session_tokyo_london_overlap"] == 0.0

    def test_london_ny_overlap(self):
        # LSE 08:00-16:30 UTC (March GMT); NYSE 13:30-20:00 UTC (post-DST March)
        # Overlap: 13:30-16:30 UTC — gradient > 0 when both open
        result = run(utc(2026, 3, 10, 15, 0))  # 15:00 UTC: both open
        assert result["session_london_ny_overlap"] > 0.0


class TestSubSessionOutputsNoInstrument:
    """When frames has no __instrument__, sub-session outputs default to 0.0."""

    def test_sub_session_defaults_to_zero_without_instrument(self):
        result = run(utc(2026, 3, 10, 15, 0))
        assert result["session_elapsed_frac"] == 0.0
        assert result["is_opening_range"] == 0.0
        assert result["is_lunch_consolidation"] == 0.0
        assert result["is_power_hour"] == 0.0


class TestSubSessionWithInstrument:
    """With __instrument__ in frames, sub-session outputs are computed."""

    def _run_with_instrument(self, utc_ts: datetime, session_id: str) -> dict:
        from src.core.models import AssetClass, Instrument
        from src.intelligence.context.session_context import SessionContextPlugin

        p = SessionContextPlugin()
        df = pd.DataFrame(
            [
                {
                    "timestamp": utc_ts,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 100,
                }
            ]
        )
        inst = Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id=session_id)
        return p.compute_full({"main": df, "__instrument__": inst})

    def test_elapsed_frac_near_zero_at_open(self):
        # NYSE 09:30 EST (pre-DST): 14:30 UTC
        result = self._run_with_instrument(utc(2026, 3, 3, 14, 30), "nyse")
        assert result["session_elapsed_frac"] is not None
        assert abs(result["session_elapsed_frac"]) < 0.01

    def test_is_opening_range_first_30_min(self):
        # NYSE 09:35 EST = 14:35 UTC (pre-DST, 5 min in) — gradient should be > 0
        result = self._run_with_instrument(utc(2026, 3, 3, 14, 35), "nyse")
        assert result["is_opening_range"] > 0.0
        assert 0.0 <= result["is_opening_range"] <= 1.0

    def test_not_opening_range_after_30_min(self):
        # NYSE 10:01 EST = 15:01 UTC (pre-DST, 31 min in) — gradient decays to 0
        result = self._run_with_instrument(utc(2026, 3, 3, 15, 1), "nyse")
        assert result["is_opening_range"] == 0.0

    def test_is_power_hour_last_60_min(self):
        # NYSE 15:30 EST = 20:30 UTC (pre-DST, 60 min before close) — gradient > 0
        result = self._run_with_instrument(utc(2026, 3, 3, 20, 30), "nyse")
        assert result["is_power_hour"] > 0.0
        assert 0.0 <= result["is_power_hour"] <= 1.0

    def test_no_sub_session_for_futures_allday(self):
        # futures_24_5 is all-day → elapsed_frac should be 0.0 (session returns None)
        result = self._run_with_instrument(utc(2026, 3, 10, 15, 0), "futures_24_5")
        assert result["session_elapsed_frac"] == 0.0


class TestGradientContinuity:
    """Verify that session flags output continuous values for mid-session times."""

    def test_session_asia_mid_window_gradient(self):
        # Asia session 20:00-04:00 ET. At 00:00 ET (05:00 UTC in March, post-DST)
        # this is mid-session — should be non-binary (0 < x < 1)
        # 2026-03-09 05:00 UTC = 01:00 ET (mid-Asia session)
        result = run(utc(2026, 3, 9, 5, 0))
        assert 0.0 < result["session_asia"] < 1.0

    def test_session_ny_mid_session_gradient(self):
        # NY session 09:30-16:00 ET. At 12:45 ET (17:45 UTC post-DST) = midpoint
        result = run(utc(2026, 3, 9, 17, 45))
        assert 0.0 < result["session_ny"] < 1.0

    def test_session_london_mid_session_gradient(self):
        # London session 03:00-12:00 ET. At 07:30 ET (12:30 UTC post-DST March 9)
        # Note: March 9 post-DST, 12:30 UTC = 08:30 ET
        result = run(utc(2026, 3, 9, 12, 30))
        assert 0.0 < result["session_london"] < 1.0

    def test_killzone_mid_window_gradient(self):
        # NY killzone 07:00-10:00 ET. At 08:30 ET (13:30 UTC post-DST March 9) = midpoint
        result = run(utc(2026, 3, 9, 13, 30))
        assert 0.0 < result["in_ny_killzone"] < 1.0

    def test_session_outside_window_is_zero(self):
        # Outside all sessions → session flags should be 0.0
        # 2026-03-15 21:00 UTC = 17:00 EDT (Sunday): after NY close, before Asia open
        result = run(utc(2026, 3, 15, 21, 0))  # Sunday 21:00 UTC
        assert result["session_asia"] == 0.0
        assert result["session_ny"] == 0.0

    def test_categorical_fields_preserved(self):
        # is_monday and is_friday must remain binary (categorical)
        monday = run(utc(2026, 3, 9, 15, 0))  # Monday
        assert monday["is_monday"] == 1.0
        assert monday["is_friday"] == 0.0
        friday = run(utc(2026, 3, 13, 15, 0))  # Friday
        assert friday["is_friday"] == 1.0
        assert friday["is_monday"] == 0.0
