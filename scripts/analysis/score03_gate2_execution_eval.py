"""SCORE-03: OOS Gate 2 (execution proof) scorer -- does the frame simulation capture

signal as real P&L out-of-sample? Champion-only (weight_epoch='143.1-08-champion'), no
challenger comparison (that decision was 143.1-08's, not this gate's -- D-06).

Per D-08 this script's single written row also satisfies FRAME-04 (Phase 142B's own
frame-quality gate) -- it is NOT a second, separate gate. Do not create a second
FRAME-04-labeled row anywhere.

Structurally a slimmed, persistence-adding version of phase143_1_08_shadow_validation.py's
evaluate_epoch: champion-only, minus the challenger/criterion-6 non-regression logic, plus
an atomic gate_evaluations INSERT.

Per D-06 the champion's already-computed 143.1-08 pooled/regime-stratified numbers are
ADOPTED (cited), not re-derived from a different population -- see provenance field in the
assembled evidence and 143.1-08-SHADOW-VALIDATION.md sections 6 (pooled) and 7
(regime-stratified).

Per D-07 the pooled verdict is NEVER reported alone: every run also computes and carries the
regime-stratified companion breakdown (evaluate_frame_gate grouped by (direction, regime)),
in the same evidence payload.

RUN AT MOST ONCE per milestone gate (OOS-EVAL-PROTOCOL.md's frozen "run once" cadence rule,
D-04) -- the real (non-dry-run) write path atomically re-checks no prior row exists before
inserting. Use --dry-run for development-time verification: full computation, printed
would-be verdict, ZERO writes to gate_evaluations, ZERO look-log append.

A statistical FAIL is not an error -- it is an expected, normal result='fail' row (the
champion's pooled numbers are already known, going in, to fail 3 of 5 SHADOW-REVIEW
criteria -- D-06). Exceptions are reserved for genuine system faults: DB unreachable,
alpha.validation.oos_start unset, or an attempted second run of this one-shot gate.

Usage:
    .venv/bin/python scripts/analysis/score03_gate2_execution_eval.py --dry-run
    .venv/bin/python scripts/analysis/score03_gate2_execution_eval.py   # real, one-shot only
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Reused verbatim (WR-03 frozen edge cases) -- do NOT rederive. See module docstring.
from scripts.analysis.phase143_1_08_shadow_validation import (  # noqa: E402
    _annualized_sharpe,
    _max_drawdown,
)
from services._batch_utils import cfg as _cfg  # noqa: E402
from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import format_iso_ts  # noqa: E402

_CHAMPION_WEIGHT_EPOCH = "143.1-08-champion"

# Single write target's gate_id -- see module docstring for the D-08 same-gate note.
_GATE_ID = "gate2_execution"

_DEFAULT_LOOK_LOG_PATH = ".planning/gate_look_log.jsonl"

# bar_ts >= $2 (OOS side, D-02/D-03); frame_variant='primary' (sole variant this phase
# writes); status != 'open' (closed frames only -- an open frame has no
# counterfactual_pnl_r to gate on). bar_ts::date is the per-frame calendar-day cluster_id.
# This population has ~22-way bar_ts ties (33,892 rows across only 1,534 distinct bar_ts --
# multiple symbols' frames opened at the exact same 5-minute bar, i.e. genuinely SIMULTANEOUS
# positions, not sequential ones). A row-level ORDER BY tie-break (e.g. by frame_id) would
# pick an arbitrary but valid ordering for those ties -- but for a path-dependent statistic
# like the cumulative-equity max-drawdown walk, treating simultaneous positions as sequential
# is not economically meaningful at all, regardless of which arbitrary order is chosen. The
# correct fix lives in _aggregate_pnl_by_bar_ts below: aggregate (SUM) pnl_r per distinct
# bar_ts BEFORE the cumulative walk, so each timestamp contributes exactly one
# (already-order-independent) value. That eliminates the tie-break question structurally --
# plain `ORDER BY bar_ts ASC` is sufficient here since the real ordering work happens in
# Python via an explicit sort over the aggregated (one-row-per-bar_ts) series.
_OOS_QUERY_SQL = """
    SELECT bar_ts, direction, regime, bar_ts::date AS cluster_id, counterfactual_pnl_r AS pnl_r
    FROM alpha_frames
    WHERE weight_epoch = $1
      AND frame_variant = 'primary'
      AND status != 'open'
      AND bar_ts >= $2
      AND counterfactual_pnl_r IS NOT NULL
    ORDER BY bar_ts ASC
