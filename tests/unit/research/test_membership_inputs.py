"""The membership reader behind universe_membership specs (todo 609 I1, B-U)."""

import asyncio
import datetime as dt
import hashlib

import pytest

from src.intelligence.research import snapshot
from src.intelligence.research.spec import PanelSpec

D = dt.date


class _Pool:
    def __init__(self, ledger, rows, seen=("OLD",), summary=None, tier_rows=()):
        self.ledger, self.rows, self.seen, self.tier_rows = ledger, rows, seen, tier_rows
        self.summary = summary or (len(ledger), 1, max(ledger, default=None))

    async def fetchrow(self, sql, *args):
        return self.summary

    async def fetchval(self, sql, *args):
        return "rule-x"

    async def fetch(self, sql, *args):
        if sql == snapshot._LEDGER_ROWS_SQL:
            return [{"as_of": d} for d in self.ledger]
        if sql in (snapshot._MEMBER_ROWS_SQL, snapshot._TIER_ROWS_SQL):
            self.last_member_sql = sql
            rows = self.tier_rows if sql == snapshot._TIER_ROWS_SQL else self.rows
            return [{"as_of": d, "symbol": s} for d, s in rows]
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
    mem_digest = hashlib.sha256(
        b"2024-01-31|A\n2024-01-31|OLD\n2024-02-29|A\n2024-02-29|B"
    ).hexdigest()
    assert got.symbols == ["A", "B", "OLD"]
    assert got.members_by_as_of[LEDGER[1]] == frozenset({"A", "B"})
    assert got.manifest["membership"] == {
        "universe": "universe_membership",
        "rule_id": "rule-x",
        "built_months": 2,
        "last_as_of": "2024-02-29",
        "members_sha256": mem_digest,
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
        _read(monkeypatch, _Pool([], [], summary=(0, 0, None)))
    with pytest.raises(ValueError, match="mixes 2 rule ids"):
        _read(monkeypatch, _Pool(LEDGER, ROWS, summary=(2, 2, LEDGER[1])))


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


def test_a_membership_universe_must_match_its_clock():
    with pytest.raises(ValueError, match="needs a 1d panel"):
        _panel(tf="5m", bars_per_session=78)
    with pytest.raises(ValueError, match="5m tier panel"):
        _panel(universe="universe_membership_5m")
    ok = _panel(universe="universe_membership_5m", tf="5m", bars_per_session=78)
    assert ok.universe == "universe_membership_5m"
    core = _panel(universe="universe_membership_5m_core", tf="5m", bars_per_session=78)
    assert core.universe == "universe_membership_5m_core"


def test_the_5m_tier_universe_reads_the_tier_rows_and_its_core_is_over_the_tier(monkeypatch):
    ledger = [D(2024, m, 28) for m in range(1, 11)]
    all_rows = [(d, "A") for d in ledger] + [(d, "B") for d in ledger]
    tier_rows = [(d, "A") for d in ledger] + [(d, "B") for d in ledger[:3]]
    pool = _Pool(ledger, all_rows, tier_rows=tier_rows)
    got = _read(monkeypatch, pool, universe="universe_membership_5m")
    assert pool.last_member_sql == snapshot._TIER_ROWS_SQL
    assert got.symbols == ["A", "B"] and got.manifest["membership"]["universe"].endswith("_5m")
    core = _read(monkeypatch, pool, universe="universe_membership_5m_core")
    assert core.symbols == ["A"]  # B is in the tier at 3 of 10 month-ends, in the membership at all
    primary = _read(monkeypatch, pool, universe="universe_membership")
    assert pool.last_member_sql == snapshot._MEMBER_ROWS_SQL and primary.symbols == ["A", "B"]


def test_the_member_array_round_trips_through_save_and_load_inside_the_hash(tmp_path):
    import dataclasses

    import numpy as np

    from src.intelligence.research import panel as panel_mod
    from src.intelligence.research import store

    close = np.full((4, 2), 10.0)
    base = panel_mod.daily_panel(close, opens=close, volume=np.ones((4, 2)))
    member = np.array([[True, False], [True, True], [False, True], [False, True]])
    path = panel_mod.save(dataclasses.replace(base, member=member), tmp_path / "a")
    loaded = panel_mod.load(path)
    assert loaded.member.dtype == np.bool_ and np.array_equal(loaded.member, member)
    other = panel_mod.save(dataclasses.replace(base, member=~member), tmp_path / "b")
    assert store.verify(path) != store.verify(other)
    assert panel_mod.load(panel_mod.save(base, tmp_path / "c")).member is None
