"""D-32 rebuild preconditions, checked before the feature_vectors_v2 rebuild is launched.

Consumed by 186-26's first task: it calls `fetch_coverage_inputs` and
`fetch_landed_markers`, passes the measured inputs (plus the pilot disk figures and the
owner's margin) to `run_all`, and refuses to launch the rebuild on
`RebuildPreconditionFailure`. Every check records a `CheckResult` even when an earlier one
fails, and the raised failure names EVERY violated gate, so one run reports the whole gap
instead of the first blocker.

The D-32 owner rule (2026-09-26), quoted: "Complete" means what todo 449's backfill can
fetch; phase 185 D3's venue-move recovery is not a precondition (recovered history enters
afterwards through content-digest keys and recomputes only affected ranges).

Every check is pure over its measured inputs; the only I/O lives in the two thin fetch
helpers at the bottom, each tested against fakes. The module writes nothing. The disk
margin is a parameter of `check_disk_guard` supplied by the caller (186-26 states it), per
the APR-exempt derived-value rule; the module seeds no APR keys.
"""

from __future__ import annotations

import dataclasses
import os
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where each landed marker comes from, so a moved artifact fails loudly here rather than
# silently passing in 186-26.
STATE_RELATIVE_PATH = Path(".planning") / "STATE.md"
GRID_MARKER_NEEDLE = "D2b landed"
REGIME_KERNEL_RELATIVE_PATH = Path("src/intelligence/features/kernels/regime.py")
WRITER_MODULE_NAME = "services.backfill_feature_factory"

# The relations 186-22 and 186-23 drop; the rebuild refuses while any of them exists
# (the old chain's writers are gone, so a surviving table is stale state, not live data).
DROPS_DUE_BEFORE_REBUILD: frozenset[str] = frozenset(
    {
        "ensemble_weights",
        "ensemble_alpha",
        "alpha_ensemble_ic",
        "alpha_events",
        "alpha_frames",
        "alpha_strategy_scores",
        "context_features",
        "feature_ic_scores_history",
        "construction_spreads",
        "ctx_events",
        "ctx_snapshots",
        "forward_returns",
    }
)

# Marker names check_dependencies_landed requires; fetch_landed_markers produces exactly
# these keys (plus the two input-sourcing markers it gathers alongside).
REQUIRED_DEPENDENCY_MARKERS: frozenset[str] = frozenset(
    {
        "bulk_load_import",
        "registry_regime_origin",
        "kernels_regime_module",
        "feature_vectors_v2_relation",
        "writer_module_import",
    }
)

# Processes whose presence means another writer is live against the tables this rebuild
# writes, or that hold the modules a live-or-resumable run forbids editing (D-32a).
LIVE_RUN_PROCESS_PATTERN = (
    "ic_engine",
    "backfill_feature_factory",
    "regime_writer",
    "feature_vector_rebuild",
)


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """One precondition's outcome: recorded whether it passed or not."""

    name: str
    ok: bool
    detail: str


@dataclasses.dataclass(frozen=True)
class CoverageRow:
    """One (symbol, tf) cell of the tradeable-coverage fetch."""

    count: int
    first: datetime
    last: datetime


class RebuildPreconditionFailure(RuntimeError):
    """The rebuild refuses to launch; the message names every violated gate."""

    def __init__(self, results: Sequence[CheckResult]):
        failed = [r for r in results if not r.ok]
        lines = [f"{r.name}: {r.detail}" for r in failed]
        passed = [r.name for r in results if r.ok]
        super().__init__(
            "rebuild preconditions failed (refusing to launch; "
            f"{len(failed)} of {len(results)} checks failed):\n  - "
            + "\n  - ".join(lines)
            + ("\npassed: " + ", ".join(passed) if passed else "")
        )
        self.results = list(results)


# ---------------------------------------------------------------------------
# The seven checks (pure)
# ---------------------------------------------------------------------------