"""

_C5_PROXY_NOTE = (
    "Criterion 5 (last_20d_IC_Sharpe / full_period_IC_Sharpe >= 0.5) is N/A on this "
    "champion population -- no recurring ensemble_ic_engine cadence exists to form a "
    "trailing-vs-full-period split (same reason phase143_1_08_shadow_validation.py's "
    "docstring documents). c7_confident_loss (short-side confident-loss tail: fails iff "
    "n_short>0 and short-side bootstrap CI upper < 0) is adopted as its documented "
    "operational PROXY and is explicitly labeled as such here -- not silently dropped, "
    "not silently substituted for the literal criterion."
)

_PROVENANCE = (
    "Champion 143.1-08 pooled and regime-stratified numbers adopted verbatim per D-06 -- "
    "see 143.1-08-SHADOW-VALIDATION.md section 6 (pooled) and section 7 "
    "(regime-stratified, todo 165). This evaluation's single written row satisfies both "
    "SCORE-03 and Phase 142B's frame-quality gate per D-08 -- see module docstring."
)


async def _load_apr(conn: asyncpg.Connection) -> tuple[int, int, int, int, int, float, float]:
    """Extends phase143_1_08_shadow_validation.py's _load_apr (lines 71-84): that helper
    already fetches every alpha.scoring.% key into apr_cfg but never extracts the c3/c4
    gate thresholds. Pull those two additional keys from the same fetch rather than
    hardcoding 0.5/0.25 literals at the call site.
    """
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        ["alpha.scoring.%", "alpha.validation.regime_gate_min_clusters"],
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    min_n = _cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30)
    bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    regime_gate_min_clusters = _cfg(apr_cfg, "alpha.validation.regime_gate_min_clusters", 20)
    min_sharpe = float(_cfg(apr_cfg, "alpha.scoring.min_sharpe", 0.5))
    max_drawdown_ratio = float(_cfg(apr_cfg, "alpha.scoring.max_drawdown_ratio", 0.25))
    return (
        min_n,
        bootstrap_max_n,
        bootstrap_batch,
        bootstrap_random_state,
        regime_gate_min_clusters,
        min_sharpe,
        max_drawdown_ratio,
    )


async def _read_oos_start(conn: asyncpg.Connection) -> datetime:
    """Read alpha.validation.oos_start from config_state. Raises (fail-loud) if unset --
    never defaults to MAX(bar_ts) or any other silent fallback."""
    row = await conn.fetchrow(
        "SELECT NULLIF(config_value, '') FROM config_state "
        "WHERE config_key = 'alpha.validation.oos_start'"
    )
    if row is None or row[0] is None:
        raise RuntimeError(
            "alpha.validation.oos_start is unset -- nothing to evaluate. Set it in "
            "config_state before running Gate 2."
        )
    oos_start = row[0]
    if isinstance(oos_start, str):
        oos_start = datetime.fromisoformat(oos_start)
    if oos_start.tzinfo is None:
        oos_start = oos_start.replace(tzinfo=UTC)
    return oos_start.astimezone(UTC)


def _aggregate_pnl_by_bar_ts(rows: list[dict[str, Any]]) -> np.ndarray:
    """SUM counterfactual_pnl_r across all frames sharing the same bar_ts, ordered ascending
    by bar_ts, for feeding a path-dependent (cumulative-equity) statistic.

    Frames sharing an exact bar_ts are genuinely SIMULTANEOUS positions -- multiple symbols'
    frames opened at the same 5-minute bar, not a sequence of trades one after another. A
    real portfolio holding N concurrent positions experiences their combined P&L
    simultaneously at that instant. Running a row-by-row cumulative sum over any per-frame
    ordering (including an arbitrary-but-valid tie-break) would treat those simultaneous
    positions as sequential, which is not economically meaningful. Aggregating to one summed
    value per distinct bar_ts BEFORE the cumulative walk fixes this structurally: SUM is
    order-independent, and after aggregation there is exactly one row per bar_ts, so ordering
    ascending by bar_ts is unambiguous and the resulting drawdown walk is fully deterministic.
    """
    by_bar_ts: dict[Any, float] = {}
    for row in rows:
        by_bar_ts[row["bar_ts"]] = by_bar_ts.get(row["bar_ts"], 0.0) + row["pnl_r"]
    return np.array([by_bar_ts[bt] for bt in sorted(by_bar_ts)], dtype=float)


def _compute_pooled_criteria(
    rows: list[dict[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    min_sharpe: float,
    max_drawdown_ratio: float,
) -> tuple[dict[str, Any], int]:
    """The pooled c1-c5 SHADOW-REVIEW criteria. Returns (pooled_dict, n_days)."""
    n_days = len({r["cluster_id"] for r in rows})
    pnl_r = [r["pnl_r"] for r in rows]
    cluster_ids = [r["cluster_id"] for r in rows]
    bar_ts = [r["bar_ts"] for r in rows]

    if rows:
        c2_passes, ci_lower, ci_upper = frame_gate_passes(
            pnl_r, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
        )
    else:
        c2_passes, ci_lower, ci_upper = False, None, None

    sharpe = _annualized_sharpe(pnl_r, bar_ts) if pnl_r else None
    # Aggregate simultaneous same-bar_ts frames (SUM) before the cumulative-equity walk --
    # see _aggregate_pnl_by_bar_ts docstring. Order-independent by construction; no tie-break
    # needed for this path-dependent statistic to be deterministic and economically meaningful.
    dd, _ = _max_drawdown(_aggregate_pnl_by_bar_ts(rows)) if rows else (None, True)

    # c3/c4 verdicts recomputed here from the APR-driven thresholds at the call site --
    # never reuse _max_drawdown's baked-in fail flag, and never hardcode the Sharpe bar.
    c3_passes = sharpe is not None and sharpe > min_sharpe
    c4_passes = dd is not None and dd < max_drawdown_ratio

    short_rows = [r for r in rows if r["direction"] == "short"]
    n_short = len(short_rows)
    short_ci_upper = float("nan")
    if n_short >= 2:
        _, _short_ci_lower, short_ci_upper = frame_gate_passes(
            [r["pnl_r"] for r in short_rows],
            [r["cluster_id"] for r in short_rows],
            1,  # no min_n floor for this informational short-side tail check
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
    c5_confident_loss = n_short > 0 and not np.isnan(short_ci_upper) and short_ci_upper < 0
    c5_passes = not c5_confident_loss

    pooled = {
        "c1_min_60_days": n_days >= 60,
        "c2_ci_lower": ci_lower,
        "c2_ci_upper": ci_upper,
        "c2_passes": c2_passes,
        "c3_sharpe": sharpe,
        "c3_passes": c3_passes,
        "c3_min_sharpe_threshold": min_sharpe,
        "c4_max_dd": dd,
        "c4_passes": c4_passes,
        "c4_max_drawdown_ratio_threshold": max_drawdown_ratio,
        "c5_confident_loss": c5_confident_loss,
        "c5_passes": c5_passes,
        "c5_proxy_note": _C5_PROXY_NOTE,
    }
    return pooled, n_days


def _compute_regime_companion(
    rows: list[dict[str, Any]],
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    regime_gate_min_clusters: int,
) -> tuple[list[dict[str, Any]], bool | None, bool]:
    """Mandatory regime-stratified companion (D-07) -- verified 2-tuple group_key round-trip
    (STEP 0): the helper's returned dict remaps dim_a -> "tf", dim_b -> "regime", so
    direction is read back from cell["tf"] and regime from cell["regime"]."""
    regime_cells = evaluate_frame_gate(
        rows,
        min_n=1,  # frame-count floor not meaningful per-cell; min_clusters is the real floor
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        group_key=lambda row: (row["direction"], row["regime"]),
        min_clusters=regime_gate_min_clusters,
    )
    evaluated_cells = [c for c in regime_cells if c["coverage"] == "evaluated"]
    c2_regime_stratified_passes = (
        all(c["passes"] for c in evaluated_cells) if evaluated_cells else None
    )
    c7_regime_stratified_no_confident_loss = not any(
        c["ci_upper"] is not None and not np.isnan(c["ci_upper"]) and c["ci_upper"] < 0
        for c in evaluated_cells
    )
    return regime_cells, c2_regime_stratified_passes, c7_regime_stratified_no_confident_loss


def _build_snapshot(
    oos_start: datetime,
    weight_epoch: str,
    apr_values_used: dict[str, Any],
    input_population_row_count: int,
    fetch_sql_sha256: str,
) -> dict[str, Any]:
    """Pre-run snapshot embedded in both the evidence jsonb and the look-log entry --
    lets a reviewer diagnose drift and safely retry a --dry-run without ambiguity."""
    return {
        "oos_start": format_iso_ts(oos_start),
        "weight_epoch": weight_epoch,
        "apr_values_used": apr_values_used,
        "input_population_row_count": input_population_row_count,
        "fetch_sql_sha256": fetch_sql_sha256,
    }


def assemble_gate2_evidence(
    rows: list[dict[str, Any]],
    weight_epoch: str,
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    min_sharpe: float,
    max_drawdown_ratio: float,
    regime_gate_min_clusters: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Pure evidence-assembly core (no I/O) -- the exact function both --dry-run and the
    real write path call, and the function this plan's unit tests exercise directly on
    synthetic rows. A statistical FAIL is a normal 'result': 'fail' value, never raised."""
    pooled, n_days = _compute_pooled_criteria(
        rows,
        min_n,
        bootstrap_max_n,
        bootstrap_batch,
        bootstrap_random_state,
        min_sharpe,
        max_drawdown_ratio,
    )
    regime_cells, c2_regime_stratified_passes, c7_regime_stratified_no_confident_loss = (
        _compute_regime_companion(
            rows,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            regime_gate_min_clusters,
        )
    )

    result = (
        "pass"
        if all(
            [
                pooled["c1_min_60_days"],
                pooled["c2_passes"],
                pooled["c3_passes"],
                pooled["c4_passes"],
                pooled["c5_passes"],
            ]
        )
        else "fail"
    )

    return {
        "weight_epoch": weight_epoch,
        "n_rows": len(rows),
        "n_days": n_days,
        "pooled": pooled,
        "regime_cells": regime_cells,
        "c2_regime_stratified_passes": c2_regime_stratified_passes,
        "c7_regime_stratified_no_confident_loss": c7_regime_stratified_no_confident_loss,
        "snapshot": snapshot,
        "result": result,
        "provenance": _PROVENANCE,
    }


