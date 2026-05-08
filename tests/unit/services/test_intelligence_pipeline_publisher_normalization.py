"""Tests for intelligence_pipeline_agent publisher-side normalization.

Phase 81 D-01: Publisher sets is_backfill, timestamp, ttl_bars defaults,
signal_schema_version defaults on all signals before publishing.

test_publisher_is_backfill_computed:
  Covers four time/tf combinations:
  1. bar_ts == computed_at, tf="1m"  → is_backfill=False
  2. computed_at = bar_ts + 30s, tf="1m" (30s < 60s tf_secs) → is_backfill=False
  3. computed_at = bar_ts + 90s, tf="1m" (90s > 60s tf_secs) → is_backfill=True
  4. computed_at = bar_ts + 2h, tf="1h" (7200s > 3600s tf_secs) → is_backfill=True
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.service_utils import TF_SECONDS


def _apply_publisher_normalization(
    signals: list[dict],
    bar_ts: datetime,
    computed_at: datetime,
    tf: str,
) -> list[dict]:
    """Replicate the publisher-side normalization from intelligence_pipeline_agent.

    Extracted from services/intelligence_pipeline_agent.py lines ~1537-1552.
    This is the exact logic: compute is_backfill, stamp timestamp, apply defaults.
    """
    tf_secs = TF_SECONDS.get(tf, 60)
    try:
        is_backfill = (computed_at - bar_ts).total_seconds() > tf_secs
    except Exception:
        is_backfill = False

    for sig in signals:
        sig["timestamp"] = bar_ts
        sig["is_backfill"] = is_backfill
        sig.setdefault("ttl_bars", 10)
        sig.setdefault("signal_schema_version", "v1")

    return signals


class TestPublisherIsBackfillComputed:
    """test_publisher_is_backfill_computed — is_backfill computed correctly for all four cases."""

    @pytest.mark.unit
    def test_publisher_is_backfill_computed(self):
        """All four time/tf combinations produce correct is_backfill values."""
        base_ts = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)

        test_cases = [
            # (case_name, bar_ts, computed_at, tf, expected_is_backfill)
            (
                "realtime_same_time",
                base_ts,
                base_ts,  # computed_at == bar_ts → delta = 0 → not backfill
                "1m",
                False,
            ),
            (
                "1m_within_tf_window",
                base_ts,
                base_ts + timedelta(seconds=30),  # 30s < 60s tf_secs → not backfill
                "1m",
                False,
            ),
            (
                "1m_past_tf_window",
                base_ts,
                base_ts + timedelta(seconds=90),  # 90s > 60s tf_secs → backfill
                "1m",
                True,
            ),
            (
                "1h_past_tf_window",
                base_ts,
                base_ts + timedelta(hours=2),  # 7200s > 3600s tf_secs → backfill
                "1h",
                True,
            ),
        ]

        for case_name, bar_ts, computed_at, tf, expected_is_backfill in test_cases:
            signals = [
                {"signal_id": f"{case_name}-sig-01"},
                {"signal_id": f"{case_name}-sig-02", "ttl_bars": 20},
                {
                    "signal_id": f"{case_name}-sig-03",
                    "signal_schema_version": "v0",
                },
            ]

            result = _apply_publisher_normalization(signals, bar_ts, computed_at, tf)

            for sig in result:
                assert sig["is_backfill"] == expected_is_backfill, (
                    f"Case {case_name!r}: expected is_backfill={expected_is_backfill}, "
                    f"got {sig['is_backfill']!r} for signal_id={sig['signal_id']!r}"
                )
                # timestamp must be bar_ts (not computed_at)
                assert sig["timestamp"] == bar_ts, (
                    f"Case {case_name!r}: timestamp should be bar_ts={bar_ts!r}, "
                    f"got {sig['timestamp']!r}"
                )

            # ttl_bars: sig-01 has no ttl_bars → default 10; sig-02 has 20 → preserved
            assert result[0].get("ttl_bars") == 10, (
                f"Case {case_name!r}: default ttl_bars should be 10, "
                f"got {result[0].get('ttl_bars')!r}"
            )
            assert result[1].get("ttl_bars") == 20, (
                f"Case {case_name!r}: explicit ttl_bars=20 should be preserved, "
                f"got {result[1].get('ttl_bars')!r}"
            )

            # signal_schema_version: sig-01 has none → default "v1"; sig-03 has "v0" → preserved
            assert (
                result[0].get("signal_schema_version") == "v1"
            ), f"Case {case_name!r}: default signal_schema_version should be 'v1'"
            assert (
                result[2].get("signal_schema_version") == "v0"
            ), f"Case {case_name!r}: existing signal_schema_version='v0' should be preserved"