def check_bar_coverage(
    coverage_rows: Mapping[tuple[str, str], CoverageRow],
    expected_spans: Mapping[tuple[str, str], tuple[datetime, datetime]],
    empty_history_spans: Sequence[tuple[str, str, str]],
) -> CheckResult:
    """D-32 bar completeness: every rebuild (symbol, tf) must cover its expected span.

    `ohlcv_empty_history` spans are listed verbatim in the detail, never assumed away: a
    provider-empty span means the backfill cannot fetch the bars, which under the owner rule
    still counts as complete, and the record of it is what makes that auditable.
    """
    lines: list[str] = []
    for key in sorted(expected_spans):
        want_first, want_last = expected_spans[key]
        row = coverage_rows.get(key)
        if row is None or row.count == 0:
            lines.append(
                f"{key[0]}|{key[1]}: no bars, expected {want_first:%Y-%m-%d}..{want_last:%Y-%m-%d}"
            )
            continue
        if row.first > want_first or row.last < want_last:
            lines.append(
                f"{key[0]}|{key[1]}: measured {row.first:%Y-%m-%d}..{row.last:%Y-%m-%d} "
                f"({row.count} rows), expected {want_first:%Y-%m-%d}..{want_last:%Y-%m-%d}"
            )
    detail = "; ".join(lines) if lines else "every rebuild (symbol, tf) covers its expected span"
    if empty_history_spans:
        listed = "; ".join(f"{s}|{tf}: {text}" for s, tf, text in empty_history_spans)
        detail = f"{detail}. ohlcv_empty_history spans: {listed}"
    return CheckResult("bar_coverage", not lines, detail)


def check_derived_grid_landed(marker_present: bool, marker_detail: str) -> CheckResult:
    """Phase 185's D2b derived 15m/1h grid must have landed (the STATE.md bullet 185-12
    writes names the date and the symbols still waiting on 5m)."""
    return CheckResult(
        "derived_grid_landed",
        bool(marker_present),
        marker_detail or "no D2b landing marker found",
    )


def check_todo445_decision(
    decision: Mapping[str, Any] | None, configured_tfs: Sequence[str]
) -> CheckResult:
    """The recorded todo 445 decision (keep_5m and its rebuild timeframe set, from
    completed/445-*.md via 186-07's result JSON) must exist and agree with the writer's
    configured tf set."""
    if not decision:
        return CheckResult(
            "todo445_decision", False, "no recorded todo 445 decision (expected keep_5m + tfs)"
        )
    recorded = str(decision.get("decision", ""))
    recorded_tfs = sorted(decision.get("rebuild_timeframes", []))
    configured = sorted(configured_tfs)
    if recorded != "keep_5m":
        return CheckResult("todo445_decision", False, f"decision is {recorded!r}, expected keep_5m")
    if recorded_tfs != configured:
        return CheckResult(
            "todo445_decision",
            False,
            f"decision rebuild_timeframes {recorded_tfs} != writer's configured {configured}",
        )
    return CheckResult("todo445_decision", True, f"keep_5m; rebuild timeframes {configured} agree")


def check_dependencies_landed(markers: Mapping[str, bool]) -> CheckResult:
    """186-06/186-15/186-18/186-24 and this plan's writer must all be in place."""
    missing = sorted(name for name in REQUIRED_DEPENDENCY_MARKERS if not markers.get(name))
    if missing:
        return CheckResult(
            "dependencies_landed", False, f"missing or false markers: {', '.join(missing)}"
        )
    return CheckResult("dependencies_landed", True, "all dependency markers present")


def check_drops_landed(present_relations: frozenset[str] | set[str]) -> CheckResult:
    """186-22/186-23's table drops must have landed: no old-chain relation may survive."""
    surviving = sorted(DROPS_DUE_BEFORE_REBUILD & set(present_relations))
    if surviving:
        return CheckResult(
            "drops_landed", False, f"tables due for drop still present: {', '.join(surviving)}"
        )
    return CheckResult("drops_landed", True, "no old-chain relation present")


