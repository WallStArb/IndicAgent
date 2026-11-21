"""The A1/A4 daily residual spec and the H-C seasonality specs (todo 609 B-S)."""

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


def test_the_daily_residual_spec_has_three_members_and_no_flag_universe():
    spec = _spec("daily_residual_h5")
    # A3 dropped the two 5-session arms, A4 dropped the continuity member (battery size excess)
    assert [m.name for m in spec.members] == [
        "residual_momentum_12_1",
        "residual_momentum_12_1_z",
        "reversal_21",
    ]
    assert spec.panel.members_universe is None
    assert [m.slot_history_sessions for m in spec.members] == [252, 252, 21]


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


def test_the_seasonality_family_is_covered_by_its_battery():
    from src.intelligence.research import runner

    gate = runner.static_gate(_spec("seasonality_h5"), require_pass=False)
    assert gate.battery == "src.intelligence.research.null_battery_seasonality"


def test_the_core_universe_never_selects_or_admits_a_name_into_the_primary_panel(monkeypatch):
    """Core is a fixed robustness panel over the span, defined from month-end rows; reading the
    primary universe must never call the core rule."""
    import asyncio

    from src.intelligence import universe_membership
    from src.intelligence.research import membership, snapshot

    called = []
    monkeypatch.setattr(membership, "core_symbols", lambda *a, **k: called.append(1))

    class Pool:
        async def fetch(self, sql, *a):
            if sql == universe_membership.LEDGER_ROWS_SQL:
                return [
                    {
                        "as_of": __import__("datetime").date(2024, 1, 31),
                        "rule_id": universe_membership.RULE_ID,
                    }
                ]
            return [{"as_of": __import__("datetime").date(2024, 1, 31), "symbol": "A"}]

        async def close(self):
            pass

    async def pool(dsn):
        return Pool()

    monkeypatch.setattr(snapshot, "read_only_pool", pool)
    got = asyncio.run(snapshot.membership_inputs("x", "universe_membership"))
    assert got.symbols == ["A"] and not called


MIN_TESTED_SESSIONS = 126  # half a year: a sub-period with fewer is not a disclosure


@pytest.mark.parametrize(
    "name",
    ["daily_residual_h5", "daily_residual_h5_core", "seasonality_h5", "seasonality_h5_core"],
)
def test_every_declared_sub_period_has_tested_sessions_under_the_specs_own_e17_memory(name):
    """timing_series tests a session only after 60 scored sessions older than s - L (L = slot
    history + horizon). A memory longer than the span before a sub-period would leave it empty
    (the H-C draft's 2009 to 2014 period did, found in review 2026-11-18)."""
    import numpy as np

    from src.intelligence.research.combiner import exchange_sessions
    from src.intelligence.research.timing import e17_memory, timing_series

    spec = _spec(name)
    sessions = exchange_sessions(
        np.datetime64(spec.panel.start), np.datetime64(spec.panel.end_exclusive) - 1
    )
    n = len(sessions)
    trade = sessions >= np.datetime64(spec.scoring.trading_start)
    memory = e17_memory(
        max(m.slot_history_sessions for m in spec.members),
        spec.horizon,
        1,
        spec.construction.vol_window_sessions,
    )
    series = timing_series(
        np.ones((n, 2)),
        np.full((n, 2), 0.001),
        np.ones(n, dtype=bool),
        trade,
        bars_per_session=1,
        warmup_sessions=spec.scoring.warmup_sessions,
        memory_sessions=memory,
    )
    tested = sessions[np.isfinite(series)]
    for start, end in spec.scoring.sub_periods:
        inside = (tested >= np.datetime64(start)) & (tested <= np.datetime64(end))
        assert inside.sum() >= MIN_TESTED_SESSIONS, (name, start, end, int(inside.sum()))
