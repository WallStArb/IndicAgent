"""Phase 166 fresh validation gate: scores a held-out OOS `alpha_frames` population per
candidate (scalar / structural / baseline) against SHADOW-REVIEW.md's frozen five criteria,
reused UNMODIFIED via `frame_gate_passes`/`evaluate_frame_gate` (OQ3) -- no new thresholds
are invented here. Writes exactly one `gate_evaluations` row per candidate under a NEW
`gate_id` (`gate166_scalar` / `gate166_structural` / `gate166_baseline`), never a second
`gate2_execution` row (D-04).

Structurally a near-verbatim mirror of scripts/analysis/score03_gate2_execution_eval.py --
see that file's module docstring for the shared machinery (frozen five criteria, regime
companion, non-finite-float JSON sanitization, atomic dry-run-then-one-shot write). This
module adds two things score03 does not need: a `--candidate` selector (per-candidate
gate_id, A4) and a `population` disclosure block reporting each candidate's raw OOS frame
footprint (frame_count / eligible_cell_count / per-(regime,tf) cell_frame_counts) so a
smaller/sparser candidate population cannot look artificially favorable without the
disparity being visible (Codex concern 2). Population counts are descriptive-only -- they
never feed the pass/fail bar.

Per D-05 every evaluation also carries a coverage disclosure block noting whether the OOS
population is restricted to 5m/15m timeframes only (todo 173) and/or mid_bull regime only --
disclosed, never gated on.

A statistical FAIL is not an error -- it is an expected, normal result='fail' row. Exceptions
are reserved for genuine system faults: DB unreachable, alpha.validation.oos_start unset, an
unknown --candidate, or an attempted second run of a one-shot gate_id.

This part of the module (Task 1) is the pure evidence-assembly core -- no I/O, no argparse,
no DB. The atomic one-shot write path, dry-run sentinel, and CLI entrypoint are added in a
follow-on commit (Task 2).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Reused verbatim (WR-03 frozen edge cases) -- do NOT rederive. See module docstring.
from scripts.analysis.phase143_1_08_shadow_validation import (  # noqa: E402
    _annualized_sharpe,
    _max_drawdown,
)
from services.counterfactual_tracker import evaluate_frame_gate, frame_gate_passes  # noqa: E402
from src.core.service_utils import format_iso_ts  # noqa: E402

# Per-candidate gate_ids (A4) -- never a re-run of gate2_execution (D-04).
_GATE_IDS: dict[str, str] = {
    "scalar": "gate166_scalar",
    "structural": "gate166_structural",
    "baseline": "gate166_baseline",
}

_C5_PROXY_NOTE = (
    "Criterion 5 (last_20d_IC_Sharpe / full_period_IC_Sharpe >= 0.5) is N/A on this "
    "OOS population -- no recurring ensemble_ic_engine cadence exists to form a "
    "trailing-vs-full-period split (same reason phase143_1_08_shadow_validation.py's "
    "docstring documents, adopted here per OQ3). c7_confident_loss (short-side "
    "confident-loss tail: fails iff n_short>0 and short-side bootstrap CI upper < 0) is "
    "adopted as its documented operational PROXY and is explicitly labeled as such here -- "
    "not silently dropped, not silently substituted for the literal criterion."
)


def _aggregate_pnl_by_bar_ts(rows: list[dict[str, Any]]) -> np.ndarray:
    """SUM counterfactual_pnl_r across all frames sharing the same bar_ts, ordered ascending
    by bar_ts, for feeding a path-dependent (cumulative-equity) statistic.

    Frames sharing an exact bar_ts are genuinely SIMULTANEOUS positions -- multiple symbols'
    frames opened at the same 5-minute bar, not a sequence of trades one after another.
    Aggregating to one summed value per distinct bar_ts BEFORE the cumulative walk fixes this
    structurally: SUM is order-independent, and after aggregation there is exactly one row
    per bar_ts, so ordering ascending by bar_ts is unambiguous and the resulting drawdown
    walk is fully deterministic (todo 172 regression guard).
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
    """The pooled c1-c5 SHADOW-REVIEW criteria, reused verbatim from score03. Returns
    (pooled_dict, n_days)."""
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
    # see _aggregate_pnl_by_bar_ts docstring (todo 172).
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
    """Mandatory regime-stratified companion (D-05/D-07) -- reused verbatim: the helper's
    returned dict remaps dim_a -> "tf", dim_b -> "regime", so direction is read back from
    cell["tf"] and regime from cell["regime"]. Cells below min_clusters are marked
    coverage="insufficient" and excluded from (not counted as failing) the aggregate."""
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