def check_disk_guard(
    projected_compressed_bytes: int,
    largest_chunk_working_set_bytes: int,
    margin_bytes: int,
    free_bytes: int,
    reserve_bytes: int,
) -> CheckResult:
    """R-09: free minus reserve must cover the projected final compressed size, the largest
    uncompressed chunk working set, and the caller's stated margin (all measured on the
    pilot chunk by 186-26). The margin is an argument, never a literal here."""
    required = projected_compressed_bytes + largest_chunk_working_set_bytes + margin_bytes
    available = free_bytes - reserve_bytes
    gb = lambda b: f"{b / 1e9:.0f} GB"  # noqa: E731
    if available < required:
        return CheckResult(
            "disk_guard",
            False,
            f"free {gb(free_bytes)} minus reserve {gb(reserve_bytes)} = {gb(available)} does not "
            f"cover projected compressed {gb(projected_compressed_bytes)} + largest chunk working "
            f"set {gb(largest_chunk_working_set_bytes)} + margin {gb(margin_bytes)} = {gb(required)}",
        )
    return CheckResult(
        "disk_guard",
        True,
        f"{gb(available)} available covers the {gb(required)} requirement "
        f"(projected {gb(projected_compressed_bytes)}, working set "
        f"{gb(largest_chunk_working_set_bytes)}, margin {gb(margin_bytes)})",
    )


def check_no_live_run(process_lines: Sequence[str], resumable_log_evidence: str) -> CheckResult:
    """D-32a/D-01: no ic_engine, backfill_feature_factory, regime_writer or rebuild process
    may be live, and no resumable run may be indicated (a resumable rebuild forbids edits to
    its import closure and would double-write the units it retakes)."""
    hits = sorted(
        line
        for line in process_lines
        if any(pattern in line for pattern in LIVE_RUN_PROCESS_PATTERN)
    )
    if hits:
        return CheckResult("no_live_run", False, f"live writer process(es): {' | '.join(hits[:5])}")
    if resumable_log_evidence:
        return CheckResult(
            "no_live_run",
            False,
            f"resumable run indicated: {resumable_log_evidence}",
        )
    return CheckResult("no_live_run", True, "no live or resumable writer process")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def run_all(
    *,
    coverage_rows: Mapping[tuple[str, str], CoverageRow],
    expected_spans: Mapping[tuple[str, str], tuple[datetime, datetime]],
    empty_history_spans: Sequence[tuple[str, str, str]],
    grid_marker_present: bool,
    grid_marker_detail: str,
    todo445_decision: Mapping[str, Any] | None,
    configured_tfs: Sequence[str],
    dependency_markers: Mapping[str, bool],
    present_relations: frozenset[str] | set[str],
    disk: Mapping[str, int],
    process_lines: Sequence[str],
    resumable_log_evidence: str,
) -> list[CheckResult]:
    """Run every D-32 check, return all results, and raise `RebuildPreconditionFailure`
    naming EVERY failure when any check fails."""
    results = [
        check_bar_coverage(coverage_rows, expected_spans, empty_history_spans),
        check_derived_grid_landed(grid_marker_present, grid_marker_detail),
        check_todo445_decision(todo445_decision, configured_tfs),
        check_dependencies_landed(dependency_markers),
        check_drops_landed(present_relations),
        check_disk_guard(
            projected_compressed_bytes=disk["projected_compressed_bytes"],
            largest_chunk_working_set_bytes=disk["largest_chunk_working_set_bytes"],
            margin_bytes=disk["margin_bytes"],
            free_bytes=disk["free_bytes"],
            reserve_bytes=disk["reserve_bytes"],
        ),
        check_no_live_run(process_lines, resumable_log_evidence),
    ]
    if any(not r.ok for r in results):
        raise RebuildPreconditionFailure(results)
    return results


# ---------------------------------------------------------------------------
# The two thin fetch helpers (the only I/O; tested against fakes)
# ---------------------------------------------------------------------------

