"""todo 609 blocker I1: the corpus rerun refuses while the IC universe differs."""

from __future__ import annotations

from types import SimpleNamespace

from services import corpus_rerun as cr
from services.corpus_universe import corpus_universe


def _importer(**modules):
    def import_module(name):
        value = modules[name]
        if isinstance(value, Exception):
            raise value
        return value

    return import_module


IC, SNAP = cr._IC_UNIVERSE_READERS
WIRED = SimpleNamespace(UNIVERSE_SOURCE=corpus_universe)


def test_passes_when_both_readers_declare_the_corpus_universe():
    assert cr.check_ic_universe_aligned(_importer(**{IC: WIRED, SNAP: WIRED})).ok


def test_missing_attribute_fails_naming_the_module():
    result = cr.check_ic_universe_aligned(_importer(**{IC: WIRED, SNAP: SimpleNamespace()}))
    assert not result.ok and SNAP in result.detail and "blocker I1" in result.detail
    assert IC not in result.detail.split("(todo")[0]


def test_other_source_fails():
    other = SimpleNamespace(UNIVERSE_SOURCE=lambda conn: [])
    result = cr.check_ic_universe_aligned(_importer(**{IC: other, SNAP: WIRED}))
    assert not result.ok and f"{IC}.UNIVERSE_SOURCE is not corpus_universe" in result.detail


def test_import_failure_is_a_failed_check_not_a_traceback():
    result = cr.check_ic_universe_aligned(
        _importer(**{IC: ModuleNotFoundError("gone"), SNAP: WIRED})
    )
    assert not result.ok and "cannot be imported" in result.detail and IC in result.detail


def test_the_live_tree_is_blocked_until_the_readers_are_wired():
    result = cr.check_ic_universe_aligned()
    assert not result.ok and "declares no UNIVERSE_SOURCE" in result.detail
