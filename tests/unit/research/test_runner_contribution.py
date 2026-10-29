# ruff: noqa: F811  (fixtures imported from test_runner_book are used as arguments)
"""run_book records contribution accounting (phase 187 plan 14 Task 3): the block, the counted
subset refits, and the book's own decision block unchanged by the extension."""

import asyncio

import numpy as np
import pytest

from src.intelligence.research import runner as runner_mod
from src.intelligence.research.runner import BudgetConfig, ContributionConfig, RunContext, run_book
from src.intelligence.research.spec import load_spec_from_file, load_spec_from_head
from tests.unit.research.test_runner_book import (  # noqa: F401  (fixtures)
    BOOK_PATH,
    BookLedger,
    _book_text,
    _certified,
    _ctx,
    fast_power,
    saved_panel,
)
from tests.unit.research.test_runner_order import (
    SPEC_PATH,
    _git,
    _panel,
    _spec_text,
)

SPEC2_PATH = "research/specs/fam2.yaml"
SETTINGS = ContributionConfig(
    exact_max_families=12, shapley_samples=50, shapley_seed=1, cluster_corr=0.7
)


def _repo(tmp_path, two_families):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "research/specs").mkdir(parents=True)
    (tmp_path / "src/intelligence").mkdir(parents=True)
    (tmp_path / SPEC_PATH).write_text(_spec_text())
    book = _book_text()
    if two_families:
        (tmp_path / SPEC2_PATH).write_text(
            _spec_text().replace("family: test_fam", "family: test_fam2")
        )
        book = book.replace(f"families: [{SPEC_PATH}]", f"families: [{SPEC_PATH}, {SPEC2_PATH}]")
    (tmp_path / BOOK_PATH).write_text(book)
    (tmp_path / "src/intelligence/x.py").write_text("X = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


@pytest.fixture
def repo1(tmp_path):
    return _repo(tmp_path, False)


@pytest.fixture
def repo2(tmp_path, monkeypatch):
    # No power plant spans several families yet (run_book refuses them); the accounting path is
    # exercised with the plant of the first family standing in for the book's.
    real = runner_mod.check_family_plant
    monkeypatch.setattr(runner_mod, "check_family_plant", lambda fams, power: real(fams[:1], power))
    return _repo(tmp_path, True)


def _synthetic(repo, contribution):
    loaded = load_spec_from_file(repo / BOOK_PATH, root=repo)
    ctx = RunContext(root=repo, budget=BudgetConfig("test", 1, 0.05), contribution=contribution)
    return asyncio.run(run_book(loaded, ctx, mode="synthetic", panel=_panel(), power_replicates=2))


def test_the_books_decision_is_identical_with_and_without_accounting(repo1, fast_power):
    plain = _synthetic(repo1, None)["evidence"]
    counted = _synthetic(repo1, SETTINGS)["evidence"]
    assert "contribution" not in plain
    assert counted["decision"] == plain["decision"] and counted["screen"] == plain["screen"]


def test_run_book_of_one_family_records_attribution_uniqueness_and_breadth_only(repo1, fast_power):
    block = _synthetic(repo1, SETTINGS)["evidence"]["contribution"]
    assert block["headline"]["n_families"] == 1
    assert "lofo" not in block and "shapley" not in block
    assert set(block["attribution"]["groups"]) == {"test_fam"}
    assert len(block["attribution"]["members"]) == 2 and "effective_breadth" in block
    assert "sign_stability" in block  # the test book is a ridge


def test_two_family_book_records_lofo_in_synthetic_mode_without_a_ledger(repo2, fast_power):
    calls = []
    real = runner_mod.book_timing

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    runner_mod.book_timing, saved = spy, runner_mod.book_timing
    try:
        block = _synthetic(repo2, SETTINGS)["evidence"]["contribution"]
    finally:
        runner_mod.book_timing = saved
    assert len(calls) == 3  # the book and its two leave-one-family-out refits
    assert set(block["lofo"]) == {"test_fam", "test_fam2"}
    assert block["shapley"]["method"] == "not_computed"  # 2 families: below the 4-family floor
    assert block["headline"]["n_families"] == 2 and block["headline"]["lofo_max_t_drop"] is not None


class SubsetLedger(BookLedger):
    def __init__(self):
        super().__init__()
        self.subsets, self.finished = {}, []

    async def start_subset_refits(self, parent_run_id, refits, author):
        self.calls.append("start_subset_refits")
        self.parent = parent_run_id
        ids = {}
        for i, refit in enumerate(refits):
            ids[tuple(sorted(refit.subset))] = f"sub-{i}"
            self.subsets[f"sub-{i}"] = refit
        return ids

    async def finish_run(self, run_id, *, status, snapshot_hash, evidence, series=None):
        if run_id.startswith("sub-"):
            self.finished.append((run_id, status, evidence, series))
            return
        await super().finish_run(
            run_id, status=status, snapshot_hash=snapshot_hash, evidence=evidence, series=series
        )


def test_real_two_family_book_records_each_subset_refit_as_an_attempt(
    repo2, saved_panel, fast_power
):
    ledger = SubsetLedger()
    ctx = _ctx(repo2, ledger, saved_panel)
    ctx.contribution = SETTINGS
    out = asyncio.run(run_book(load_spec_from_head(repo2, BOOK_PATH), ctx, mode="real"))
    assert out["status"] == "completed"
    assert ledger.calls.index("start_subset_refits") < ledger.calls.index(
        ("finish_run", "completed")
    )
    assert ledger.parent == "run-0"
    assert sorted(r.subset for r in ledger.subsets.values()) == [("test_fam",), ("test_fam2",)]
    assert [s for _, s, _, _ in ledger.finished] == ["completed", "completed"]
    for _, _, evidence, series in ledger.finished:
        assert evidence["stage"] == "subset_refit" and "t" in evidence["decision"]
        assert series is not None
    recipe = next(iter(ledger.subsets.values())).recipe
    assert (
        recipe.params["accounting"] == "family_lofo_shapley_v1"
        and recipe.params["parent_recipe_hash"]
    )
    assert "contribution" in ledger.evidence and ledger.evidence["contribution"]["lofo"]


def test_a_failing_accounting_never_fails_the_finished_book_test(repo1, fast_power, monkeypatch):
    def boom(*args, **kwargs):
        raise np.linalg.LinAlgError("Eigenvalues did not converge")

    monkeypatch.setattr(runner_mod.contribution, "account", boom)
    out = _synthetic(repo1, SETTINGS)
    assert out["status"] == "completed"
    assert "LinAlgError" in out["evidence"]["contribution"]["error"]
    assert out["evidence"]["decision"]["t"] is not None


def test_one_failing_subset_refit_is_recorded_failed_and_the_other_still_completes(
    repo2, saved_panel, fast_power, monkeypatch
):
    real = runner_mod._refit_subset
    seen = []

    def flaky(book, stack, cols, **kwargs):
        seen.append(tuple(cols))
        if len(seen) == 1:
            raise ValueError("refit blew up")
        return real(book, stack, cols, **kwargs)

    monkeypatch.setattr(runner_mod, "_refit_subset", flaky)
    ledger = SubsetLedger()
    ctx = _ctx(repo2, ledger, saved_panel)
    ctx.contribution = SETTINGS
    out = asyncio.run(run_book(load_spec_from_head(repo2, BOOK_PATH), ctx, mode="real"))
    assert out["status"] == "completed"
    assert sorted(s for _, s, _, _ in ledger.finished) == ["completed", "failed"]
    assert any("refit blew up" in e.get("error", "") for _, _, e, _ in ledger.finished)
    lofo = ledger.evidence["contribution"]["lofo"]
    assert sorted(np.isfinite(v["t_without"]) for v in lofo.values()) == [False, True]


def test_attribution_covers_only_the_sessions_the_statistic_scored(repo1, fast_power):
    out = _synthetic(repo1, SETTINGS)["evidence"]
    assert out["contribution"]["attribution"]["total"] is not None
    assert out["decision"]["n_sessions"] > 0
