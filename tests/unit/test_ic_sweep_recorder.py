"""IC sweep recorder (todo 671, ledger 2026-11-24i): spec identity, series and direction, the
purge, the declared n_looks, resumability, and the per-session measurement. The ledger SQL has
its own tests (tests/unit/research/test_ledger_sweep_block.py)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from services import ic_sweep_recorder as rec
from src.intelligence.measure.session_ic import session_rank_ic
from src.intelligence.research.ledger import AttemptSeries, LedgerRefusal

OOS = datetime(2025, 12, 24, 5, 15, tzinfo=UTC)


def _spec(**overrides):
    base = dict(
        tf="1d",
        horizon=5,
        direction="long",
        min_names=30,
        oos_start=OOS,
        panels_key="p",
        features_key="f",
        feature_names=["b", "a"],
    )
    return rec.block_spec(**{**base, **overrides})


def test_spec_hash_moves_with_every_input_and_not_with_name_order():
    base = _spec()
    assert base == _spec(feature_names=["a", "b"])  # order does not matter
    assert base[2] != _spec(direction="short")[2]
    for change in (
        {"horizon": 1},
        {"min_names": 31},
        {"panels_key": "q"},
        {"features_key": "g"},
        {"feature_names": ["a"]},
    ):
        assert base[2] != _spec(**change)[2], change
    assert base[0].startswith("research/sweeps/1d_h5_long_") and base[0].endswith(".json")
    with pytest.raises(ValueError):
        _spec(direction="both")


def test_series_keeps_tested_sessions_and_short_is_the_negation():
    days = np.array(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"], dtype="datetime64[D]")
    ic = np.array([0.1, np.nan, -0.2, 0.3])
    long = rec.cell_series(days, ic, direction="long", oos_start=OOS)
    short = rec.cell_series(days, ic, direction="short", oos_start=OOS)
    assert list(long.sessions) == [days[0], days[2], days[3]]
    np.testing.assert_array_equal(long.values, [0.1, -0.2, 0.3])
    np.testing.assert_array_equal(short.values, -long.values)
    assert rec.cell_series(days, np.full(4, np.nan), direction="long", oos_start=OOS) is None


def test_series_reaching_oos_start_is_refused():
    days = np.array(["2025-12-22", "2025-12-24"], dtype="datetime64[D]")
    with pytest.raises(ValueError, match="oos_start"):
        rec.cell_series(days, np.array([0.1, 0.2]), direction="long", oos_start=OOS)


def test_evidence_carries_the_cell_and_the_hac_disclosure():
    series = AttemptSeries(
        np.arange("2020-01-01", "2020-03-01", dtype="datetime64[D]"),
        np.random.default_rng(1).standard_normal(60) * 0.02 + 0.01,
    )
    ev = rec.cell_evidence(feature="f", tf="1d", horizon=5, direction="long", series=series)
    assert ev["cell"] == {"feature": "f", "tf": "1d", "horizon": 5, "direction": "long"}
    assert ev["decision"]["n_sessions"] == 60 and "t" in ev["decision"] and "p" in ev["decision"]


class FakeLedger:
    def __init__(self, recorded=()):
        self.recorded = set(recorded)
        self.blocks: list[tuple] = []

    async def has_real_run(self, digest):
        return digest in self.recorded

    async def record_sweep_block(self, request, cells):
        self.blocks.append((request, cells))
        return {name: "run" for name in cells}


def _measurement():
    sessions = np.arange("2020-01-01", "2020-01-11", dtype="datetime64[D]")
    ic = np.random.default_rng(2).standard_normal((10, 3)) * 0.05
    ic[:, 2] = np.nan  # a column with no tested session
    return rec.Measurement(
        sessions=sessions,
        names=("a", "b", "c"),
        ic={1: ic, 5: ic * 2},
        panels_key="p",
        features_key="f",
        excluded_no_concept=("zz",),
    )


def _record(ledger, m, **kw):
    args = dict(
        tf="1d",
        horizons=(1, 5),
        min_names=30,
        oos_start=OOS,
        vintage="v",
        code_commit="c" * 40,
        declared_n_looks=8,
        dry_run=False,
    )
    return asyncio.run(rec.record_blocks(ledger, m, **{**args, **kw}))


def test_two_attempts_per_cell_per_horizon_and_unmeasured_are_reported():
    ledger = FakeLedger()
    report = _record(ledger, _measurement())
    assert report["recorded"] == 8 and report["attempts_to_record"] == 8  # 2 cells x 2 x 2
    assert len(ledger.blocks) == 4
    assert report["unmeasured"] == {"1": ["c"], "5": ["c"]}
    assert report["excluded_no_concept"] == ["zz"]
    directions = [b[0].spec_path.split("_")[1:3] for b in ledger.blocks]
    assert sorted(d[1] for d in directions) == ["long", "long", "short", "short"]
    long = next(c for r, c in ledger.blocks if "_h1_long_" in r.spec_path)["a"][0]
    short = next(c for r, c in ledger.blocks if "_h1_short_" in r.spec_path)["a"][0]
    np.testing.assert_array_equal(short.values, -long.values)


def test_declared_n_looks_must_equal_the_attempts_before_any_write():
    ledger = FakeLedger()
    with pytest.raises(LedgerRefusal, match="declared n_looks 7"):
        _record(ledger, _measurement(), declared_n_looks=7)
    with pytest.raises(LedgerRefusal, match="declared n_looks None"):
        _record(ledger, _measurement(), declared_n_looks=None)
    assert ledger.blocks == []


def test_dry_run_writes_nothing_and_needs_no_declaration():
    ledger = FakeLedger()
    report = _record(ledger, _measurement(), dry_run=True, declared_n_looks=None)
    assert ledger.blocks == [] and report["recorded"] == 0 and report["attempts_to_record"] == 8


def test_a_recorded_block_is_skipped_so_the_run_resumes():
    first = FakeLedger()
    _record(first, _measurement())
    done = {r.spec_hash for r, _ in first.blocks[:2]}
    ledger = FakeLedger(recorded=done)
    report = _record(ledger, _measurement(), declared_n_looks=4)
    assert report["attempts_already_recorded"] == 4 and report["recorded"] == 4
    assert len(ledger.blocks) == 2


# --- measure: the per-session IC on a session's one grid ---------------------------------


def _session(n=8, m=40, k=4, horizons=(1, 2)):
    rng = np.random.default_rng(5)
    feats = rng.standard_normal((n, m, k))
    targets = {h: 0.2 * feats[:, :, 0] + rng.standard_normal((n, m)) for h in horizons}
    exists = np.ones((n, m), dtype=bool)
    grid = SimpleNamespace(
        timestamps=np.array([f"2020-01-0{i + 1}" for i in range(n)], dtype="datetime64[ns]"),
        valid_grid=lambda: exists,
    )
    ctx = SimpleNamespace(
        panels=[SimpleNamespace(bars_per_session=1)],
        grid=grid,
        present=exists,
        stack=lambda h: SimpleNamespace(targets=targets[h]),
    )
    names = [f"f{i}" for i in range(k)]
    session = SimpleNamespace(
        ctx=ctx,
        names=names,
        run=SimpleNamespace(apr={rec._BLOCK_COLUMNS_KEY: 2}, horizons=horizons),
        fetch=lambda block: feats[:, :, [int(b[1:]) for b in block]],
    )
    return session, feats, targets, exists


def test_measure_matches_the_pure_function_for_any_block_width(monkeypatch):
    monkeypatch.setattr(rec, "panels_digest", lambda grid, panels: "p")
    session, feats, targets, exists = _session()
    got = rec.measure(session, {"f0", "f1", "f2", "f3", "other"}, min_names=5)
    assert got.names == ("f0", "f1", "f2", "f3")
    for h in (1, 2):
        np.testing.assert_array_equal(
            got.ic[h], session_rank_ic(feats, targets[h], exists, min_names=5)
        )
    session.run.apr[rec._BLOCK_COLUMNS_KEY] = 4
    again = rec.measure(session, {"f0", "f1", "f2", "f3"}, min_names=5)
    for h in (1, 2):
        np.testing.assert_array_equal(got.ic[h], again.ic[h])
    assert got.features_key == again.features_key


def test_measure_excludes_columns_without_a_feature_concept(monkeypatch):
    monkeypatch.setattr(rec, "panels_digest", lambda grid, panels: "p")
    session, *_ = _session()
    got = rec.measure(session, {"f0", "f2"}, min_names=5)
    assert got.names == ("f0", "f2") and got.excluded_no_concept == ("f1", "f3")


def test_an_intraday_clock_is_refused():
    session, *_ = _session()
    session.ctx.panels[0].bars_per_session = 78
    with pytest.raises(ValueError, match="1d clock"):
        rec.measure(session, {"f0"}, min_names=5)
