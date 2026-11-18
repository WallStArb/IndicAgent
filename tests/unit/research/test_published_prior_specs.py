"""The A1/A2 daily residual spec and the H-C seasonality specs (todo 609 B-S)."""

from pathlib import Path

import pytest

from src.intelligence.research.families import seasonality
from src.intelligence.research.families.common import declared_memory_rows
from src.intelligence.research.spec import load_spec_from_file

ROOT = Path(__file__).resolve().parents[3]
PAIRS = (("daily_residual_h5", "daily_residual_h5_core"), ("seasonality_h5", "seasonality_h5_core"))


def _spec(name):
    return load_spec_from_file(ROOT / f"research/specs/{name}.yaml", root=ROOT).model


@pytest.mark.parametrize(("primary", "core"), PAIRS)
def test_the_primary_and_core_specs_differ_only_in_the_universe_comments_aside(primary, core):
    a, b = _spec(primary), _spec(core)
    assert a.panel.universe == "universe_membership"
    assert b.panel.universe == "universe_membership_core"
    assert a.panel.universe_exclusion == b.panel.universe_exclusion == "seen_names"
    assert a.model_copy(update={"panel": b.panel}) == b


def test_the_daily_residual_spec_has_six_members_and_no_flag_universe():
    spec = _spec("daily_residual_h5")
    assert [m.name for m in spec.members][:3] == [
        "residual_momentum_12_1",
        "residual_momentum_12_1_z",
        "residual_momentum_12_1_continuity",
    ]
    assert len(spec.members) == 6 and spec.panel.members_universe is None
    m3 = next(m for m in spec.members if m.name.endswith("continuity"))
    assert (m3.slot_history_sessions, m3.declared_memory_rows) == (
        252,
        declared_memory_rows(252, 1),
    )


@pytest.mark.parametrize("name", ["seasonality_h5", "seasonality_h5_core"])
def test_the_seasonality_memory_comes_from_the_helper_and_the_values_are_the_pinned_ones(name):
    spec = _spec(name)
    slot = seasonality.slot_history_sessions(60)
    for member in spec.members:
        assert member.slot_history_sessions == slot == 1403
        assert member.declared_memory_rows == declared_memory_rows(slot, 1) == 1676
        assert member.params["max_missing_fraction"] == 0.25
    c1, c2 = spec.members
    assert c1.params == {"lags": 5, "min_lags": 3, "max_missing_fraction": 0.25}
    assert c2.params == {"window_months": 60, "max_missing_fraction": 0.25}
    assert spec.scoring.trading_start == "2009-03-02"


def test_the_null_battery_lists_every_registered_daily_residual_member():
    from src.intelligence.research import null_battery_daily_residual as battery

    registered = [m.name for m in _spec("daily_residual_h5").members]
    assert [name for name, *_ in battery.MEMBERS] == registered


def test_seasonality_has_no_battery_yet_so_a_run_is_refused_before_the_ledger():
    from src.intelligence.research import runner

    with pytest.raises(runner.RunRefused, match="no E17 H0 battery covers"):
        runner.static_gate(_spec("seasonality_h5"))


def test_the_core_universe_never_selects_or_admits_a_name_into_the_primary_panel(monkeypatch):
    """Core is a fixed robustness panel over the span, defined from month-end rows; reading the
    primary universe must never call the core rule."""
    import asyncio

    from src.intelligence.research import membership, snapshot

    called = []
    monkeypatch.setattr(membership, "core_symbols", lambda *a, **k: called.append(1))

    class Pool:
        async def fetchrow(self, sql, *a):
            return (1, 1, __import__("datetime").date(2024, 1, 31))

        async def fetchval(self, sql, *a):
            return "r"

        async def fetch(self, sql, *a):
            if sql == snapshot._LEDGER_ROWS_SQL:
                return [{"as_of": __import__("datetime").date(2024, 1, 31)}]
            return [{"as_of": __import__("datetime").date(2024, 1, 31), "symbol": "A"}]

        async def close(self):
            pass

    async def pool(dsn):
        return Pool()

    monkeypatch.setattr(snapshot, "read_only_pool", pool)
    got = asyncio.run(snapshot.membership_inputs("x", "universe_membership"))
    assert got.symbols == ["A"] and not called
