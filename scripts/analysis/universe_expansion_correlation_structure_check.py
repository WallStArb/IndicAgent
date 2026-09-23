#!/usr/bin/env python3
"""
universe_expansion_correlation_structure_check.py -- Phase 174 (174-14, D-09/D-10)

Committed, re-runnable version of the ad-hoc analysis that produced
`docs/research/phase174-single-name-book-correlation-structure-2026-09-15.md`. Turns D-10's
two pre-registered pilot-gate thresholds into literal code constants, evaluated by this script,
before any pilot data exists -- the pilot's numbers are only comparable to that baseline if both
are produced by the identical method (same coverage filter, same return definition, same regime
join), which is why this script's acceptance test is reproducing the published baseline table,
not merely resembling it.

Method (must match the baseline document exactly -- do not "fix" any of this):
- Returns are `ln(close[t] / close[t-1])`, close-to-close. This is a DESCRIPTIVE correlation-
  structure characterization, not an IC/alpha measurement -- the `executable_open_to_open`
  return-type invariant that governs `forward_returns`/`ic_engine` (CLAUDE.md's "Executable
  returns only" rule) does NOT apply here and must never be imported into this script.
- Coverage filter: symbols with <95% non-null daily bars over the requested window are dropped
  (see `_MIN_DAILY_COVERAGE` below), logged once as a list, never silently.
- Pairwise correlations via `pandas.DataFrame.corr(min_periods=20)`; reported mean/median are
  over the strict upper triangle only.
- PC variance share via `np.linalg.eigvalsh` on the (NaN-filled) correlation matrix.
- `n_eff = N / (1 + (N - 1) * avg_pairwise_corr)` -- the standard diversification-shrinkage
  formula, not the participation-ratio formula `effective_breadth_diagnostic.py` uses elsewhere
  in this repo; the two are different definitions and are not interchangeable here.
- Regime conditioning: inner-join the daily return dates to `market_regimes`
  (`regime_group='equity'`, `tf='1d'`), recomputing the full statistic set per `regime_label`.

Why the D-10 gate uses RAW correlation, not the SPY-residualized view also computed here: read
directly against the live `services/ic_engine.py` source (not assumed) -- IC is computed via
`rankdata(X, axis=0)` (the two live call sites are `rankdata(X_raw_block[idx], axis=0)` and
`rankdata(X_sub_nd, axis=0)`), which ranks each feature column across every row in the pooled
(tf, regime) cell -- every symbol AND every timestamp together --
and `ic_engine` never cross-sectionally demeans or z-scores per timestamp before this ranking
step. A common market-wide move on a given day is therefore NOT netted out of the pooled rank
correlation that becomes IC: raw co-movement between symbols directly pollutes it. Raw pairwise
correlation is the metric that actually corresponds to what limits ic_engine's realized effective
breadth, so it is the only input `evaluate_d10_gate()` accepts. The SPY-residualized table is
computed and printed for interpretability only (why a cohort is or isn't correlated) and must
never feed the gate.

Exit-code contract:
    0 -- ran successfully, and (under --gate) both D-10 thresholds cleared.
    2 -- ran successfully, but (under --gate) the gate FAILED (a distinct code from both success
         and error, so a caller checking `!= 0` cannot read a failing gate as an infrastructure
         problem, and a caller checking `== 0` cannot read it as a pass).
    1 -- the script itself errored (DB connection failure, unhandled exception, bad arguments).

Usage:
    .venv/bin/python scripts/analysis/universe_expansion_correlation_structure_check.py \\
        --tag single_name_equity --json-out /var/tmp/p174_baseline_repro.json
    .venv/bin/python scripts/analysis/universe_expansion_correlation_structure_check.py \\
        --symbols-file /var/tmp/universe_expansion_stratified_sample_....csv --gate
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402

setup_service_logging("logs/universe_expansion_correlation_structure_check.log")
_logger = structlog.get_logger(__name__)

_JOB_NAME = "universe-expansion-correlation-structure-check"

_TIMEFRAME = "1d"
_SYMBOL_BATCH_SIZE = 25

# Pairwise correlation and residualization both require at least this many overlapping non-null
# observations to fit -- shared constant so the two pure functions can never silently disagree.
_CORR_MIN_PERIODS = 20

# D-10's two pre-registered pilot-gate thresholds (174-CONTEXT.md). Deliberately NOT APR keys
# (not registered in the adaptive parameter config store): the APR mandate exists to stop
# tunable numerics from being frozen into code, but a pre-registered gate threshold is the
# opposite case -- its entire epistemic value
# comes from being immutable after the result is seen, and an APR key is by construction
# adjustable at run time by anyone with a psql prompt. Changing these requires a code edit, a
# commit and a reviewable diff. Per D-10's own wording: "fixed here before any pilot data exists
# -- not adjustable after seeing the result."
_D10_GATE_UNCONDITIONAL_MAX = 0.10
_D10_GATE_HIGH_BEAR_MAX = 0.30

# Coverage-filter threshold fixed by the published baseline document
# (docs/research/phase174-single-name-book-correlation-structure-2026-09-15.md), not a tunable
# knob -- same non-APR reasoning as the D-10 thresholds above: changing it makes the pilot's
# numbers non-comparable to the published baseline, which is the entire point of this gate. A
# methodology constant, not a threshold someone should be able to loosen from a psql prompt.
_MIN_DAILY_COVERAGE = 0.95


# ---------------------------------------------------------------------------
# Pure functions -- no I/O, no logging, no module globals. Unit-tested directly against
# synthetic data with analytically known answers in
# tests/unit/scripts/test_universe_expansion_correlation_structure_check.py.
# ---------------------------------------------------------------------------


def correlation_structure(returns: pd.DataFrame) -> dict[str, Any]:
    """Pairwise correlation, PC variance share and effective-breadth statistics for a
    (dates x symbols) frame of log returns. Pure -- no I/O.

    Returns a dict with n_symbols, n_obs, avg_pairwise_corr, median_pairwise_corr,
    pc1_variance_share, pc1_3_variance_share, n_eff.
    """
    n_symbols = returns.shape[1]
    n_obs = returns.shape[0]

    corr = returns.corr(min_periods=_CORR_MIN_PERIODS)

    upper_mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
    upper_values = corr.to_numpy()[upper_mask]
    upper_values = upper_values[~np.isnan(upper_values)]
    avg_pairwise_corr = float(np.mean(upper_values)) if upper_values.size else float("nan")
    median_pairwise_corr = float(np.median(upper_values)) if upper_values.size else float("nan")

    # PC variance share: fillna(0.0) on the correlation matrix before eigvalsh -- the diagonal
    # is always 1.0 (self-correlation, never NaN), so filling missing off-diagonal entries with
    # 0 ("assume no correlation where unmeasurable") leaves the matrix's trace (= n_symbols, the
    # total variance a correlation matrix's eigenvalues always sum to) unaffected.
    corr_filled = corr.fillna(0.0).to_numpy()
    eigvals = np.linalg.eigvalsh(corr_filled)[::-1]  # descending
    total_variance = float(eigvals.sum())
    if total_variance > 0:
        pc1_variance_share = float(eigvals[0] / total_variance)
        pc1_3_variance_share = float(eigvals[: min(3, len(eigvals))].sum() / total_variance)
    else:
        pc1_variance_share = float("nan")
        pc1_3_variance_share = float("nan")

    if n_symbols > 1 and not np.isnan(avg_pairwise_corr):
        n_eff = float(n_symbols / (1 + (n_symbols - 1) * avg_pairwise_corr))
    else:
        n_eff = float(n_symbols)

    return {
        "n_symbols": n_symbols,
        "n_obs": n_obs,
        "avg_pairwise_corr": avg_pairwise_corr,
        "median_pairwise_corr": median_pairwise_corr,
        "pc1_variance_share": pc1_variance_share,
        "pc1_3_variance_share": pc1_3_variance_share,
        "n_eff": n_eff,
    }


def _gated_corr(
    result: dict[str, Any] | None, leg: str, threshold: float, failed_conditions: list[str]
) -> float | None:
    """Pure. One D-10 leg: append a named failure reason to `failed_conditions` unless the
    leg's avg_pairwise_corr is a finite measurement over >= 2 symbols at or below `threshold`.
    """
    corr = result.get("avg_pairwise_corr") if result is not None else None
    n_symbols = result.get("n_symbols") if result is not None else None
    if corr is None or not math.isfinite(corr):
        failed_conditions.append(
            f"{leg} avg_pairwise_corr missing or non-finite ({corr!r}) -- "
            "fails closed, cannot pass by omission"
        )
    elif n_symbols is not None and n_symbols < 2:
        failed_conditions.append(
            f"{leg} n_symbols={n_symbols} < 2 -- no cross-section measured, fails closed"
        )
    elif corr > threshold:
        failed_conditions.append(
            f"{leg} avg_pairwise_corr={corr:.4f} exceeds threshold={threshold}"
        )
    return corr


def evaluate_d10_gate(
    unconditional: dict[str, Any] | None, high_bear: dict[str, Any] | None
) -> dict[str, Any]:
    """Pure. D-10's pre-registered pass/fail decision over RAW (not residualized) correlation
    results only -- see module docstring's "Why the D-10 gate uses RAW correlation" section.

    Fails closed: a missing result, a missing or non-finite avg_pairwise_corr, or a
    cross-section of fewer than two symbols is a FAIL with a named reason in
    `failed_conditions`, never a pass by omission -- a pilot whose high_bear correlation could
    not be measured has not cleared a gate that requires measuring it. Non-finite matters
    because correlation_structure() returns NaN when no pair clears min_periods, and
    `nan > threshold` is False.

    Threshold reading is "<=": a value exactly at the threshold clears it (D-10's own wording).
    """
    failed_conditions: list[str] = []
    unconditional_corr = _gated_corr(
        unconditional, "unconditional", _D10_GATE_UNCONDITIONAL_MAX, failed_conditions
    )
    high_bear_corr = _gated_corr(high_bear, "high_bear", _D10_GATE_HIGH_BEAR_MAX, failed_conditions)

    return {
        "passed": len(failed_conditions) == 0,
        "unconditional_corr": unconditional_corr,
        "unconditional_threshold": _D10_GATE_UNCONDITIONAL_MAX,
        "high_bear_corr": high_bear_corr,
        "high_bear_threshold": _D10_GATE_HIGH_BEAR_MAX,
        "failed_conditions": failed_conditions,
    }


def residualize_against_factor(
    returns: pd.DataFrame, factor_returns: pd.Series
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Pure. Per-symbol OLS beta regression of each symbol's return column against a single
    factor return series (`r_i = alpha_i + beta_i * factor + e_i`), closed-form single-regressor
    estimator: `beta = cov(factor, r_i) / var(factor)`, `alpha = mean(r_i) - beta * mean(factor)`.

    Returns a (dates x symbols) DataFrame of residuals `e_i`, aligned to `returns`' index and
    columns, plus a dict[str, float] of the fitted per-symbol betas (NaN for skipped symbols).

    Deliberately generic (any factor series) -- this plan only calls it with SPY, but the
    function itself does not encode that choice, so it does not need to change if a different or
    additional factor is chosen later.

    Symbols with fewer than `_CORR_MIN_PERIODS` overlapping non-null observations are skipped
    (residual column left all-NaN, beta recorded as NaN) rather than fit on too little data --
    matches `correlation_structure`'s own min_periods convention.
    """
    factor_aligned = factor_returns.reindex(returns.index)

    residuals = pd.DataFrame(index=returns.index, columns=returns.columns, dtype=float)
    betas: dict[str, float] = {}

    for col in returns.columns:
        pair = pd.concat([returns[col], factor_aligned], axis=1, keys=["r", "f"]).dropna()
        if len(pair) < _CORR_MIN_PERIODS:
            residuals[col] = np.nan
            betas[col] = float("nan")
            continue

        r = pair["r"].to_numpy()
        f = pair["f"].to_numpy()
        f_mean = f.mean()
        r_mean = r.mean()
        var_f = float(np.mean((f - f_mean) ** 2))
        if var_f == 0:
            residuals[col] = np.nan
            betas[col] = float("nan")
            continue
        cov_rf = float(np.mean((r - r_mean) * (f - f_mean)))
        beta = cov_rf / var_f
        alpha = r_mean - beta * f_mean

        betas[col] = float(beta)
        residuals[col] = returns[col] - alpha - beta * factor_aligned

    return residuals, betas


# ---------------------------------------------------------------------------
# I/O shell -- cohort resolution, bar fetch, coverage filter, regime join, table printing.
# ---------------------------------------------------------------------------


def _batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _to_utc_date(ts: Any) -> date:
    if getattr(ts, "tzinfo", None) is None:
        return ts.date()
    return ts.astimezone(UTC).date()


def _resolve_cohort_by_tag(conn: psycopg.Connection, tag: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM instrument_tags WHERE tag = %(tag)s ORDER BY symbol",
            {"tag": tag},
        )
        return [row[0] for row in cur.fetchall()]


def _resolve_cohort_from_file(path: Path) -> list[str]:
    """One symbol per line, or a CSV carrying a `symbol` column -- the shape Plan 08's dry-run
    writes (`symbol,name,index_position_value,cap_bucket,cap_bucket_min,cap_bucket_max`).
    """
    lines = path.read_text().strip().splitlines()
    if not lines:
        return []
    header = lines[0].strip()
    if "," in header or header.lower() == "symbol":
        df = pd.read_csv(path)
        col = "symbol" if "symbol" in df.columns else df.columns[0]
        return [str(s).strip() for s in df[col].tolist() if str(s).strip()]
    return [ln.strip() for ln in lines if ln.strip()]


def _fetch_daily_closes(
    conn: psycopg.Connection, symbols: list[str], start: str, end_exclusive: str
) -> pd.DataFrame:
    """(date x symbol) wide frame of daily closes from market_data_ohlcv_tradeable. Batched
    (25 symbols/query, matching instrument_compute_eligibility_audit.py's convention) via
    `symbol = ANY(%(symbols)s)`, parameterized throughout. Never reads the raw
    `market_data_ohlcv` table (~82% synthetic-fill/flat-carry-forward placeholder bars
    intraday).
    """
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, symbol, close
                FROM market_data_ohlcv_tradeable
                WHERE timeframe = %(timeframe)s AND symbol = ANY(%(symbols)s)
                  AND timestamp >= %(start)s AND timestamp < %(end_exclusive)s
                """,
                {
                    "timeframe": _TIMEFRAME,
                    "symbols": batch,
                    "start": start,
                    "end_exclusive": end_exclusive,
                },
            )
            rows = cur.fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["timestamp", "symbol", "close"]))

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["date"] = df["timestamp"].map(_to_utc_date)
    return df.pivot(index="date", columns="symbol", values="close").sort_index()


def _fetch_regime_map(
    conn: psycopg.Connection, regime_group: str, regime_tf: str, start: str, end_exclusive: str
) -> dict[date, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts, regime_label
            FROM market_regimes
            WHERE regime_group = %(regime_group)s AND tf = %(tf)s
              AND ts >= %(start)s AND ts < %(end_exclusive)s
            """,
            {
                "regime_group": regime_group,
                "tf": regime_tf,
                "start": start,
                "end_exclusive": end_exclusive,
            },
        )
        rows = cur.fetchall()
    return {_to_utc_date(row[0]): row[1] for row in rows}


