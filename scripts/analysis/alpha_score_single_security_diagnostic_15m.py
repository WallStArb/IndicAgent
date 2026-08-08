#!/usr/bin/env python3
"""alpha_score SINGLE-SECURITY diagnostic -- corrects the prior script's category
error (that one tested cross-sectional ranking, a portfolio/relative-value question,
same shape as cross_sectional_relative_value). This tests the actual question: does
alpha_score predict THAT SYMBOL's own future return, independent of what other
symbols are doing -- no ranking, no cross-sectional comparison, no short leg.

Mirrors Phase 148's own Gate 1 methodology as closely as possible: a per-symbol IC
with a real bootstrap CI (ic_math.py's _circular_block_bootstrap_ic -- the same
production machinery ic_engine.py itself uses, temporal block bootstrap respecting
each symbol's own autocorrelation, not the cross-sectional day-cluster tool used for
the portfolio test), then report what FRACTION of symbols individually clear
ci_lower>0 -- the same "qualifying fraction" shape Gate 1's original 140/640
(21.875%) result used, not a single flat pooled number.

tf=15m only (forward_returns OOS coverage constraint, same as before). Read-only
diagnostic -- no writes, exit code always 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import structlog  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.statistics.ic_math import _circular_block_bootstrap_ic  # noqa: E402

setup_service_logging("logs/alpha_score_single_security_diagnostic_15m.log")
_logger = structlog.get_logger(__name__)

_TF = "15m"
_MIN_BARS_PER_SYMBOL = 100


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache

    block_size = int(_cfg(apr_dict, f"alpha.ic.bootstrap_block_size.{_TF}", 26))
    n_boot = int(_cfg(apr_dict, "alpha.ic.bootstrap_resamples", 2000))

    print(f"alpha_score SINGLE-SECURITY diagnostic -- tf={_TF}, OOS window (bar_ts >= 2025-12-24)")
    print(f"block_size={block_size} n_boot={n_boot} min_bars_per_symbol={_MIN_BARS_PER_SYMBOL}")

    print("\nFetching alpha_events x forward_returns (executable_open_to_open) ...")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ae.symbol, ae.bar_ts, ae.alpha_score, fr.return_mid
            FROM alpha_events ae
            JOIN forward_returns fr
              ON fr.symbol = ae.symbol AND fr.tf = ae.tf AND fr.bar_ts = ae.bar_ts
             AND fr.return_type = 'executable_open_to_open' AND fr.complete_mid = true
            WHERE ae.tf = %s AND ae.bar_ts >= '2025-12-24'
            ORDER BY ae.symbol, ae.bar_ts
            """,
            (_TF,),
        )
        rows = cur.fetchall()
    print(f"  {len(rows)} rows")

    by_symbol: dict[str, list[tuple[float, float]]] = {}
    for symbol, _bar_ts, alpha_score, return_mid in rows:
        by_symbol.setdefault(symbol, []).append((float(alpha_score), float(return_mid)))

    print(f"  {len(by_symbol)} distinct symbols")

    rng = np.random.default_rng(42)
    per_symbol_results: list[tuple[str, int, float, float, float]] = []
    all_scores: list[float] = []
    all_returns: list[float] = []

    for symbol, pairs in sorted(by_symbol.items()):
        n = len(pairs)
        if n < _MIN_BARS_PER_SYMBOL:
            continue
        scores = np.array([p[0] for p in pairs], dtype=float)
        returns = np.array([p[1] for p in pairs], dtype=float)
        all_scores.extend(scores.tolist())
        all_returns.extend(returns.tolist())

        if np.std(scores) < 1e-12 or np.std(returns) < 1e-12:
            continue
        X = scores.reshape(-1, 1)
        ci_lower, ci_upper = _circular_block_bootstrap_ic(X, returns, block_size, n_boot, rng)
        point_ic = float(
            np.corrcoef(np.argsort(np.argsort(scores)), np.argsort(np.argsort(returns)))[0, 1]
        )
        per_symbol_results.append((symbol, n, point_ic, float(ci_lower[0]), float(ci_upper[0])))

    n_qualify = sum(1 for (_s, _n, _ic, lo, _hi) in per_symbol_results if lo > 0.0)
    n_total = len(per_symbol_results)

    print(f"\n--- Per-symbol results ({n_total} symbols with >= {_MIN_BARS_PER_SYMBOL} bars) ---\n")
    for symbol, n, point_ic, ci_lower, ci_upper in sorted(
        per_symbol_results, key=lambda r: r[3], reverse=True
    ):
        verdict = "PASS" if ci_lower > 0.0 else ""
        print(f"  {symbol}: n={n} ic={point_ic:.4f} ci=[{ci_lower:.4f}, {ci_upper:.4f}] {verdict}")

    print(
        f"\nQUALIFYING FRACTION: {n_qualify}/{n_total} ({100.0 * n_qualify / n_total:.1f}%) "
        f"symbols individually clear ci_lower > 0"
    )
    print(
        "(Phase 148's original Gate 1 qualifying bar was a 2% floor across 640 symbol/regime/tf "
        "cells, 140 qualified = 21.875% -- this is a coarser, symbol-only, single-tf cut, not a "
        "like-for-like reproduction, but the same qualifying-fraction shape.)"
    )

    all_scores_arr = np.array(all_scores)
    all_returns_arr = np.array(all_returns)
    pooled_point_ic = float(np.corrcoef(all_scores_arr, all_returns_arr)[0, 1])
    print(
        f"\nPooled-across-all-symbols raw Pearson (all {len(all_scores)} obs, no ranking/"
        f"demeaning, each (symbol,bar) treated as one draw): {pooled_point_ic:.5f}"
    )

    conn.close()


if __name__ == "__main__":
    main()
