#!/usr/bin/env python3
"""cointegrated_pairs_residual pilot -- Signal-Extraction candidate, pre-registered design:
docs/research/measurement-cointegrated-pairs-residual.md.

Named, economically-linked pairs only -- no correlation scan (avoids the multiple-comparisons
trap a blind screen across all 80 symbols would create):
  EEM/VWO, EFA/EZU, MCHI/FXI, IEF/TLT, GDX/GLD, OIH/XOP

Staged design, run in order, each stage gating the next:
  1. Engle-Granger cointegration screen (daily closes, in-sample) -- reject p >= 0.05
  2. OOS stability check -- re-run Stage 1 on the holdout window alone
  3. Ornstein-Uhlenbeck fit (OLS on discretized AR(1) form) for survivors -- half-life = ln(2)/theta
  4. Falsification bar: day-clustered bootstrap CI on OU z-score vs forward_returns at tf=15m
  5. Cost-hurdle gate, pre-registered before seeing Stage 4's number

Read-only diagnostic -- no writes, no config_state changes, exit code always 0.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import structlog  # noqa: E402
from statsmodels.regression.linear_model import OLS  # noqa: E402
from statsmodels.tools import add_constant  # noqa: E402
from statsmodels.tsa.stattools import coint  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db, _fetch_bars_from_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402

setup_service_logging("logs/cointegrated_pairs_residual_pilot.log")
_logger = structlog.get_logger(__name__)

_PAIRS: list[tuple[str, str]] = [
    ("EEM", "VWO"),
    ("EFA", "EZU"),
    ("MCHI", "FXI"),
    ("IEF", "TLT"),
    ("GDX", "GLD"),
    ("OIH", "XOP"),
]
_TF = "15m"  # turnover/cost-relevant tf for Stage 4, not 1d
_COINT_P_THRESHOLD = 0.05
# Fixed before any result is read (Component 6, rule 3 of todo 005's sibling design --
# same discipline applied here): split date chosen from data availability alone, not tuned.
_DEFAULT_SPLIT_DATE = date(2024, 1, 1)


@dataclass(frozen=True)
class CointResult:
    p_value: float
    passes: bool


def _daily_log_closes(conn, symbol: str) -> tuple[list[date], np.ndarray]:
    bars = _fetch_bars_from_db(conn, symbol, "1d")
    dates = [b["ts"].date() if hasattr(b["ts"], "date") else b["ts"] for b in bars]
    closes = np.log(np.array([b["close"] for b in bars], dtype=float))
    return dates, closes


def _split(
    dates: list[date], values: np.ndarray, split_date: date
) -> tuple[np.ndarray, np.ndarray]:
    idx = np.array([d < split_date for d in dates])
    return values[idx], values[~idx]


def _engle_granger(y0: np.ndarray, y1: np.ndarray) -> CointResult:
    _stat, p_value, _crit = coint(y0, y1, trend="c", autolag="aic")
    return CointResult(p_value=float(p_value), passes=p_value < _COINT_P_THRESHOLD)


def _fit_ou(spread: np.ndarray) -> tuple[float, float, float]:
    """Fit dX_t = theta(mu - X_t)dt + sigma dW_t via OLS on the discretized AR(1) form:
    X_{t+1} - X_t = theta*mu - theta*X_t + eps, i.e. regress diff(X) on X[:-1] with a
    constant. Returns (theta, mu, half_life). theta <= 0 (non-mean-reverting) is reported
    as half_life=inf, not silently clamped to a positive number."""
    x = spread[:-1]
    dx = np.diff(spread)
    design = add_constant(x)
    model = OLS(dx, design).fit()
    const, slope = model.params[0], model.params[1]
    theta = -slope
    if theta <= 0:
        return theta, float("nan"), float("inf")
    mu = const / theta
    half_life = math.log(2) / theta
    return theta, mu, half_life


def _zscore(spread: np.ndarray, mu: float, window: int = 60) -> np.ndarray:
    """Rolling z-score of the spread around its OU-fitted long-run mean mu, using a
    trailing rolling std (causal -- only past values inform each z at time t)."""
    z = np.full(len(spread), np.nan)
    for t in range(window, len(spread)):
        window_vals = spread[t - window : t]
        std = window_vals.std(ddof=1)
        if std > 1e-10:
            z[t] = (spread[t] - mu) / std
    return z


def _circular_block_bootstrap_ic_1d(
    x: np.ndarray, y: np.ndarray, block_size: int, n_boot: int, rng: np.random.Generator
) -> tuple[float, float, float]:
    """Day-clustered bootstrap CI on Spearman IC of x (z-score) vs y (forward return).
    Same circular block-index mechanic as ic_math._circular_block_bootstrap_ic, re-ranking
    every replicate -- reused pattern, not reimplemented from scratch (see that function's
    docstring for why re-ranking inside the loop is the correctness-critical step)."""
    from scipy.stats import rankdata

    n = len(x)
    n_blocks = math.ceil(n / block_size)
    offsets = np.arange(block_size)
    point_ic = float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])
    boot_ics = np.zeros(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + offsets).ravel()[:n] % n
        boot_ics[b] = np.corrcoef(rankdata(x[idx]), rankdata(y[idx]))[0, 1]
    ci_lower = float(np.percentile(boot_ics, 2.5))
    ci_upper = float(np.percentile(boot_ics, 97.5))
    return point_ic, ci_lower, ci_upper


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-boot", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--split-date",
        type=str,
        default=_DEFAULT_SPLIT_DATE.isoformat(),
        help="Fixed before any result is read -- do not tune after seeing a holdout number.",
    )
    args = parser.parse_args()
    split_date = date.fromisoformat(args.split_date)

    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache
    block_size = int(_cfg(apr_dict, f"alpha.ic.bootstrap_block_size.{_TF}", 26))
    min_reliable_n = int(_cfg(apr_dict, "alpha.ic.min_reliable_n", 100))
    rng = np.random.default_rng(args.seed)

    print(
        f"cointegrated_pairs_residual pilot -- {len(_PAIRS)} named pairs, split_date={split_date}"
    )
    print(f"block_size={block_size} n_boot={args.n_boot} min_reliable_n={min_reliable_n}\n")

    survivors: list[tuple[str, str]] = []

    for sym_a, sym_b in _PAIRS:
        print(f"=== {sym_a}/{sym_b} ===")
        dates_a, close_a = _daily_log_closes(conn, sym_a)
        dates_b, close_b = _daily_log_closes(conn, sym_b)
        if dates_a != dates_b:
            common = sorted(set(dates_a) & set(dates_b))
            idx_a = {d: i for i, d in enumerate(dates_a)}
            idx_b = {d: i for i, d in enumerate(dates_b)}
            close_a = np.array([close_a[idx_a[d]] for d in common])
            close_b = np.array([close_b[idx_b[d]] for d in common])
            dates_common = common
        else:
            dates_common = dates_a

        a_in, a_out = _split(dates_common, close_a, split_date)
        b_in, b_out = _split(dates_common, close_b, split_date)

        # Stage 1: in-sample cointegration screen
        stage1 = _engle_granger(a_in, b_in)
        print(
            f"  Stage 1 (in-sample coint): p={stage1.p_value:.4f} -> {'PASS' if stage1.passes else 'FAIL'}"
        )
        if not stage1.passes:
            print("  DEAD -- does not cointegrate in-sample.\n")
            continue

        # Stage 2: OOS stability check
        if len(a_out) < 30:
            print(f"  Stage 2: INSUFFICIENT holdout data (n={len(a_out)})\n")
            continue
        stage2 = _engle_granger(a_out, b_out)
        print(
            f"  Stage 2 (OOS coint): p={stage2.p_value:.4f} -> {'PASS' if stage2.passes else 'FAIL'}"
        )
        if not stage2.passes:
            print("  DEAD -- cointegrated in-sample but not OOS (noise, not structure).\n")
            continue

        # Stage 3: OU fit on the FULL series (in-sample + OOS combined -- the spread's
        # long-run parameters are a property of the whole history, not re-fit per split)
        spread_full = close_a - close_b
        theta, mu, half_life = _fit_ou(spread_full)
        print(f"  Stage 3 (OU fit): theta={theta:.5f} mu={mu:.4f} half_life={half_life:.1f} days")
        if not math.isfinite(half_life):
            print(
                "  DEAD -- non-mean-reverting (theta <= 0) despite passing cointegration tests.\n"
            )
            continue

        survivors.append((sym_a, sym_b))
        print(f"  Survives Stages 1-3. Proceeding to Stage 4 (tf={_TF}).")

        # Stage 4: falsification bar at tf=15m
        bars_a = _fetch_bars_from_db(conn, sym_a, _TF)
        bars_b = _fetch_bars_from_db(conn, sym_b, _TF)
        ts_a = {b["ts"]: b["close"] for b in bars_a}
        ts_b = {b["ts"]: b["close"] for b in bars_b}
        common_ts = sorted(set(ts_a) & set(ts_b))
        if len(common_ts) < min_reliable_n:
            print(f"  Stage 4: INSUFFICIENT tf={_TF} overlap (n={len(common_ts)})\n")
            continue
        log_a = np.log(np.array([ts_a[t] for t in common_ts]))
        log_b = np.log(np.array([ts_b[t] for t in common_ts]))
        spread_15m = log_a - log_b
        z = _zscore(spread_15m, mu)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fr_a.bar_ts, fr_a.return_mid, fr_b.return_mid
                FROM forward_returns fr_a
                JOIN forward_returns fr_b
                  ON fr_b.tf = fr_a.tf AND fr_b.bar_ts = fr_a.bar_ts
                 AND fr_b.symbol = %s AND fr_b.return_type = 'executable_open_to_open'
                 AND fr_b.complete_mid = true
                WHERE fr_a.symbol = %s AND fr_a.tf = %s
                  AND fr_a.return_type = 'executable_open_to_open' AND fr_a.complete_mid = true
                ORDER BY fr_a.bar_ts
                """,
                (sym_b, sym_a, _TF),
            )
            ret_rows = cur.fetchall()
        ret_by_ts = {
            (r[0] if r[0].tzinfo else r[0].replace(tzinfo=UTC)): (r[1], r[2]) for r in ret_rows
        }

        z_aligned, spread_ret_aligned = [], []
        for i, t in enumerate(common_ts):
            if math.isnan(z[i]):
                continue
            rets = ret_by_ts.get(t)
            if rets is None or rets[0] is None or rets[1] is None:
                continue
            z_aligned.append(z[i])
            spread_ret_aligned.append(rets[0] - rets[1])  # spread's forward return

        n_stage4 = len(z_aligned)
        print(f"  Stage 4: n={n_stage4} aligned (z-score, next-bar spread return)")
        if n_stage4 < min_reliable_n:
            print(f"  Stage 4: INSUFFICIENT n={n_stage4} < min_reliable_n={min_reliable_n}\n")
            continue

        # Predicting reversion: -z should positively predict the spread's forward return
        # (high z = spread too wide = expect it to narrow = negative spread return next,
        # so test corr(-z, spread_return))
        point_ic, ci_lo, ci_hi = _circular_block_bootstrap_ic_1d(
            -np.asarray(z_aligned), np.asarray(spread_ret_aligned), block_size, args.n_boot, rng
        )
        crosses_zero = ci_lo <= 0.0 <= ci_hi
        verdict = (
            "NO EFFECT (CI crosses zero)"
            if crosses_zero
            else ("POSITIVE" if point_ic > 0 else "NEGATIVE")
        )
        print(f"  Stage 4 result: ic={point_ic:.5f} ci=[{ci_lo:.5f}, {ci_hi:.5f}] -> {verdict}")
        print(
            "  Stage 5 (cost-hurdle gate): NOT RUN in this pilot -- gated on Stage 4 clearing "
            "CI first, per pre-registration. Reusing cross_sectional_spread_tracker.py's cost "
            "sweep is the next step if Stage 4 clears.\n"
        )

    print(f"\n{len(survivors)}/{len(_PAIRS)} pairs survived Stages 1-3: {survivors}")
    print(
        "Verdict rule (pre-registered): if zero pairs both cointegrate OOS and show "
        "predictive residual reversion (Stage 4 CI excludes zero), cointegrated_pairs_residual is dead."
    )
    conn.close()


if __name__ == "__main__":
    main()
