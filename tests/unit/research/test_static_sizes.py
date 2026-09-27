"""E17's per-family static-size precondition (todo 447): the gate comes from the battery's gating
cells, the measurement recovers planted sizes on the panel the run scores, and the runner refuses
a family above the gate (uncharged, recorded) and records the sizes when it passes."""

from __future__ import annotations

import asyncio
import dataclasses

import numpy as np
import pytest

from src.intelligence.research import dividends, static_sizes
from src.intelligence.research import null_battery as nb1
from src.intelligence.research import null_battery_overnight_intraday as nb2
from src.intelligence.research import runner as runner_mod
from src.intelligence.research.families import intraday_periodicity as F1
from src.intelligence.research.families import overnight_intraday as F2
from src.intelligence.research.panel import Panel
from src.intelligence.research.runner import BudgetConfig, RunContext, RunRefused, run_family
from src.intelligence.research.spec import load_spec_from_head
from tests.unit.research import test_runner_legs as legs_tests
from tests.unit.research.test_runner_order import (
    BPS,
    SESSIONS,
    SPEC_PATH,
    FakeLedger,
    _ctx,
    _panel,
    repo,  # noqa: F401 - fixture
    saved_panel,  # noqa: F401 - fixture
)

IDIO_SD = 0.002  # per-bar idiosyncratic sd of the panels below


