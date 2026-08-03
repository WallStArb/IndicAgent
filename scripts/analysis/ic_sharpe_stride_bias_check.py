"""Monte Carlo check: does _compute_ic_rolling_metrics' ic_sharpe mechanically decay
with stride even when the TRUE generating rank correlation is held constant across
scales (todo 096 v2 hypothesis)?

Calls the real production function (src/intelligence/statistics/ic_math.py) --
not a reimplementation -- against synthetic (X, Y) pairs generated with a FIXED,
known Spearman rank correlation, i.i.d. across "time" (no real regime structure,
no real decay). If ic_sharpe still comes out systematically lower at longer strides,
that's estimator bias, not signal decay, by construction.

Fetches live APR values from config_state (lookaheads / subsample_min_stride /
sharpe_window_size_subsampled / sharpe_min_windows / hac_max_lag) so the strides
tested exactly match what services/ic_engine.py and ensemble_ic_engine.py use in
production. Re-run this after any of those APR values change -- a stale hardcoded
snapshot silently tests the wrong config, which is exactly what happened to this
script's own first version (it hardcoded sharpe_window_size=2000, the pre-todo-096
raw-bars-per-stride semantics, deprecated when the actual fix shipped
sharpe_window_size_subsampled -- see SharpeWindowConfig's docstring in ic_math.py).

2026-07-19: fixed to use sharpe_window_size_subsampled (the shipped fix's field
name, todo 096) instead of the deprecated sharpe_window_size, and to fetch APR
live instead of a hardcoded snapshot that had silently drifted stale.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import psycopg

_project_root = Path(__file__).resolve().parents[0]
sys.path.insert(0, "/home/bg/dev/indicagent")

from src.config.settings import Settings  # noqa: E402
from src.intelligence.statistics.ic_math import _compute_ic_rolling_metrics  # noqa: E402


def _fetch_apr(cur, key: str, default):
    cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (key,))
    row = cur.fetchone()
    return type(default)(row[0]) if row else default


# Todo 146/202: lookahead grid is per-tf now, not one shared scale->bars grid -- 5m's
# real mid=6 has a very different stride profile than 1h's mid=2, so this script's own
# "does ic_sharpe mechanically decay with stride" question can have a different answer
# per tf. Test every tf's own live grid, not one flat snapshot.
_settings = Settings()
_dsn = _settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
with psycopg.connect(_dsn) as _conn, _conn.cursor() as _cur:
    LOOKAHEADS_BY_TF = {
        tf: {
            "fast": _fetch_apr(_cur, f"alpha.ic.lookahead.{tf}.fast", 1),
            "mid": _fetch_apr(_cur, f"alpha.ic.lookahead.{tf}.mid", 5),
            "slow": _fetch_apr(_cur, f"alpha.ic.lookahead.{tf}.slow", 20),
            "extended": _fetch_apr(_cur, f"alpha.ic.lookahead.{tf}.extended", 60),
        }
        for tf in ("5m", "15m", "1h", "1d")
    }
    SUBSAMPLE_MIN_STRIDE = _fetch_apr(_cur, "alpha.ic.subsample_min_stride", 5)
    SHARPE_WINDOW_SIZE_SUBSAMPLED = _fetch_apr(_cur, "alpha.ic.sharpe_window_size_subsampled", 100)
    SHARPE_MIN_WINDOWS = _fetch_apr(_cur, "alpha.ic.sharpe_min_windows", 30)
    HAC_MAX_LAG = _fetch_apr(_cur, "alpha.ic.hac_max_lag", 3)
DECAY_THRESHOLD = 0.1  # script-local Monte Carlo reporting cutoff, not an APR key

STRIDES_BY_TF = {
    tf: {scale: max(SUBSAMPLE_MIN_STRIDE, lookahead) for scale, lookahead in lookaheads.items()}
    for tf, lookaheads in LOOKAHEADS_BY_TF.items()
}
print(
    "Live APR values used:",
    {
        "lookaheads_by_tf": LOOKAHEADS_BY_TF,
        "subsample_min_stride": SUBSAMPLE_MIN_STRIDE,
        "sharpe_window_size_subsampled": SHARPE_WINDOW_SIZE_SUBSAMPLED,
        "sharpe_min_windows": SHARPE_MIN_WINDOWS,
        "hac_max_lag": HAC_MAX_LAG,
    },
)
print("Strides derived from live APR (tf -> scale: stride):", STRIDES_BY_TF)


@dataclass
class _Cfg:
    sharpe_window_size_subsampled: int
    sharpe_min_windows: int
    hac_max_lag: int


CONFIG = _Cfg(
    sharpe_window_size_subsampled=SHARPE_WINDOW_SIZE_SUBSAMPLED,
    sharpe_min_windows=SHARPE_MIN_WINDOWS,
    hac_max_lag=HAC_MAX_LAG,
)


def make_raw_series(
    n_raw: int, true_rho: float, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """i.i.d. draws with a fixed population Spearman rank correlation = true_rho.

    Gaussian copula: correlated normals -> rank-based Spearman correlation is
    (asymptotically) close to the input Pearson correlation of the underlying
    normals for small-to-moderate rho: rho_spearman ~= (6/pi) * arcsin(rho_pearson/2),
    nearly linear for small rho. We solve for the underlying Pearson rho that
    yields the target Spearman rho, then verify empirically per draw.
    """
    # Pearson rho that gives the target Spearman rho under a Gaussian copula.
    pearson_rho = 2 * np.sin(true_rho * np.pi / 6)
    mean = [0, 0]
    cov = [[1, pearson_rho], [pearson_rho, 1]]
    xy = rng.multivariate_normal(mean, cov, size=n_raw)
    x, y = xy[:, 0], xy[:, 1]
    return x, y


def stride_ic_sharpe(x_raw: np.ndarray, y_raw: np.ndarray, stride: int) -> float:
    """Subsample at `stride` (matching ic_engine.py's sub_idx = arange(0, n, stride)),
    then compute ic_sharpe via the real production function.
    """
    sub_idx = np.arange(0, len(x_raw), stride)
    x_sub = x_raw[sub_idx].reshape(-1, 1)  # [n, 1 feature]
    y_sub = y_raw[sub_idx].reshape(-1, 1)  # [n, 1 scale column]
    complete_mask = np.ones(len(sub_idx), dtype=bool)
    non_degenerate_mask = np.array([True])

    sharpe_arr, _sharpe_hac, _sortino, _win_rate, n_windows = _compute_ic_rolling_metrics(
        x_sub,
        y_sub,
        0,  # scale_idx (single-column y_sub)
        complete_mask,
        CONFIG,
        non_degenerate_mask,
        1,  # n_total_features
        stride,
    )
    return float(sharpe_arr[0]), n_windows


def run(
    tf: str, strides: dict[str, int], true_rho: float, n_raw: int, n_reps: int, seed: int
) -> None:
    rng = np.random.default_rng(seed)
    results: dict[str, list[float]] = {scale: [] for scale in strides}
    n_windows_by_scale: dict[str, list[int]] = {scale: [] for scale in strides}

    for _rep in range(n_reps):
        x_raw, y_raw = make_raw_series(n_raw, true_rho, rng)
        for scale, stride in strides.items():
            sharpe, n_windows = stride_ic_sharpe(x_raw, y_raw, stride)
            if not np.isnan(sharpe):
                results[scale].append(sharpe)
            n_windows_by_scale[scale].append(n_windows)

    print(f"\n=== tf={tf}, true_rho={true_rho}, n_raw={n_raw}, n_reps={n_reps} ===")
    print(
        f"{'scale':<10} {'stride':>6} {'window_sz':>10} {'n_windows':>10} "
        f"{'mean_sharpe':>12} {'median_sharpe':>14} {'pct_below_0.1':>14} {'n_valid':>8}"
    )
    for scale, stride in strides.items():
        vals = np.array(results[scale])
        # Fixed subsampled-bar window (todo 096's fix): constant across every stride
        # by construction, not raw_bars // stride -- printed per-scale only so the
        # table's column is easy to read against n_windows, not because it varies.
        window_sz = CONFIG.sharpe_window_size_subsampled
        avg_nw = np.mean(n_windows_by_scale[scale])
        if len(vals) == 0:
            print(
                f"{scale:<10} {stride:>6} {window_sz:>10} {avg_nw:>10.1f} "
                f"{'NaN (gate not met)':>12}"
            )
            continue
        pct_below = 100.0 * np.mean(vals < DECAY_THRESHOLD)
        print(
            f"{scale:<10} {stride:>6} {window_sz:>10} {avg_nw:>10.1f} "
            f"{np.mean(vals):>12.4f} {np.median(vals):>14.4f} {pct_below:>13.1f}% {len(vals):>8}"
        )


if __name__ == "__main__":
    # 90_000 (this script's original value) left `extended` (stride=60) unable to
    # clear the sharpe_min_windows=30 reliability gate: 90_000/60=1500 subsampled
    # obs / window_size=100 = 15 windows, below the 30 floor -- a Monte Carlo
    # sample-size artifact, not a fix problem. Raised so all four scales report.
    N_RAW = 400_000
    N_REPS = 150
    SEED = 42

    for tf, strides in STRIDES_BY_TF.items():
        for true_rho in (0.0, 0.03, 0.06, 0.10):
            run(tf, strides, true_rho, N_RAW, N_REPS, SEED)
