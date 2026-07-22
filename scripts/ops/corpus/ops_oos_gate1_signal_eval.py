#!/usr/bin/env python3
"""OOS Gate 1 (signal proof) scorer -- SCORE-02.

Standalone, one-shot script answering the foundational question this whole measurement
pipeline exists to settle: does alpha_score predict forward returns out-of-sample? Composes
services.ensemble_ic_engine's pure Fisher-z IC methodology and
src.intelligence.statistics.ic_math's shared helpers (NOT the newer bootstrap-based CI
method) onto the OOS half (bar_ts >= alpha.validation.oos_start) of ensemble_alpha -- the
full scored-bar population, not the post-emission execution subset -- so the resulting OOS
numbers stay apples-to-apples with the single existing in-sample alpha_ensemble_ic row.

Standalone rather than a new EnsembleICEngine mode because ensemble_alpha's downstream
in-sample table has no column distinguishing in-sample vs. OOS-scored rows -- writing OOS
results there would create two indistinguishable row populations. This script's verdict +
evidence is written to gate_evaluations only.

RUN-ONCE DISCIPLINE (D-04): this scorer runs AT MOST ONCE for this milestone gate, per
docs/plans/OOS-EVAL-PROTOCOL.md's frozen cadence rule. It is NOT a re-runnable smoke test.
Use --dry-run for any dev-time verification of script correctness; do not re-run the real
(non-dry-run) path "to check if it passes now" after any tweak. The real write path
re-asserts (inside one transaction) that no prior row exists for this gate before inserting,
so a crash mid-run rolls back cleanly and is safely retryable -- but a genuinely completed
prior run is refused, not silently overwritten.

A statistical FAIL or insufficient-N outcome is a NORMAL expected result (writes a
result='fail'/'insufficient' row) -- it is NEVER raised as an exception. Exceptions are
reserved for genuine system faults: unset alpha.validation.oos_start, DB unreachable, a
missing statsmodels dependency (asserted at import time below, so a missing dep fails loud
at load, not mid-run), or a gate that has already run once.

Usage:
    python scripts/ops/corpus/ops_oos_gate1_signal_eval.py --dry-run
    python scripts/ops/corpus/ops_oos_gate1_signal_eval.py --symbols SPY TLT --tf 1h
    python scripts/ops/corpus/ops_oos_gate1_signal_eval.py   # real run -- ONCE, per D-04
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog
from scipy.stats import rankdata

# Explicit top-level import so a missing statsmodels dependency raises loud at module load,
# not mid-run (Antigravity LOW review finding).
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from services.ensemble_ic_engine import _SCALE_RETURN_COLUMNS, compute_walk_forward_stable
from src.config.settings import Settings, get_active_contracts
from src.core.service_utils import format_iso_ts, setup_service_logging
from src.intelligence.statistics.ic_math import (
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)

setup_service_logging("logs/oos_gate1_signal_eval.log")

_logger = structlog.get_logger(__name__)

_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]
_DEFAULT_LOOK_LOG_PATH = ".planning/gate_look_log.jsonl"
_GATE_ID = "gate1_signal"

# Copied from services.ensemble_ic_engine._WORKER_FETCH_SQL verbatim, with the single
# predicate `ea.bar_ts < %s` changed to `ea.bar_ts >= %s` (OOS side, D-02/D-03) and %s
# placeholders converted to asyncpg's $N style (this script is not dispatched through a
# ProcessPoolExecutor -- it is a simpler standalone one-shot, so no psycopg2 worker
# indirection is needed). Table, join shape, and the executable-return filter are
# unchanged: still ensemble_alpha (every scored bar, not the post-emission execution
# subset), still fr.return_type = 'executable_open_to_open', still the market_regimes join.
_GATE1_FETCH_SQL = """
    SELECT ea.alpha_score,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow,
           CASE WHEN fr.return_extended_suspect THEN NULL ELSE fr.return_extended END
               AS return_extended,
           mr.regime_label
    FROM ensemble_alpha ea
    JOIN forward_returns fr
      ON fr.symbol = ea.symbol AND fr.tf = ea.tf AND fr.bar_ts = ea.bar_ts
      AND fr.return_type = 'executable_open_to_open'
    JOIN market_regimes mr
      ON mr.regime_group = 'equity' AND mr.tf = ea.tf AND mr.ts = ea.bar_ts
    WHERE ea.symbol = $1 AND ea.tf = $2 AND ea.weight_version = $3 AND ea.bar_ts >= $4
    ORDER BY ea.bar_ts
