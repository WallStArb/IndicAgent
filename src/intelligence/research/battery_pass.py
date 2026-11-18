"""Stored E17 battery pass records: a real run is refused unless its family's H0 battery has a
recorded pass for the inputs and the code it ran at (methodology-change-ledger E17, condition 2;
todo 635 review).

A record is the driver's own JSON (`scripts/research/e17_null_battery.py`, schema
`e17_null_battery_v1`) plus a binding block, stored under `research/battery_passes/`:

    binding = {"family": ..., "battery_input_hash": ..., "battery_code_key": ...,
               "spec_hashes": [...], "recorded": "YYYY-MM-DD"}

`battery_input_hash` covers what the battery simulates (members, horizon, factor vintage, the
construction and the scoring's warmup), so a primary spec and its core twin share one record;
`spec_hashes` lists the registered specs the record covers, for the reader. `battery_code_key` is
the AST-normalized hash of the battery's import closure (the runner is passed by name only) plus the
runner functions that feed S1, the masks, the members and the vol, so an edit that changes the
statistic or what it sees stales every pass, and an edit to logging or plumbing does not.

Passed means: no non-diagnostic failure, at least MIN_SIMS simulations per cell, and every cell of
the battery's own scenario list run with the battery's own settings, recomputed from the report. The legacy waiver table covers the specs that already have
recorded real runs (their E17 passes are ledger prose with no result file); it is code, one row per
spec hash with its ledger citation, and never gains a row for a new or amended spec.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import hashlib
import importlib
import json
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from src.core import code_identity
from src.intelligence.research.spec import family_spec_hash

SCHEMA = "e17_null_battery_v1"
MIN_SIMS = 1000
RECORD_DIR = Path(__file__).resolve().parents[3] / "research" / "battery_passes"
RUNNER = "src.intelligence.research.runner"
SELF = "src.intelligence.research.battery_pass"
# Named but not hashed: the runner (its S1 and mask functions are hashed separately) and this module
# (the key's own machinery is not the statistic a battery certifies).
OPAQUE = (RUNNER, SELF)
# Runner functions that feed S1 (the seen-member prices), the member and target masks, the members'
# call and the vol: an edit to any of them stales every pass. Plumbing and logging are not listed.
RUNNER_STATISTIC_FUNCTIONS = (
    "compute_residuals",
    "_s1_input",
    "compute_members",
    "_member_fn",
    "_vol",
)
# Module-level runner values the batteries read (the S1 factor vintages): hashed like the functions.
RUNNER_STATISTIC_ASSIGNMENTS = ("FACTOR_SPECS",)
# Modules the S1 cells reach only through the runner's lazy import or through the transform table.
EXTRA_ENTRIES = ("src.intelligence.research.transforms", "src.intelligence.research.factors")

# (family, spec hash) -> the ledger entry that records its E17 battery pass. Filled from research_run
# once DB reads are allowed (todo 635 follow-up); a test fails on a row with no recorded real run.
# Keyed on the spec hash, so an amended or new spec never inherits a waiver.
LEGACY_WAIVERS: dict[tuple[str, str], str] = {}


class BatteryPassRefused(RuntimeError):
    """No recorded pass covers this family at these inputs and this code."""


def battery_input_hash(spec) -> str:
    """sha256 over what the battery simulates for a family spec (a FamilySpec)."""
    body = {
        "family": spec.family,
        "horizon": spec.horizon,
        "factor_spec": spec.factor_spec,
        "members": [
            {
                "name": m.name,
                "signal": m.signal,
                "params": dict(sorted(m.params.items())),
                "slot_history_sessions": m.slot_history_sessions,
                "declared_memory_rows": m.declared_memory_rows,
            }
            for m in spec.members
        ],
        "construction": spec.construction.model_dump(mode="json"),
        "scoring": {
            "warmup_sessions": spec.scoring.warmup_sessions,
            "timing_statistic": spec.scoring.timing_statistic,
        },
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def function_key(module: str, names: Iterable[str], assignments: Iterable[str] = ()) -> str:
    """sha256 over the AST-normalized source of the named top-level functions and module-level
    assignments of `module` (no docstrings, comments or formatting). Raises when a name is absent.
    """
    tree = ast.parse(code_identity.source_path(module).read_bytes())
    functions = {
        n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    values: dict[str, ast.AST] = {}
    for n in tree.body:
        if isinstance(n, ast.Assign):
            values.update({t.id: n for t in n.targets if isinstance(t, ast.Name)})
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            values[n.target.id] = n
    digest = hashlib.sha256()
    for name in sorted(set(names)):
        if name not in functions:
            raise BatteryPassRefused(f"{module} has no top-level function {name!r}")
        node = functions[name]
        if ast.get_docstring(node) is not None:
            node.body = node.body[1:] or [ast.Pass()]
        digest.update(name.encode() + b"\x00" + ast.dump(node).encode() + b"\x01")
    for name in sorted(set(assignments)):
        if name not in values:
            raise BatteryPassRefused(f"{module} has no top-level assignment {name!r}")
        digest.update(name.encode() + b"\x02" + ast.dump(values[name]).encode() + b"\x01")
    return digest.hexdigest()


def battery_code_key(battery_module: str, family_module: str) -> str:
    """The code key a pass is bound to: the closure of the battery, the family module and the
    S1 entries (the runner by name only) plus the runner's statistic functions."""
    closure = code_identity.import_closure(
        [battery_module, family_module, *EXTRA_ENTRIES], io_boundary=OPAQUE
    )
    digest = hashlib.sha256()
    digest.update(code_identity.code_key(closure, io_boundary=OPAQUE).encode())
    digest.update(
        function_key(RUNNER, RUNNER_STATISTIC_FUNCTIONS, RUNNER_STATISTIC_ASSIGNMENTS).encode()
    )
    return digest.hexdigest()


