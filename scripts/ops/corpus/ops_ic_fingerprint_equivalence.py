#!/usr/bin/env python3
"""Fresh-vs-fingerprint-skip equivalence harness for ic_engine.py (Phase 162 Plan 04,
todo 134's empirical closing proof).

Answers the direct empirical question this whole 162-01..162-04 arc exists to settle:
does the whole-cell fingerprint (code_content_key + apr_snapshot_key + upstream_watermark,
migration 251/162-03) capture EVERYTHING that determines a cell's IC? Runs a small symbol
subset through ic_engine.py TWICE against the SAME --training-window-end -- once forced
fresh (--refresh), once via the normal fingerprint-skip path (which should find the
fingerprints run A wrote and skip entirely, touching zero rows) -- and diffs the resulting
feature_ic_scores rows on the FULL value set, including bh_adjusted_p/passes_fdr (populated
by a post-write BH-FDR backfill pass, not the per-cell write itself -- Risk 2, BH-FDR family
coherence must hold across the skip path too).

This is DB-backed and cannot run in the unit sandbox -- the harness's own nonzero/zero exit
code IS the empirical proof, run manually against a live corpus.

SAFETY (production-data-corruption guard, not in the plan's own threat register but a real
consequence of how --refresh scopes cross-sectional recompute -- see this script's
_preflight_check_no_existing_rows docstring): cross-sectional (POOLED) cell membership is
derived ONLY from the --symbols this script passes to ic_engine.py, not the full corpus
symbol universe. Running --refresh with a narrow subset against a --training-window-end
that ALREADY has real full-corpus data would DELETE-then-recompute that window's POOLED
cells using only the narrow subset, silently corrupting the real corpus. This script
therefore REFUSES to run (exit nonzero) if any feature_ic_scores rows already exist for the
requested (symbols + POOLED, tfs, training_window_end) combination, unless --force is passed
with full understanding of that risk. The intended usage is a dedicated, otherwise-unused
--training-window-end value picked specifically for this equivalence check.

Usage:
    python scripts/ops/corpus/ops_ic_fingerprint_equivalence.py \\
        --symbols SPY QQQ IWM TLT GLD --tf 1d \\
        --training-window-end 2026-01-01T00:00:00+00:00

    # Drift study (optional, Task 2): IC-vs-lag curve informing refresh_min_new_fraction
    python scripts/ops/corpus/ops_ic_fingerprint_equivalence.py \\
        --symbols SPY QQQ IWM TLT GLD --tf 1d \\
        --training-window-end 2026-01-01T00:00:00+00:00 --drift-study
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.service_utils import format_iso_ts, setup_service_logging

setup_service_logging("logs/ic_fingerprint_equivalence.log")

_logger = structlog.get_logger(__name__)

_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]
_DEFAULT_DRIFT_LAGS_DAYS: list[int] = [1, 5, 10, 20]

# EPSILON_TOLERANCE per CLAUDE.md: financial math float comparisons never use bare `==`.
_EPSILON_TOLERANCE = 1e-9

# feature_ic_scores columns compared for VALUE equivalence -- everything except the PK
# identity columns (compared separately, as the diff key) and computed_at (bookkeeping
# timestamp, compared SEPARATELY below as the "did B actually skip" proof, not folded into
# the value-divergence signal). Column list taken from the LIVE schema (`\\d
# feature_ic_scores`), NOT migration 156's original DDL -- the live table has drifted well
# beyond that migration (ic_shrunk/regime_scope/partial_ic/etc. added by later phases;
# is_decaying/decay_detected_at/recovery_eligible_at from 156 no longer exist; `regime` is
# now NOT NULL with a '_pooled' sentinel for pooled rows rather than NULL).
_PK_COLUMNS: tuple[str, ...] = ("feature_name", "symbol", "tf", "regime", "lookahead_bars")
_VALUE_COLUMNS: tuple[str, ...] = (
    "vector_domain",
    "is_pooled",
    "n_independent",
    "reliable",
    "ic_value",
    "ic_sign",
    "p_value",
    "ic_ci_lower",
    "ic_ci_upper",
    "passes_ci_gate",
    "bh_adjusted_p",
    "passes_fdr",
    "wf_fold_count",
    "wf_pass_count",
    "wf_ic_sharpe",
    "passes_walkforward",
    "ic_sharpe",
    "ic_sharpe_n_windows",
    "regime_label_source",
    "ic_sortino",
    "ic_win_rate",
    "cluster_id",
    "feature_status_at_eval",
    "ic_sharpe_hac",
    "regime_scope",
    "ic_shrunk",
    "shrinkage_weight",
    "partial_ic",
    "partial_ic_p_value",
    "partial_ic_n",
    "passes_partial_fdr",
    "sign_hit_rate",
    "magnitude_conditional_ic",
    "cumulative_e_value",
)
_FLOAT_COLUMNS: frozenset[str] = frozenset(
    {
        "ic_value",
        "p_value",
        "ic_ci_lower",
        "ic_ci_upper",
        "bh_adjusted_p",
        "wf_ic_sharpe",
        "ic_sharpe",
        "ic_sortino",
        "ic_win_rate",
        "ic_sharpe_hac",
        "ic_shrunk",
        "shrinkage_weight",
        "partial_ic",
        "partial_ic_p_value",
        "sign_hit_rate",
        "magnitude_conditional_ic",
        "cumulative_e_value",
    }
)

_SNAPSHOT_SQL = """
    SELECT feature_name, vector_domain, symbol, tf, regime, lookahead_bars, is_pooled,
           n_independent, reliable, ic_value, ic_sign, p_value, ic_ci_lower, ic_ci_upper,
           passes_ci_gate, bh_adjusted_p, passes_fdr, wf_fold_count, wf_pass_count,
           wf_ic_sharpe, passes_walkforward, ic_sharpe, ic_sharpe_n_windows,
           regime_label_source, ic_sortino, ic_win_rate, cluster_id, feature_status_at_eval,
           ic_sharpe_hac, regime_scope, ic_shrunk, shrinkage_weight, partial_ic,
           partial_ic_p_value, partial_ic_n, passes_partial_fdr, sign_hit_rate,
           magnitude_conditional_ic, cumulative_e_value, computed_at
    FROM feature_ic_scores
    WHERE (symbol = ANY($1) OR symbol = 'POOLED')
      AND tf = ANY($2)
      AND training_window_end = $3
