#!/usr/bin/env python3
"""
ops_emission_threshold_sweep.py — EM-CAL empirical emission-threshold calibration
(todo 065, mechanism specified in docs/research/measurement-alpha-emission.md).

Sweeps `alpha.quant.threshold.{tf}` over a candidate grid against the persisted
conviction surface (`ensemble_alpha`), computing net-of-cost mean executable forward
return per emitted event and event count N as a function of threshold, per (tf, regime)
stratum. Selects the threshold maximizing net return per event subject to
`N >= min_events_per_stratum`. Reports whether per-(tf, regime) granularity is earned
(swept optimum differs from the per-TF optimum by more than the estimate's CI) or
whether the per-TF threshold should stand.

**IN-SAMPLE ONLY (bar_ts < alpha.validation.oos_start).** docs/plans/OOS-EVAL-PROTOCOL.md
lists "Threshold tuning" by name among the uses the holdout window must NEVER serve —
this script enforces that as a hard filter, not an option. measurement-alpha-emission.md
originally said "OOS window only" for EM-CAL; that was backwards and corrected 2026-07-14
(see that doc's EM-CAL section). Any post-hoc OOS check of a calibrated threshold goes
through the single authoritative EnsembleICEngine OOS gate (Phase 144) — never this
script, and never more than once per OOS-EVAL-PROTOCOL's cadence rule.

**This is a report, not a promotion tool.** `--commit-to-apr` is intentionally
unimplemented (raises) — no code path in this file writes to config_state. Per todo 065's
2026-07-14 sequencing note: the corpus rebuild in progress at time of writing (Phase
143.1-07) is correcting the exact inputs this sweep reads (ic_sharpe stride-bias,
eligibility sign asymmetry, Fisher-z CI miscalibration) — any threshold this script
computes today is provisional methodology validation, not a candidate for promotion,
until re-run against the corrected corpus.

Mirrors the `ops_ensemble_weight_compare.py` precedent: informational ops-script judgment
harness, always exits 0, promoted to a BaseBatch oneshot only if run cadence ever proves
that's warranted.

Usage:
    python scripts/ops/alpha/ops_emission_threshold_sweep.py --weight-version v1
    python scripts/ops/alpha/ops_emission_threshold_sweep.py --weight-version v1 --tf 5m \
        --thresholds 0.5,0.8,1.0,1.2,1.5,1.8,2.0
"""

from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr
from src.config.settings import Settings
from src.core.service_utils import parse_iso_ts

_KNOWN_TFS = ["5m", "15m", "1h", "1d"]

# EM-CAL's own doc doesn't pin a lookahead horizon; hold_max_bars calibration (todo 088)
# is the more principled per-stratum source once it exists. Defaulting to the nearest
# horizon (fast) as the simplest defensible choice for a first pass -- flagged, not final.
_DEFAULT_LOOKAHEAD = "fast"
_VALID_LOOKAHEADS = ("fast", "mid", "slow", "extended")

# alpha.emission.min_events_per_stratum does not exist in config_state yet (the EM-CAL
# doc calls it out as a new key, [initial_estimate], to be seeded when EM-CAL formally
# lands). Fallback used only for this dry-run harness.
_FALLBACK_MIN_EVENTS_PER_STRATUM = 30

_DEFAULT_THRESHOLD_GRID = (0.4, 0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.2, 2.6, 3.0)

_SWEEP_SQL_TEMPLATE = """
    SELECT
        ea.tf, ea.regime,
        ea.alpha_score, ea.alpha_ci_lower, ea.alpha_ci_upper, ea.effective_n,
        fr.{return_col} AS forward_return
    FROM ensemble_alpha ea
    JOIN forward_returns fr
      ON fr.symbol = ea.symbol AND fr.tf = ea.tf AND fr.bar_ts = ea.bar_ts
    WHERE ea.weight_version = $1
      AND ea.bar_ts < $2::timestamptz
      AND ea.tf = ANY($3::text[])
      AND fr.return_type = 'executable_open_to_open'
      AND fr.{complete_col} = true
      AND fr.{return_col} IS NOT NULL
      AND ea.effective_n IS NOT NULL
"""


@dataclass
class _ThresholdResult:
    threshold: float
    n_events: int
    mean_net_return: float | None
    se_net_return: float | None

    @property
    def _half_width(self) -> float | None:
        if self.mean_net_return is None or self.se_net_return is None:
            return None
        return 1.96 * self.se_net_return

    @property
    def ci_lower(self) -> float | None:
        return None if self._half_width is None else self.mean_net_return - self._half_width

    @property
    def ci_upper(self) -> float | None:
        return None if self._half_width is None else self.mean_net_return + self._half_width


