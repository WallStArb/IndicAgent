#!/usr/bin/env python3
"""OOS Holdout Eval — read-only diagnostic IC scorer over the pre-committed holdout window.

Scores feature IC over bars with bar_ts >= alpha.validation.oos_start and compares the
qualifying-feature count against the existing in-sample feature_ic_scores population.
Strictly READ-ONLY: this module issues SELECT statements only -- it never mutates any
corpus table. The only output is a markdown report file.

Per docs/plans/OOS-EVAL-PROTOCOL.md, this harness is DIAGNOSTIC ONLY. It is never a
promotion gate — the authoritative OOS scorer is EnsembleICEngine (Phase 142A/144).

Composes existing machinery rather than reimplementing it:
  - forward_log_return() from services.forward_return_writer -- the canonical executable
    return formula (CLAUDE.md Invariant 1: ln(open[T+N+1] / open[T+1])).
  - _vectorized_ic / _fisher_z_ci / _p_values_from_ic / _nan_to_none from services.ic_engine
    -- the same IC math used for in-sample feature_ic_scores.

Usage:
    python scripts/ops/corpus/ops_oos_holdout_eval.py
    python scripts/ops/corpus/ops_oos_holdout_eval.py --symbols SPY TLT --tf 1h
    python scripts/ops/corpus/ops_oos_holdout_eval.py --report-path docs/analysis/oos-holdout-eval.md
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from scipy.stats import rankdata
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync as _load_config_service
from services.forward_return_writer import forward_log_return
from services.ic_engine import (
    _FEATURE_NAMES,
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)
from src.config.settings import Settings, get_active_contracts
from src.core.service_utils import setup_service_logging
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/oos_holdout_eval.log")

_logger = structlog.get_logger(__name__)

_JOB = "oos-holdout-eval"

_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]
_DEFAULT_REPORT_PATH = "docs/analysis/oos-holdout-eval.md"

# Gradient scale fallback lookaheads (mirrors forward_return_writer._SCALE_FALLBACKS).
_SCALE_FALLBACKS: dict[str, int] = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable, no DB)
# ---------------------------------------------------------------------------


def _oos_mask(bar_ts_arr: np.ndarray, oos_start: datetime) -> np.ndarray:
    """Boolean mask selecting bars with bar_ts >= oos_start.

    Args:
        bar_ts_arr: Array (dtype object or datetime64) of bar timestamps.
        oos_start: The OOS holdout boundary (timezone-aware UTC).

    Returns:
        Boolean array, same length as bar_ts_arr, True where bar_ts >= oos_start.
    """
    if len(bar_ts_arr) == 0:
        return np.array([], dtype=bool)
    return np.array([ts >= oos_start for ts in bar_ts_arr], dtype=bool)


def _count_qualifying(ci_lower_arr: np.ndarray, passes_fdr_arr: np.ndarray) -> int:
    """Count cells qualifying as ic_ci_lower > 0 AND passes_fdr is true.

    NaN ci_lower values never qualify (NaN comparisons are always False).

    Args:
        ci_lower_arr: Array of ic_ci_lower values (may contain NaN).
        passes_fdr_arr: Boolean array of passes_fdr flags, same length.

    Returns:
        Count of cells where ci_lower_arr > 0 AND passes_fdr_arr is True.
    """
    if len(ci_lower_arr) == 0:
        return 0
    qualifies = (ci_lower_arr > 0) & passes_fdr_arr.astype(bool)
    return int(np.sum(qualifies))


# ---------------------------------------------------------------------------
# DB-backed scoring (read-only)
# ---------------------------------------------------------------------------


def _read_oos_start(conn: Any) -> datetime:
    """Read alpha.validation.oos_start from config_state. Raises if unset."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT NULLIF(config_value, '') FROM config_state "
            "WHERE config_key = 'alpha.validation.oos_start'"
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(
            "OOS boundary unset — nothing to evaluate. "
            "Set alpha.validation.oos_start in config_state before running this harness."
        )
    oos_start = row[0]
    if isinstance(oos_start, str):
        oos_start = datetime.fromisoformat(oos_start)
    if oos_start.tzinfo is None:
        oos_start = oos_start.replace(tzinfo=UTC)
    return oos_start.astimezone(UTC)