def _print_verdict(evidence: dict[str, Any], regime_gate_min_clusters: int) -> None:
    """Human-readable report -- never prints the pooled verdict without the regime
    coverage table alongside it (D-07)."""
    print(f"\n=== GATE 2 EXECUTION PROOF ({evidence['weight_epoch']}) ===")
    for key, value in evidence["pooled"].items():
        print(f"  pooled.{key}: {value}")
    print(f"  n_rows: {evidence['n_rows']}  n_days: {evidence['n_days']}")
    print(f"  c2_regime_stratified_passes: {evidence['c2_regime_stratified_passes']}")
    print(
        "  c7_regime_stratified_no_confident_loss: "
        f"{evidence['c7_regime_stratified_no_confident_loss']}"
    )
    print(f"  --- regime coverage (min_clusters={regime_gate_min_clusters}) ---")
    for cell in sorted(evidence["regime_cells"], key=lambda c: (c["tf"], c["regime"])):
        print(
            f"    direction={cell['tf']} regime={cell['regime']} "
            f"n_frames={cell['n_frames']} n_clusters={cell['n_clusters']} "
            f"coverage={cell['coverage']} passes={cell['passes']} "
            f"ci_lower={cell['ci_lower']} ci_upper={cell['ci_upper']}"
        )
    print(f"\n=== RESULT: {evidence['result'].upper()} ===")
    print(f"  provenance: {evidence['provenance']}")


