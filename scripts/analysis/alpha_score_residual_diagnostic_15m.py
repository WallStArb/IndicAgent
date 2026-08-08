#!/usr/bin/env python3
"""alpha_score cross-sectional residual -- diagnostic-tier test, pre-registered design:
docs/plans/OOS-EVAL-PROTOCOL.md's "New-construction decision, 2026-08-08" addendum
(todo 278). Required prerequisite before any authoritative Gate 1/Gate 2 look at a
residual-stripping construction.

Mechanism (todo 277's finding): alpha_score is substantially a disguised common
cross-sectional factor (100% same-direction firing at 15m/1h/1d). This tests whether
the RESIDUAL after removing that per-bar common component (mean alpha_score across
symbols at that bar_ts) carries real predictive power the raw score doesn't -- todo
277's own number (ic_residual=0.00453 pooled Pearson) was diagnostic-tier-adjacent but
used none of this project's real statistical machinery. This script does.

Falsification bar (pre-registered here, before running): per-bar_ts cross-sectional
Spearman rank IC (residual vs. forward_returns.return_mid, executable_open_to_open,
across symbols within that bar) must clear a day-clustered bootstrap CI
(gate_math.frame_gate_passes, verbatim -- no new bootstrap implemented) AND beat a
shuffled-ranking null (permute residual-to-symbol assignment within each bar, same
mechanism cross_sectional_relative_value's own original falsification script used).
Both the raw alpha_score and the residual are tested, pooled AND per-regime (BH-FDR
across regime cells) -- deciding to look at only one after seeing the other would be
regime-slicing p-hacking, same discipline as every other pilot this session.

tf=15m only: forward_returns has zero OOS-window (bar_ts >= 2025-12-24) rows at
5m/1h/1d, confirmed directly (not a query bug) -- this is the only tf where this test
is even possible right now.

Read-only diagnostic -- no writes, no config_state changes, exit code always 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import structlog  # noqa: E402
from scipy.stats import rankdata  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.statistics.gate_math import frame_gate_passes  # noqa: E402
from src.intelligence.statistics.ic_math import apply_bh_fdr  # noqa: E402

setup_service_logging("logs/alpha_score_residual_diagnostic_15m.log")
_logger = structlog.get_logger(__name__)

_TF = "15m"
_MIN_SYMBOLS_PER_BAR = 5


def _spearman_ic(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < _MIN_SYMBOLS_PER_BAR or np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return None
    rx = rankdata(x)
    ry = rankdata(y)
    corr = float(np.corrcoef(rx, ry)[0, 1])
    return None if np.isnan(corr) else corr


def _per_bar_ic_series(
    bar_groups: dict[str, list[tuple[float, float]]],
) -> dict[str, float]:
    """(score_or_residual, return_mid) pairs per bar_ts -> {bar_ts: spearman_ic}."""
    result: dict[str, float] = {}
    for bar_ts, pairs in bar_groups.items():
        x = np.array([p[0] for p in pairs], dtype=float)
        y = np.array([p[1] for p in pairs], dtype=float)
        ic = _spearman_ic(x, y)
        if ic is not None:
            result[bar_ts] = ic
    return result


def _shuffled_null_p(
    bar_groups_score: dict[str, list[float]],
    bar_groups_return: dict[str, list[float]],
    observed_mean_ic: float,
    n_shuffles: int,
    rng: np.random.Generator,
) -> float:
    """Permute score-to-symbol assignment WITHIN each bar, n_shuffles times --
    same mechanism cross_sectional_relative_value's original t3 script used.
    Returns P(null mean IC >= observed mean IC), one-sided.
    """
    bar_ts_list = list(bar_groups_score.keys())
    beat_count = 0
    for _ in range(n_shuffles):
        null_ics = []
        for bar_ts in bar_ts_list:
            scores = np.array(bar_groups_score[bar_ts], dtype=float)
            returns = np.array(bar_groups_return[bar_ts], dtype=float)
            if len(scores) < _MIN_SYMBOLS_PER_BAR:
                continue
            shuffled = rng.permutation(scores)
            ic = _spearman_ic(shuffled, returns)
            if ic is not None:
                null_ics.append(ic)
        if null_ics and float(np.mean(null_ics)) >= observed_mean_ic:
            beat_count += 1
    return beat_count / n_shuffles


def _report_cell(
    label: str,
    ic_series: dict[str, float],
    bar_to_regime: dict[str, str] | None,
    regime_filter: str | None,
    bar_groups_score: dict[str, list[float]],
    bar_groups_return: dict[str, list[float]],
    *,
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    n_shuffles: int,
    rng: np.random.Generator,
) -> tuple[str, float | None, float | None]:
    if regime_filter is not None and bar_to_regime is not None:
        bars = [b for b in ic_series if bar_to_regime.get(b) == regime_filter]
    else:
        bars = list(ic_series.keys())

    ic_values = [ic_series[b] for b in bars]
    cluster_ids = [b.split("T")[0] for b in bars]  # calendar date from ISO bar_ts

    if len(ic_values) < min_n:
        print(f"{label}: n_bars={len(ic_values)} < min_n={min_n} -- INSUFFICIENT")
        return label, None, None

    passes, ci_lower, ci_upper = frame_gate_passes(
        ic_values, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )
    mean_ic = float(np.mean(ic_values))

    filtered_score = {b: bar_groups_score[b] for b in bars if b in bar_groups_score}
    filtered_return = {b: bar_groups_return[b] for b in bars if b in bar_groups_return}
    null_p = _shuffled_null_p(filtered_score, filtered_return, mean_ic, n_shuffles, rng)

    verdict = "PASS" if passes else "fail"
    print(
        f"{label}: n_bars={len(ic_values)} mean_ic={mean_ic:.5f} "
        f"ci=[{ci_lower:.5f}, {ci_upper:.5f}] null_p={null_p:.4f} -> {verdict}"
    )
    return label, ci_lower, null_p


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache

    min_n = int(_cfg(apr_dict, "alpha.scoring.min_strategy_n", 30))
    bootstrap_max_n = int(_cfg(apr_dict, "alpha.scoring.bootstrap_max_n", 5000))
    bootstrap_batch = int(_cfg(apr_dict, "alpha.scoring.bootstrap_batch", 1000))
    bootstrap_random_state = int(_cfg(apr_dict, "alpha.scoring.bootstrap_random_state", 42))
    n_shuffles = int(_cfg(apr_dict, "alpha.construction.null_shuffles", 40))
    fdr_alpha = float(_cfg(apr_dict, "alpha.ic.fdr_alpha", 0.05))

    print(f"alpha_score residual diagnostic -- tf={_TF}, OOS window (bar_ts >= 2025-12-24)")
    print(
        f"min_n={min_n} bootstrap_max_n={bootstrap_max_n} n_shuffles={n_shuffles} "
        f"fdr_alpha={fdr_alpha}"
    )

    print("\nFetching alpha_events x forward_returns (executable_open_to_open) ...")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ae.bar_ts, ae.symbol, ae.regime, ae.alpha_score, fr.return_mid
            FROM alpha_events ae
            JOIN forward_returns fr
              ON fr.symbol = ae.symbol AND fr.tf = ae.tf AND fr.bar_ts = ae.bar_ts
             AND fr.return_type = 'executable_open_to_open' AND fr.complete_mid = true
            WHERE ae.tf = %s AND ae.bar_ts >= '2025-12-24'
            ORDER BY ae.bar_ts
            """,
            (_TF,),
        )
        rows = cur.fetchall()
    print(f"  {len(rows)} rows")

    raw_by_bar: dict[str, list[float]] = {}
    return_by_bar: dict[str, list[float]] = {}
    residual_by_bar: dict[str, list[float]] = {}
    bar_regime: dict[str, str] = {}
    bar_scores_tmp: dict[str, list[float]] = {}

    for bar_ts, _symbol, regime, alpha_score, return_mid in rows:
        key = bar_ts.isoformat()
        raw_by_bar.setdefault(key, []).append(float(alpha_score))
        return_by_bar.setdefault(key, []).append(float(return_mid))
        bar_scores_tmp.setdefault(key, []).append(float(alpha_score))
        bar_regime[key] = regime

    for key, scores in bar_scores_tmp.items():
        bar_mean = float(np.mean(scores))
        residual_by_bar[key] = [s - bar_mean for s in scores]

    print(f"  {len(raw_by_bar)} distinct bars with >=1 event")

    raw_ic_series = _per_bar_ic_series(
        {k: list(zip(raw_by_bar[k], return_by_bar[k])) for k in raw_by_bar}
    )
    residual_ic_series = _per_bar_ic_series(
        {k: list(zip(residual_by_bar[k], return_by_bar[k])) for k in residual_by_bar}
    )
    print(
        f"  {len(raw_ic_series)}/{len(raw_by_bar)} bars produced a raw IC "
        f"(>= {_MIN_SYMBOLS_PER_BAR} symbols, non-degenerate)"
    )

    rng = np.random.default_rng(42)
    regimes = sorted({r for r in bar_regime.values() if r is not None})

    print("\n--- RAW alpha_score ---\n")
    _report_cell(
        "RAW POOLED",
        raw_ic_series,
        None,
        None,
        raw_by_bar,
        return_by_bar,
        min_n=min_n,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        n_shuffles=n_shuffles,
        rng=rng,
    )
    raw_regime_results = []
    for regime in regimes:
        raw_regime_results.append(
            _report_cell(
                f"RAW regime={regime}",
                raw_ic_series,
                bar_regime,
                regime,
                raw_by_bar,
                return_by_bar,
                min_n=min_n,
                bootstrap_max_n=bootstrap_max_n,
                bootstrap_batch=bootstrap_batch,
                bootstrap_random_state=bootstrap_random_state,
                n_shuffles=n_shuffles,
                rng=rng,
            )
        )

    print("\n--- RESIDUAL (per-bar common component removed) ---\n")
    _report_cell(
        "RESIDUAL POOLED",
        residual_ic_series,
        None,
        None,
        residual_by_bar,
        return_by_bar,
        min_n=min_n,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        n_shuffles=n_shuffles,
        rng=rng,
    )
    residual_regime_results = []
    for regime in regimes:
        residual_regime_results.append(
            _report_cell(
                f"RESIDUAL regime={regime}",
                residual_ic_series,
                bar_regime,
                regime,
                residual_by_bar,
                return_by_bar,
                min_n=min_n,
                bootstrap_max_n=bootstrap_max_n,
                bootstrap_batch=bootstrap_batch,
                bootstrap_random_state=bootstrap_random_state,
                n_shuffles=n_shuffles,
                rng=rng,
            )
        )

    print(f"\n--- BH-FDR across {len(regimes)} regime cells (RESIDUAL) ---\n")
    resid_p = [p for (_l, _ci, p) in residual_regime_results if p is not None]
    resid_labels = [label for (label, _ci, p) in residual_regime_results if p is not None]
    if resid_p:
        reject, p_corrected = apply_bh_fdr(resid_p, fdr_alpha)
        for label, r, pc in zip(resid_labels, reject, p_corrected):
            print(f"  {label}: null_p_corrected={pc:.4f} passes_fdr={bool(r)}")

    print(
        "\nVerdict rule (pre-registered): RESIDUAL POOLED must clear ci_lower>0 AND "
        "null_p<0.05 to be a live candidate for its own new gate_id. RAW is reported "
        "for comparison only, not part of the verdict (todo 277 already showed it's "
        "near-zero)."
    )
    conn.close()


if __name__ == "__main__":
    main()
