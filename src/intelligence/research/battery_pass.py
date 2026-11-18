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

from scipy.stats import binom

from src.core import code_identity
from src.intelligence.research.spec import family_spec_hash

SCHEMA = "e17_null_battery_v1"
MIN_SIMS = 1000
# The driver's binomial bound (scripts/research/e17_null_battery.py): a cell fails when it rejects more
# than the BOUND_QUANTILE quantile of Binomial(sims, alpha). Pinned here, not read from the record.
BOUND_QUANTILE = 0.99
ALPHAS = (0.05, 0.01, 0.00167)
RECORD_DIR = Path(__file__).resolve().parents[3] / "research" / "battery_passes"
RUNNER = "src.intelligence.research.runner"
SELF = "src.intelligence.research.battery_pass"
SNAPSHOT = "src.intelligence.research.snapshot"
SPEC = "src.intelligence.research.spec"
# Named but not hashed: the runner, the snapshot reader and the spec module (the functions the statistic calls are
# hashed separately; the rest is plumbing and database reads) and this module
# (the key's own machinery is not the statistic a battery certifies).
OPAQUE = (RUNNER, SNAPSHOT, SPEC, SELF)
# Runner functions that feed S1 (the seen-member prices), the member and target masks, the members'
# call and the vol: an edit to any of them stales every pass. Plumbing and logging are not listed.
RUNNER_STATISTIC_FUNCTIONS = (
    "compute_residuals",
    "_s1_input",
    "compute_members",
    "_member_fn",
    "member_input",
    "_vol",
)
# Functions of other opaque-or-large modules the runner functions above call.
SNAPSHOT_STATISTIC_FUNCTIONS = ("session_dates",)
# The spec module is opaque too: the battery reads a spec only to resolve each member's function, and
# what the spec says is covered by battery_input_hash, so a new spec field or validator must not
# stale every pass. The member resolution is hashed.
SPEC_STATISTIC_FUNCTIONS = ("resolve_member", "_check_member_path")
SPEC_STATISTIC_ASSIGNMENTS = ("MEMBER_PREFIX",)
# Module-level runner values the batteries read (the S1 factor vintages): hashed like the functions.
RUNNER_STATISTIC_ASSIGNMENTS = ("FACTOR_SPECS",)
# Modules the S1 cells reach only through the runner's lazy import or through the transform table.
EXTRA_ENTRIES = (
    "src.intelligence.research.transforms",
    "src.intelligence.research.factors",
    # What the hashed runner functions call: the masks, the input alignment and smoothing.
    "src.intelligence.research.membership",
    "src.intelligence.research.align",
    "src.intelligence.research.smoothing",
)

# (family, spec hash) -> the ledger entry that records its E17 battery pass. Filled from research_run
# once DB reads are allowed (todo 635 follow-up); a test fails on a row with no recorded real run.
# Keyed on the spec hash, so an amended or new spec never inherits a waiver.
LEGACY_WAIVERS: dict[tuple[str, str], str] = {}


# family -> the seed bases of its pre-declared replication (todo 636): a family listed here can only be
# bound pooled over exactly these blocks, so a favourable single block can never be bound alone. A new
# entry is a reviewed commit made BEFORE the replication launches, like the declaration it mirrors.
DECLARED_REPLICATIONS: dict[str, tuple[int, ...]] = {"daily_residual": (0, 1_000_000)}
SEED_STRIDE = 10_000  # the driver's seed = seed_base + SEED_STRIDE * cell_index + simulation


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
    digest.update(function_key(SNAPSHOT, SNAPSHOT_STATISTIC_FUNCTIONS).encode())
    digest.update(function_key(SPEC, SPEC_STATISTIC_FUNCTIONS, SPEC_STATISTIC_ASSIGNMENTS).encode())
    return digest.hexdigest()


@contextlib.contextmanager
def sources_at(commit: str, repo_root: Path):
    """Within the block every module source read through code_identity is the file as of `commit`
    (git show), so a key computed inside is the key of the code a past run used."""
    original = code_identity.source_path
    if getattr(original, "_battery_pass_at_commit", False):
        raise BatteryPassRefused("sources_at does not nest")
    with tempfile.TemporaryDirectory(prefix="battery_pass_") as tmp:
        cache: dict[Path, Path] = {}

        def at_commit(name: str) -> Path:
            path = original(name)
            if path in cache:
                return cache[path]
            try:
                rel = path.resolve().relative_to(repo_root.resolve())
            except ValueError as error:
                raise BatteryPassRefused(
                    f"{name} resolves to {path}, outside the repository {repo_root}: its source "
                    "as of the commit is unknown"
                ) from error
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

        at_commit._battery_pass_at_commit = True
        code_identity.source_path = at_commit
        try:
            yield
        finally:
            code_identity.source_path = original