def _passes_gate(
    alpha_score: float,
    ci_lower: float | None,
    ci_upper: float | None,
    effective_n: float,
    threshold: float,
    cost_hurdle: float,
    effective_n_gate: float,
) -> bool:
    """Pure helper: mirrors AlphaPublisher's four-gate stack (effective_n, abs
    threshold, direction-aware CI + cost hurdle) minus the top_features-nonempty gate,
    which has no bearing on whether a bar WOULD have emitted -- it only depends on
    whether ensemble_weights had rows cached for that stratum at publish time, not on
    anything this sweep varies.
    """
    if effective_n < effective_n_gate:
        return False
    if abs(alpha_score) <= threshold:
        return False
    if alpha_score > 0:
        return ci_lower is not None and ci_lower > cost_hurdle
    return ci_upper is not None and ci_upper < -cost_hurdle


def _net_return_for_event(alpha_score: float, forward_return: float, cost_hurdle: float) -> float:
    """Net-of-cost executable forward return in the direction the event would trade,
    minus the cost hurdle already expressed in return units (same convention as
    AlphaPublisher's CI gate)."""
    direction_sign = 1.0 if alpha_score > 0 else -1.0
    return direction_sign * forward_return - cost_hurdle


def _sweep_stratum(
    rows: list[dict],
    thresholds: tuple[float, ...],
    cost_hurdle: float,
    effective_n_gate: float,
) -> list[_ThresholdResult]:
    """Pure helper: compute N and net-of-cost mean return per threshold for one
    (tf, regime) stratum's already-filtered row set."""
    results = []
    for threshold in thresholds:
        net_returns = [
            _net_return_for_event(r["alpha_score"], r["forward_return"], cost_hurdle)
            for r in rows
            if _passes_gate(
                r["alpha_score"],
                r["alpha_ci_lower"],
                r["alpha_ci_upper"],
                r["effective_n"],
                threshold,
                cost_hurdle,
                effective_n_gate,
            )
        ]
        n = len(net_returns)
        if n == 0:
            results.append(_ThresholdResult(threshold, 0, None, None))
            continue
        mean_r = statistics.fmean(net_returns)
        se_r = statistics.stdev(net_returns) / (n**0.5) if n > 1 else None
        results.append(_ThresholdResult(threshold, n, mean_r, se_r))
    return results


def _select_optimal(results: list[_ThresholdResult], min_events: int) -> _ThresholdResult | None:
    """Pure helper: argmax net return per event among thresholds clearing the N floor.
    None if no threshold in the grid clears the floor for this stratum."""
    eligible = [r for r in results if r.n_events >= min_events and r.mean_net_return is not None]
    if not eligible:
        return None
    return max(eligible, key=lambda r: r.mean_net_return)


