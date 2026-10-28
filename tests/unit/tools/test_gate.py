"""Unit tests for tools/gate.py: what a change needs, the migration-number guard, the step runner
and the cross-session parity lock."""

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tools import gate


def test_a_research_edit_needs_the_frozen_verdict_check():
    assert gate.classify(["src/intelligence/research/combiner.py"]).needs_repro
    assert gate.classify(["src/intelligence/statistics/hac.py"]).needs_repro
    assert gate.classify(["scripts/research/determinism/repro_frozen.py"]).needs_repro


def test_other_edits_do_not():
    plan = gate.classify(
        ["docs/foundation/glossary.md", "tests/unit/research/test_x.py", "services/x.py"]
    )
    assert not plan.needs_repro and plan.migrations == ()


def test_migrations_are_the_top_level_sql_files_sorted():
    plan = gate.classify(
        [
            "production/migrations/531_b.sql",
            "production/migrations/530_a.sql",
            "production/migrations/archive/001_old.sql",
            "production/migrations/README.md",
        ]
    )
    assert plan.migrations == ("production/migrations/530_a.sql", "production/migrations/531_b.sql")


BASE = ["529_spread_window_apr_descriptions.sql", "530_typed_domains.sql"]


def test_a_number_held_by_another_file_on_the_base_is_a_clash():
    problems = gate.migration_clashes(["production/migrations/530_something_else.sql"], BASE)
    assert len(problems) == 1 and "530" in problems[0] and "530_typed_domains.sql" in problems[0]


def test_the_same_file_already_on_the_base_is_not_a_clash():
    assert gate.migration_clashes(["production/migrations/530_typed_domains.sql"], BASE) == []


def test_two_changed_migrations_with_one_number_clash():
    problems = gate.migration_clashes(
        ["production/migrations/531_a.sql", "production/migrations/531_b.sql"], BASE
    )
    assert len(problems) == 1 and "shares number 531" in problems[0]


def test_a_free_number_passes_and_a_badly_named_file_is_reported():
    assert gate.migration_clashes(["production/migrations/531_new.sql"], BASE) == []
    assert "not named" in gate.migration_clashes(["production/migrations/new.sql"], BASE)[0]


def _steps(plan, **over):
    args = dict(repro_dir="/r", logs="/l", compare_all=False, integration=())
    return gate.build_steps(plan, "py", **{**args, **over})


def test_the_plan_is_the_suite_then_what_the_change_needs():
    plain = _steps(gate.Plan(False, ()))
    assert [s.name for s in plain] == ["unit"]
    full = _steps(gate.Plan(True, ()), compare_all=True, integration=("tests/integration/x.py",))
    assert [s.name for s in full] == ["unit", "repro_frozen", "compare_all", "integration"]
    assert [s.locked for s in full] == [False, True, True, False]
    assert full[1].expect == "bit-identical"


def _py(code: str, name: str = "s", **kw) -> gate.Step:
    return gate.Step(name, (sys.executable, "-c", code), **kw)


def test_steps_run_in_order_and_stop_at_the_first_failure(tmp_path):
    steps = [
        _py("print('a')", "one"),
        _py("raise SystemExit(3)", "two"),
        _py("print('c')", "three"),
    ]
    results = gate.run_steps(steps, tmp_path, tmp_path / "logs", tmp_path / "lock")
    assert [(r["step"], r["ok"]) for r in results] == [("one", True), ("two", False)]
    assert results[1]["returncode"] == 3
    assert "a" in Path(results[0]["log"]).read_text()


def test_a_step_that_exits_zero_without_its_expected_text_fails(tmp_path):
    step = _py("print('nothing to see')", "repro", expect="bit-identical")
    (result,) = gate.run_steps([step], tmp_path, tmp_path / "logs", tmp_path / "lock")
    assert not result["ok"] and result["missing"] == "bit-identical"
    ok = _py("print('phase: bit-identical')", "repro", expect="bit-identical")
    assert gate.run_steps([ok], tmp_path, tmp_path / "logs2", tmp_path / "lock")[0]["ok"]


def test_the_parity_lock_excludes_a_second_holder_and_names_the_first(tmp_path):
    lock = tmp_path / "gate" / "parity.lock"
    with gate.parity_lock(lock, "first", timeout=5):
        with pytest.raises(TimeoutError, match="first"):
            with gate.parity_lock(lock, "second", timeout=0.2, poll=0.05):
                pass
    with gate.parity_lock(lock, "third", timeout=1):  # released on exit
        pass


def test_a_waiter_gets_the_lock_when_the_holder_leaves(tmp_path):
    lock = tmp_path / "parity.lock"
    order = []

    def hold():
        with gate.parity_lock(lock, "holder", timeout=5):
            order.append("held")
            time.sleep(0.4)
        order.append("released")

    thread = threading.Thread(target=hold)
    thread.start()
    while "held" not in order:
        time.sleep(0.02)
    with gate.parity_lock(lock, "waiter", timeout=5, poll=0.05):
        order.append("waiter")
    thread.join()
    assert order == ["held", "released", "waiter"]


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def clone(tmp_path):
    """A working clone of a bare origin whose main holds one migration and one source file."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(work, "config", key, value)
    (work / "production/migrations").mkdir(parents=True)
    (work / "production/migrations/001_first.sql").write_text("select 1;\n")
    (work / "src").mkdir()
    (work / "src/a.py").write_text("A = 1\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "push", "-q", "origin", "HEAD:main")
    return work


def test_changed_paths_cover_unstaged_untracked_and_committed(clone):
    (clone / "src/a.py").write_text("A = 2\n")
    (clone / "src/new.py").write_text("B = 1\n")
    (clone / "src/c.py").write_text("C = 1\n")
    _git(clone, "add", "src/c.py")
    _git(clone, "commit", "-q", "-m", "c")
    paths, base = gate.changed_paths(clone, "origin/main")
    assert paths == ["src/a.py", "src/c.py", "src/new.py"] and len(base) == 40


def test_main_dry_run_prints_the_plan(clone, monkeypatch, capsys):
    (clone / "src/intelligence/research").mkdir(parents=True)
    (clone / "src/intelligence/research/x.py").write_text("X = 1\n")
    monkeypatch.chdir(clone)
    assert gate.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "plan: unit, repro_frozen" in out and "1 changed file" in out


def test_main_stops_on_a_migration_number_clash(clone, monkeypatch, capsys):
    (clone / "production/migrations/001_second.sql").write_text("select 2;\n")
    monkeypatch.chdir(clone)
    assert gate.main(["--dry-run"]) == 1
    assert "number 1 is held on the base" in capsys.readouterr().out


def test_main_with_nothing_changed_fails_loudly(clone, monkeypatch, capsys):
    monkeypatch.chdir(clone)
    assert gate.main(["--dry-run"]) == 1
    assert "nothing changed" in capsys.readouterr().out


def test_the_main_checkout_is_the_one_holding_dot_git(clone, tmp_path):
    scratch = tmp_path / "scratch"
    _git(clone, "worktree", "add", "-q", "--detach", str(scratch))
    assert gate.main_checkout(scratch) == clone.resolve()