def _static_panel(static_sd: float, *, seed=0, m=60, sessions=SESSIONS) -> Panel:
    """Independent names with a fixed per-(bar, name) mean of static_sd slot sds, no factor."""
    rng = np.random.default_rng(seed)
    n = sessions * BPS
    slot_sd = IDIO_SD * np.sqrt(2)  # a family 1 slot is two bars
    slot_mu = static_sd * slot_sd * rng.standard_normal((BPS // 2, m))
    mu = np.repeat(slot_mu, 2, axis=0) / 2  # both bars of a slot carry half its mean
    r = IDIO_SD * rng.standard_normal((n, m)) + np.tile(mu, (sessions, 1))
    close = 100 * np.exp(np.cumsum(r, axis=0))
    opens = np.vstack([np.full((1, m), 100.0), close[:-1]])
    days = np.datetime64("2010-01-04T14:30") + np.repeat(np.arange(sessions), BPS) * np.timedelta64(
        1, "D"
    )
    ts = days + np.tile(np.arange(BPS), sessions) * np.timedelta64(15, "m")
    return Panel(
        tf="15m",
        symbols=tuple(f"S{i}" for i in range(m)),
        timestamps=ts,
        bars_per_session=BPS,
        valid=np.ones(n, dtype=bool),
        open=opens,
        close=close,
        volume=np.full((n, m), 1e5),
        manifest={
            "start": "2010-01-01",
            "end_exclusive": "2012-01-01",
            "universe": "compute_eligible",
        },
    )


def _measure(panel: Panel, cell_rows: int = 2) -> static_sizes.StaticSizes:
    return static_sizes.measure(
        panel, cell_rows=cell_rows, trading_start="2010-01-01", coverage_floor=20
    )


def test_gates_come_from_the_batteries_gating_cells():
    g1 = static_sizes.gate_for(F1)
    assert g1.battery == nb1.__name__ and g1.cell_rows == nb1.SLOT_BARS
    assert g1.static_sd == (2 * nb1.MEASURED_STATIC_CELL_SD,)
    assert g1.time_of_day == (2 * nb1.MEASURED_SLOT_EFFECT_SD,)
    g2 = static_sizes.gate_for(F2)
    assert g2.cell_rows == 1
    assert g2.static_sd == pytest.approx(tuple(2 * v for v in nb2.MEASURED_STATIC_SD))
    assert g2.time_of_day == pytest.approx(tuple(2 * abs(a) for a in nb2.MEASURED_LEG_MEANS))


def test_diagnostic_cells_never_set_the_gate():
    cells = nb1.scenarios()
    assert max(c.static_cell_sd for c in cells) == 0.3  # the diagnostics are there
    assert static_sizes.gate_for(F1).static_sd[0] < 0.3


def test_measure_recovers_a_planted_static_sd_and_none_on_a_null_panel():
    null = _measure(_static_panel(0.0, m=200, sessions=1500))
    assert null.pooled_static_sd() < 0.02
    planted = _measure(_static_panel(0.2, m=200, sessions=1500))
    assert planted.pooled_static_sd() == pytest.approx(0.2, rel=0.2)
    assert planted.split_half_corr > 0.5
    assert planted.names == 200


def test_time_of_day_is_net_of_sampling_noise():
    """A market factor with no time-of-day mean: the raw rms is noise, the net size is not."""
    p = _panel(seed=1)
    sizes = _measure(p)
    assert sizes.pooled_time_of_day_raw() > 0.05  # what a raw rms would refuse on
    assert sizes.pooled_time_of_day() < sizes.pooled_time_of_day_raw()
    se = np.asarray(sizes.per_cell_time_of_day_se)
    assert (se > 0).all()


def test_exceedances_name_the_offending_measure():
    gate = static_sizes.StaticGate("b", 1, (0.05, 0.05, 0.05), (0.1, 0.1, 0.1))
    sizes = static_sizes.StaticSizes(
        (0.01, 0.2, 0.01), (0.0, 0.0, 0.5), (0.01, 0.01, 0.01), 0.1, 500, 60
    )
    problems = static_sizes.exceedances(sizes, gate)
    assert len(problems) == 2
    assert "static sd (cell 1)" in problems[0] and "time of day (cell 2)" in problems[1]


def test_synthetic_family_above_the_gate_is_refused_with_its_sizes(repo):  # noqa: F811
    loaded = load_spec_from_head(repo, SPEC_PATH)
    ctx = RunContext(root=repo, budget=BudgetConfig("test", 1, 0.05))
    out = asyncio.run(run_family(loaded, ctx, mode="synthetic", panel=_static_panel(0.3)))
    assert {v["status"] for v in out.values()} == {"refused"}
    ev = out["lag1"]["evidence"]
    assert ev["stage"] == "refusal" and "static sd (pooled)" in ev["refusal"]
    assert nb1.__name__ in ev["refusal"]
    block = ev["static_sizes"]["test_fam"]
    assert block["passes"] is False and block["pooled_static_sd"] > 0.038


def test_synthetic_family_below_the_gate_runs_and_records_its_sizes(repo):  # noqa: F811
    loaded = load_spec_from_head(repo, SPEC_PATH)
    ctx = RunContext(root=repo, budget=BudgetConfig("test", 1, 0.05))
    out = asyncio.run(run_family(loaded, ctx, mode="synthetic", panel=_static_panel(0.0)))
    assert {v["status"] for v in out.values()} == {"completed"}
    block = out["lag1"]["evidence"]["static_sizes"]["test_fam"]
    assert block["passes"] is True and block["method"] == static_sizes.METHOD
    assert block["gate"]["static_sd"] == [2 * nb1.MEASURED_STATIC_CELL_SD]


def test_real_refusal_is_recorded_and_uncharged(repo, tmp_path):  # noqa: F811
    from src.intelligence.research import panel as panel_mod
    from src.intelligence.research.ledger import UNCHARGED_STATUSES

    saved = panel_mod.save(_static_panel(0.3), tmp_path)
    ledger = FakeLedger()
    loaded = load_spec_from_head(repo, SPEC_PATH)
    out = asyncio.run(run_family(loaded, _ctx(repo, ledger, saved, []), mode="real"))
    assert ledger.calls[:3] == ["has_real_run", "start_runs", "build_snapshot"]
    assert ledger.calls[3:] == [("finish_run", "refused")] * 2
    assert "refused" in UNCHARGED_STATUSES
    assert ledger.evidence["static_sizes"]["test_fam"]["passes"] is False
    assert {v["status"] for v in out.values()} == {"refused"}


def test_family_without_a_battery_is_refused_before_the_ledger(
    repo, saved_panel, monkeypatch  # noqa: F811
):
    monkeypatch.delattr(F1, "NULL_BATTERY")
    ledger = FakeLedger()
    loaded = load_spec_from_head(repo, SPEC_PATH)
    with pytest.raises(RunRefused, match="no E17 H0 battery"):
        asyncio.run(run_family(loaded, _ctx(repo, ledger, saved_panel, []), mode="real"))
    assert "start_runs" not in ledger.calls


def _dividend_payers(panel: Panel, payers: int, every: int, y: float):
    """Price-only bars whose first `payers` names drop by y at each ex-date session's open, and
    the grid that records those dividends."""
    n_s, bps, m = panel.n_sessions, panel.bars_per_session, len(panel.symbols)
    ex = np.zeros((n_s, m))
    ex[every::every, :payers] = y
    drop = np.repeat(np.cumprod(1 - ex, axis=0), bps, axis=0)
    priced = dataclasses.replace(panel, open=panel.open * drop, close=panel.close * drop)
    covered = np.ones((n_s, m), dtype=bool)
    grid = dividends.DividendGrid(panel.symbols, ex, np.zeros((n_s, m)), covered)
    return priced, grid


def test_total_return_spec_is_measured_on_total_return_legs(tmp_path):
    """The measurement reads the analysis panel: after total_return and the legs transform.
    Dividend payers' overnight legs carry a static loss in price-only bars and none in total
    return."""
    loaded = legs_tests._load(
        tmp_path, legs_tests._spec_text("total_return: {suspect_yield: 0.10}")
    )
    spec = loaded.model
    priced, grid = _dividend_payers(_static_panel(0.0, m=60, sessions=SESSIONS), 30, 5, 0.01)
    total, _ = runner_mod._prepare_panel(spec, priced, source_hash=None, symbols=None, grid=grid)
    price_only, _ = runner_mod._prepare_panel(
        spec, priced, source_hash=None, symbols=None, grid=dividends.no_dividends(priced)
    )
    gate = static_sizes.gate_for(F2)
    tr = runner_mod.static_precondition(spec, total, gate)
    po = runner_mod.static_precondition(spec, price_only, gate)
    assert po["per_cell_static_sd"][0] > 5 * max(tr["per_cell_static_sd"][0], 0.01)
    assert tr["passes"] and not po["passes"]


def test_split_segments_are_measured_as_separate_names():
    p = _static_panel(0.0, m=40)
    n_s, m = p.n_sessions, len(p.symbols)
    unconfirmed = np.zeros((n_s, m))
    unconfirmed[SESSIONS // 2, 0] = 0.5  # one suspect event splits S0
    grid = dividends.DividendGrid(
        p.symbols, unconfirmed.copy(), unconfirmed, np.ones((n_s, m), dtype=bool)
    )
    split = dividends.total_return(p, grid, suspect_yield=0.1)
    assert "S0~1" in split.symbols
    assert _measure(split).names == m + 1