@contextlib.contextmanager
def sources_at(commit: str, repo_root: Path):
    """Within the block every module source read through code_identity is the file as of `commit`
    (git show), so a key computed inside is the key of the code a past run used."""
    original = code_identity.source_path
    with tempfile.TemporaryDirectory(prefix="battery_pass_") as tmp:
        cache: dict[Path, Path] = {}

        def at_commit(name: str) -> Path:
            path = original(name)
            if path in cache:
                return cache[path]
            try:
                rel = path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                return path
            body = subprocess.run(
                ["git", "show", f"{commit}:{rel.as_posix()}"],
                cwd=repo_root,
                check=True,
                capture_output=True,
            ).stdout
            copy = Path(tmp) / rel
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(body)
            cache[path] = copy
            return copy

        code_identity.source_path = at_commit
        try:
            yield
        finally:
            code_identity.source_path = original


def problems(record: Mapping, scenarios: Sequence[Mapping]) -> list[str]:
    """Why a driver record does not count as a pass (empty when it does). `scenarios` are the
    battery's current cells as dicts (`dataclasses.asdict`); the record must have run each of them
    exactly (a shortened panel is another cell), and the result is recomputed from the report, not
    read from the failure list."""
    out = []
    if record.get("schema") != SCHEMA:
        out.append(f"schema {record.get('schema')!r} is not {SCHEMA!r}")
    if record.get("failures"):
        out.append(
            f"{len(record['failures'])} non-diagnostic failure(s), e.g. {record['failures'][0]}"
        )
    if int(record.get("sims_per_cell", 0)) < MIN_SIMS:
        out.append(f"{record.get('sims_per_cell')} sims per cell, below {MIN_SIMS}")
    ran = {s.get("name"): dict(s) for s in record.get("scenarios", [])}
    for cell in scenarios:
        name = cell["name"]
        if name not in ran:
            out.append(f"scenario {name} not run")
        elif ran[name] != dict(cell):
            out.append(f"scenario {name} was run with other settings than the battery's own")
    diagnostic = set(record.get("diagnostic_cells", ()))
    for row in record.get("report", []):
        if row.get("cell") in diagnostic:
            continue
        if int(row.get("sims", 0)) < MIN_SIMS:
            out.append(f"{row.get('cell')}/{row.get('arm')}: {row.get('sims')} sims")
        for alpha, level in row.get("levels", {}).items():
            if level["rejected"] > level["bound"]:
                out.append(
                    f"{row.get('cell')}/{row.get('arm')} at {alpha}: "
                    f"{level['rejected']} > {level['bound']}"
                )
    return out


def battery_scenarios(battery_module: str) -> list[dict]:
    return [dataclasses.asdict(s) for s in importlib.import_module(battery_module).scenarios()]


