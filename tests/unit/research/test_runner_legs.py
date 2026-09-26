"""Family 2 through the runner (B1, B3): the legs transform, per-leg S1, the members' universe
filter, the transform's causality probe, the uncharged book refusal, and family 1's spec hash
staying unchanged."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import numpy as np
import pytest

from src.intelligence.research import legs
from src.intelligence.research import runner as runner_mod
from src.intelligence.research.families.common import declared_memory_rows
from src.intelligence.research.guards import GuardFailure
from src.intelligence.research.runner import BudgetConfig, RunContext, run_family
from src.intelligence.research.spec import load_spec_from_file
from tests.unit.research.test_runner_order import _panel

F2 = "src.intelligence.research.families.overnight_intraday"
MEMBERS = [  # name, function, params, slot history (prereg section 3)
    ("intraday_persistence_20", "intraday_persistence", "{window_sessions: 20}", 20),
    ("overnight_to_intraday_20", "overnight_to_intraday", "{window_sessions: 20}", 21),
    ("gap_fade", "gap_fade", "{}", 1),
    ("gap_fade_z", "gap_fade_z", "{window_sessions: 20}", 21),
]


def _spec_text(universe_line: str = "") -> str:
    members = "".join(f"""
  - name: {name}
    signal: {F2}.{fn}
    params: {params}
    slot_history_sessions: {hist}
    declared_memory_rows: {declared_memory_rows(hist, 3)}""" for name, fn, params, hist in MEMBERS)
    return (
        textwrap.dedent(f"""
        kind: family
        family: f2_test
        prior_source: docs/plans/prereg.md
        horizon: 1
        factor_spec: vintage_1
        panel:
          universe: compute_eligible
          tf: 15m
          bars_per_session: 4
          start: "2010-01-01"
          end_exclusive: "2012-01-01"
          transform: session_legs
          {universe_line}
        members:""")
        + members
        + textwrap.dedent("""
        construction:
          name: rank_vol_neutral
          direction: 1
          coverage_floor: 20
          vol_window_sessions: 20
          vol_min_finite_fraction: 0.5
        scoring:
          session_scoring: true
          trading_start: "2010-01-01"
          sub_periods: [["2010-01-01", "2011-12-31"]]
          min_shift: 5
          bootstrap_mean_block: 5
          bootstrap_reps: 200
          seed: 1
          warmup_sessions: 20
          calibration_refit_sessions: 10
          coverage_fraction: 0.5
          ridge_epsilon_fraction: 0.1
          mv_condition_max: 1000.0
          ic_shrinkage_k: 100.0
          timing_statistic: e17
        guards: {seed: 3, n_random: 1, max_rows: 6, s1_probe_sessions: 330}
        costs: {bps_low: 1.0, bps_high: 5.0}
        """)
    )


def _load(tmp_path: Path, text: str):
    path = tmp_path / "research/specs/f2.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return load_spec_from_file(path, root=tmp_path)


def test_synthetic_family2_run_completes_on_the_legs_panel(tmp_path):
    loaded = _load(tmp_path, _spec_text())
    assert loaded.model.panel.analysis_bars_per_session == 3
    ctx = RunContext(root=tmp_path, budget=BudgetConfig("test", 1, 0.05))
    out = asyncio.run(run_family(loaded, ctx, mode="synthetic", panel=_panel()))
    assert {v["status"] for v in out.values()} == {"completed"}, out
    rec = out["gap_fade"]["evidence"]
    assert rec["hashes"]["transform"] == "session_legs"


def test_prepare_panel_narrows_to_the_members_universe(tmp_path):
    loaded = _load(tmp_path, _spec_text("members_universe: us_session_equity"))
    src = _panel()
    panel, probe = runner_mod._prepare_panel(
        loaded.model, src, source_hash="h", symbols=["S3", "S1", "ZZ"]
    )
    assert panel.symbols == ("S1", "S3") and panel.bars_per_session == 3
    assert panel.manifest["members_universe"] == "us_session_equity"
    assert panel.manifest["members_universe_size"] == 2
    assert probe.bars_per_session == 4 and probe.symbols == ("S1", "S3")


def test_transform_probe_catches_a_lookahead(monkeypatch):
    src = _panel()
    rows = np.array([3 * 50, 3 * 50 + 1, 3 * 50 + 2])
    legs.transform_causality_probe(src, rows, seed=0)  # the real transform passes

    real = legs.session_legs

    def peeking(source, **kw):  # row 1's close reads the next session's bar 0
        out = real(source, **kw)
        c = out.close.copy()
        c[1:-3:3] = out.close[4::3]
        return out.__class__(**{**out.__dict__, "close": c})

    monkeypatch.setattr(legs, "session_legs", peeking)
    with pytest.raises(GuardFailure, match="lookahead"):
        legs.transform_causality_probe(src, rows, seed=0)


def test_book_with_a_transformed_family_is_refused_before_the_ledger(tmp_path):
    from src.intelligence.research.runner import RunRefused, run_book

    fam = _load(tmp_path, _spec_text())
    fake_book = type("L", (), {"model": object.__new__(runner_mod.BookSpec), "families": [fam]})
    ctx = RunContext(root=tmp_path, budget=BudgetConfig("test", 1, 0.05))
    with pytest.raises(RunRefused, match="B2"):
        asyncio.run(run_book(fake_book, ctx, mode="real"))


def test_family1_spec_hash_unchanged_by_the_new_optional_fields():
    root = Path(__file__).resolve().parents[3]
    loaded = load_spec_from_file(
        root / "research/specs/family1_intraday_periodicity.yaml", root=root
    )
    assert loaded.spec_hash == "b828c285a369b97f35790585327e7a8d8ae98af2db65ec059204603fae172466"
    assert loaded.model.panel.transform is None
    assert loaded.model.panel.analysis_bars_per_session == 26
    book = load_spec_from_file(root / "research/specs/book_v1.yaml", root=root)
    assert book.spec_hash == "4cf8d2e98e5e140c120062c560b53b9914cc866581e9a992e38202193f9e2604"