def problems(
    record: Mapping, scenarios: Sequence[Mapping], *, judge_bounds: bool = True
) -> list[str]:
    """Why a driver record does not count as a pass (empty when it does). `scenarios` are the
    battery's current cells as dicts (`dataclasses.asdict`); the record must have run each of them
    exactly (a shortened panel is another cell), and the result is recomputed from the report, not
    read from the failure list."""
    out = []
    if record.get("schema") != SCHEMA:
        out.append(f"schema {record.get('schema')!r} is not {SCHEMA!r}")
    if judge_bounds and record.get("failures"):
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
    gating = [c["name"] for c in scenarios if c["name"] not in diagnostic]
    rows: dict[str, list[Mapping]] = {}
    for row in record.get("report", []):
        rows.setdefault(row.get("cell"), []).append(row)
    arms_by_cell = {}
    for name in gating:
        cell_rows = rows.get(name, [])
        arms = [r.get("arm") for r in cell_rows]
        if not cell_rows:
            out.append(f"{name}: no report rows")
            continue
        if len(set(arms)) != len(arms):
            out.append(f"{name}: duplicate arm rows")
        arms_by_cell[name] = set(arms)
        for row in cell_rows:
            sims = int(row.get("sims", 0))
            if sims < MIN_SIMS:
                out.append(f"{name}/{row.get('arm')}: {sims} sims")
            levels = row.get("levels", {})
            if {str(a) for a in ALPHAS} != set(levels):
                out.append(
                    f"{name}/{row.get('arm')}: levels {sorted(levels)} are not {list(ALPHAS)}"
                )
                continue
            for alpha in ALPHAS if judge_bounds else ():
                rejected = int(levels[str(alpha)]["rejected"])
                bound = int(binom.ppf(BOUND_QUANTILE, sims, alpha))
                if rejected > bound:
                    out.append(f"{name}/{row.get('arm')} at {alpha}: {rejected} > {bound}")
    if len({frozenset(a) for a in arms_by_cell.values()}) > 1:
        out.append("the gating cells do not all report the same arms")
    return out


def importlib_diagnostic(battery_module: str) -> frozenset[str]:
    """The battery's diagnostic cells (documented limits, never gating)."""
    return frozenset(importlib.import_module(battery_module).DIAGNOSTIC_CELLS)


def battery_scenarios(battery_module: str) -> list[dict]:
    return [dataclasses.asdict(s) for s in importlib.import_module(battery_module).scenarios()]


