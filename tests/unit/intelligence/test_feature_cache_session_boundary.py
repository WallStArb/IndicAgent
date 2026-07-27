"""Regression: update_session_vp()'s session-boundary reset is DST-aware (todo 178 WR-02).

Before the fix, the "has today's session opened yet" check compared a fixed UTC-hour APR
value (ny_session_start_utc_hour/minute, tuned for EDT = 13:30 UTC = 9:30 ET) against the
bar's raw UTC clock time, with no DST adjustment. During EST (standard time, UTC-5 instead of
EDT's UTC-4), 9:30 ET is actually 14:30 UTC, not 13:30 -- so a bar at 14:00 UTC in January
(9:00 AM ET, still pre-market) was incorrectly treated as "session already open," attributing
it to the wrong session day and risking a spurious mid-session accumulator reset or
cross-session bar contamination.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.intelligence.feature_cache import FeatureCache
from tests.unit.intelligence.test_volume_profile_primitives import _make_cfg


def test_session_boundary_is_dst_aware_during_est() -> None:
    """January (EST, UTC-5): 9:30 ET open is 14:30 UTC, not the EDT-tuned 13:30 UTC config
    value. A 14:00 UTC bar (9:00 AM ET) is pre-market and must attribute to the PRIOR session
    day; a 14:35 UTC bar (9:35 AM ET) is post-open and must attribute to the SAME calendar day."""
    cfg = _make_cfg()
    cache = FeatureCache()

    pre_market = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)  # 9:00 AM ET -- before 9:30 open
    cache.update_session_vp(pre_market, 100.0, 99.0, 99.5, 1000.0, cfg)
    assert (
        cache._session_day == datetime(2023, 1, 2).date()
    ), "pre-market bar (9:00 AM ET) must attribute to the prior session day, not today"

    post_open = datetime(2023, 1, 3, 14, 35, tzinfo=UTC)  # 9:35 AM ET -- after 9:30 open
    cache.update_session_vp(post_open, 100.0, 99.0, 99.5, 1000.0, cfg)
    assert (
        cache._session_day == datetime(2023, 1, 3).date()
    ), "post-open bar (9:35 AM ET) must attribute to today's session day"
    # The transition between the two bars above is a genuine new-session reset (Jan 2 -> Jan
    # 3), so _sess_bars correctly holds only the post-open bar, not both.
    assert len(cache._sess_bars) == 1


def test_session_boundary_still_correct_during_edt() -> None:
    """July (EDT, UTC-4): 9:30 ET open is 13:30 UTC, matching the config value exactly --
    confirms the fix doesn't regress the case the old UTC-hour comparison got right."""
    cfg = _make_cfg()
    cache = FeatureCache()

    pre_market = datetime(2023, 7, 3, 13, 0, tzinfo=UTC)  # 9:00 AM ET -- before 9:30 open
    cache.update_session_vp(pre_market, 100.0, 99.0, 99.5, 1000.0, cfg)
    assert cache._session_day == datetime(2023, 7, 2).date()

    post_open = datetime(2023, 7, 3, 13, 35, tzinfo=UTC)  # 9:35 AM ET -- after 9:30 open
    cache.update_session_vp(post_open, 100.0, 99.0, 99.5, 1000.0, cfg)
    assert cache._session_day == datetime(2023, 7, 3).date()