def _apply_coverage_filter(close_wide: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Drops symbols with <_MIN_DAILY_COVERAGE non-null daily bars over the fetched window,
    denominator = the number of distinct dates ANY cohort symbol has (the union of all fetched
    trading dates), matching the baseline document's method exactly. Dropped symbols are
    returned as a single list -- log ONCE at the call site, never per-symbol.
    """
    n_total_dates = len(close_wide.index)
    if n_total_dates == 0:
        return close_wide, list(close_wide.columns)
    coverage = close_wide.notna().sum() / n_total_dates
    retained = coverage[coverage >= _MIN_DAILY_COVERAGE].index.tolist()
    dropped = sorted(set(close_wide.columns) - set(retained))
    return close_wide[retained], dropped


def _log_returns(close_wide: pd.DataFrame) -> pd.DataFrame:
    return np.log(close_wide).diff().dropna(how="all")


def _regime_conditioned_results(
    returns: pd.DataFrame, regime_map: dict[date, str]
) -> dict[str, dict[str, Any] | None]:
    if not regime_map:
        return {}
    label_by_date = pd.Series(regime_map)
    labels_for_returns = pd.Series(returns.index, index=returns.index).map(label_by_date)
    results: dict[str, dict[str, Any] | None] = {}
    for label in sorted(set(regime_map.values())):
        sub_returns = returns.loc[labels_for_returns == label]
        results[label] = correlation_structure(sub_returns) if not sub_returns.empty else None
    return results


def _print_correlation_table(results: dict[str, dict[str, Any] | None], title: str) -> None:
    print(f"\n{title}")
    header = (
        f"{'Regime':<16}{'N':>6}{'Avg':>10}{'Median':>10}"
        f"{'PC1 share':>12}{'PC1-3 share':>14}{'n_eff':>8}{'n_obs':>8}"
    )
    print(header)
    for label, r in results.items():
        if r is None:
            print(f"{label:<16}{'(no data for this regime -- 0 rows)':>68}")
            continue
        print(
            f"{label:<16}{r['n_symbols']:>6}{r['avg_pairwise_corr']:>10.4f}"
            f"{r['median_pairwise_corr']:>10.4f}{r['pc1_variance_share'] * 100:>11.2f}%"
            f"{r['pc1_3_variance_share'] * 100:>13.2f}%{r['n_eff']:>8.2f}{r['n_obs']:>8}"
        )


def _beta_distribution(betas: dict[str, float]) -> dict[str, float]:
    values = np.array([v for v in betas.values() if not np.isnan(v)], dtype=float)
    if values.size == 0:
        return {
            "mean": float("nan"),
            "median": float("nan"),
            "std": float("nan"),
            "min": float("nan"),
            "max": float("nan"),
        }
    return {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "std": float(values.std()),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 174 D-09/D-10 correlation-structure diagnostic: pairwise correlation, PC "
            "variance share, n_eff, regime-conditioned, plus the D-10 pre-registered pilot gate "
            "and a reported-only SPY-residualized view. Exit codes: 0=pass, 2=gate failed, "
            "1=error."
        ),
        epilog=(
            "Exit-code contract: 0 = ran successfully and, under --gate, both D-10 thresholds "
            "cleared. 2 = ran successfully and the gate FAILED. 1 = the script itself errored. "
            "A failing gate never shares an exit code with success or an infrastructure error."
        ),
    )
    cohort_group = parser.add_mutually_exclusive_group(required=True)
    cohort_group.add_argument("--tag", help="Resolve cohort via instrument_tags.tag = <value>.")
    cohort_group.add_argument("--symbols", help="Comma-separated symbol list.")
    cohort_group.add_argument(
        "--symbols-file", type=Path, help="One symbol per line, or a CSV with a symbol column."
    )
    parser.add_argument("--start", default="2018-01-01", help="Window start (inclusive).")
    parser.add_argument("--end", default="2026-09-02", help="Window end (inclusive).")
    parser.add_argument("--regime-group", default="equity")
    parser.add_argument("--regime-tf", default="1d")
    parser.add_argument("--factor-symbol", default="SPY", help="Market factor for residualization.")
    parser.add_argument("--json-out", type=Path, help="Write the full result structure as JSON.")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Evaluate the D-10 gate and set the process exit code from it (0 pass / 2 fail).",
    )
    args = parser.parse_args(argv)

    status = "success"
    exit_code = 0
    try:
        if args.tag:
            symbols = None  # resolved after DB connect
        elif args.symbols:
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        else:
            symbols = _resolve_cohort_from_file(args.symbols_file)

        settings = Settings()
        conn = psycopg.connect(settings.database_url)
        conn.autocommit = True
        try:
            if args.tag:
                symbols = _resolve_cohort_by_tag(conn, args.tag)
            assert symbols is not None

            end_exclusive = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()

            close_wide = _fetch_daily_closes(conn, symbols, args.start, end_exclusive)
            if close_wide.empty:
                print(
                    "FAILED: no daily bars found for the requested cohort/window.", file=sys.stderr
                )
                status = "failure"
                return 1

            close_filtered, dropped_symbols = _apply_coverage_filter(close_wide)
            _logger.info(
                "universe_expansion_correlation_structure_check.coverage_filter",
                n_population=len(symbols),
                n_retained=close_filtered.shape[1],
                n_dropped=len(dropped_symbols),
                dropped_symbols=dropped_symbols,
            )
            print(
                f"Coverage filter (<{_MIN_DAILY_COVERAGE:.0%} of {len(close_wide.index)} "
                f"distinct dates): dropped {len(dropped_symbols)}/{len(symbols)} symbols: "
                f"{dropped_symbols}"
            )

            returns = _log_returns(close_filtered)
            regime_map = _fetch_regime_map(
                conn, args.regime_group, args.regime_tf, args.start, end_exclusive
            )

            raw_results: dict[str, dict[str, Any] | None] = {
                "unconditional": correlation_structure(returns)
            }
            raw_results.update(_regime_conditioned_results(returns, regime_map))
            _print_correlation_table(raw_results, "RAW pairwise daily-return correlation")

            factor_close = _fetch_daily_closes(
                conn, [args.factor_symbol], args.start, end_exclusive
            )
            factor_returns = _log_returns(factor_close)[args.factor_symbol]
            resid_returns, betas = residualize_against_factor(returns, factor_returns)

            resid_results: dict[str, dict[str, Any] | None] = {
                "unconditional": correlation_structure(resid_returns)
            }
            resid_results.update(_regime_conditioned_results(resid_returns, regime_map))
            _print_correlation_table(
                resid_results,
                f"RESIDUALIZED (vs {args.factor_symbol}, reported only -- does not gate)",
            )

            beta_dist = _beta_distribution(betas)
            print(
                f"\nFitted {args.factor_symbol} beta distribution: mean={beta_dist['mean']:.4f} "
                f"median={beta_dist['median']:.4f} std={beta_dist['std']:.4f} "
                f"min={beta_dist['min']:.4f} max={beta_dist['max']:.4f}"
            )

            gate_result: dict[str, Any] | None = None
            if args.gate:
                gate_result = evaluate_d10_gate(
                    raw_results.get("unconditional"), raw_results.get("high_bear")
                )
                print(f"\nD-10 gate: {'PASSED' if gate_result['passed'] else 'FAILED'}")
                if not gate_result["passed"]:
                    for reason in gate_result["failed_conditions"]:
                        print(f"  - {reason}")
                    status = "gate_failed"
                    exit_code = 2

            if args.json_out:
                payload = {
                    "cohort": {
                        "n_population": len(symbols),
                        "n_retained": close_filtered.shape[1],
                        "dropped_symbols": dropped_symbols,
                        "retained_symbols": sorted(close_filtered.columns.tolist()),
                    },
                    "window": {"start": args.start, "end": args.end},
                    "regimes": raw_results,
                    "residualized_regimes": resid_results,
                    "factor_symbol": args.factor_symbol,
                    "factor_betas": betas,
                    "beta_distribution": beta_dist,
                    "gate": gate_result,
                }
                args.json_out.write_text(json.dumps(payload, indent=2, default=str))

            return exit_code
        finally:
            conn.close()
    except Exception as error:
        status = "failure"
        _logger.error("universe_expansion_correlation_structure_check.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_NAME, "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(_JOB_NAME)
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
