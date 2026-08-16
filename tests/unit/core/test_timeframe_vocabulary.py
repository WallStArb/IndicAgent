"""Unit tests for src.core.timeframe_vocabulary (todo 327)."""

import pytest

from src.core import timeframe_vocabulary


@pytest.fixture(autouse=True)
def _reset():
    """Every test starts with no VocabularyService registered."""
    timeframe_vocabulary.reset_vocabulary_service_for_test()
    yield
    timeframe_vocabulary.reset_vocabulary_service_for_test()


@pytest.mark.unit
def test_standard_timeframes_returns_default_when_unregistered():
    """No VocabularyService registered yet -> falls back to the literal default."""
    result = timeframe_vocabulary.standard_timeframes(default=("1m", "5m"))
    assert result == ("1m", "5m")


@pytest.mark.unit
def test_standard_timeframes_reads_registered_service():
    """Once a VocabularyService is registered, reads its active_codes("timeframe")."""

    class _FakeVocab:
        def active_codes(self, namespace):
            assert namespace == "timeframe"
            return ["1m", "5m", "15m", "1h", "4h", "1d"]

    timeframe_vocabulary.set_vocabulary_service(_FakeVocab())
    result = timeframe_vocabulary.standard_timeframes()
    assert result == ("1m", "5m", "15m", "1h", "4h", "1d")


@pytest.mark.unit
def test_standard_timeframes_falls_back_on_empty_registry():
    """A registered service with zero codes for the namespace still falls back --
    never silently returns an empty tuple (that would break every caller's loop)."""

    class _EmptyVocab:
        def active_codes(self, namespace):
            return []

    timeframe_vocabulary.set_vocabulary_service(_EmptyVocab())
    result = timeframe_vocabulary.standard_timeframes(default=("1m",))
    assert result == ("1m",)


@pytest.mark.unit
def test_assert_subset_passes_for_registered_subset():
    """assert_known_subset() is a no-op when every code is registered."""

    class _FakeVocab:
        def active_codes(self, namespace):
            return ["1m", "5m", "15m", "1h", "4h", "1d"]

    timeframe_vocabulary.set_vocabulary_service(_FakeVocab())
    # Must not raise.
    timeframe_vocabulary.assert_known_subset(("1m", "5m", "15m", "1h"), context="test")


@pytest.mark.unit
def test_assert_subset_raises_for_unregistered_code():
    """assert_known_subset() raises loud if a caller's hardcoded subset references a
    timeframe CVR doesn't know about -- the actual drift D-07 exists to catch."""

    class _FakeVocab:
        def active_codes(self, namespace):
            return ["1m", "5m", "15m", "1h", "4h", "1d"]

    timeframe_vocabulary.set_vocabulary_service(_FakeVocab())
    with pytest.raises(ValueError, match="30m"):
        timeframe_vocabulary.assert_known_subset(("1m", "30m"), context="test")


@pytest.mark.unit
def test_assert_subset_skips_when_unregistered():
    """No VocabularyService registered (e.g. a script run without daemon startup) ->
    assert_known_subset() is a no-op, not a crash -- matches standard_timeframes()'s
    same fallback-permissive contract."""
    # Must not raise even though "bogus" isn't a real timeframe -- there's no registry
    # to check against yet.
    timeframe_vocabulary.assert_known_subset(("bogus",), context="test")