def _append_look_log(look_log_path: Path, run_ts: datetime, evidence: dict[str, Any]) -> None:
    """Append-only look log (matches ops_oos_holdout_eval.py's D-04 auditability pattern) --
    written AFTER commit, never before, and never on the --dry-run path."""
    entry = {
        "run_ts": format_iso_ts(run_ts),
        "result": evidence["result"],
        "snapshot": evidence["snapshot"],
    }
    look_log_path.parent.mkdir(parents=True, exist_ok=True)
    with look_log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _json_safe(obj: Any) -> Any:
    """Recursively replace non-finite floats (inf/-inf/nan) with their conventional string
    representations before JSON serialization.

    Python's json.dumps emits the bare (unquoted) tokens Infinity/-Infinity/NaN for these
    values by default -- valid Python, but NOT valid JSON per RFC 8259, which PostgreSQL's
    jsonb parser correctly rejects (InvalidTextRepresentationError: "Token 'Infinity' is
    invalid"). c2_ci_upper/c7 short-side CI upper bounds legitimately land at +inf for this
    one-sided test (a meaningful "no upper bound", not an error) -- this evidence payload
    always contains such values, so the write path must handle them, not merely tolerate
    them by luck of which numbers happen to be finite on a given run.
    """
    if isinstance(obj, float):
        if obj == float("inf"):
            return "Infinity"
        if obj == float("-inf"):
            return "-Infinity"
        if obj != obj:  # NaN != NaN is the standard finite check
            return "NaN"
        return obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