"""


# ---------------------------------------------------------------------------
# Fail-loud OOS boundary read (copied near-verbatim from
# scripts/ops/corpus/ops_oos_holdout_eval.py lines 114-130)
# ---------------------------------------------------------------------------


async def _read_oos_start(pool: asyncpg.Pool) -> datetime:
    """Read alpha.validation.oos_start from config_state. Raises if unset/empty.

    Never falls back to MAX(bar_ts) or silently scores the whole corpus -- an unset
    boundary would forge the gate's OOS integrity (T-148-02).
    """
    row = await pool.fetchrow(
        "SELECT NULLIF(config_value, '') FROM config_state "
        "WHERE config_key = 'alpha.validation.oos_start'"
    )
    if row is None or row[0] is None:
        raise RuntimeError(
            "OOS boundary unset -- nothing to evaluate. "
            "Set alpha.validation.oos_start in config_state before running Gate 1."
        )
    oos_start = row[0]
    if isinstance(oos_start, str):
        oos_start = datetime.fromisoformat(oos_start)
    if oos_start.tzinfo is None:
        oos_start = oos_start.replace(tzinfo=UTC)
    return oos_start.astimezone(UTC)


# ---------------------------------------------------------------------------
# DB-backed fetch (read-only)
# ---------------------------------------------------------------------------


async def _fetch_symbol_tf_rows(
    pool: asyncpg.Pool, symbol: str, tf: str, weight_version: str, oos_start: datetime
) -> list[dict[str, Any]]:
    """Fetch one (symbol, tf)'s OOS-side rows (bar_ts >= oos_start). READ-ONLY."""
    rows = await pool.fetch(_GATE1_FETCH_SQL, symbol, tf, weight_version, oos_start)
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pure compute (unit-testable, no DB)
# ---------------------------------------------------------------------------


def _compute_fold_ics(
    x_valid: np.ndarray, y_valid: np.ndarray, walk_forward_folds: int
) -> list[float]:
    """Split already-validated (in bar_ts order) observations into contiguous folds and
    compute one IC per fold, for compute_walk_forward_stable's fold-magnitude-ratio check.
    """
    n = len(x_valid)
    if n < walk_forward_folds * 4:
        return []
    fold_size = n // walk_forward_folds
    fold_ics: list[float] = []
    for i in range(walk_forward_folds):
        start = i * fold_size
        end = n if i == walk_forward_folds - 1 else (i + 1) * fold_size
        if end - start < 4:
            continue
        ranks_x = rankdata(x_valid[start:end]).reshape(-1, 1)
        ranks_y = rankdata(y_valid[start:end])
        fold_ic = float(_vectorized_ic(ranks_x, ranks_y)[0])
        if not np.isnan(fold_ic):
            fold_ics.append(fold_ic)
    return fold_ics


