"""CI guard: a TEMPORARY exception names its retirement and dies with it (plan 185-44).

Every allow-list entry whose reason contains TEMPORARY, in tests/unit/test_*boundary*.py and
tests/unit/test_*_registry.py (the census definition, scripts/ops/ops_complexity_census.py),
must name its retirement as a plan id (`retire: 185-42`) or a todo (`retire: todo 489`). The
entry fails once that plan's SUMMARY exists (.planning/phases/ or an archived milestone) or the
todo is in .planning/todos/completed/: the retiring change removes the exception in the same
commit. A TEMPORARY reason that names nothing fails, unless the entry is in the frozen list of
clause-less entries that existed on 2026-10-06, which may only shrink (an entry there that no
longer exists, or that has gained a clause, fails as stale).

The same expiry applies to _PENDING_RETIREMENT in test_table_and_apr_key_readers.py: a table or
APR key a plan orphaned stays allowed until its named plan's SUMMARY exists; after that the entry
fails while the name is still created or seeded by the migrations, and fails as stale once the
name is gone (remove the entry with the name).

CI-clean: filesystem only, no database.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from scripts.ops.ops_complexity_census import (
    ALLOW_LIST_GLOBS,
    TemporaryEntry,
    plan_summary_exists,
    temporary_entries,
)
from tests.unit._migration_catalog import REPO_ROOT, migration_catalog
from tests.unit.test_table_and_apr_key_readers import _PENDING_RETIREMENT

_PLANNING_DIR = REPO_ROOT / ".planning"
_RETIRE = re.compile(r"retire:\s*(?:todo\s+(\d+)|(\d{2,3}[A-Z]?(?:\.\d+)?-\d{2})\b)")

# Frozen 2026-10-06 (plan 185-44): TEMPORARY entries that predate the retire-clause rule.
# MAY ONLY SHRINK. Key: "<file>::<variable>[<entry key>]".
_FROZEN_CLAUSELESS: dict[str, str] = {
    "tests/unit/test_ibkr_history_lease_boundary.py::_ALLOW_LIST[services/backfill_feature_factory.py]": (
        "predates 185-44; its reason points at the phase 185 deferred items, not a plan"
    ),
    "tests/unit/test_ibkr_history_lease_boundary.py::_ALLOW_LIST[scripts/infrastructure/backfill/_history_fetch_item.py]": (
        "predates 185-44; its reason names plan 189-08 in prose (phase 189 files are paused)"
    ),
}


def entry_id(entry: TemporaryEntry) -> str:
    return f"{entry.file}::{entry.variable}[{entry.key}]"


def retirement_done(reason: str, planning_dir: Path) -> tuple[str, bool] | None:
    """(clause, done) for the reason's retire clause, or None when it names nothing."""
    match = _RETIRE.search(reason)
    if not match:
        return None
    todo, plan = match.groups()
    if plan:
        return f"plan {plan}", plan_summary_exists(plan, planning_dir)
    completed = planning_dir / "todos" / "completed"
    done = completed.exists() and any(
        (lead := re.match(r"(\d+)", path.name)) and int(lead.group(1)) == int(todo)
        for path in completed.iterdir()
    )
    return f"todo {todo}", done


def temporary_violations(
    entries: Iterable[TemporaryEntry],
    frozen: Mapping[str, str],
    is_done: Callable[[str], tuple[str, bool] | None],
) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        ident = entry_id(entry)
        seen.add(ident)
        clause = is_done(entry.reason)
        if clause is None:
            if ident not in frozen:
                problems.append(
                    f"{ident}: TEMPORARY reason names no retirement; add `retire: <plan id>` "
                    "or `retire: todo <n>`"
                )
        elif clause[1]:
            problems.append(f"{ident}: {clause[0]} is complete; remove this TEMPORARY exception")
        elif ident in frozen:
            problems.append(f"{ident}: now has a retire clause; remove it from the frozen list")
    problems += [
        f"{ident}: frozen entry no longer exists; remove it from the frozen list"
        for ident in sorted(set(frozen) - seen)
    ]
    return problems


def pending_violations(
    pending: Mapping[str, str],
    present: set[str],
    is_done: Callable[[str], tuple[str, bool] | None],
) -> list[str]:
    problems: list[str] = []
    for name, reason in sorted(pending.items()):
        clause = is_done(reason)
        if clause is None:
            problems.append(f"pending retirement {name}: reason has no `retire: <plan id>`")
        elif name not in present:
            problems.append(f"pending retirement {name}: already gone; remove the stale entry")
        elif clause[1]:
            problems.append(
                f"pending retirement {name}: {clause[0]} is complete but the name is still "
                "created or seeded; retire it in a migration"
            )
    return problems


