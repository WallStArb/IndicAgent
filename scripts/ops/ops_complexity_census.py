#!/usr/bin/env python3
"""ops_complexity_census.py - count the repo's complexity debt (plan 185-44).

One read-only census, run once by plan 185-44 to record the baseline
(.planning/phases/185-daily-data-foundation/185-COMPLEXITY-BASELINE.md) and rerun unchanged by
plan 185-43, whose exit criteria require every count to go down or be explained. Each count is
a pure function over an injected listing; main() gathers the listings from the filesystem, git,
systemctl and one read-only database session.

Definitions (the baseline states the same text):
- scripts_total / scripts_ops: *.py and *.sh files under scripts/ and under scripts/ops/,
  excluding __init__.py and __pycache__.
- temporary_entries: allow-list entries whose reason contains "TEMPORARY", in
  tests/unit/test_*boundary*.py and tests/unit/test_*_registry.py.
- tables_public / views_public: information_schema.tables rows in schema public, table_type
  'BASE TABLE' and 'VIEW'.
- apr_keys_without_reader: config_state keys with no reader in services/, src/ or scripts/
  (*.py, *.sh, *.sql). A reader is the literal key, or, for a key built in code, a dotted
  prefix of the key followed by a `{` placeholder, a `%` format or a closing quote (the
  registry's naming rule: `<prefix>.{tf}`, `<prefix>_{tf}`, a quoted `<prefix>.` joined to a
  unit name). This file names no real key, so it is never a reader itself.
  Migrations and tests are not readers.
- services_without_live_consumer: _DAG_ORDER units (services/service_auditor.py) whose systemd
  unit is failed, missing, or inactive without being Type=oneshot or having a loaded timer,
  plus the units CLAUDE.md documents as archived or dormant.
- todos_pending: files in .planning/todos/pending/.
- docs_stale_status: files under docs/ (excluding docs/research/) whose Status line starts
  with proposed, draft or in progress, and whose last git change is older than 30 days or
  whose Status names a plan or phase whose SUMMARY files say it is complete.

Usage:
  .venv/bin/python -m scripts.ops.ops_complexity_census            # JSON on stdout
  .venv/bin/python -m scripts.ops.ops_complexity_census --markdown # counts table + listings
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Census definition, not a tunable: the plan fixes the stale-doc age at 30 days so 185-43's
# rerun measures the same thing (APR-exempt: a statistic's definition).
STALE_DOC_DAYS = 30
_SECONDS_PER_DAY = 86400

READER_DIRS = ("services", "src", "scripts")
READER_GLOBS = ("*.py", "*.sh", "*.sql")
ALLOW_LIST_GLOBS = ("test_*boundary*.py", "test_*_registry.py")

# Units CLAUDE.md names as dormant count as having no live consumer whatever their unit state.
# Empty since plan 185-45 removed the I8 AI stack units it listed (alpha-swarm,
# narrative-compute, llm-writer, swarm-ledger-writer) from _DAG_ORDER.
DORMANT_UNITS: dict[str, str] = {}

_STALE_STATUS = re.compile(r"^(?:proposed|draft|in[ -]progress)\b", re.IGNORECASE)
_STATUS_LINE = re.compile(
    r"^[ \t>*_-]*status[ \t*_]*:[ \t*_]*(.+?)[ \t*_]*$", re.IGNORECASE | re.MULTILINE
)
# A plan id like 185-27 or 142B-03; the lookarounds keep date fragments (2026-10-06) out.
_PLAN_ID = re.compile(r"(?<![\w.-])(\d{2,3}[A-Z]?(?:\.\d+)?-\d{2})(?![\w-])")
_PHASE_REF = re.compile(r"\bphase\s+(\d{2,3}[A-Z]?(?:\.\d+)?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class TemporaryEntry:
    file: str
    variable: str
    key: str
    reason: str


@dataclass(frozen=True)
class UnitState:
    unit_type: str
    active_state: str
    load_state: str


@dataclass(frozen=True)
class DocHeader:
    path: str
    status: str
    last_change_epoch: float


# ---------------------------------------------------------------------------------------------
# scripts


def count_scripts(paths: Iterable[str]) -> dict[str, list[str]]:
    total = sorted(
        path
        for path in paths
        if path.startswith("scripts/")
        and path.endswith((".py", ".sh"))
        and "__pycache__" not in path.split("/")
        and path.rsplit("/", 1)[-1] != "__init__.py"
    )
    return {"total": total, "ops": [path for path in total if path.startswith("scripts/ops/")]}


# ---------------------------------------------------------------------------------------------
# TEMPORARY allow-list entries


def _strings_in(node: ast.AST) -> list[str]:
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.append(child.value)
    return found


def _dict_entries(node: ast.Dict, prefix: str) -> Iterable[tuple[str, ast.AST]]:
    for key_node, value_node in zip(node.keys, node.values, strict=True):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            continue
        key = f"{prefix}/{key_node.value}" if prefix else key_node.value
        if isinstance(value_node, ast.Dict):
            yield from _dict_entries(value_node, key)
        else:
            yield key, value_node


def temporary_entries(sources: Mapping[str, str]) -> list[TemporaryEntry]:
    """Every module-level dict entry (nested dicts flattened to key paths) whose reason
    contains TEMPORARY. A reason is the entry's string value, or the TEMPORARY strings inside
    a non-string value (a call or tuple carrying a reason argument)."""
    entries: list[TemporaryEntry] = []
    for file, text in sorted(sources.items()):
        for statement in ast.parse(text).body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target, value = statement.targets[0], statement.value
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                target, value = statement.target, statement.value
            else:
                continue
            if not (isinstance(target, ast.Name) and isinstance(value, ast.Dict)):
                continue
            for key, value_node in _dict_entries(value, ""):
                reasons = [text for text in _strings_in(value_node) if "TEMPORARY" in text]
                if reasons:
                    entries.append(TemporaryEntry(file, target.id, key, " ".join(reasons)))
    return entries


# ---------------------------------------------------------------------------------------------
# APR keys without a reader


_LITERAL_TAIL = re.compile(r"(?![\w])(?!\.[\w{])")
_PREFIX_TAIL = re.compile(r"[{%\"']")


def _bounded(corpus: str, needle: str, tail: re.Pattern[str]) -> bool:
    """needle occurs in corpus not preceded by a word char or dot, then matches tail."""
    start = corpus.find(needle)
    while start != -1:
        before = corpus[start - 1] if start else " "
        if not (before.isalnum() or before in "_.") and tail.match(corpus, start + len(needle)):
            return True
        start = corpus.find(needle, start + 1)
    return False


def has_apr_reader(key: str, corpus: str) -> bool:
    if _bounded(corpus, key, _LITERAL_TAIL):
        return True
    for index, char in enumerate(key):
        if char not in "._" or "." not in key[:index]:
            continue
        if _bounded(corpus, key[: index + 1], _PREFIX_TAIL):
            return True
    return False


def apr_keys_without_reader(keys: Iterable[str], corpus: str) -> list[str]:
    return sorted(key for key in set(keys) if not has_apr_reader(key, corpus))


def load_reader_corpus(repo_root: Path) -> str:
    """The text every reader check searches: services/, src/, scripts/ source files."""
    parts: list[str] = []
    for directory in READER_DIRS:
        for glob in READER_GLOBS:
            for path in sorted((repo_root / directory).rglob(glob)):
                if "__pycache__" in path.parts:
                    continue
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n\x00\n".join(parts)


# ---------------------------------------------------------------------------------------------
# services with no live consumer


def parse_dag_units(source: str) -> list[str]:
    for statement in ast.parse(source).body:
        target = None
        if isinstance(statement, ast.AnnAssign):
            target, value = statement.target, statement.value
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        if isinstance(target, ast.Name) and target.id == "_DAG_ORDER":
            assert isinstance(value, ast.Dict)
            return [key.value for key in value.keys if isinstance(key, ast.Constant)]
    raise ValueError("_DAG_ORDER not found")


def parse_systemctl_show(output: str) -> dict[str, UnitState]:
    states: dict[str, UnitState] = {}
    for block in output.strip().split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if "Id" in fields:
            states[fields["Id"]] = UnitState(
                fields.get("Type", ""), fields.get("ActiveState", ""), fields.get("LoadState", "")
            )
    return states


def services_without_live_consumer(
    units: Sequence[str], states: Mapping[str, UnitState], dormant: Mapping[str, str]
) -> list[tuple[str, str]]:
    missing = UnitState("", "inactive", "not-found")
    found: list[tuple[str, str]] = []
    for unit in units:
        service = states.get(f"{unit}.service", missing)
        timer = states.get(f"{unit}.timer", missing)
        if unit in dormant:
            found.append((unit, f"documented: {dormant[unit]}"))
        elif service.load_state != "loaded":
            found.append((unit, f"missing ({service.load_state or 'not-found'})"))
        elif service.active_state == "failed":
            found.append((unit, "failed"))
        elif (
            service.active_state == "inactive"
            and service.unit_type != "oneshot"
            and timer.load_state != "loaded"
        ):
            found.append((unit, f"inactive Type={service.unit_type or '?'} with no timer"))
    return found


# ---------------------------------------------------------------------------------------------
# docs with stale Status lines


def parse_status_line(text: str) -> str | None:
    match = _STATUS_LINE.search("\n".join(text.splitlines()[:60]))
    return match.group(1).strip() if match else None


def _summary_dirs(planning_dir: Path) -> list[Path]:
    return [planning_dir / "phases", *sorted((planning_dir / "milestones").glob("*phases*"))]


def plan_summary_exists(plan_id: str, planning_dir: Path) -> bool:
    phase, plan = plan_id.rsplit("-", 1)
    names = {f"{phase}-{plan}-SUMMARY.md", f"{phase.zfill(3)}-{plan}-SUMMARY.md"}
    return any(
        (phase_dir / name).exists()
        for root in _summary_dirs(planning_dir)
        if root.exists()
        for phase_dir in root.iterdir()
        if phase_dir.is_dir()
        for name in names
    )


def phase_complete(phase: str, planning_dir: Path) -> bool:
    """True when a directory for the phase exists and every PLAN in it has its SUMMARY."""
    prefixes = {f"{phase}-", f"{phase.zfill(3)}-"}
    for root in _summary_dirs(planning_dir):
        if not root.exists():
            continue
        for phase_dir in root.iterdir():
            if not (phase_dir.is_dir() and any(phase_dir.name.startswith(p) for p in prefixes)):
                continue
            plans = sorted(phase_dir.glob("*-PLAN.md"))
            if plans and all(
                (phase_dir / plan.name.replace("-PLAN.md", "-SUMMARY.md")).exists()
                for plan in plans
            ):
                return True
    return False


def stale_docs(
    headers: Iterable[DocHeader],
    *,
    now_epoch: float,
    is_plan_complete: Callable[[str], bool],
    is_phase_complete: Callable[[str], bool],
    max_age_days: int = STALE_DOC_DAYS,
) -> list[tuple[str, str, str]]:
    """(path, status, why) for every doc whose open Status line is stale."""
    found: list[tuple[str, str, str]] = []
    for header in sorted(headers, key=lambda h: h.path):
        if header.path.startswith("docs/research/") or not _STALE_STATUS.match(header.status):
            continue
        age_days = int((now_epoch - header.last_change_epoch) // _SECONDS_PER_DAY)
        why = None
        if age_days > max_age_days:
            why = f"unchanged {age_days} days"
        else:
            plans = [p for p in _PLAN_ID.findall(header.status) if is_plan_complete(p)]
            phases = [p for p in _PHASE_REF.findall(header.status) if is_phase_complete(p)]
            if plans:
                why = f"names completed plan {plans[0]}"
            elif phases:
                why = f"names completed phase {phases[0]}"
        if why:
            found.append((header.path, header.status, why))
    return found


# ---------------------------------------------------------------------------------------------
# rendering


def render_markdown(census: Mapping[str, Any]) -> str:
    lines = ["| Measure | Count |", "|---|---|"]
    lines += [f"| {name} | {count} |" for name, count in census["counts"].items()]
    for name, listing in census["listings"].items():
        lines += ["", f"### {name} ({len(listing)})", ""]
        lines += [f"- {item}" for item in listing] or ["- (none)"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------
# gathering (side-effect-free reads)


def _run(args: Sequence[str], cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def _doc_ages(repo_root: Path) -> dict[str, float]:
    """Last commit time per path under docs/, newest first wins."""
    ages: dict[str, float] = {}
    stamp = 0.0
    log = _run(["git", "log", "--format=@%ct", "--name-only", "--", "docs"], repo_root)
    for line in log.splitlines():
        if line.startswith("@"):
            stamp = float(line[1:])
        elif line and line not in ages:
            ages[line] = stamp
    return ages


def _doc_headers(repo_root: Path, now_epoch: float) -> list[DocHeader]:
    ages = _doc_ages(repo_root)
    headers: list[DocHeader] = []
    for path in sorted((repo_root / "docs").rglob("*.md")):
        relative = str(path.relative_to(repo_root))
        status = parse_status_line(path.read_text(encoding="utf-8", errors="ignore"))
        if status:
            headers.append(DocHeader(relative, status, ages.get(relative, now_epoch)))
    return headers


def _unit_states(units: Sequence[str], repo_root: Path) -> dict[str, UnitState]:
    names = [f"{unit}.{kind}" for unit in units for kind in ("service", "timer")]
    output = _run(["systemctl", "show", "-p", "Id,Type,ActiveState,LoadState", *names], repo_root)
    states = parse_systemctl_show(output)
    # systemctl reports a not-found unit under its requested name; key by request order.
    return {
        name: states.get(name, UnitState("", "inactive", "not-found")) for name in names
    } | states


def _database_listings() -> tuple[list[str], list[str], list[str]]:
    import psycopg

    from src.config.settings import Settings

    with psycopg.connect(Settings().database_url) as conn:
        conn.read_only = True
        rows = conn.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type IN ('BASE TABLE', 'VIEW') "
            "ORDER BY table_name"
        ).fetchall()
        keys = [row[0] for row in conn.execute("SELECT config_key FROM config_state")]
        conn.rollback()
    tables = [name for name, kind in rows if kind == "BASE TABLE"]
    views = [name for name, kind in rows if kind == "VIEW"]
    return tables, views, sorted(keys)


def build_census(repo_root: Path) -> dict[str, Any]:
    now = time.time()
    tracked = _run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], repo_root)
    scripts = count_scripts(path for path in tracked.splitlines() if (repo_root / path).exists())
    allow_list_files = sorted(
        {path for glob in ALLOW_LIST_GLOBS for path in (repo_root / "tests" / "unit").glob(glob)}
    )
    temporaries = temporary_entries(
        {str(path.relative_to(repo_root)): path.read_text() for path in allow_list_files}
    )
    tables, views, keys = _database_listings()
    corpus = load_reader_corpus(repo_root)
    unread = apr_keys_without_reader(keys, corpus)
    units = parse_dag_units((repo_root / "services" / "service_auditor.py").read_text())
    dead = services_without_live_consumer(units, _unit_states(units, repo_root), DORMANT_UNITS)
    pending = sorted(
        str(path.relative_to(repo_root))
        for path in (repo_root / ".planning" / "todos" / "pending").iterdir()
        if path.is_file()
    )
    planning = repo_root / ".planning"
    stale = stale_docs(
        _doc_headers(repo_root, now),
        now_epoch=now,
        is_plan_complete=lambda plan: plan_summary_exists(plan, planning),
        is_phase_complete=lambda phase: phase_complete(phase, planning),
    )
    listings: dict[str, list[str]] = {
        "scripts_total": scripts["total"],
        "scripts_ops": scripts["ops"],
        "temporary_entries": [f"{e.file} {e.variable}[{e.key}]: {e.reason}" for e in temporaries],
        "tables_public": tables,
        "views_public": views,
        "apr_keys_without_reader": unread,
        "services_without_live_consumer": [f"{unit}: {why}" for unit, why in dead],
        "todos_pending": pending,
        "docs_stale_status": [f"{path}: {why} (Status: {status})" for path, status, why in stale],
    }
    counts = {name: len(listing) for name, listing in listings.items()}
    counts["apr_keys_total"] = len(keys)
    return {"counts": counts, "listings": listings}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--markdown", action="store_true", help="counts table and listings")
    args = parser.parse_args(argv)
    census = build_census(project_root)
    if args.markdown:
        sys.stdout.write(render_markdown(census))
    else:
        json.dump(census, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
