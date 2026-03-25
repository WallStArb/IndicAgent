from datetime import datetime, timezone
from src.core.bar_normalizer import _generate_session_slots

UTC = timezone.utc


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class TestCrypto24_7:
    def test_fills_every_slot_no_gaps(self):
        start = ts("2026-03-10 00:00:00")
        end   = ts("2026-03-10 00:05:00")
        slots = _generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
        assert slots == [
            ts("2026-03-10 00:00:00"),
            ts("2026-03-10 00:01:00"),
            ts("2026-03-10 00:02:00"),
            ts("2026-03-10 00:03:00"),
            ts("2026-03-10 00:04:00"),
            ts("2026-03-10 00:05:00"),
        ]

    def test_weekend_included(self):
        # Saturday/Sunday — crypto trades
        start = ts("2026-03-14 12:00:00")  # Saturday
        end   = ts("2026-03-14 12:02:00")
        slots = _generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
        assert len(slots) == 3


class TestFx24_5:
    def test_weekday_slots_included(self):
        # Monday 2026-03-09 00:00 UTC — FX open
        start = ts("2026-03-09 00:00:00")
        end   = ts("2026-03-09 00:02:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert len(slots) == 3

    def test_saturday_excluded(self):
        # Saturday 2026-03-14 — FX closed
        start = ts("2026-03-14 12:00:00")
        end   = ts("2026-03-14 12:05:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []

    def test_sunday_excluded(self):
        # Sunday 2026-03-15 — FX closed
        start = ts("2026-03-15 10:00:00")
        end   = ts("2026-03-15 10:05:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []
