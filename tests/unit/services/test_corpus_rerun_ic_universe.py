"""todo 609 blocker I1: the corpus rerun refuses while an IC timeframe's universe differs."""

from __future__ import annotations

from types import SimpleNamespace

from services import corpus_rerun as cr
from src.intelligence.research.snapshot import membership_inputs


def _importer(**modules):
    def import_module(name):
        value = modules[name]
        if isinstance(value, Exception):
            raise value
        return value

    return import_module


IC, SNAP = cr._IC_UNIVERSE_READERS
BOTH = SimpleNamespace(UNIVERSE_SOURCE={"1d": membership_inputs, "5m": membership_inputs})
ONLY_1D = SimpleNamespace(UNIVERSE_SOURCE={"1d": membership_inputs})


def test_passes_when_both_readers_declare_the_membership_reader_for_every_timeframe():
    assert cr.check_ic_universe_aligned(_importer(**{IC: BOTH, SNAP: BOTH})).ok


def test_a_missing_mapping_fails_naming_the_module():
    result = cr.check_ic_universe_aligned(_importer(**{IC: BOTH, SNAP: SimpleNamespace()}))
    assert not result.ok and SNAP in result.detail and "blocker I1" in result.detail
    assert IC not in result.detail.split("(todo")[0]


def test_a_missing_timeframe_fails_loudly_with_no_default():
    result = cr.check_ic_universe_aligned(_importer(**{IC: ONLY_1D, SNAP: BOTH}))
    assert not result.ok and f"{IC} declares no 5m universe" in result.detail


def test_another_reader_fails_naming_the_timeframe():
    other = SimpleNamespace(UNIVERSE_SOURCE={"1d": lambda conn: [], "5m": membership_inputs})
    result = cr.check_ic_universe_aligned(_importer(**{IC: other, SNAP: BOTH}))
    assert not result.ok and f"{IC}.UNIVERSE_SOURCE['1d'] is not membership_inputs" in result.detail


def test_import_failure_is_a_failed_check_not_a_traceback():
    result = cr.check_ic_universe_aligned(
        _importer(**{IC: ModuleNotFoundError("gone"), SNAP: BOTH})
    )
    assert not result.ok and "cannot be imported" in result.detail and IC in result.detail


def test_the_live_tree_reads_the_membership_universe_for_every_corpus_timeframe():
    result = cr.check_ic_universe_aligned()
    assert result.ok, result.detail