def _allow_list_sources(tests_dir: Path, repo_root: Path) -> dict[str, str]:
    paths = sorted({path for glob in ALLOW_LIST_GLOBS for path in tests_dir.glob(glob)})
    return {str(path.relative_to(repo_root)): path.read_text() for path in paths}


def test_temporary_allow_list_entries_name_an_open_retirement():
    entries = temporary_entries(_allow_list_sources(REPO_ROOT / "tests" / "unit", REPO_ROOT))
    problems = temporary_violations(
        entries, _FROZEN_CLAUSELESS, lambda reason: retirement_done(reason, _PLANNING_DIR)
    )
    assert not problems, "\n".join(problems)


def test_pending_retirements_expire_with_their_plan():
    tables, keys = migration_catalog()
    problems = pending_violations(
        _PENDING_RETIREMENT,
        tables | keys,
        lambda reason: retirement_done(reason, _PLANNING_DIR),
    )
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# the guard's own behavior, on fakes


def _planning(tmp_path: Path) -> Path:
    planning = tmp_path / ".planning"
    (planning / "phases" / "185-x").mkdir(parents=True)
    (planning / "todos" / "completed").mkdir(parents=True)
    return planning


def _entries(tmp_path: Path, source: str) -> list[TemporaryEntry]:
    tests_dir = tmp_path / "tests" / "unit"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_fake_boundary.py").write_text(source)
    return temporary_entries(_allow_list_sources(tests_dir, tmp_path))


def test_fake_plan_clause_passes_until_its_summary_exists(tmp_path):
    planning = _planning(tmp_path)
    entries = _entries(tmp_path, '_ALLOW_LIST = {"a.py": "TEMPORARY: x (retire: 185-99)"}\n')
    check = lambda reason: retirement_done(reason, planning)  # noqa: E731
    assert temporary_violations(entries, {}, check) == []
    (planning / "phases" / "185-x" / "185-99-SUMMARY.md").write_text("")
    assert temporary_violations(entries, {}, check) == [
        "tests/unit/test_fake_boundary.py::_ALLOW_LIST[a.py]: plan 185-99 is complete; "
        "remove this TEMPORARY exception"
    ]


def test_fake_todo_clause_fails_once_the_todo_is_completed(tmp_path):
    planning = _planning(tmp_path)
    entries = _entries(tmp_path, '_ALLOW_LIST = {"a.py": "TEMPORARY: x (retire: todo 999)"}\n')
    check = lambda reason: retirement_done(reason, planning)  # noqa: E731
    assert temporary_violations(entries, {}, check) == []
    (planning / "todos" / "completed" / "999-some-todo.md").write_text("")
    assert len(temporary_violations(entries, {}, check)) == 1


def test_fake_clauseless_entry_fails_unless_frozen_and_frozen_only_shrinks(tmp_path):
    planning = _planning(tmp_path)
    entries = _entries(tmp_path, '_ALLOW_LIST = {"a.py": "TEMPORARY: someday"}\n')
    check = lambda reason: retirement_done(reason, planning)  # noqa: E731
    ident = "tests/unit/test_fake_boundary.py::_ALLOW_LIST[a.py]"
    assert len(temporary_violations(entries, {}, check)) == 1
    assert temporary_violations(entries, {ident: "frozen"}, check) == []
    gone = "tests/unit/test_fake_boundary.py::_ALLOW_LIST[b.py]"
    assert temporary_violations(entries, {ident: "frozen", gone: "frozen"}, check) == [
        f"{gone}: frozen entry no longer exists; remove it from the frozen list"
    ]


def test_fake_pending_retirement_lifecycle(tmp_path):
    planning = _planning(tmp_path)
    check = lambda reason: retirement_done(reason, planning)  # noqa: E731
    pending = {"infra.fake.key": "orphaned by 185-98 (retire: 185-99)"}
    assert pending_violations(pending, {"infra.fake.key"}, check) == []
    (planning / "phases" / "185-x" / "185-99-SUMMARY.md").write_text("")
    assert pending_violations(pending, {"infra.fake.key"}, check) == [
        "pending retirement infra.fake.key: plan 185-99 is complete but the name is still "
        "created or seeded; retire it in a migration"
    ]
    assert pending_violations(pending, set(), check) == [
        "pending retirement infra.fake.key: already gone; remove the stale entry"
    ]
    assert pending_violations({"t": "no clause"}, {"t"}, check) == [
        "pending retirement t: reason has no `retire: <plan id>`"
    ]
