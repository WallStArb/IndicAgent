"""D-32 rebuild preconditions, checked before the feature_vectors_v2 rebuild is launched.

Consumed by 186-26's first task: it calls `fetch_coverage_inputs` (empty-history spans),
`fetch_landed_markers`, `fetch_d2_inputs` (1d verdicts), `fetch_bar_verdict_inputs` (intraday
verdicts) and `fetch_final_landed_markers`, passes the measured inputs (plus the pilot disk
figures and the owner's margin) to `run_all`, and refuses to launch the rebuild on
`RebuildPreconditionFailure`. Since plan 185-41 `check_d2_landed` and `check_bar_coverage` read
the computed `bar_integrity` verdicts through `src/intelligence/bars/verdict_gate.py`, the same
gate promotion uses; a failing, missing or stale verdict fails and is named. Every check records a `CheckResult` even when an earlier one
fails, and the raised failure names EVERY violated gate, so one run reports the whole gap
instead of the first blocker.

The D-32 owner rule (2026-09-26), quoted: "Complete" means what todo 449's backfill can
fetch; phase 185 D3's venue-move recovery is not a precondition (recovered history enters
afterwards through content-digest keys and recomputes only affected ranges).

Every check is pure over its measured inputs; the only I/O lives in the thin fetch
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

from src.intelligence.bars.verdict_gate import (
    VerdictScan,
    fetch_verdict_scan,
    load_report_max_age_hours,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where each landed marker comes from, so a moved artifact fails loudly here rather than
# silently passing in 186-26.
STATE_RELATIVE_PATH = Path(".planning") / "STATE.md"
GRID_MARKER_NEEDLE = "D2b landed"
REGIME_KERNEL_RELATIVE_PATH = Path("src/intelligence/features/kernels/regime.py")
WRITER_MODULE_NAME = "services.backfill_feature_factory"

# The phase 185 and 189 cleanup and data plans that must have landed before the single rebuild:
# 185-42/185-45 (cleanup, so the writer's code_content_key is taken on final code), 185-43
# (census exit proof) and 189-11 (5m backfill complete, vendor rows out). Presence of the
# SUMMARY file is the landing marker, as for the other dependency markers.
REQUIRED_FINAL_LANDED_SUMMARIES: frozenset[str] = frozenset(
    {"185-42-SUMMARY.md", "185-43-SUMMARY.md", "185-45-SUMMARY.md", "189-11-SUMMARY.md"}
)

# Intraday timeframes the bar coverage verdicts judge; stray vendor rows gate the rebuild only.
INTRADAY_VERDICT_TFS: tuple[str, ...] = ("5m", "15m", "1h")
REBUILD_EXTRA_CHECKS: frozenset[str] = frozenset({"stray_vendor_rows"})

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
# The eight checks (pure)
# ---------------------------------------------------------------------------


def _verdict_detail(scan: VerdictScan, limit: int = 10) -> str:
    """Failing symbols with their (tf, check, reason) lines, truncated to `limit` symbols."""
    names = sorted(scan.failures)
    shown = [f"{name} [{'; '.join(scan.failures[name][:3])}]" for name in names[:limit]]
    more = f", ... (+{len(names) - limit} more)" if len(names) > limit else ""
    return f"{len(names)} of {scan.n_symbols} symbols fail: {', '.join(shown)}{more}"


def _verdict_result(name: str, scan: VerdictScan, what: str) -> CheckResult:
    if scan.n_symbols == 0:
        return CheckResult(name, False, "no symbols were judged (an empty gate proves nothing)")
    if scan.failures:
        return CheckResult(name, False, _verdict_detail(scan))
    first, last = scan.first_evaluated_at, scan.last_evaluated_at
    window = f"{first:%Y-%m-%d %H:%M}Z..{last:%Y-%m-%d %H:%M}Z" if first and last else "no rows"
    return CheckResult(
        name, True, f"all {scan.n_symbols} symbols pass {what}; verdicts evaluated {window}"
    )


def check_bar_coverage(
    scan: VerdictScan, empty_history_spans: Sequence[tuple[str, str, str]]
) -> CheckResult:
    """D-32 bar completeness: every rebuild symbol passes the intraday verdicts (5m slot_coverage,
    digest_fresh and coverage_cache; 15m and 1h digest_fresh and grid_parity) plus
    stray_vendor_rows, fresh. Reads the same rows promotion reads (plan 185-41).

    `ohlcv_empty_history` spans are listed verbatim in the detail, never assumed away: a
    provider-empty span means the backfill cannot fetch the bars, which under the owner rule
    still counts as complete, and the record of it is what makes that auditable.
    """
    result = _verdict_result("bar_coverage", scan, "every intraday verdict and stray_vendor_rows")
    if empty_history_spans:
        listed = "; ".join(f"{s}|{tf}: {text}" for s, tf, text in empty_history_spans)
        return CheckResult(
            result.name, result.ok, f"{result.detail}. ohlcv_empty_history spans: {listed}"
        )
    return result


def check_derived_grid_landed(marker_present: bool, marker_detail: str) -> CheckResult:
    """Phase 185's D2b derived 15m/1h grid must have landed (the STATE.md bullet 185-12
    writes names the date and the symbols still waiting on 5m)."""
    return CheckResult(
        "derived_grid_landed",
        bool(marker_present),
        marker_detail or "no D2b landing marker found",
    )


def check_d2_landed(scan: VerdictScan) -> CheckResult:
    """Phase 185's 1d layer must have landed and be proven: every 1d rebuild symbol passes every
    required 1d verdict (session coverage, policy conformance, lineage, canonical recompute,
    digest, seams, vendor basis), fresh. A rebuild launched on bars that fail or lack a fresh
    verdict keeps them until someone re-runs it (todo 489)."""
    return _verdict_result("d2_landed", scan, "every 1d verdict")


def check_data_layer_final_landed(markers: Mapping[str, bool]) -> CheckResult:
    """185-42, 185-43, 185-45 and 189-11 must have landed: the 186-26 rebuild runs once, on final
    code (the writer's code_content_key covers this module) and final bars. An early launch would
    also block 185-42's edit of the rebuild writer."""
    missing = sorted(name for name in REQUIRED_FINAL_LANDED_SUMMARIES if not markers.get(name))
    if missing:
        return CheckResult(
            "data_layer_final_landed", False, f"missing SUMMARY files: {', '.join(missing)}"
        )
    return CheckResult("data_layer_final_landed", True, "185-42, 185-43, 185-45 and 189-11 landed")


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
    bar_scan: VerdictScan,
    empty_history_spans: Sequence[tuple[str, str, str]],
    grid_marker_present: bool,
    grid_marker_detail: str,
    d2_scan: VerdictScan,
    final_landed_markers: Mapping[str, bool],
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
        check_bar_coverage(bar_scan, empty_history_spans),
        check_derived_grid_landed(grid_marker_present, grid_marker_detail),
        check_d2_landed(d2_scan),
        check_data_layer_final_landed(final_landed_markers),
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
# The thin fetch helpers (the only I/O; tested against fakes)
# ---------------------------------------------------------------------------

_COVERAGE_SQL = """
SELECT symbol, timeframe, count(*), min(timestamp), max(timestamp)
FROM market_data_ohlcv_tradeable
WHERE timeframe = ANY(%s) AND symbol = ANY(%s)
GROUP BY symbol, timeframe
"""

_EMPTY_SPANS_SQL = """
SELECT symbol, timeframe, empty_from::date::text, empty_through::date::text
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
        # Session-level setting: restore it so a caller reusing the connection for longer
        # work does not inherit the cap.
        cur.execute("RESET statement_timeout")
    return rows, spans


def fetch_d2_inputs(
    conn: Any, symbols: Sequence[str], *, now: datetime | None = None
) -> VerdictScan:
    """The measured input of check_d2_landed: the 1d verdict gate over `symbols` (the latest
    verdicts and the latest changing 1d load per symbol, the freshness window from APR).
    Read-only. Since 185-41 it returns a VerdictScan, not (missing_lineage, missing_digest), and
    the `rule_version` argument is gone (lineage is a view and the rule is d2-v2 everywhere)."""
    return fetch_verdict_scan(conn, symbols, ("1d",), load_report_max_age_hours(conn), now=now)


def fetch_bar_verdict_inputs(
    conn: Any, symbols: Sequence[str], tfs: Sequence[str], *, now: datetime | None = None
) -> VerdictScan:
    """The measured input of check_bar_coverage: the intraday verdict gate over `symbols` for the
    rebuild's intraday timeframes (`tfs` minus 1d), plus stray_vendor_rows. Read-only."""
    intraday = [tf for tf in INTRADAY_VERDICT_TFS if tf in tfs]
    return fetch_verdict_scan(
        conn,
        symbols,
        intraday,
        load_report_max_age_hours(conn),
        extra_checks=REBUILD_EXTRA_CHECKS,
        now=now,
    )


def fetch_final_landed_markers(project_root: Path | None = None) -> dict[str, bool]:
    """The measured input of check_data_layer_final_landed: for each required SUMMARY file name,
    whether it exists in its phase directory (a PLAN is not a landing)."""
    phases = (project_root or _PROJECT_ROOT) / ".planning" / "phases"
    return {
        name: any(phases.glob(f"{name.split('-', 1)[0]}-*/{name}"))
        for name in sorted(REQUIRED_FINAL_LANDED_SUMMARIES)
    }


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