def make_record(
    driver_records: Sequence[Mapping],
    *,
    spec,
    spec_hashes: Sequence[str],
    battery_module: str,
    family_module: str,
    driver_commit: str,
    input_hash_then: str,
    code_key_then: str,
    dirty: Sequence[str],
    recorded: str,
) -> dict:
    """One pass record from the driver JSON(s) of one battery (a battery may be run in parts, as
    the S1 cell is). The `*_then` values were computed from the sources and the spec as of
    `driver_commit` (sources_at); the record binds the current inputs and code, and refuses unless
    they equal the ones the driver ran at, the working tree is clean, every part names this
    battery and ran at `driver_commit`, the battery's own inputs match the spec, and the merged
    result is a pass."""
    if not driver_records:
        raise BatteryPassRefused("no driver record to bind")
    battery = importlib.import_module(battery_module)
    if not hasattr(battery, "inputs_mismatch"):
        raise BatteryPassRefused(f"{battery_module} defines no inputs_mismatch(spec)")
    mismatch = battery.inputs_mismatch(spec)
    if mismatch:
        raise BatteryPassRefused(f"the battery's own inputs differ from the spec: {mismatch}")
    if dirty:
        raise BatteryPassRefused(f"uncommitted change(s) in the checkout: {sorted(dirty)[:5]}")
    for part in driver_records:
        if part.get("battery") != battery_module:
            raise BatteryPassRefused(f"a part ran {part.get('battery')}, not {battery_module}")
        if part.get("commit") != driver_commit:
            raise BatteryPassRefused(
                f"a part ran at {part.get('commit')}, not at the stated driver commit {driver_commit}"
            )
    input_hash, code_key = battery_input_hash(spec), battery_code_key(battery_module, family_module)
    if input_hash != input_hash_then:
        raise BatteryPassRefused("the battery's inputs changed since the driver ran")
    if code_key != code_key_then:
        raise BatteryPassRefused("the battery's code changed since the driver ran")
    merged = {
        "schema": driver_records[0].get("schema"),
        "battery": battery_module,
        "sims_per_cell": min(int(r.get("sims_per_cell", 0)) for r in driver_records),
        "scenarios": [s for r in driver_records for s in r.get("scenarios", [])],
        "report": [c for r in driver_records for c in r.get("report", [])],
        "failures": [f for r in driver_records for f in r.get("failures", [])],
        "diagnostic_cells": sorted(battery.DIAGNOSTIC_CELLS),
        "commit": driver_commit,
    }
    bad = problems(merged, battery_scenarios(battery_module))
    if bad:
        raise BatteryPassRefused("; ".join(bad))
    binding = {
        "family": spec.family,
        "battery_input_hash": input_hash,
        "battery_code_key": code_key,
        "spec_hashes": sorted(spec_hashes),
        "recorded": recorded,
    }
    return {**merged, "binding": binding}


def load_records(directory: Path = RECORD_DIR) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]


def require(
    spec,
    *,
    battery_module: str,
    family_module: str,
    records: Sequence[Mapping] | None = None,
    waivers: Mapping[tuple[str, str], str] | None = None,
) -> str:
    """Return what covers the family ('record' or the waiver's ledger citation), or raise
    BatteryPassRefused naming exactly what is missing or stale."""
    records = load_records() if records is None else records
    waivers = LEGACY_WAIVERS if waivers is None else waivers
    input_hash = battery_input_hash(spec)
    waived = waivers.get((spec.family, family_spec_hash(spec)))
    if waived is not None:
        return waived
    mine = [r for r in records if r.get("binding", {}).get("family") == spec.family]
    if not mine:
        raise BatteryPassRefused(
            f"family {spec.family}: no recorded E17 battery pass (research/battery_passes/); run "
            f"{battery_module} through scripts/research/e17_null_battery.py and bind the result"
        )
    key = battery_code_key(battery_module, family_module)
    scenarios = battery_scenarios(battery_module)
    reasons = []
    for record in mine:
        bound = record["binding"]
        if bound.get("battery_input_hash") != input_hash:
            reasons.append("recorded for other inputs (members, horizon, construction or warmup)")
        elif bound.get("battery_code_key") != key:
            reasons.append("recorded at other battery code (an edit to the statistic since)")
        elif record.get("battery") != battery_module:
            reasons.append(f"recorded for battery {record.get('battery')}")
        elif bad := problems(record, scenarios):
            reasons.append("; ".join(bad))
        else:
            return "record"
    raise BatteryPassRefused(
        f"family {spec.family}: no recorded E17 battery pass is current: " + " | ".join(reasons)
    )
