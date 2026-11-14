"""CI guard: nothing in the repo points at a unit, script, module or topic that no longer exists.

A deletion that misses one reference leaves a silent failure behind: an auditor that restarts a
dead unit forever, a target waiting on a unit that is gone, a doc that sends an operator to a
deleted script (todo 614 rows 5 and 19 each left several). Four checks:

- systemd: every service's ExecStart script or first-party module exists, every timer's
  activated unit exists, and every `indicagent-*` unit a target or unit file orders against
  exists in production/systemd (template instances resolve to their `name@.service`).
- auditor registries: `_ONESHOT_UNITS` names a unit file that exists (the `_DAG_ORDER` and
  `_AGENT_ID_TO_UNIT` check lives in services/test_service_auditor_registry_integrity.py).
- topics: every suffix in the Kafka topic specs is a topic some `stream_keys` function builds.
- docs: a backticked repo path or `indicagent-*` unit name in a live doc resolves. Docs written
  before this guard hold known stale references, frozen in dangling_reference_baseline.json,
  which only ever shrinks: a new dangling reference fails, a baseline entry that now resolves
  is harmless, and whoever fixes docs prunes it (`.venv/bin/python -m
  tests.unit.test_no_dangling_references --write-baseline` regenerates the file from the live
  docs, so run it only after fixing, never to admit a new reference). Archives, research notes and finished phases are history
  and are not scanned.

CI-clean: filesystem only.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SYSTEMD = REPO / "production" / "systemd"
BASELINE = Path(__file__).with_name("dangling_reference_baseline.json")
_REGEN = ".venv/bin/python -m tests.unit.test_no_dangling_references --write-baseline"

_FIRST_PARTY = ("services", "scripts", "src", "tools", "production", "tests")
_UNIT_NAME = re.compile(r"indicagent-[a-z0-9][a-z0-9-]*(?:@[a-z0-9-]+)?")
# `indicagent-52` style session ids (a two-character suffix) name Claude sessions, not units.
_SESSION_ID = re.compile(r"indicagent-[0-9a-z]{2}")
_BACKTICK_PATH = re.compile(
    r"`((?:services|scripts|src|tools|production|tests)/[A-Za-z0-9_./-]+"
    r"\.(?:py|sh|yml|yaml|sql|service|timer|target|json|toml))`"
)
_SCANNED_ROOT_FILES = ("CLAUDE.md", "README.md", "services/README.md")
_HISTORY_DIRS = ("docs/archive", "docs/research", "docs/plans/archive", "docs/ideas")


def _unit_files() -> set[str]:
    return {path.name for path in SYSTEMD.iterdir() if path.is_file()}


def _unit_exists(unit: str, files: set[str]) -> bool:
    """`name.service`, `name.timer`, `name.target` or a bare/template-instance name."""
    if "." not in unit:
        return any(f"{unit}{suffix}" in files for suffix in (".service", ".timer", ".target"))
    if unit in files:
        return True
    base, rest = unit.split("@", 1) if "@" in unit else (unit, "")
    if rest and "." in rest:
        return f"{base}@.{rest.split('.', 1)[1]}" in files
    return False


def _exec_targets(text: str) -> list[str]:
    targets = []
    for line in text.splitlines():
        if not line.startswith("ExecStart="):
            continue
        tokens = line[len("ExecStart=") :].lstrip("-@+!").split()
        for index, token in enumerate(tokens):
            if token == "-m" and index + 1 < len(tokens):
                module = tokens[index + 1]
                if module.split(".")[0] in _FIRST_PARTY:
                    targets.append(module.replace(".", "/") + ".py")
                break
            if token.endswith((".py", ".sh")):
                targets.append(token)
                break
    # units hard-code the install path (/home/bg/dev/indicagent/...); CI checks out elsewhere
    return [re.sub(r"^/.*?/indicagent/", "", target) for target in targets]


def _unit_name_findings() -> list[str]:
    files = _unit_files()
    problems = []
    for path in sorted(SYSTEMD.iterdir()):
        if path.suffix not in (".service", ".timer", ".target"):
            continue
        text = path.read_text()
        if path.suffix == ".service":
            for target in _exec_targets(text):
                if not (REPO / target).exists():
                    problems.append(f"{path.name}: ExecStart runs {target}, which does not exist")
        if path.suffix == ".timer":
            match = re.search(r"^Unit=(\S+)", text, re.M)
            activated = match.group(1) if match else path.stem + ".service"
            if not _unit_exists(activated, files):
                problems.append(f"{path.name}: activates {activated}, which has no unit file")
        for line in text.splitlines():
            match = re.match(r"(?:After|Before|Requires|Wants|BindsTo|PartOf)=(.*)", line)
            for unit in (match.group(1).split() if match else []):
                if unit.startswith("indicagent-") and not _unit_exists(unit, files):
                    problems.append(f"{path.name}: orders against {unit}, which has no unit file")
    return problems


def test_systemd_units_point_only_at_things_that_exist():
    problems = _unit_name_findings()
    assert not problems, "dangling systemd references:\n" + "\n".join(problems)


def test_the_oneshot_registry_names_only_real_unit_files():
    from services.service_auditor import _ONESHOT_UNITS

    files = _unit_files()
    # Infra sentinels and units installed outside the repo are named in the registry on purpose.
    allowed_outside_repo = {
        "indicagent-redpanda-ready",
        "indicagent-timescaledb-ready",
        # a corpus-pipeline oneshot that takes the run's --training-window-end: no static unit
        # by design (services/test_service_auditor_registry_integrity.py, todo 402)
        "indicagent-feature-lifecycle",
    }
    missing = sorted(
        unit
        for unit in _ONESHOT_UNITS
        if unit not in allowed_outside_repo and not _unit_exists(unit, files)
    )
    assert not missing, f"_ONESHOT_UNITS names units with no file in production/systemd: {missing}"


def test_every_kafka_topic_spec_is_built_by_a_stream_keys_function():
    spec_source = (
        REPO / "scripts/infrastructure/setup/infrastructure_init_kafka_topics.py"
    ).read_text()
    keys_source = (REPO / "src/core/stream_keys.py").read_text()
    suffixes = re.findall(r'^\s+\("([a-z0-9_.]+)",\s*\d', spec_source, re.M)
    assert suffixes, "no topic specs parsed"
    # A dynamic family (market.bars.raw.<provider>) is added at runtime, not listed here.
    missing = sorted(
        s for s in suffixes if f'}}{s}"' not in keys_source and f'"{s}"' not in keys_source
    )
    assert not missing, f"topic specs no stream_keys function builds (delete or restore): {missing}"


def _container_names() -> set[str]:
    compose = (REPO / "production" / "docker-compose.yml").read_text()
    return set(re.findall(r"container_name:\s*(\S+)", compose))


def _doc_files() -> list[Path]:
    files = [REPO / name for name in _SCANNED_ROOT_FILES if (REPO / name).exists()]
    for directory, _, names in os.walk(REPO / "docs"):
        relative = Path(directory).relative_to(REPO).as_posix()
        if any(relative == h or relative.startswith(h + "/") for h in _HISTORY_DIRS):
            continue
        files.extend(Path(directory) / name for name in names if name.endswith(".md"))
    return sorted(files)


def _dangling_doc_references() -> set[str]:
    unit_files = _unit_files()
    containers = _container_names()
    found = set()
    for doc in _doc_files():
        text = doc.read_text()
        relative = doc.relative_to(REPO).as_posix()
        for match in _BACKTICK_PATH.finditer(text):
            if not (REPO / match.group(1)).exists():
                found.add(f"{relative}|{match.group(1)}")
        for match in _UNIT_NAME.finditer(text):
            unit = match.group(0)
            if unit in containers or _SESSION_ID.fullmatch(unit):
                continue
            if not _unit_exists(unit, unit_files):
                found.add(f"{relative}|{unit}")
    return found


def test_docs_reference_nothing_new_that_is_gone():
    baseline = set(json.loads(BASELINE.read_text()))
    new = sorted(_dangling_doc_references() - baseline)
    assert not new, (
        "docs reference a path or unit that does not exist; fix the doc, or the deletion that "
        "missed it (never add to the baseline by regenerating it):\n" + "\n".join(new)
    )


if __name__ == "__main__":
    if "--write-baseline" in sys.argv:
        BASELINE.write_text(json.dumps(sorted(_dangling_doc_references()), indent=1) + "\n")
        print(f"wrote {BASELINE}")
