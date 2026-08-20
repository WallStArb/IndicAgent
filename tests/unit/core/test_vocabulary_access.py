"""Unit tests for src.core.vocabulary_access (todo 327, generalized todo 330)."""

import pytest

from src.core import vocabulary_access


class _FakeVocab:
    """Reports a fixed CVR-registered set per namespace, `timeframe` by default."""

    def __init__(self, codes=("1m", "5m", "15m", "1h", "4h", "1d")):
        self._codes = codes

    def active_codes(self, namespace):
        return list(self._codes)


class _EmptyVocab:
    """A registered VocabularyService with zero codes for any namespace -- the
    unseeded-DB / migration-never-replayed / namespace-typo case, distinct from
    "never registered" (no VocabularyService object at all)."""

    def active_codes(self, namespace):
        return []


@pytest.fixture(autouse=True)
def _reset():
    """Every test starts with no VocabularyService registered."""
    vocabulary_access.reset_vocabulary_service_for_test()
    yield
    vocabulary_access.reset_vocabulary_service_for_test()


@pytest.mark.unit
def test_codes_returns_default_when_unregistered():
    """No VocabularyService registered yet -> falls back to the literal default."""
    result = vocabulary_access.codes("timeframe", default=("1m", "5m"))
    assert result == ("1m", "5m")


@pytest.mark.unit
def test_codes_reads_registered_service_for_arbitrary_namespace():
    """Once a VocabularyService is registered, reads its active_codes(namespace) --
    not hardcoded to "timeframe" (todo 330 generalizes this beyond timeframe, e.g.
    todo 324's "gradient_scale" namespace)."""
    vocabulary_access.set_vocabulary_service(_FakeVocab(codes=("fast", "mid", "slow")))
    result = vocabulary_access.codes("gradient_scale", default=())
    assert result == ("fast", "mid", "slow")


@pytest.mark.unit
def test_codes_falls_back_on_empty_registry():
    """A registered service with zero codes for the namespace still falls back --
    never silently returns an empty tuple (that would break every caller's loop)."""
    vocabulary_access.set_vocabulary_service(_EmptyVocab())
    result = vocabulary_access.codes("timeframe", default=("1m",))
    assert result == ("1m",)


@pytest.mark.unit
def test_standard_timeframes_returns_default_when_unregistered():
    """standard_timeframes() is a thin wrapper over codes("timeframe", ...)."""
    result = vocabulary_access.standard_timeframes(default=("1m", "5m"))
    assert result == ("1m", "5m")


@pytest.mark.unit
def test_standard_timeframes_reads_registered_service():
    """Once a VocabularyService is registered, reads its active_codes("timeframe")."""
    vocabulary_access.set_vocabulary_service(_FakeVocab())
    result = vocabulary_access.standard_timeframes()
    assert result == ("1m", "5m", "15m", "1h", "4h", "1d")


@pytest.mark.unit
def test_assert_subset_passes_for_registered_subset():
    """assert_known_subset() is a no-op when every value is registered."""
    vocabulary_access.set_vocabulary_service(_FakeVocab())
    # Must not raise.
    vocabulary_access.assert_known_subset("timeframe", ("1m", "5m", "15m", "1h"), context="test")


@pytest.mark.unit
def test_assert_subset_raises_for_unregistered_code():
    """assert_known_subset() raises loud if a caller's hardcoded subset references a
    value CVR doesn't know about for that namespace -- the actual drift D-07 exists
    to catch."""
    vocabulary_access.set_vocabulary_service(_FakeVocab())
    with pytest.raises(ValueError, match="30m"):
        vocabulary_access.assert_known_subset("timeframe", ("1m", "30m"), context="test")


@pytest.mark.unit
def test_assert_subset_checks_the_given_namespace_not_timeframe():
    """assert_known_subset() checks against whatever namespace it's called with --
    a value valid in one namespace but absent from another still raises."""
    vocabulary_access.set_vocabulary_service(_FakeVocab(codes=("fast", "mid", "slow")))
    with pytest.raises(ValueError, match="gradient_scale"):
        vocabulary_access.assert_known_subset("gradient_scale", ("fast", "1m"), context="test")


@pytest.mark.unit
def test_assert_subset_skips_when_unregistered():
    """No VocabularyService registered (e.g. a script run without daemon startup) ->
    assert_known_subset() is a no-op, not a crash -- matches codes()'s same
    fallback-permissive contract."""
    # Must not raise even though "bogus" isn't a real timeframe -- there's no registry
    # to check against yet.
    vocabulary_access.assert_known_subset("timeframe", ("bogus",), context="test")


@pytest.mark.unit
def test_codes_warns_on_empty_but_registered():
    """A registered service with zero codes for the namespace is a real gap (unseeded
    DB, migration never replayed, a namespace-name typo) distinct from "never
    registered" -- must log a warning even though it still falls back."""
    from structlog.testing import capture_logs

    vocabulary_access.set_vocabulary_service(_EmptyVocab())
    with capture_logs() as cap_logs:
        result = vocabulary_access.codes("timeframe", default=("1m",))
    assert result == ("1m",)
    events = [e["event"] for e in cap_logs]
    assert "vocabulary_access.empty_registry_fallback" in events, f"Expected warning in {events}"
    warning_entry = next(
        e for e in cap_logs if e["event"] == "vocabulary_access.empty_registry_fallback"
    )
    assert warning_entry["log_level"] == "warning"
    assert warning_entry["namespace"] == "timeframe"
    assert warning_entry["default"] == ("1m",)


@pytest.mark.unit
def test_codes_does_not_warn_when_unregistered():
    """No VocabularyService registered at all is the documented, intentional fallback
    for scripts/tests running outside daemon startup -- must stay silent."""
    from structlog.testing import capture_logs

    with capture_logs() as cap_logs:
        result = vocabulary_access.codes("timeframe", default=("1m", "5m"))
    assert result == ("1m", "5m")
    events = [e["event"] for e in cap_logs]
    assert (
        "vocabulary_access.empty_registry_fallback" not in events
    ), f"Unexpected warning in {events}"
