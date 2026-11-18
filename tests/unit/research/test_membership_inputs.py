"""The membership reader behind universe_membership specs (todo 609 I1, B-U)."""

import asyncio
import datetime as dt
import hashlib

import pytest

from src.intelligence.research import snapshot
from src.intelligence.research.spec import PanelSpec

D = dt.date


class _Pool:
    def __init__(self, ledger, rows, seen=("OLD",), summary=None):
        self.ledger, self.rows, self.seen = ledger, rows, seen
        self.summary = summary or (len(ledger), 1, max(ledger, default=None), "rule-x")

    async def fetchrow(self, sql, *args):
        return self.summary

    async def fetch(self, sql, *args):
        if sql == snapshot._LEDGER_ROWS_SQL:
            return [{"as_of": d} for d in self.ledger]
        if sql == snapshot._MEMBER_ROWS_SQL:
            return [{"as_of": d, "symbol": s} for d, s in self.rows]
        return [{"symbol": s} for s in self.seen]  # the seen-names query

    async def close(self):
        pass


def _read(monkeypatch, pool, universe="universe_membership", exclusion=None, *, pin=True):
    async def fake(dsn):
        return pool

    monkeypatch.setattr(snapshot, "read_only_pool", fake)
    if pin:
        digest = hashlib.sha256("\n".join(pool.seen).encode()).hexdigest()
        monkeypatch.setattr(snapshot, "DAILY_SEEN_BEFORE_CUTOFF_SHA256", digest)
    return asyncio.run(
        snapshot.membership_inputs(
            "postgresql://unused",
            universe,
            start="2024-01-01",
            end_exclusive="2024-12-31",
            exclusion=exclusion,
        )
    )


LEDGER = [D(2024, 1, 31), D(2024, 2, 29)]
ROWS = [(LEDGER[0], "A"), (LEDGER[0], "OLD"), (LEDGER[1], "A"), (LEDGER[1], "B")]


def test_symbols_are_every_name_ever_a_member_and_the_manifest_pins_the_rule(monkeypatch):
    got = _read(monkeypatch, _Pool(LEDGER, ROWS))
    assert got.symbols == ["A", "B", "OLD"]
    assert got.members_by_as_of[LEDGER[1]] == frozenset({"A", "B"})
    assert got.manifest["membership"] == {
        "rule_id": "rule-x",
        "built_months": 2,
        "last_as_of": "2024-02-29",
        "exclusion": None,
        "excluded_names": 0,
        "exclusion_sha256": None,
    }


def test_the_seen_names_exclusion_drops_the_listed_names_and_pins_the_list(monkeypatch):
    got = _read(monkeypatch, _Pool(LEDGER, ROWS), exclusion="seen_names")
    assert got.symbols == ["A", "B"]
    assert "OLD" not in got.members_by_as_of[LEDGER[0]]
    pinned = got.manifest["membership"]
    assert pinned["exclusion"] == "seen_names"
    sleeve = sorted({"OLD", *snapshot.DAILY_SEEN_SLEEVE})
    assert pinned["excluded_names"] == len(sleeve)
    assert pinned["exclusion_sha256"] == hashlib.sha256("\n".join(sleeve).encode()).hexdigest()


def test_the_exclusion_changes_the_pin(monkeypatch):
    with_list = _read(monkeypatch, _Pool(LEDGER, ROWS), exclusion="seen_names")
    without = _read(monkeypatch, _Pool(LEDGER, ROWS))
    assert with_list.manifest != without.manifest


def test_a_seen_set_that_no_longer_reproduces_refuses(monkeypatch):
    pool = _Pool(LEDGER, ROWS)
    _read(monkeypatch, pool, pin=True)  # pins the hash of ("OLD",)
    pool.seen = ("OLD", "NEW")
    with pytest.raises(ValueError, match="not the pinned set"):
        _read(monkeypatch, pool, exclusion="seen_names", pin=False)


def test_core_keeps_names_that_are_members_at_ninety_percent_of_the_span(monkeypatch):
    ledger = [D(2024, m, 28) for m in range(1, 11)]
    rows = [(d, "ALWAYS") for d in ledger] + [(d, "SOMETIMES") for d in ledger[:5]]
    got = _read(monkeypatch, _Pool(ledger, rows), universe="universe_membership_core")
    assert got.symbols == ["ALWAYS"]
    assert got.members_by_as_of[ledger[0]] == frozenset({"ALWAYS"})


def test_an_empty_ledger_refuses_and_so_does_a_mixed_rule_ledger(monkeypatch):
    with pytest.raises(ValueError, match="no built month-end"):
        _read(monkeypatch, _Pool([], [], summary=(0, 0, None, None)))
    with pytest.raises(ValueError, match="mixes 2 rule ids"):
        _read(monkeypatch, _Pool(LEDGER, ROWS, summary=(2, 2, LEDGER[1], "rule-x")))


def test_unknown_universe_and_exclusion_refuse(monkeypatch):
    with pytest.raises(ValueError, match="not a membership universe"):
        _read(monkeypatch, _Pool(LEDGER, ROWS), universe="compute_eligible_1d")
    with pytest.raises(ValueError, match="unknown universe exclusion"):
        _read(monkeypatch, _Pool(LEDGER, ROWS), exclusion="everything")


def _panel(**overrides):
    base = {
        "universe": "universe_membership",
        "tf": "1d",
        "bars_per_session": 1,
        "start": "2007-03-01",
        "end_exclusive": "2025-12-23",
    }
    return PanelSpec(**{**base, **overrides})


def test_the_new_spec_values_and_field_validate_and_an_old_spec_is_unchanged():
    assert _panel(universe_exclusion="seen_names").universe_exclusion == "seen_names"
    assert _panel(universe="universe_membership_core").universe == "universe_membership_core"
    with pytest.raises(ValueError, match="applies to the membership universes"):
        _panel(universe="compute_eligible_1d", universe_exclusion="seen_names")
    with pytest.raises(ValueError):
        _panel(universe_exclusion="other_list")