def _compute_symbol_tf_cells(
    rows: list[dict[str, Any]],
    symbol: str,
    tf: str,
    walk_forward_folds: int,
    wf_stability_ratio: float,
    wf_stability_metric: str,
    min_reliable_n: int,
) -> list[dict[str, Any]]:
    """Compute rank-IC + Fisher-z CI + p-value + walk-forward-stability per (symbol, tf,
    scale) cell from one symbol/tf's already-fetched OOS rows. alpha_score is the single
    predictor (no feature-level collinearity clustering needed, matching
    services.ensemble_ic_engine's own single-predictor treatment).
    """
    if not rows:
        return []

    alpha_score = np.array(
        [np.nan if r["alpha_score"] is None else float(r["alpha_score"]) for r in rows],
        dtype=float,
    )
    results: list[dict[str, Any]] = []

    for scale, column in _SCALE_RETURN_COLUMNS.items():
        y = np.array([np.nan if r[column] is None else float(r[column]) for r in rows], dtype=float)
        valid = ~np.isnan(y) & ~np.isnan(alpha_score)
        n_valid = int(np.sum(valid))
        if n_valid < 4:
            continue

        x_valid = alpha_score[valid]
        y_valid = y[valid]

        ranks_x = rankdata(x_valid).reshape(-1, 1)
        ranks_y = rankdata(y_valid)
        ic_vec = _vectorized_ic(ranks_x, ranks_y)
        ci_lower, ci_upper = _fisher_z_ci(ic_vec, n_valid)
        p_values = _p_values_from_ic(ic_vec, n_valid)

        fold_ics = _compute_fold_ics(x_valid, y_valid, walk_forward_folds)
        walk_forward_stable = (
            compute_walk_forward_stable(fold_ics, wf_stability_ratio, wf_stability_metric)
            if fold_ics
            else False
        )

        results.append(
            {
                "symbol": symbol,
                "tf": tf,
                "scale": scale,
                "n_valid": n_valid,
                "ic_value": _nan_to_none(float(ic_vec[0])),
                "ic_ci_lower": _nan_to_none(float(ci_lower[0])),
                "ic_ci_upper": _nan_to_none(float(ci_upper[0])),
                "p_value": float(p_values[0]),
                "reliable": n_valid >= min_reliable_n,
                "walk_forward_stable": walk_forward_stable,
            }
        )
    return results


def _apply_corpus_fdr(results: list[dict[str, Any]], fdr_alpha: float) -> None:
    """Apply ONE BH-FDR correction across every OOS cell (mutates results in place).

    Copied near-verbatim from ops_oos_holdout_eval.py's _apply_corpus_fdr.
    """
    if not results:
        return
    p_values = [r["p_value"] for r in results]
    reject, p_corrected, _, _ = multipletests(p_values, alpha=fdr_alpha, method="fdr_bh")
    for i, r in enumerate(results):
        r["bh_adjusted_p"] = float(p_corrected[i])
        r["passes_fdr"] = bool(reject[i])


def _assemble_verdict(
    cells: list[dict[str, Any]], min_qualifying_fraction: float
) -> dict[str, Any]:
    """Classify Gate 1's overall result: 'pass' | 'fail' | 'insufficient'.

    A statistical FAIL or insufficient-N outcome is a NORMAL expected result value -- never
    raised as an exception. Only genuine system faults (handled elsewhere) raise.
    """
    if not cells:
        return {
            "result": "insufficient",
            "reason": "zero (symbol, tf, scale) cells computed from the OOS population",
            "n_cells": 0,
        }

    reliable_cells = [c for c in cells if c["reliable"]]
    if not reliable_cells:
        return {
            "result": "insufficient",
            "reason": "no cell reached min_reliable_n",
            "n_cells": len(cells),
        }

    qualifying = [
        c
        for c in reliable_cells
        if c.get("passes_fdr") and c["ic_ci_lower"] is not None and c["ic_ci_lower"] > 0
    ]
    qualifying_fraction = len(qualifying) / len(reliable_cells)
    result = "pass" if qualifying_fraction >= min_qualifying_fraction else "fail"
    return {
        "result": result,
        "n_cells": len(cells),
        "n_reliable_cells": len(reliable_cells),
        "n_qualifying": len(qualifying),
        "qualifying_fraction": qualifying_fraction,
        "min_qualifying_fraction": min_qualifying_fraction,
    }


def _build_snapshot(
    oos_start: datetime,
    apr_values_used: dict[str, Any],
    input_population_row_count: int,
    fetch_sql_sha256: str,
) -> dict[str, Any]:
    """Pre-run integrity snapshot (Consensus Concern 2): embedded in BOTH the evidence
    jsonb and the look-log entry, so any later divergence from this baseline is diagnosable.
    """
    return {
        "oos_start": format_iso_ts(oos_start),
        "apr_values_used": apr_values_used,
        "input_population_row_count": input_population_row_count,
        "fetch_sql_sha256": fetch_sql_sha256,
    }