_COVERAGE_SQL = """
SELECT symbol, timeframe, count(*), min(timestamp), max(timestamp)
FROM market_data_ohlcv_tradeable
WHERE timeframe = ANY(%s) AND symbol = ANY(%s)
GROUP BY symbol, timeframe
"""

_EMPTY_SPANS_SQL = """
SELECT symbol, timeframe, first_bar::text, last_bar::text
FROM ohlcv_empty_history
WHERE timeframe = ANY(%s)
"""


def fetch_coverage_inputs(
    conn: Any, tfs: Sequence[str], symbols: Sequence[str]
) -> tuple[dict[tuple[str, str], CoverageRow], list[tuple[str, str, str]]]:
    """The measured inputs of check_bar_coverage: grouped min/max/count per (symbol, tf) from
    `market_data_ohlcv_tradeable` only, plus the `ohlcv_empty_history` spans for the rebuild's
    tfs. Read-only; the statement timeout keeps a cold hypertable scan from holding a lock
    longer than the check needs."""
    rows: dict[tuple[str, str], CoverageRow] = {}
    spans: list[tuple[str, str, str]] = []
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '10min'")
        cur.execute(_COVERAGE_SQL, (list(tfs), list(symbols)))
        for symbol, tf, count, first, last in cur.fetchall():
            rows[(symbol, tf)] = CoverageRow(count=int(count), first=first, last=last)
        cur.execute(_EMPTY_SPANS_SQL, (list(tfs),))
        spans = [
            (symbol, tf, f"{first_text}..{last_text}")
            for symbol, tf, first_text, last_text in cur.fetchall()
        ]
    return rows, spans


def fetch_process_lines() -> list[str]:
    """The measured input of check_no_live_run: `ps -eo pid,args` lines minus this process's
    own. A launcher that wires the precheck into backfill_feature_factory itself (or imports
    the writer module, as fetch_landed_markers does) would otherwise match
    LIVE_RUN_PROCESS_PATTERN against its own command line and refuse every launch."""
    completed = subprocess.run(
        ["ps", "-eo", "pid,args"], capture_output=True, text=True, check=True
    )
    own_pid = str(os.getpid())
    return [
        line
        for line in completed.stdout.splitlines()
        if line.split() and line.split()[0] != own_pid
    ]


def fetch_landed_markers(conn: Any, state_path: Path | None = None) -> dict[str, bool]:
    """The measured inputs of check_dependencies_landed and check_drops_landed's companion:
    import checks, the registry's regime origin, the regime kernel module, the v2 relation
    (through the passed connection, never a psql subprocess), the writer module's import, and
    the 185 D2b STATE.md bullet. Returns exactly REQUIRED_DEPENDENCY_MARKERS plus
    `grid_marker` (consumed as grid_marker_present/grid_marker_detail by run_all's caller)."""
    from src.intelligence.features.contract.registry import default_registry

    state_path = state_path or _PROJECT_ROOT / STATE_RELATIVE_PATH
    markers: dict[str, bool] = {}
    try:
        from services import backfill_feature_factory as writer  # noqa: F401

        markers["writer_module_import"] = hasattr(writer, "run_rebuild_stage")
    except Exception:
        markers["writer_module_import"] = False
    try:
        from services._batch_utils import BulkLoadSpec, bulk_load  # noqa: F401

        markers["bulk_load_import"] = True
    except Exception:
        markers["bulk_load_import"] = False
    try:
        markers["registry_regime_origin"] = any(
            kernel.origin == "regime" for kernel in default_registry().kernels
        )
    except Exception:
        markers["registry_regime_origin"] = False
    markers["kernels_regime_module"] = (_PROJECT_ROOT / REGIME_KERNEL_RELATIVE_PATH).is_file()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('feature_vectors_v2') IS NOT NULL",
        )
        markers["feature_vectors_v2_relation"] = bool(cur.fetchone()[0])

    try:
        markers["grid_marker"] = GRID_MARKER_NEEDLE in state_path.read_text()
    except OSError:
        markers["grid_marker"] = False
    return markers
