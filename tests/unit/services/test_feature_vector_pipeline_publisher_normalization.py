"""Tests for feature_vector_pipeline_agent publisher-side normalization.

Phase 81 D-01: Publisher sets is_backfill, timestamp, ttl_bars defaults
on all signals before publishing.

test_publisher_is_backfill_computed:
  Covers four time/tf combinations:
  1. bar_ts == computed_at, tf="1m"  → is_backfill=False
  2. computed_at = bar_ts + 30s, tf="1m" (30s < 60s tf_secs) → is_backfill=False
  3. computed_at = bar_ts + 90s, tf="1m" (90s > 60s tf_secs) → is_backfill=True
  4. computed_at = bar_ts + 2h, tf="1h" (7200s > 3600s tf_secs) → is_backfill=True
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from src.core.service_utils import TF_SECONDS


def _apply_publisher_normalization(
    signals: list[dict],
    bar_ts: datetime,
    computed_at: datetime,
    tf: str,
    *,
    stamp_signal_id: bool = False,
) -> list[dict]:
    """Replicate the publisher-side normalization from feature_vector_pipeline_agent.

    Extracted from services/intelligence_pipeline.py _publish_signals_or_dlq.
    stamp_signal_id=True also replicates the signal_id setdefault added in the
    env-cleanup fix.
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
        if stamp_signal_id:
            sig.setdefault("signal_id", str(uuid4()))

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
                {"signal_id": f"{case_name}-sig-03"},
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


class TestPublisherSignalId:
    """Publisher stamps signal_id on every signal before publishing."""

    @pytest.mark.unit
    def test_signal_id_stamped_when_absent(self):
        """Signal without signal_id gets a fresh UUID."""
        sig = {"setup_plugin": "trend_following", "ttl_bars": 10}
        _apply_publisher_normalization(
            [sig],
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            "1m",
            stamp_signal_id=True,
        )
        assert "signal_id" in sig
        UUID(sig["signal_id"])  # raises ValueError if not a valid UUID

    @pytest.mark.unit
    def test_signal_id_preserved_when_present(self):
        """Existing signal_id is never overwritten."""
        existing_id = "abc-123"
        sig = {"signal_id": existing_id, "ttl_bars": 10}
        _apply_publisher_normalization(
            [sig],
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            "1m",
            stamp_signal_id=True,
        )
        assert sig["signal_id"] == existing_id

    @pytest.mark.unit
    def test_each_signal_gets_unique_id(self):
        """Two signals in the same bar get distinct IDs."""
        sigs = [{"ttl_bars": 10}, {"ttl_bars": 10}]
        _apply_publisher_normalization(
            sigs,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            "1m",
            stamp_signal_id=True,
        )
        assert sigs[0]["signal_id"] != sigs[1]["signal_id"]