def _compute_population_footprint(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive-only disclosure of a candidate's raw OOS population footprint (Codex
    concern 2): total frame_count, distinct-(regime,tf)-cell eligible_cell_count, and a
    per-(regime,tf) cell_frame_counts map. A smaller/sparser candidate population cannot
    look artificially favorable versus another arm without this disparity being visible.

    NEVER feeds the pass/fail bar -- descriptive disclosure only (OQ3 intact: no new
    thresholds invented from these counts).
    """
    cell_frame_counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['regime']}.{row['tf']}"
        cell_frame_counts[key] = cell_frame_counts.get(key, 0) + 1
    return {
        "frame_count": len(rows),
        "eligible_cell_count": len(cell_frame_counts),
        "cell_frame_counts": cell_frame_counts,
    }


def _build_coverage_disclosure(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Descriptive-only disclosure (never gates) of tf/regime coverage limits: whether the
    OOS population is restricted to 5m/15m timeframes only (todo 173) and/or mid_bull regime
    only (D-05). Disclosed alongside every evaluation, not gated on."""
    observed_tfs = sorted({row["tf"] for row in rows})
    observed_regimes = sorted({row["regime"] for row in rows})
    tf_5m_15m_only = bool(observed_tfs) and set(observed_tfs).issubset({"5m", "15m"})
    regime_mid_bull_only = bool(observed_regimes) and set(observed_regimes) == {"mid_bull"}
    return {
        "observed_tfs": observed_tfs,
        "observed_regimes": observed_regimes,
        "tf_5m_15m_only": tf_5m_15m_only,
        "regime_mid_bull_only": regime_mid_bull_only,
    }


def _build_snapshot(
    oos_start: datetime,
    candidate: str,
    weight_epoch: str,
    apr_values_used: dict[str, Any],
    input_population_row_count: int,
    fetch_sql_sha256: str,
) -> dict[str, Any]:
    """Pre-run snapshot embedded in both the evidence jsonb and the look-log entry -- lets a
    reviewer diagnose drift and safely retry a --dry-run without ambiguity."""
    return {
        "oos_start": format_iso_ts(oos_start),
        "candidate": candidate,
        "weight_epoch": weight_epoch,
        "apr_values_used": apr_values_used,
        "input_population_row_count": input_population_row_count,
        "fetch_sql_sha256": fetch_sql_sha256,
    }


def assemble_gate166_evidence(
    rows: list[dict[str, Any]],
    candidate: str,
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
    synthetic rows. A statistical FAIL is a normal 'result': 'fail' value, never raised.

    Raises ValueError for an unknown candidate (never silently falls back to a gate_id --
    D-04's "never gate2_execution" guarantee is structural, not conventional).
    """
    if candidate not in _GATE_IDS:
        raise ValueError(f"unknown candidate {candidate!r} -- must be one of {sorted(_GATE_IDS)}")
    gate_id = _GATE_IDS[candidate]

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
    population = _compute_population_footprint(rows)
    disclosure = _build_coverage_disclosure(rows)

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
        "candidate": candidate,
        "gate_id": gate_id,
        "n_rows": len(rows),
        "n_days": n_days,
        "pooled": pooled,
        "regime_cells": regime_cells,
        "c2_regime_stratified_passes": c2_regime_stratified_passes,
        "c7_regime_stratified_no_confident_loss": c7_regime_stratified_no_confident_loss,
        "population": population,
        "disclosure": disclosure,
        "snapshot": snapshot,
        "result": result,
    }


def _print_verdict(evidence: dict[str, Any], regime_gate_min_clusters: int) -> None:
    """Human-readable report -- never prints the pooled verdict without the regime
    coverage table and population footprint alongside it (D-05/D-07)."""
    print(f"\n=== GATE166 {evidence['gate_id']} ({evidence['candidate']}) ===")
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
    print("  --- population footprint (Codex concern 2, descriptive only) ---")
    print(
        f"    frame_count={evidence['population']['frame_count']} "
        f"eligible_cell_count={evidence['population']['eligible_cell_count']}"
    )
    for cell_key, count in sorted(evidence["population"]["cell_frame_counts"].items()):
        print(f"    cell {cell_key}: {count} frames")
    print("  --- coverage disclosure (D-05/todo 173, descriptive only) ---")
    print(
        f"    observed_tfs={evidence['disclosure']['observed_tfs']} "
        f"tf_5m_15m_only={evidence['disclosure']['tf_5m_15m_only']}"
    )
    print(
        f"    observed_regimes={evidence['disclosure']['observed_regimes']} "
        f"regime_mid_bull_only={evidence['disclosure']['regime_mid_bull_only']}"
    )
    print(f"\n=== RESULT: {evidence['result'].upper()} ===")


def _json_safe(obj: Any) -> Any:
    """Recursively replace non-finite floats (inf/-inf/nan) with their conventional string
    representations before JSON serialization.

    Python's json.dumps emits the bare (unquoted) tokens Infinity/-Infinity/NaN for these
    values by default -- valid Python, but NOT valid JSON per RFC 8259, which PostgreSQL's
    jsonb parser correctly rejects. c2_ci_upper/c7 short-side CI upper bounds legitimately
    land at +inf for this one-sided test (a meaningful "no upper bound", not an error) --
    this evidence payload always contains such values, so the write path must handle them,
    not merely tolerate them by luck of which numbers happen to be finite on a given run.
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
