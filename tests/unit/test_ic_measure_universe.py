"""ic_measure reads the membership universe on 1d (todo 609 I1)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from services import ic_measure
from src.intelligence.research import snapshot


def _self(symbols=None):
    return SimpleNamespace(args=SimpleNamespace(symbols=symbols), dsn="postgresql://unused")


def test_1d_reads_the_membership_and_returns_its_inputs(monkeypatch):
    inputs = snapshot.MembershipInputs(["A", "B"], {}, {"membership": {"rule_id": "r"}})
    calls = []

    async def fake(dsn, universe, **kwargs):
        calls.append((dsn, universe, kwargs))
        return inputs

    monkeypatch.setattr(snapshot, "membership_inputs", fake)
    symbols, got = ic_measure.IcMeasure._universe(_self(), "1d")
    assert symbols == ["A", "B"] and got is inputs
    assert calls == [("postgresql://unused", "universe_membership", {})]


def test_5m_still_reads_the_flag_and_an_explicit_list_is_an_unmasked_subset(monkeypatch):
    async def flag(dsn, dimension):
        return [dimension]

    monkeypatch.setattr(snapshot, "universe_symbols", flag)
    assert ic_measure.IcMeasure._universe(_self(), "5m") == (["compute_eligible"], None)
    assert ic_measure.IcMeasure._universe(_self(["Z", "Y"]), "1d") == (["Y", "Z"], None)


def test_the_module_declares_only_the_1d_reader_so_the_rerun_check_fails_for_5m():
    assert ic_measure.UNIVERSE_SOURCE == {"1d": snapshot.membership_inputs}


@pytest.mark.parametrize("membership", [None, {"rule_id": "r", "built_months": 2}])
def test_identity_snapshot_carries_the_membership_only_when_given(membership):
    # computational_keys is read from a real APR mapping elsewhere; here only the new key matters.
    apr = {k: 1 for k in ic_measure.computational_keys("1d")}
    apr[ic_measure._OOS_START_KEY] = None
    snap = ic_measure.identity_snapshot(
        apr, "1d", [1], datetime(2025, 1, 1, tzinfo=UTC), membership
    )
    assert ("universe.membership" in snap) is (membership is not None)
    if membership is not None:
        assert snap["universe.membership"] == membership
