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
the battery's own scenario list present. The legacy waiver table covers the specs that already have
recorded real runs (their E17 passes are ledger prose with no result file); it is code, one row per
spec hash with its ledger citation, and never gains a row for a new or amended spec.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from src.core import code_identity

SCHEMA = "e17_null_battery_v1"
MIN_SIMS = 1000
RECORD_DIR = Path(__file__).resolve().parents[3] / "research" / "battery_passes"
RUNNER = "src.intelligence.research.runner"
# Runner functions that feed S1 (the seen-member prices), the member and target masks, the members'
# call and the vol: an edit to any of them stales every pass. Plumbing and logging are not listed.
RUNNER_STATISTIC_FUNCTIONS = (
    "compute_residuals",
    "_s1_input",
    "compute_members",
    "_member_fn",
    "_vol",
)
# Modules the S1 cells reach only through the runner's lazy import or through the transform table.
EXTRA_ENTRIES = ("src.intelligence.research.transforms", "src.intelligence.research.factors")

# family, battery_input_hash -> the ledger entry that records its E17 battery pass. Filled from
# research_run once DB reads are allowed (todo 635 follow-up); a test fails on a row with no recorded
# real run. Never a row for a new or amended spec.
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


def function_key(module: str, names: Iterable[str]) -> str:
    """sha256 over the AST-normalized source of the named top-level functions of `module` (no
    docstrings, comments or formatting). Raises when a name is not a top-level function."""
    tree = ast.parse(code_identity.source_path(module).read_bytes())
    found = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    digest = hashlib.sha256()
    for name in sorted(set(names)):
        if name not in found:
            raise BatteryPassRefused(f"{module} has no top-level function {name!r}")
        node = found[name]
        if ast.get_docstring(node) is not None:
            node.body = node.body[1:] or [ast.Pass()]
        digest.update(name.encode() + b"\x00" + ast.dump(node).encode() + b"\x01")
    return digest.hexdigest()


def battery_code_key(battery_module: str, family_module: str) -> str:
    """The code key a pass is bound to: the closure of the battery, the family module and the
    S1 entries (the runner by name only) plus the runner's statistic functions."""
    closure = code_identity.import_closure(
        [battery_module, family_module, *EXTRA_ENTRIES], io_boundary=(RUNNER,)
    )
    digest = hashlib.sha256()
    digest.update(code_identity.code_key(closure, io_boundary=(RUNNER,)).encode())
    digest.update(function_key(RUNNER, RUNNER_STATISTIC_FUNCTIONS).encode())
    return digest.hexdigest()


def problems(record: Mapping, scenario_names: Iterable[str]) -> list[str]:
    """Why a driver record does not count as a pass (empty when it does)."""
    out = []
    if record.get("schema") != SCHEMA:
        out.append(f"schema {record.get('schema')!r} is not {SCHEMA!r}")
    if record.get("failures"):
        out.append(
            f"{len(record['failures'])} non-diagnostic failure(s), e.g. {record['failures'][0]}"
        )
    if int(record.get("sims_per_cell", 0)) < MIN_SIMS:
        out.append(f"{record.get('sims_per_cell')} sims per cell, below {MIN_SIMS}")
    ran = {s.get("name") for s in record.get("scenarios", [])}
    missing = sorted(set(scenario_names) - ran)
    if missing:
        out.append(f"scenario(s) not run: {missing}")
    return out


def make_record(
    driver_records: Sequence[Mapping], *, binding: Mapping, scenario_names: Iterable[str]
) -> dict:
    """One pass record from the driver JSON(s) of one battery (a battery may be run in parts, as
    the S1 cell is): the parts are merged and judged together; raises when the merge is not a pass.
    """
    if not driver_records:
        raise BatteryPassRefused("no driver record to bind")
    merged = {
        "schema": driver_records[0].get("schema"),
        "battery": driver_records[0].get("battery"),
        "sims_per_cell": min(int(r.get("sims_per_cell", 0)) for r in driver_records),
        "scenarios": [s for r in driver_records for s in r.get("scenarios", [])],
        "report": [c for r in driver_records for c in r.get("report", [])],
        "failures": [f for r in driver_records for f in r.get("failures", [])],
        "commits": sorted({r.get("commit", "") for r in driver_records}),
    }
    bad = problems(merged, scenario_names)
    if bad:
        raise BatteryPassRefused("; ".join(bad))
    return {**merged, "binding": dict(binding)}


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
    waived = waivers.get((spec.family, input_hash))
    if waived is not None:
        return waived
    mine = [r for r in records if r.get("binding", {}).get("family") == spec.family]
    if not mine:
        raise BatteryPassRefused(
            f"family {spec.family}: no recorded E17 battery pass (research/battery_passes/); run "
            f"{battery_module} through scripts/research/e17_null_battery.py and bind the result"
        )
    key = battery_code_key(battery_module, family_module)
    scenario_names = [s.name for s in importlib.import_module(battery_module).scenarios()]
    reasons = []
    for record in mine:
        bound = record["binding"]
        if bound.get("battery_input_hash") != input_hash:
            reasons.append("recorded for other inputs (members, horizon, construction or warmup)")
        elif bound.get("battery_code_key") != key:
            reasons.append("recorded at other battery code (an edit to the statistic since)")
        elif record.get("battery") != battery_module:
            reasons.append(f"recorded for battery {record.get('battery')}")
        elif bad := problems(record, scenario_names):
            reasons.append("; ".join(bad))
        else:
            return "record"
    raise BatteryPassRefused(
        f"family {spec.family}: no recorded E17 battery pass is current: " + " | ".join(reasons)
    )