def _pool_reports(reports: Sequence[Sequence[Mapping]]) -> list[dict]:
    """Sum simulations and rejections per (cell, arm, alpha) over blocks; the bound is dropped (it is
    recomputed at the pooled n)."""
    pooled: dict[tuple, dict] = {}
    for report in reports:
        for row in report:
            key = (row["cell"], row["arm"])
            out = pooled.setdefault(
                key,
                {"cell": row["cell"], "arm": row["arm"], "sims": 0, "levels": {}},
            )
            out["sims"] += int(row["sims"])
            for alpha, level in row["levels"].items():
                out["levels"][alpha] = out["levels"].get(alpha, 0) + int(level["rejected"])
    return [
        {**row, "levels": {a: {"rejected": n} for a, n in row["levels"].items()}}
        for row in pooled.values()
    ]


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
    replication_blocks: Sequence[Sequence[Mapping]] = (),
    seed_bases: Sequence[int] = (),
) -> dict:
    """One pass record from the driver JSON(s) of one battery (a battery may be run in parts, as
    the S1 cell is). The `*_then` values were computed from the sources and the spec as of
    `driver_commit` (sources_at); the record binds the current inputs and code, and refuses unless
    they equal the ones the driver ran at, the working tree is clean, every part names this
    battery and ran at `driver_commit`, the battery's own inputs match the spec, and the merged
    result is a pass.

    `replication_blocks` are further complete runs of the whole battery on other seed blocks (a
    pre-declared replication, todo 636): all blocks' parts get the same checks, every block must run
    the same cells, `seed_bases` (one per block, first the main one) must be distinct, and the pass
    criterion is the POOLED counts (simulations and rejections summed per cell, arm and alpha)
    against the same binomial bound at the pooled n. Every block is kept in the record, and the
    pooled report is what `problems` judges; no block is judged alone. A family in
    DECLARED_REPLICATIONS can only be bound pooled over exactly its declared seed bases. Limits:
    the driver JSON of a block run before the driver recorded `seed_base` cannot prove its seeds
    (`seed_base_recorded` False in the record), and that several runs of a block were made and one
    kept is not visible in the JSON; both rest on the pinned declaration and the run logs."""
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
    blocks = [list(driver_records), *(list(b) for b in replication_blocks)]
    declared = DECLARED_REPLICATIONS.get(spec.family)
    if declared is not None and tuple(seed_bases) != declared:
        raise BatteryPassRefused(
            f"family {spec.family} has a pre-declared replication on seed bases {declared}; bind "
            f"it pooled over exactly those blocks, not {tuple(seed_bases)} (todo 636)"
        )
    if len(blocks) > 1:
        if len(seed_bases) != len(blocks):
            raise BatteryPassRefused("a replication needs one seed base per block")
        spans = []
        for base, block in zip(seed_bases, blocks, strict=True):
            cells = max(len(p.get("scenarios", [])) for p in block)
            sims = max(int(p.get("sims_per_cell", 0)) for p in block)
            spans.append((base, base + SEED_STRIDE * (cells - 1) + sims))
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
            raise BatteryPassRefused(f"the blocks' seed ranges overlap: {spans}")
    for block in blocks:
        names = [c.get("name") for part in block for c in part.get("scenarios", [])]
        if len(set(names)) != len(names):
            raise BatteryPassRefused("a cell appears in more than one driver part")
    if (
        len({frozenset(c.get("name") for p in b for c in p.get("scenarios", [])) for b in blocks})
        > 1
    ):
        raise BatteryPassRefused("the blocks did not run the same cells")
    for part in (p for block in blocks for p in block):
        if part.get("dirty_tracked") is None or part["dirty_tracked"]:
            raise BatteryPassRefused(
                f"a part ran with uncommitted changes or without recording them: "
                f"{part.get('dirty_tracked')}"
            )
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

    def merge(block: Sequence[Mapping]) -> dict:
        return {
            "schema": block[0].get("schema"),
            "battery": battery_module,
            "sims_per_cell": min(int(r.get("sims_per_cell", 0)) for r in block),
            "scenarios": [s for r in block for s in r.get("scenarios", [])],
            "report": [c for r in block for c in r.get("report", [])],
            "failures": [f for r in block for f in r.get("failures", [])],
        }

    per_block = [merge(b) for b in blocks]
    if len(per_block) > 1:
        cells_ = battery_scenarios(battery_module)
        for i, m in enumerate(per_block):
            bad_block = problems(m, cells_, judge_bounds=False)
            if bad_block:
                raise BatteryPassRefused(f"block {i + 1}: " + "; ".join(bad_block))
        shapes = {frozenset((r["cell"], r["arm"]) for r in m["report"]) for m in per_block}
        if len(shapes) > 1:
            raise BatteryPassRefused("the blocks report different (cell, arm) sets")
        if len({json.dumps(m["report"], sort_keys=True) for m in per_block}) < len(per_block):
            raise BatteryPassRefused("two blocks have identical reports: a block was replayed")
        for i, block in enumerate(blocks):
            for part in block:
                claimed = part.get("seed_base")
                if claimed is not None and claimed != seed_bases[i]:
                    raise BatteryPassRefused(
                        f"block {i + 1} ran on seed base {claimed}, not the claimed {seed_bases[i]}"
                    )
    if (
        len(
            {
                json.dumps(sorted(m["scenarios"], key=lambda c: c["name"]), sort_keys=True)
                for m in per_block
            }
        )
        > 1
    ):
        raise BatteryPassRefused("the blocks ran the cells with different settings")
    merged = {
        **per_block[0],
        "diagnostic_cells": sorted(battery.DIAGNOSTIC_CELLS),
        "commit": driver_commit,
    }
    if len(per_block) > 1:
        merged["report"] = _pool_reports([m["report"] for m in per_block])
        merged["sims_per_cell"] = sum(m["sims_per_cell"] for m in per_block)
        merged["failures"] = (
            []
        )  # the pooled counts are judged by problems(), not a block's own list
        merged["blocks"] = [
            {
                "seed_base": seed_bases[i],
                # The driver JSON of a block run before the driver recorded `seed_base` cannot
                # prove its seeds; the claim then rests on the pinned declaration and the run log.
                "seed_base_recorded": all("seed_base" in p for p in blocks[i]),
                **m,
            }
            for i, m in enumerate(per_block)
        ]
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