"""


# ---------------------------------------------------------------------------
# Risk 5 (resource contention): refuse to run alongside a live ic_engine run.
# ---------------------------------------------------------------------------


def _refuse_if_ic_engine_running() -> None:
    """Refuses (exit nonzero) if another ic_engine.py process is already live.

    This harness dispatches TWO full ic_engine.py invocations itself; colliding with an
    already-running ic_engine.py would double the worker-pool contention this project has
    already OOM'd on once (162-01's own incident record). Checked once at the very start.
    """
    result = subprocess.run(["ps", "aux"], capture_output=True, text=True, check=True)
    running = [
        line
        for line in result.stdout.splitlines()
        if "ic_engine.py" in line
        and "grep" not in line
        and "ops_ic_fingerprint_equivalence" not in line
    ]
    if running:
        print(
            "FATAL: another ic_engine.py process is already running -- refusing to start "
            "(this harness dispatches two more full ic_engine.py invocations itself; "
            "colliding with a live run risks worker-pool resource contention/OOM).",
            file=sys.stderr,
        )
        for line in running:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Production-data-corruption guard (Rule 2 addition -- see module docstring's SAFETY
# section): --refresh's cross-sectional recompute scope is narrower than the real corpus
# whenever a subset of symbols is passed. Never run this harness against a
# --training-window-end that already carries real corpus data.
# ---------------------------------------------------------------------------


async def _preflight_check_no_existing_rows(
    pool: asyncpg.Pool,
    symbols: list[str],
    tfs: list[str],
    training_window_end: datetime,
    force: bool,
) -> bool:
    """Returns True iff this run OWNS every row it will touch (safe to auto-clean up on
    success). Refuses (exit nonzero) if pre-existing rows are found and --force was not
    passed -- see module docstring's SAFETY section for the exact corruption mechanism
    this guards against (narrow-subset --refresh silently overwriting full-corpus POOLED
    cells at a training_window_end that already has real data).
    """
    existing = await pool.fetch(_SNAPSHOT_SQL, symbols, tfs, training_window_end)
    if existing:
        if not force:
            print(
                f"FATAL: {len(existing)} feature_ic_scores row(s) already exist for this "
                f"(symbols/POOLED, tfs, training_window_end={format_iso_ts(training_window_end)}) "
                "combination. Running --refresh here risks silently narrowing/overwriting real "
                "corpus data (cross-sectional POOLED cells are scoped to whatever --symbols "
                "this harness passes, not the full corpus universe). Use a dedicated, "
                "otherwise-unused --training-window-end for this equivalence check, or pass "
                "--force if you have independently verified this is safe.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            f"WARNING: --force passed with {len(existing)} pre-existing row(s) -- this run does "
            "NOT own that data and will NOT auto-clean up on success.",
            file=sys.stderr,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# ic_engine.py subprocess dispatch
# ---------------------------------------------------------------------------


def _run_ic_engine(
    symbols: list[str], tfs: list[str], training_window_end: datetime, *, refresh: bool
) -> None:
    """One full ic_engine.py invocation (subprocess). Raises on nonzero exit."""
    cmd = [
        sys.executable,
        "services/ic_engine.py",
        "--symbols",
        *symbols,
        "--tf",
        *tfs,
        "--training-window-end",
        format_iso_ts(training_window_end),
    ]
    if refresh:
        cmd.append("--refresh")
    _logger.info("ic_fingerprint_equivalence.dispatch", cmd=cmd, refresh=refresh)
    result = subprocess.run(cmd, cwd=str(project_root))
    if result.returncode != 0:
        raise RuntimeError(f"ic_engine.py exited {result.returncode} (refresh={refresh}): {cmd}")


# ---------------------------------------------------------------------------
# Snapshot fetch + diff (pure comparison logic, DB read only)
# ---------------------------------------------------------------------------


def _snapshot_key(row: dict[str, Any]) -> tuple:
    return tuple(row[c] for c in _PK_COLUMNS)


async def _fetch_snapshot(
    pool: asyncpg.Pool, symbols: list[str], tfs: list[str], training_window_end: datetime
) -> dict[tuple, dict[str, Any]]:
    rows = await pool.fetch(_SNAPSHOT_SQL, symbols, tfs, training_window_end)
    return {_snapshot_key(dict(r)): dict(r) for r in rows}


@dataclass
class _DiffResult:
    ok: bool
    value_divergences: list[str] = field(default_factory=list)
    skip_not_occurred: list[str] = field(default_factory=list)
    missing_keys: list[tuple] = field(default_factory=list)
    extra_keys: list[tuple] = field(default_factory=list)


def _values_equal(col: str, a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    if col in _FLOAT_COLUMNS:
        return abs(float(a) - float(b)) <= _EPSILON_TOLERANCE
    return a == b


def _diff_snapshots(
    snap_a: dict[tuple, dict[str, Any]], snap_b: dict[tuple, dict[str, Any]]
) -> _DiffResult:
    """Compares run A's (--refresh) snapshot to run B's (fingerprint-skip) snapshot.

    Two independent signals, accumulated (never logged per-row inside the loop, per
    CLAUDE.md's "never log per-row inside a loop over the full corpus" pattern -- this
    subset is small, but the accumulate-then-report-once shape is followed regardless):

      1. value_divergences -- any _VALUE_COLUMNS mismatch on a common key. This is the
         actual completeness proof: the fingerprint must capture everything that
         determines a cell's IC, INCLUDING bh_adjusted_p/passes_fdr (Risk 2).
      2. skip_not_occurred -- computed_at changed on a common key. B is expected to
         SKIP (touch zero rows), so computed_at must be byte-identical to A's write. A
         changed computed_at proves B recomputed rather than skipped -- a distinct
         "throughput/mechanism" failure from a value divergence (the values could
         still be numerically correct even if B wastefully recomputed them).
    """
    keys_a = set(snap_a)
    keys_b = set(snap_b)
    result = _DiffResult(ok=True)
    # key=str: PK tuples include `regime` (None for POOLED rows) mixed with str values
    # across different rows -- Python 3 can't compare None < str, so sort by string repr.
    result.missing_keys = sorted(keys_a - keys_b, key=str)
    result.extra_keys = sorted(keys_b - keys_a, key=str)
    if result.missing_keys or result.extra_keys:
        result.ok = False

    for key in sorted(keys_a & keys_b, key=str):
        row_a, row_b = snap_a[key], snap_b[key]
        for col in _VALUE_COLUMNS:
            if not _values_equal(col, row_a[col], row_b[col]):
                result.value_divergences.append(
                    f"{key}: column={col} run_A={row_a[col]!r} run_B={row_b[col]!r}"
                )
        if row_a["computed_at"] != row_b["computed_at"]:
            result.skip_not_occurred.append(
                f"{key}: computed_at run_A={row_a['computed_at']!r} run_B={row_b['computed_at']!r} "
                "(B did not skip -- it recomputed and rewrote this row)"
            )

    if result.value_divergences or result.skip_not_occurred:
        result.ok = False
    return result


# ---------------------------------------------------------------------------
# Cleanup (only for rows this run owns -- see _preflight_check_no_existing_rows)
# ---------------------------------------------------------------------------


async def _cleanup_owned_rows(
    pool: asyncpg.Pool, tfs: list[str], training_window_end: datetime
) -> None:
    """Deletes every feature_ic_scores/ic_cell_fingerprints row at this test's dedicated
    training_window_end, across all symbols/tfs -- safe ONLY because the pre-flight check
    already confirmed this window was empty before this run touched it, so anything found
    here now was written by this run alone. Runs on the success path only (never on
    failure -- divergent rows are left in place for inspection).
    """
    async with pool.acquire() as conn, conn.transaction():
        result_scores = await conn.execute(
            "DELETE FROM feature_ic_scores WHERE tf = ANY($1) AND training_window_end = $2",
            tfs,
            training_window_end,
        )
        result_fps = await conn.execute(
            "DELETE FROM ic_cell_fingerprints WHERE tf = ANY($1) AND training_window_end = $2",
            tfs,
            training_window_end,
        )
    _logger.info(
        "ic_fingerprint_equivalence.cleanup_complete",
        feature_ic_scores=result_scores,
        ic_cell_fingerprints=result_fps,
    )


# ---------------------------------------------------------------------------
# Equivalence check orchestration
# ---------------------------------------------------------------------------


async def _run_equivalence_check(
    pool: asyncpg.Pool,
    symbols: list[str],
    tfs: list[str],
    training_window_end: datetime,
    force: bool,
    keep_test_data: bool,
) -> int:
    owns_all_rows = await _preflight_check_no_existing_rows(
        pool, symbols, tfs, training_window_end, force
    )

    print(f"[run A] --refresh forced-fresh compute: symbols={symbols} tf={tfs}")
    t0 = time.monotonic()
    _run_ic_engine(symbols, tfs, training_window_end, refresh=True)
    print(f"[run A] complete in {time.monotonic() - t0:.1f}s")
    snap_a = await _fetch_snapshot(pool, symbols, tfs, training_window_end)
    print(f"[run A] snapshot: {len(snap_a)} feature_ic_scores rows")

    print(f"[run B] fingerprint-skip path (no --refresh): symbols={symbols} tf={tfs}")
    t0 = time.monotonic()
    _run_ic_engine(symbols, tfs, training_window_end, refresh=False)
    print(f"[run B] complete in {time.monotonic() - t0:.1f}s")
    snap_b = await _fetch_snapshot(pool, symbols, tfs, training_window_end)
    print(f"[run B] snapshot: {len(snap_b)} feature_ic_scores rows")

    diff = _diff_snapshots(snap_a, snap_b)

    if diff.ok:
        print(
            f"PASS: {len(snap_a)} rows identical (full value set incl bh_adjusted_p/passes_fdr) "
            "AND run B genuinely skipped (computed_at unchanged on every row) -- the fingerprint "
            "captures everything that determines a cell's IC."
        )
        if owns_all_rows and not keep_test_data:
            await _cleanup_owned_rows(pool, tfs, training_window_end)
            print("Test rows cleaned up (this run owned them).")
        return 0

    print(
        "FAIL: divergence found between run A (--refresh) and run B (fingerprint-skip).",
        file=sys.stderr,
    )
    if diff.missing_keys:
        print(
            f"  Missing in run B ({len(diff.missing_keys)} keys): {diff.missing_keys}",
            file=sys.stderr,
        )
    if diff.extra_keys:
        print(f"  Extra in run B ({len(diff.extra_keys)} keys): {diff.extra_keys}", file=sys.stderr)
    if diff.value_divergences:
        print(f"  Value divergences ({len(diff.value_divergences)}):", file=sys.stderr)
        for line in diff.value_divergences:
            print(f"    {line}", file=sys.stderr)
    if diff.skip_not_occurred:
        print(
            f"  Skip did NOT occur ({len(diff.skip_not_occurred)} rows recomputed):",
            file=sys.stderr,
        )
        for line in diff.skip_not_occurred:
            print(f"    {line}", file=sys.stderr)
    print(
        "Test rows left in place for inspection (no cleanup on failure). Manually clean up "
        f"feature_ic_scores/ic_cell_fingerprints at training_window_end="
        f"{format_iso_ts(training_window_end)} once root-caused.",
        file=sys.stderr,
    )
    return 1


# ---------------------------------------------------------------------------
# Drift study (optional, Task 2) -- IC-at-T vs IC-at-T+lag across the given subset.
# Diagnostic-only output informing whether alpha.ic.refresh_min_new_fraction should ever
# move off its migration-252 disabled seed (0). NOT a pass/fail gate.
# ---------------------------------------------------------------------------


async def _run_drift_study(
    pool: asyncpg.Pool,
    symbols: list[str],
    tfs: list[str],
    training_window_end: datetime,
    lags_days: list[int],
    force: bool,
) -> int:
    """Runs ic_engine.py --refresh at training_window_end and at training_window_end +
    each lag in lags_days, then reports how much ic_value drifts per cell as a function
    of lag. A stratified sample IS the --symbols/--tf subset the operator passed in --
    this study is explicitly informational (its output would justify a future nonzero
    alpha.ic.refresh_min_new_fraction seed), never a gate.

    Same production-data-corruption guard as the equivalence check applies here --
    EVERY window this study touches (baseline + every lag) must be pre-flight-checked
    empty before its own --refresh call, for the identical narrow-subset cross-sectional
    overwrite reason documented on _preflight_check_no_existing_rows.
    """
    all_windows = [training_window_end] + [
        training_window_end + timedelta(days=d) for d in lags_days
    ]
    for window in all_windows:
        await _preflight_check_no_existing_rows(pool, symbols, tfs, window, force)

    print(f"[drift-study] baseline T={format_iso_ts(training_window_end)}")
    _run_ic_engine(symbols, tfs, training_window_end, refresh=True)
    baseline = await _fetch_snapshot(pool, symbols, tfs, training_window_end)
    baseline_ic = {key: row["ic_value"] for key, row in baseline.items()}

    print(f"{'lag_days':>10}  {'n_cells':>8}  {'mean_abs_drift':>15}  {'max_abs_drift':>15}")
    for lag_days in lags_days:
        lag_window_end = training_window_end + timedelta(days=lag_days)
        _run_ic_engine(symbols, tfs, lag_window_end, refresh=True)
        lag_snapshot = await _fetch_snapshot(pool, symbols, tfs, lag_window_end)

        drifts: list[float] = []
        for key, row in lag_snapshot.items():
            baseline_value = baseline_ic.get(key)
            if baseline_value is None or row["ic_value"] is None:
                continue
            drifts.append(abs(float(row["ic_value"]) - float(baseline_value)))

        if drifts:
            mean_drift = sum(drifts) / len(drifts)
            max_drift = max(drifts)
        else:
            mean_drift = float("nan")
            max_drift = float("nan")
        print(f"{lag_days:>10}  {len(drifts):>8}  {mean_drift:>15.6f}  {max_drift:>15.6f}")

        # Cleanup this lag's throwaway window immediately -- do not accumulate N extra
        # test windows in the corpus across the study.
        await _cleanup_owned_rows(pool, tfs, lag_window_end)

    await _cleanup_owned_rows(pool, tfs, training_window_end)
    print(
        "[drift-study] complete -- diagnostic only, NOT a pass/fail gate. This output is what "
        "would justify a future nonzero alpha.ic.refresh_min_new_fraction seed (migration 252 "
        "currently seeds it 0/disabled)."
    )
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _main_async(args: argparse.Namespace) -> int:
    training_window_end = datetime.fromisoformat(args.training_window_end)
    if training_window_end.tzinfo is None:
        print(
            "FATAL: --training-window-end must be timezone-aware ISO 8601 (UTC).", file=sys.stderr
        )
        return 1
    training_window_end = training_window_end.astimezone(UTC)

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        if args.drift_study:
            return await _run_drift_study(
                pool, args.symbols, args.tf, training_window_end, args.drift_lag_days, args.force
            )
        return await _run_equivalence_check(
            pool, args.symbols, args.tf, training_window_end, args.force, args.keep_test_data
        )
    finally:
        await pool.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="A small (~5-symbol) subset. Required -- this harness never defaults to the full "
        "corpus universe (deliberately narrow scope, see module docstring SAFETY section).",
    )
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    parser.add_argument(
        "--training-window-end",
        required=True,
        help="REQUIRED, ISO 8601 timezone-aware. Use a dedicated, otherwise-unused value -- "
        "see module docstring SAFETY section for why reusing a real corpus window is refused.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Bypass the pre-flight no-existing-rows guard. Only use if you have independently "
        "verified this training_window_end's pre-existing data is safe to narrow-recompute.",
    )
    parser.add_argument(
        "--keep-test-data",
        action="store_true",
        default=False,
        help="Skip auto-cleanup on a PASS (rows are always kept on FAIL, regardless of this flag).",
    )
    parser.add_argument(
        "--drift-study",
        action="store_true",
        default=False,
        help="Run the optional IC-drift-vs-lag diagnostic instead of the equivalence check.",
    )
    parser.add_argument("--drift-lag-days", nargs="+", type=int, default=_DEFAULT_DRIFT_LAGS_DAYS)
    return parser.parse_args()


def main() -> None:
    _refuse_if_ic_engine_running()
    args = _parse_args()
    exit_code = asyncio.run(_main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