async def _write_gate2_row(
    pool: asyncpg.Pool, evidence: dict[str, Any], run_ts: datetime, look_log_path: Path
) -> None:
    """Atomic real write: within ONE transaction, re-assert no prior row exists, then
    INSERT -- both in the same transaction (Consensus Concern 2). Look-log append happens
    only AFTER commit."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval(
                "SELECT count(*) FROM gate_evaluations WHERE gate_id = $1", _GATE_ID
            )
            if existing:
                raise RuntimeError(
                    f"'{_GATE_ID}' already has {existing} row(s) in gate_evaluations -- "
                    "run-once cadence (D-04) violated. This gate has already run; do not "
                    "re-run it to check if it passes now."
                )
            await conn.execute(
                "INSERT INTO gate_evaluations (gate_id, result, evidence, run_ts) "
                "VALUES ($1, $2, $3::jsonb, $4)",
                _GATE_ID,
                evidence["result"],
                json.dumps(_json_safe(evidence)),
                run_ts,
            )
    _append_look_log(look_log_path, run_ts, evidence)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "SCORE-03 / Gate 2 (execution proof) OOS scorer. Champion-only, no "
            "challenger. Run AT MOST ONCE per milestone gate -- use --dry-run for "
            "development verification."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Full computation, printed verdict, ZERO writes to gate_evaluations or the "
        "look-log.",
    )
    parser.add_argument("--weight-epoch", default=_CHAMPION_WEIGHT_EPOCH)
    parser.add_argument("--look-log-path", default=_DEFAULT_LOOK_LOG_PATH)
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            (
                min_n,
                bootstrap_max_n,
                bootstrap_batch,
                bootstrap_random_state,
                regime_gate_min_clusters,
                min_sharpe,
                max_drawdown_ratio,
            ) = await _load_apr(conn)
            oos_start = await _read_oos_start(conn)
            rows = [dict(r) for r in await conn.fetch(_OOS_QUERY_SQL, args.weight_epoch, oos_start)]

        run_ts = datetime.now(UTC)
        fetch_sql_sha256 = hashlib.sha256(_OOS_QUERY_SQL.encode("utf-8")).hexdigest()
        apr_values_used = {
            "min_strategy_n": min_n,
            "bootstrap_max_n": bootstrap_max_n,
            "bootstrap_batch": bootstrap_batch,
            "bootstrap_random_state": bootstrap_random_state,
            "regime_gate_min_clusters": regime_gate_min_clusters,
            "min_sharpe": min_sharpe,
            "max_drawdown_ratio": max_drawdown_ratio,
        }
        snapshot = _build_snapshot(
            oos_start, args.weight_epoch, apr_values_used, len(rows), fetch_sql_sha256
        )
        evidence = assemble_gate2_evidence(
            rows,
            args.weight_epoch,
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            min_sharpe,
            max_drawdown_ratio,
            regime_gate_min_clusters,
            snapshot,
        )

        _print_verdict(evidence, regime_gate_min_clusters)

        if args.dry_run:
            print("[DRY-RUN] no rows written, look-log untouched")
            return

        await _write_gate2_row(pool, evidence, run_ts, Path(args.look_log_path))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