def _assemble_evidence(
    cells: list[dict[str, Any]],
    oos_start: datetime,
    snapshot: dict[str, Any],
    verdict: dict[str, Any],
) -> dict[str, Any]:
    """Full evidence jsonb payload written to gate_evaluations.evidence."""
    return {
        "cells": cells,
        "oos_start": format_iso_ts(oos_start),
        "snapshot": snapshot,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Write path (real run only)
# ---------------------------------------------------------------------------


async def _write_gate_result(
    pool: asyncpg.Pool,
    gate_id: str,
    result: str,
    evidence: dict[str, Any],
    run_ts: datetime,
) -> None:
    """Atomic real write (Consensus Concern 2): re-assert no prior row for this gate_id
    THEN INSERT, both inside ONE transaction, so a crash between the check and the write
    rolls back cleanly and is safely retryable. D-04: this gate runs at most once per
    milestone -- a pre-existing row means it already ran; refuse rather than silently
    accumulate a second verdict.
    """
    async with pool.acquire() as conn, conn.transaction():
        existing = await conn.fetchval(
            "SELECT count(*) FROM gate_evaluations WHERE gate_id = $1", gate_id
        )
        if existing > 0:
            raise RuntimeError(
                f"Gate '{gate_id}' has already run (D-04: run at most once per milestone "
                "gate) -- refusing to write a second verdict row. Use --dry-run to verify "
                "script correctness without consuming the one-shot gate."
            )
        await conn.execute(
            "INSERT INTO gate_evaluations (gate_id, result, evidence, run_ts) "
            "VALUES ($1, $2, $3::jsonb, $4)",
            gate_id,
            result,
            json.dumps(evidence, default=str),
            run_ts,
        )


def _append_gate_look_log(
    look_log_path: Path,
    run_ts: datetime,
    symbols: list[str],
    tfs: list[str],
    snapshot: dict[str, Any],
) -> None:
    """Append one entry to the append-only gate look log (D-04 auditability, mirrors
    ops_oos_holdout_eval.py's _append_look_log). Embeds the pre-run snapshot alongside run
    metadata so any later divergence from this baseline is diagnosable. Only called AFTER
    the real write's transaction commits.
    """
    entry = {
        "run_ts": format_iso_ts(run_ts),
        "gate_id": _GATE_ID,
        "symbols": symbols,
        "tfs": tfs,
        "snapshot": snapshot,
    }
    look_log_path.parent.mkdir(parents=True, exist_ok=True)
    with look_log_path.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# Orchestration (dry-run-aware; independent of argparse so it is directly testable)
# ---------------------------------------------------------------------------


async def _run_gate1(
    pool: asyncpg.Pool,
    symbols: list[str],
    tfs: list[str],
    weight_version: str,
    oos_start: datetime,
    apr_cfg: dict[str, Any],
    dry_run: bool,
    look_log_path: Path,
) -> dict[str, Any]:
    """Fetch -> compute -> verdict -> (dry-run print | atomic write + look-log).

    --dry-run runs the FULL computation and prints the would-be verdict/evidence but
    performs ZERO writes to gate_evaluations and ZERO append to the look-log (Consensus
    Concern 3) -- lets a developer verify script correctness without consuming the one-shot
    gate. Returns the assembled evidence dict either way.
    """
    fdr_alpha = float(_cfg(apr_cfg, "alpha.ic.fdr_alpha", 0.05))
    walk_forward_folds = int(_cfg(apr_cfg, "alpha.ic.walk_forward_folds", 3))
    wf_stability_ratio = float(_cfg(apr_cfg, "alpha.ensemble_ic.wf_stability_ratio", 3.0))
    wf_stability_metric = str(_cfg(apr_cfg, "alpha.ensemble_ic.wf_stability_metric", "ic_ratio"))
    min_reliable_n = int(_cfg(apr_cfg, "alpha.ic.min_reliable_n", 100))
    min_qualifying_fraction = float(
        _cfg(apr_cfg, "alpha.ensemble_ic.min_qualifying_fraction", 0.60)
    )

    fetch_sql_sha256 = hashlib.sha256(_GATE1_FETCH_SQL.encode()).hexdigest()

    all_cells: list[dict[str, Any]] = []
    input_population_row_count = 0
    for tf in tfs:
        for symbol in symbols:
            rows = await _fetch_symbol_tf_rows(pool, symbol, tf, weight_version, oos_start)
            input_population_row_count += len(rows)
            all_cells.extend(
                _compute_symbol_tf_cells(
                    rows,
                    symbol,
                    tf,
                    walk_forward_folds,
                    wf_stability_ratio,
                    wf_stability_metric,
                    min_reliable_n,
                )
            )

    _apply_corpus_fdr(all_cells, fdr_alpha)
    verdict = _assemble_verdict(all_cells, min_qualifying_fraction)

    apr_values_used = {
        "fdr_alpha": fdr_alpha,
        "walk_forward_folds": walk_forward_folds,
        "wf_stability_ratio": wf_stability_ratio,
        "wf_stability_metric": wf_stability_metric,
        "min_reliable_n": min_reliable_n,
        "min_qualifying_fraction": min_qualifying_fraction,
        "weight_version": weight_version,
    }
    snapshot = _build_snapshot(
        oos_start, apr_values_used, input_population_row_count, fetch_sql_sha256
    )
    evidence = _assemble_evidence(all_cells, oos_start, snapshot, verdict)

    if dry_run:
        print("[DRY-RUN] no rows written, look-log untouched")
        print(
            json.dumps(
                {"gate_id": _GATE_ID, "result": verdict["result"], "evidence": evidence},
                indent=2,
                default=str,
            )
        )
        return evidence

    run_ts = datetime.now(UTC)
    await _write_gate_result(pool, _GATE_ID, verdict["result"], evidence, run_ts)
    _append_gate_look_log(look_log_path, run_ts, symbols, tfs, snapshot)
    _logger.info("gate1_signal.write_complete", result=verdict["result"], gate_id=_GATE_ID)
    return evidence


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Standalone OOS Gate 1 (signal proof) scorer. Runs at most once per milestone "
            "gate (D-04) -- use --dry-run for any dev-time verification; do not re-run the "
            "real path to check if it passes."
        )
    )
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Full computation, printed verdict, ZERO writes to gate_evaluations/look-log.",
    )
    parser.add_argument("--look-log-path", default=_DEFAULT_LOOK_LOG_PATH)
    args = parser.parse_args()

    t0 = time.monotonic()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            apr_cfg = await load_apr_dict_async(conn)
        weight_version = str(_cfg(apr_cfg, "alpha.ensemble.weight_version", "v1"))

        oos_start = await _read_oos_start(pool)
        _logger.info("gate1_signal.oos_start", value=str(oos_start))

        if args.symbols:
            symbols = args.symbols
        else:
            symbols = sorted({inst.symbol for inst in get_active_contracts(settings)})
        tfs: list[str] = args.tf

        _logger.info(
            "gate1_signal.starting",
            symbols_count=len(symbols),
            tfs=tfs,
            oos_start=str(oos_start),
            dry_run=args.dry_run,
        )

        await _run_gate1(
            pool=pool,
            symbols=symbols,
            tfs=tfs,
            weight_version=weight_version,
            oos_start=oos_start,
            apr_cfg=apr_cfg,
            dry_run=args.dry_run,
            look_log_path=Path(args.look_log_path),
        )

        _logger.info("gate1_signal.complete", elapsed_s=round(time.monotonic() - t0, 2))
    except Exception as error:  # CLAUDE.md: exception variable name is `error`
        _logger.error("gate1_signal.failed", error=str(error))
        raise
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