def _granularity_earned(
    regime_optimal: _ThresholdResult, tf_optimal_ci: tuple[float, float]
) -> bool:
    """Pure helper: per-regime threshold is admitted only if its optimal net return's
    CI does not overlap the per-TF optimal's CI (evaluated on the same pooled-TF
    estimate) -- a real, not noise-level, difference."""
    if regime_optimal.ci_lower is None or regime_optimal.ci_upper is None:
        return False
    tf_lower, tf_upper = tf_optimal_ci
    return regime_optimal.ci_lower > tf_upper or regime_optimal.ci_upper < tf_lower


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="EM-CAL empirical emission-threshold sweep (todo 065) -- report only"
    )
    parser.add_argument("--weight-version", required=True)
    parser.add_argument("--tf", default=None, choices=_KNOWN_TFS, help="Restrict to one timeframe")
    parser.add_argument(
        "--lookahead",
        default=_DEFAULT_LOOKAHEAD,
        choices=_VALID_LOOKAHEADS,
        help=f"forward_returns horizon column (return_<lookahead>); default {_DEFAULT_LOOKAHEAD}",
    )
    parser.add_argument(
        "--thresholds",
        default=",".join(str(t) for t in _DEFAULT_THRESHOLD_GRID),
        help="Comma-separated threshold grid to sweep",
    )
    parser.add_argument(
        "--min-events-per-stratum",
        type=int,
        default=_FALLBACK_MIN_EVENTS_PER_STRATUM,
        help=(
            "N floor below which a stratum keeps its per-TF parent threshold. "
            "alpha.emission.min_events_per_stratum is not yet an APR key -- this CLI "
            f"default ({_FALLBACK_MIN_EVENTS_PER_STRATUM}) is a placeholder, not a "
            "calibrated value."
        ),
    )
    parser.add_argument(
        "--commit-to-apr",
        action="store_true",
        help="Not implemented -- this script is report-only until re-run against a corrected corpus.",
    )
    args = parser.parse_args()

    if args.commit_to_apr:
        print(
            "REFUSED: --commit-to-apr is intentionally unimplemented. This sweep's "
            "current inputs (feature_ic_scores / alpha_ensemble_ic) predate the "
            "Phase 143.1-07 corpus-integrity fixes (ic_sharpe stride bias, eligibility "
            "sign asymmetry, Fisher-z CI). Re-run after that corpus lands before any "
            "threshold from this script is considered for promotion."
        )
        return 1

    thresholds = tuple(float(t) for t in args.thresholds.split(","))
    tfs = [args.tf] if args.tf else _KNOWN_TFS
    return_col = f"return_{args.lookahead}"
    complete_col = f"complete_{args.lookahead}"

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            apr = await _load_apr(conn)

            oos_start_raw = apr.get("alpha.validation.oos_start")
            if not oos_start_raw:
                print(
                    "FAILED: alpha.validation.oos_start missing from config_state -- "
                    "cannot enforce the in-sample-only filter without it. Refusing to "
                    "run rather than silently falling back to the full corpus "
                    "(see OOS-EVAL-PROTOCOL.md's degradation rules)."
                )
                return 1
            # apr dict values are raw config_state strings; asyncpg needs a real
            # datetime for a timestamptz bind param, not the ISO string itself.
            oos_start = parse_iso_ts(oos_start_raw)

            effective_n_gate = _cfg(apr, "alpha.ensemble.effective_n_gate", 3.0)
            cost_hurdles = {tf: _cfg(apr, f"alpha.quant.cost_hurdle.{tf}", 0.0) for tf in tfs}

            print("## EM-CAL Emission Threshold Sweep (todo 065) -- PROVISIONAL, in-sample only")
            print()
            print(f"weight_version: {args.weight_version}")
            print(f"lookahead: {args.lookahead} (return_{args.lookahead})")
            print(f"in-sample cutoff (alpha.validation.oos_start): {oos_start}")
            print(f"effective_n_gate: {effective_n_gate}")
            print(
                f"min_events_per_stratum: {args.min_events_per_stratum} (placeholder, not APR-seeded)"
            )
            print(f"threshold grid: {list(thresholds)}")
            print()

            sql = _SWEEP_SQL_TEMPLATE.format(return_col=return_col, complete_col=complete_col)
            rows = await conn.fetch(sql, args.weight_version, oos_start, tfs)
            rows_by_tf: dict[str, list[dict]] = {tf: [] for tf in tfs}
            for row in rows:
                rows_by_tf[row["tf"]].append(row)

            for tf in tfs:
                rows_for_tf = rows_by_tf[tf]

                if not rows_for_tf:
                    print(f"### {tf}: no in-sample rows -- skipping")
                    print()
                    continue

                tf_results = _sweep_stratum(
                    rows_for_tf, thresholds, cost_hurdles[tf], effective_n_gate
                )
                tf_optimal = _select_optimal(tf_results, args.min_events_per_stratum)

                print(f"### {tf} (cost_hurdle={cost_hurdles[tf]}, pooled across regimes)")
                print()
                print(f"seed threshold (alpha.quant.threshold.{tf}): see config_state")
                print()
                print("| threshold | N | mean_net_return | CI |")
                print("|---|---|---|---|")
                for r in tf_results:
                    ci_str = (
                        f"[{r.ci_lower:.5f}, {r.ci_upper:.5f}]" if r.ci_lower is not None else "n/a"
                    )
                    mean_str = (
                        f"{r.mean_net_return:.5f}" if r.mean_net_return is not None else "n/a"
                    )
                    marker = (
                        " <- optimal"
                        if tf_optimal is not None and r.threshold == tf_optimal.threshold
                        else ""
                    )
                    print(f"| {r.threshold} | {r.n_events} | {mean_str} | {ci_str}{marker} |")
                print()

                if tf_optimal is None:
                    print(
                        f"No threshold in the grid clears N >= {args.min_events_per_stratum} for {tf} pooled."
                    )
                    print()
                    continue

                rows_by_regime: dict[str, list[dict]] = {}
                for row in rows_for_tf:
                    if row["regime"]:
                        rows_by_regime.setdefault(row["regime"], []).append(row)

                if rows_by_regime:
                    print(f"Per-regime granularity check ({tf}):")
                    print()
                    print(
                        "| regime | optimal_threshold | N | mean_net_return | granularity_earned |"
                    )
                    print("|---|---|---|---|---|")
                    for regime, regime_rows in sorted(rows_by_regime.items()):
                        regime_results = _sweep_stratum(
                            regime_rows, thresholds, cost_hurdles[tf], effective_n_gate
                        )
                        regime_optimal = _select_optimal(
                            regime_results, args.min_events_per_stratum
                        )
                        if regime_optimal is None:
                            print(
                                f"| {regime} | n/a | - | - | NO (N floor not cleared, "
                                f"per-TF threshold stands) |"
                            )
                            continue
                        earned = _granularity_earned(
                            regime_optimal, (tf_optimal.ci_lower or 0.0, tf_optimal.ci_upper or 0.0)
                        )
                        print(
                            f"| {regime} | {regime_optimal.threshold} | {regime_optimal.n_events} | "
                            f"{regime_optimal.mean_net_return:.5f} | {'YES' if earned else 'NO'} |"
                        )
                    print()

        print("---")
        print(
            "Falsification check: if the sweep surface above is flat (mean_net_return "
            "insensitive to threshold, within CI, across the whole grid) for every "
            "stratum, EM-CAL is falsified per docs/research/measurement-alpha-emission.md "
            "-- the seed thresholds stand and this script retires to a one-time-audit "
            "artifact rather than an ongoing calibration tool."
        )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
