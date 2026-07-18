"""Unit tests: VocabularyService (Phase 161, Controlled Vocabulary System).

Pure-Python, no-DB style (mirrors tests/unit/test_concept_registry_service.py): builds a
VocabularyService, populates `_entries`/`_groups` caches directly (bypassing
initialize()/DB entirely), and asserts the synchronous hot-path readers.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.config.vocabulary_service import VocabEntry, VocabularyService


def _service_with_fixture() -> VocabularyService:
    service = VocabularyService("postgresql://unused")
    service._entries = {
        "timeframe": {
            "1m": VocabEntry(
                code="1m", label="1 Minute", description=None, sort_order=0, is_deprecated=False
            ),
            "5m": VocabEntry(
                code="5m", label="5 Minutes", description=None, sort_order=1, is_deprecated=False
            ),
            "1h": VocabEntry(
                code="1h", label="1 Hour", description=None, sort_order=2, is_deprecated=False
            ),
        },
        "regime_hmm": {
            "trending_up": VocabEntry(
                code="trending_up",
                label="Trending Up",
                description=None,
                sort_order=0,
                is_deprecated=False,
            ),
            "ranging": VocabEntry(
                code="ranging",
                label="Ranging",
                description=None,
                sort_order=1,
                is_deprecated=False,
            ),
        },
    }
    service._groups = {
        ("regime_hmm", "trending"): frozenset({"trending_up"}),
    }
    return service


def test_codes_returns_seeded_codes_in_sort_order():
    service = _service_with_fixture()
    assert service.codes("timeframe") == ["1m", "5m", "1h"]


def test_codes_unknown_namespace_returns_empty_list():
    service = _service_with_fixture()
    assert service.codes("no_such_namespace") == []


def test_label_returns_entry_label():
    service = _service_with_fixture()
    assert service.label("timeframe", "1m") == "1 Minute"


def test_label_unknown_code_falls_back_to_code():
    service = _service_with_fixture()
    assert service.label("timeframe", "99z") == "99z"


def test_group_codes_returns_frozenset_of_members():
    service = _service_with_fixture()
    assert service.group_codes("regime_hmm", "trending") == frozenset({"trending_up"})


def test_group_codes_unknown_group_returns_empty_frozenset():
    service = _service_with_fixture()
    assert service.group_codes("regime_hmm", "no_such_group") == frozenset()


def test_namespace_returns_list_of_vocab_entries():
    service = _service_with_fixture()
    entries = service.namespace("timeframe")
    assert [e.code for e in entries] == ["1m", "5m", "1h"]
    assert all(isinstance(e, VocabEntry) for e in entries)


def test_namespace_unknown_returns_empty_list():
    service = _service_with_fixture()
    assert service.namespace("no_such_namespace") == []


def test_no_db_calls_after_init():
    """codes()/label()/group_codes()/namespace() are synchronous and touch no DB pool
    after caches are populated — hot-path reads must be zero-I/O per D-05."""
    service = _service_with_fixture()
    # No pool was ever assigned (still None) — hot-path reads must not require one.
    assert service._db_pool is None
    for method_name in ("codes", "label", "group_codes", "namespace"):
        method = getattr(service, method_name)
        assert not inspect.iscoroutinefunction(method)

    # Exercise every reader with the pool still None — proves no pool access occurs.
    assert service.codes("timeframe")
    assert service.label("timeframe", "1m")
    assert service.group_codes("regime_hmm", "trending")
    assert service.namespace("timeframe")