def _read_oos_rows(
    conn: Any, symbol: str, tf: str, oos_start: datetime
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read feature_vectors + market_data_ohlcv opens for bars in the OOS window.

    Returns (bar_ts_arr, opens_arr, feature_matrix) sorted by bar_ts ascending.
    feature_matrix has shape [n_obs, n_features] (columns ordered by _FEATURE_NAMES).
    READ-ONLY: SELECT only, no writes.
    """
    feature_cols_sql = ", ".join(f"fv.{name}" for name in _FEATURE_NAMES)
    query = f"""
        SELECT fv.bar_ts, m.open, {feature_cols_sql}
        FROM feature_vectors fv
        JOIN market_data_ohlcv m
          ON m.symbol = fv.symbol AND m.timeframe = fv.tf AND m.timestamp = fv.bar_ts
        WHERE fv.symbol = %s AND fv.tf = %s AND fv.bar_ts >= %s
        ORDER BY fv.bar_ts ASC
    """
    with conn.cursor() as cur:
        cur.execute(query, (symbol, tf, oos_start))
        rows = cur.fetchall()

    if not rows:
        return (
            np.array([], dtype=object),
            np.array([], dtype=float),
            np.zeros((0, len(_FEATURE_NAMES))),
        )

    bar_ts_arr = np.array([r[0] for r in rows], dtype=object)
    opens_arr = np.array([r[1] for r in rows], dtype=float)
    feature_matrix = np.array(
        [[np.nan if v is None else float(v) for v in r[2:]] for r in rows], dtype=float
    )
    return bar_ts_arr, opens_arr, feature_matrix


def _score_symbol_tf(
    bar_ts_arr: np.ndarray,
    opens_arr: np.ndarray,
    feature_matrix: np.ndarray,
    lookaheads: dict[str, int],
) -> list[dict[str, Any]]:
    """Compute IC point estimates + p-values for each (feature, lookahead) cell.

    Uses forward_log_return() for the executable-return computation (composition,
    no reimplementation) and _vectorized_ic / _fisher_z_ci / _p_values_from_ic from
    ic_engine for the IC math.
    """
    n_obs = len(bar_ts_arr)
    results: list[dict[str, Any]] = []
    if n_obs < 4:
        return results

    for scale, n_bars in lookaheads.items():
        y = forward_log_return(opens_arr, n_bars)
        valid = ~np.isnan(y)
        n_valid = int(np.sum(valid))
        if n_valid < 4:
            continue

        X_valid = feature_matrix[valid]
        y_valid = y[valid]

        # Degenerate (zero-variance) features skipped, matching ic_engine's guard.
        stds = np.nanstd(X_valid, axis=0)
        nd_mask = stds > 1e-8
        if not np.any(nd_mask):
            continue

        X_nd = X_valid[:, nd_mask]
        # NaN feature values within the valid window: treat as missing via column-wise
        # nan-safe ranking fallback (mean-impute pre-rank) to keep the diagnostic robust.
        col_means = np.nanmean(X_nd, axis=0)
        X_nd_filled = np.where(np.isnan(X_nd), col_means, X_nd)

        ranks_X = rankdata(X_nd_filled, axis=0)
        ranks_y = rankdata(y_valid)
        ic_vec = _vectorized_ic(ranks_X, ranks_y)
        ci_lower, ci_upper = _fisher_z_ci(ic_vec, n_valid)
        p_values = _p_values_from_ic(ic_vec, n_valid)

        feature_names_nd = [name for name, keep in zip(_FEATURE_NAMES, nd_mask) if keep]
        for idx, feature_name in enumerate(feature_names_nd):
            results.append(
                {
                    "feature_name": feature_name,
                    "scale": scale,
                    "lookahead_bars": n_bars,
                    "n_independent": n_valid,
                    "ic_value": _nan_to_none(float(ic_vec[idx])),
                    "ic_ci_lower": _nan_to_none(float(ci_lower[idx])),
                    "ic_ci_upper": _nan_to_none(float(ci_upper[idx])),
                    "p_value": float(p_values[idx]),
                }
            )
    return results


def _apply_corpus_fdr(results: list[dict[str, Any]], fdr_alpha: float) -> None:
    """Apply ONE BH-FDR correction across all OOS cells (mutates results in place)."""
    if not results:
        return
    p_values = [r["p_value"] for r in results]
    reject, p_corrected, _, _ = multipletests(p_values, alpha=fdr_alpha, method="fdr_bh")
    for i, r in enumerate(results):
        r["bh_adjusted_p"] = float(p_corrected[i])
        r["passes_fdr"] = bool(reject[i])


def _read_in_sample_qualifying_count(conn: Any, tf: str) -> int:
    """Query existing feature_ic_scores for the in-sample qualifying-cell count.

    Qualifying definition matches the OOS harness: ic_ci_lower > 0 AND passes_fdr = true.
    READ-ONLY.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM feature_ic_scores "
            "WHERE tf = %s AND ic_ci_lower > 0 AND passes_fdr = true",
            (tf,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _drop_verdict(oos_qualifying: int, in_sample: int, significant_drop_fraction: float) -> str:
    """Classify OOS-vs-in-sample qualifying-cell drop for one TF (diagnostic only)."""
    if in_sample == 0:
        return "no in-sample baseline"
    if oos_qualifying == 0:
        return "SEVERE DROP — possible overfitting"
    if oos_qualifying < in_sample * significant_drop_fraction:
        return "significant drop — investigate"
    return "consistent"


def _write_report(
    report_path: Path,
    oos_start: datetime,
    per_tf_results: dict[str, list[dict[str, Any]]],
    in_sample_counts: dict[str, int],
    fdr_alpha: float,
    significant_drop_fraction: float,
) -> None:
    lines = [
        "# OOS Holdout Evaluation Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"OOS boundary (alpha.validation.oos_start): {oos_start.isoformat()}",
        "",
        "DIAGNOSTIC ONLY — this report is never a promotion gate. See "
        "docs/plans/OOS-EVAL-PROTOCOL.md. The authoritative OOS scorer is "
        "EnsembleICEngine (Phase 142A/144).",
        "",
        "| TF | In-sample qualifying | OOS qualifying | Verdict |",
        "|----|----------------------|-----------------|---------|",
    ]

    for tf, results in per_tf_results.items():
        oos_qualifying = _count_qualifying(
            np.array(
                [r["ic_ci_lower"] if r["ic_ci_lower"] is not None else np.nan for r in results]
            ),
            np.array([r.get("passes_fdr", False) for r in results]),
        )
        in_sample = in_sample_counts.get(tf, 0)
        verdict = _drop_verdict(oos_qualifying, in_sample, significant_drop_fraction)
        lines.append(f"| {tf} | {in_sample} | {oos_qualifying} | {verdict} |")

    lines.append("")
    lines.append(f"BH-FDR alpha: {fdr_alpha}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only OOS holdout IC scorer — diagnostic only, never a promotion gate."
    )
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    parser.add_argument("--report-path", default=_DEFAULT_REPORT_PATH)
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("oos_holdout_eval.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    settings = Settings()
    psycopg2.extras.register_uuid()
    conn = psycopg2.connect(
        settings.database_url,
        options="-c idle_in_transaction_session_timeout=0",
    )
    try:
        cfg = _load_config_service(conn)
        fdr_alpha = float(cfg.get_sync("alpha.ic.fdr_alpha", 0.05))
        significant_drop_fraction = float(
            cfg.get_sync("alpha.validation.oos_significant_drop_fraction", 0.5)
        )
        lookaheads = {
            scale: int(cfg.get_sync(f"alpha.ic.lookahead.{scale}", fb))
            for scale, fb in _SCALE_FALLBACKS.items()
        }

        oos_start = _read_oos_start(conn)
        _logger.info("oos_holdout_eval.oos_start", value=str(oos_start))

        if args.symbols:
            symbols = args.symbols
        else:
            symbols = sorted({inst.symbol for inst in get_active_contracts(settings)})
        tfs: list[str] = args.tf

        _logger.info(
            "oos_holdout_eval.starting",
            symbols_count=len(symbols),
            tfs=tfs,
            oos_start=str(oos_start),
        )

        per_tf_results: dict[str, list[dict[str, Any]]] = {tf: [] for tf in tfs}
        in_sample_counts: dict[str, int] = {}

        for tf in tfs:
            in_sample_counts[tf] = _read_in_sample_qualifying_count(conn, tf)
            for symbol in symbols:
                bar_ts_arr, opens_arr, feature_matrix = _read_oos_rows(conn, symbol, tf, oos_start)
                if len(bar_ts_arr) == 0:
                    continue
                results = _score_symbol_tf(bar_ts_arr, opens_arr, feature_matrix, lookaheads)
                per_tf_results[tf].extend(results)

            _apply_corpus_fdr(per_tf_results[tf], fdr_alpha)

        report_path = Path(args.report_path)
        _write_report(
            report_path,
            oos_start,
            per_tf_results,
            in_sample_counts,
            fdr_alpha,
            significant_drop_fraction,
        )

        _logger.info(
            "oos_holdout_eval.complete",
            report_path=str(report_path),
            elapsed_s=round(time.monotonic() - t0, 2),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
