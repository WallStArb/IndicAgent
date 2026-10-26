"""Unit tests for EntryType enum — Phase 134 Plan 02.

Covers:
1. EntryType member values match the 5 exact string literals they replace
2. EntryType extends str so enum members compare equal to raw strings
"""

from src.intelligence.trading.signal_outcome import EntryType


class TestEntryTypeValues:
    """EntryType member values must match the exact strings they replace in the codebase."""

    def test_entry_type_values_match_strings(self):
        assert EntryType.AT_CLOSE.value == "at_close"
        assert EntryType.AT_PULLBACK.value == "at_pullback"
        assert EntryType.AT_LIMIT.value == "at_limit"
        assert EntryType.AT_RECLAIM.value == "at_reclaim"
        assert EntryType.ZONE_PROXIMAL.value == "zone_proximal"

    def test_entry_type_has_exactly_five_members(self):
        assert len(EntryType) == 5

    def test_entry_type_str_subclass(self):
        # EntryType extends str — enum member must compare equal to its value string.
        # This is the asyncpg compatibility guarantee: no .value call needed for DB writes.
        assert EntryType.AT_CLOSE == "at_close"
        assert EntryType.AT_PULLBACK == "at_pullback"
        assert EntryType.AT_LIMIT == "at_limit"
        assert EntryType.AT_RECLAIM == "at_reclaim"
        assert EntryType.ZONE_PROXIMAL == "zone_proximal"
