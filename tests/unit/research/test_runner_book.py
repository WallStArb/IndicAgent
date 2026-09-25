"""Runner book mode (D-08, D-09, D-11, D-21): gate, charged row, shift floor, exact power
refusal, S8 and the screen outcome."""

import asyncio
import textwrap

import numpy as np
import pytest

from src.intelligence.research import runner as runner_mod
from src.intelligence.research.power import PowerDecision, PowerRun
from src.intelligence.research.runner import (
    BudgetConfig,
    RunContext,
    RunRefused,
    book_identities,
    run_book,
)
from src.intelligence.research.spec import load_spec_from_file, load_spec_from_head
from src.intelligence.research.synthetic import CalibratedPlant
from tests.unit.research.test_runner_order import (
    BPS,
    SPEC_PATH,
    FakeLedger,
    _git,
    _panel,
    _spec_text,
)

BOOK_PATH = "research/specs/book.yaml"
KEYS = {"schema", "decision", "shift_null", "power", "screen", "cost_band"}


def _book_text(replicates=4):
    return textwrap.dedent(f"""
        kind: book
        book: test_book
        prior_source: docs/plans/prereg.md
        families: [{SPEC_PATH}]
        combiner: {{window_sessions: 80, refit_sessions: 10, penalty: 1.0, min_obs: 200}}
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
        guards: {{seed: 3, n_random: 1, max_rows: 6, s1_probe_sessions: 330}}
        costs: {{bps_low: 1.0, bps_high: 5.0}}
        power:
          planted_rank_ic: 0.05
          participation_ratio: 10.0
          n_common_factors: 3
          plant_lags_sessions: 5
          replicates: {replicates}
          seed: 11
          calibration_panels: 1
          calibration_seed: 12
          calibration_tolerance: 0.01
        """)


@pytest.fixture(scope="module")
def saved_panel(tmp_path_factory):
    from src.intelligence.research import panel as panel_mod

    return panel_mod.save(_panel(), tmp_path_factory.mktemp("panels"))


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "research/specs").mkdir(parents=True)
    (tmp_path / "src/intelligence").mkdir(parents=True)
    (tmp_path / SPEC_PATH).write_text(_spec_text())
    (tmp_path / BOOK_PATH).write_text(_book_text())
    (tmp_path / "src/intelligence/x.py").write_text("X = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@pytest.fixture
def fast_power(monkeypatch):
    """Replace calibration and replicates with a recorded, powered decision."""
    calls = []

    def calibrate(*args, **kwargs):
        return CalibratedPlant(0.1, 0.05, 0.001, 3)

    def estimate(problem, **kwargs):
        calls.append(("estimate_power", problem.bar))
        calls.append(("masks", problem.finite_mask, problem.target_mask))
        return PowerRun(PowerDecision(True, 60, 10, 100, 0.5, 70), (), 1.0)

    monkeypatch.setattr(runner_mod.synthetic, "calibrate_plant", calibrate)
    monkeypatch.setattr(runner_mod.power, "estimate_power", estimate)
    return calls


def _ctx(repo, ledger, saved_panel, budget_m=1):
    async def build(dsn, out_dir, spec):
        ledger.calls.append("build_snapshot")
        return saved_panel

    return RunContext(
        root=repo,
        budget=BudgetConfig(vintage_id="test", budget_m=budget_m, screen_alpha=0.05),
        ledger=ledger,
        build_snapshot=build,
    )


class BookLedger(FakeLedger):
    async def start_runs(self, request, identities, run_concepts):
        self.request, self.identities = request, identities
        return await super().start_runs(request, identities, run_concepts)


def _run(repo, ledger, saved_panel, **kw):
    loaded = load_spec_from_head(repo, BOOK_PATH)
    return asyncio.run(run_book(loaded, _ctx(repo, ledger, saved_panel, **kw), mode="real"))


def _spy_evaluate(monkeypatch, ledger):
    real = runner_mod.book_timing

    def spy(*args, **kwargs):
        ledger.calls.append("book_timing")
        return real(*args, **kwargs)

    monkeypatch.setattr(runner_mod, "book_timing", spy)


def test_real_order_and_request(repo, saved_panel, fast_power, monkeypatch):
    ledger = BookLedger()
    _spy_evaluate(monkeypatch, ledger)
    out = _run(repo, ledger, saved_panel)
    assert ledger.calls[:3] == ["has_real_run", "start_runs", "build_snapshot"]
    assert ledger.calls[3:] == ["book_timing", ("finish_run", "completed")]
    assert fast_power  # estimate_power ran, before evaluate_book (it is not in ledger.calls)
    r = ledger.request
    assert (r.kind, r.budget_m, r.screen_alpha, r.vintage) == ("book_test", 1, 0.05, "test")
    assert out["status"] == "completed"
    ev = ledger.evidence
    assert KEYS <= set(ev)
    assert ev["screen"]["p"] == ev["decision"]["p"]
    assert ev["screen"]["p_below_bar"] == (ev["decision"]["p"] < 0.05 / 1)
    assert ev["power"]["powered"] is True and ev["power"]["passes"] == 60
    assert fast_power[0] == ("estimate_power", 0.05 / 1)
    # Replicates are planted on the real residual availability, not the close mask: S1's
    # loading warm-up leaves the first sessions without residuals (no power inflation).
    _, finite_mask, target_mask = fast_power[1]
    closes = np.isfinite(_panel().close)
    assert target_mask is not None
    assert finite_mask.sum() < closes.sum() and not finite_mask[: 200 * BPS].any()


def test_identities_link_book_to_family(repo):
    ids = {i.name: i for i in book_identities(load_spec_from_head(repo, BOOK_PATH))}
    assert ids["book.test_book"].kind == "book_version"
    assert ids["book.test_book"].parents == ("family.test_fam",)
    assert ids["member.test_fam.lag1"].parents == ("family.test_fam",)


def _refused(repo, saved_panel, ledger=None):
    ledger = ledger or BookLedger()
    with pytest.raises(RunRefused):
        _run(repo, ledger, saved_panel)
    assert "build_snapshot" not in ledger.calls
    return ledger


def test_refuses_family_edited_after_commit(repo, saved_panel, fast_power):
    loaded = load_spec_from_head(repo, BOOK_PATH)
    (repo / SPEC_PATH).write_text(_spec_text() + "# edited\n")
    ledger = BookLedger()
    with pytest.raises(RunRefused):
        asyncio.run(run_book(loaded, _ctx(repo, ledger, saved_panel), mode="real"))
    assert "start_runs" not in ledger.calls


def test_refuses_uncommitted_book(repo, saved_panel, fast_power):
    (repo / "research/specs/book2.yaml").write_text(_book_text())
    loaded = load_spec_from_file(repo / "research/specs/book2.yaml", root=repo)
    ledger = BookLedger()
    with pytest.raises(RunRefused):
        asyncio.run(run_book(loaded, _ctx(repo, ledger, saved_panel), mode="real"))
    assert "start_runs" not in ledger.calls


def test_refuses_dirty_code_prior_run_and_exhausted_budget(repo, saved_panel, fast_power):
    assert "start_runs" not in _refused(repo, saved_panel, BookLedger(prior=True)).calls
    _refused(repo, saved_panel, BookLedger(refuse=True))
    (repo / "src/intelligence/new.py").write_text("Y = 1\n")
    assert "start_runs" not in _refused(repo, saved_panel).calls


def test_underpowered_refusal(repo, saved_panel, monkeypatch):
    monkeypatch.setattr(
        runner_mod.synthetic,
        "calibrate_plant",
        lambda *a, **k: CalibratedPlant(0.1, 0.05, 0.001, 3),
    )
    monkeypatch.setattr(
        runner_mod.power,
        "estimate_power",
        lambda problem, **kw: PowerRun(PowerDecision(False, 10, 51, 100, 0.5, 61), (), 1.0),
    )
    ledger = BookLedger()
    _spy_evaluate(monkeypatch, ledger)
    out = _run(repo, ledger, saved_panel)
    assert out["status"] == "refused"
    ev = ledger.evidence
    assert ev["refusal"] == "underpowered at IC 0.05"
    assert ev["power"]["passes"] == 10 and ev["power"]["failures"] == 51
    assert ev["power"]["plant_coef"] == 0.1 and "decision" not in ev
    assert "book_timing" not in ledger.calls


def test_guard_failure_ends_row_guard_failed(repo, saved_panel, fast_power, monkeypatch):
    def fail(*args, **kwargs):
        raise runner_mod.guards.GuardFailure("lookahead: planted")

    monkeypatch.setattr(runner_mod, "real_guards", fail)
    ledger = BookLedger()
    assert _run(repo, ledger, saved_panel)["status"] == "guard_failed"
    assert "lookahead" in ledger.evidence["error"]


def test_evaluate_error_fails_row_and_propagates(repo, saved_panel, fast_power, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("S8 exploded")

    monkeypatch.setattr(runner_mod, "book_timing", boom)
    ledger = BookLedger()
    with pytest.raises(RuntimeError, match="exploded"):
        _run(repo, ledger, saved_panel)
    assert set(ledger.status.values()) == {"failed"}


def test_synthetic_mode_real_power_and_override(repo):
    loaded = load_spec_from_file(repo / BOOK_PATH, root=repo)
    ctx = RunContext(root=repo, budget=BudgetConfig("test", 1, 0.05))
    out = asyncio.run(run_book(loaded, ctx, mode="synthetic", panel=_panel(), power_replicates=2))
    assert out["run_id"] is None
    assert out["status"] in {"completed", "refused"}
    assert out["evidence"]["power"]["replicates"] == 2
    with pytest.raises(ValueError, match="synthetic mode only"):
        asyncio.run(
            run_book(
                loaded,
                RunContext(root=repo, budget=BudgetConfig("t", 1, 0.05), ledger=BookLedger()),
                mode="real",
                power_replicates=2,
            )
        )
