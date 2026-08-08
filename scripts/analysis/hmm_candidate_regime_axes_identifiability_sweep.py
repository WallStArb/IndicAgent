"""Candidate single-security regime AXES: standalone identifiability sweep (Phase 171 follow-on).

WHY THIS EXISTS
---------------
`hmm_regime_axis_decomposition_identifiability_sweep.py` decomposed production's 5-column
observation matrix into the three families it already contains (trend, volatility, volume) and
measured each standalone. Trend and volatility identify cleanly at low K; volume never
identifies at any K. That study could only test families *already present in
`_build_obs_matrix`*.

This sweep asks the next question: are there OTHER single-security regime concepts -- ones
requiring feature construction that does not exist anywhere in the current observation matrix --
that identify cleanly enough to earn their own `regime_*` stratification cut? Four candidates:

  1. systematic     idiosyncratic-vs-systematic dominance: is the name moving with the market
                    or on its own driver? (needs a benchmark reference series)
  2. persistence    momentum-persistence vs mean-reversion: do moves continue or snap back?
                    (NOT direction -- that is the existing trend axis)
  3. tail           tail-risk / skew: is the return distribution lopsided or symmetric?
  4. volume_price   volume-price CONFIRMATION: does volume corroborate price moves, or diverge?
                    (NOT raw volume level -- that is the already-dead volume axis)

Falsification looks like: an axis fails both bars on most cells (reject), or identifies only
because its two "states" have coincident emission means (the semantically-empty-model trap the
companion study caught on the volume axis -- `min_state_separation` is the instrument for it).

METHOD
------
Fitting, decoding, canonicalization, diagnostics, and bars are inherited UNCHANGED by direct
import from `hmm_regime_axis_decomposition_identifiability_sweep` -- `_fit_one`,
`_run_config_cell`, `_agreement_stats`, `_pick_champion`, `_count_distinct_solutions`,
`_min_state_separation`, `_passes`. Only the observation matrix is new. That harness was
validated against the composite control arm in the companion study, so these numbers sit on a
known-good instrument rather than a re-implementation.

Per (symbol, tf) x axis x window x K:
  1. Build the axis's 2-column feature matrix from raw OHLCV (+ a benchmark series for
     `systematic`), then `StandardScaler().fit_transform` -- production parity.
  2. 20 seeds from pool A (base = `alpha.hmm.random_state`), 20 from disjoint pool B (base
     1000). Champion per pool = highest (converged, log_likelihood).
  3. Production-faithful decode -> `_smooth_states(min_hold_bars)` -> `_build_label_map`.
  4. Cross-block agreement + Cohen's kappa. Bars (BOTH required): agreement >= 0.90 AND
     kappa >= 0.80. Plus production's own `_check_occupation_gate`.

Headline convention: the MINIMUM across cells and the PASS COUNT, never an average.

CANONICALIZATION
----------------
`_build_label_map` rank-orders states by fitted `means[:, 0]`. Column 0 of every axis below is
that axis's primary/ordering dimension (see `_AXIS_SPECS`), so the map is a rank-ordering
canonicalization on the right variable for each axis, exactly as in the companion study. The
emitted label *strings* stay trend-flavoured ("trending_up" on the tail axis means
"most-right-skewed state"); only the ordinal rank participates in agreement.

THE WINDOW-STABILITY PROBE (new here)
-------------------------------------
Every candidate is a SECOND- or HIGHER-ORDER statistic (correlation, autocorrelation, third
moment) rather than a raw return, so its own sampling variance at a short window can dominate
any real regime structure. A failed identifiability test would then be ambiguous: "no persistent
regime exists" vs "the window was too short to estimate the statistic". Those are different
conclusions and conflating them would repeat exactly the class of measurement artifact this
investigation already caught once (the missing-StandardScaler bug in two earlier pilots).

The probe resolves it directly, per axis per candidate window, with a NON-OVERLAPPING
split-half reliability measure:

  * block_reliability -- correlation between the axis's primary statistic estimated on
    ADJACENT DISJOINT windows (blocks [i*W, (i+1)*W) and [(i+1)*W, (i+2)*W)). The two
    estimates share no data whatsoever, so a positive correlation can only come from
    structure that persists across the block boundary. By the classical two-parallel-
    measurements identity this coefficient IS the fraction of the statistic's variance that
    is real rather than estimation error: 0.05 means 95% of what the HMM would be fitting is
    noise; 0.70 means the statistic is mostly signal.
  * null_block_reliability -- the same on a series whose rows have been jointly permuted
    (permutation preserves the unconditional distribution exactly -- same marginal skewness,
    same contemporaneous cross-series correlation -- while destroying all time dependence).
    It must come out ~0.0; that is the instrument's own calibration check, not a comparison.

An OVERLAPPING-window statistic was deliberately NOT used for this. std(real)/std(null) and
the lag-1 autocorrelation of the rolling series are both confounded: under permutation a fat
left tail's single worst return lands in a random window and inflates that window's skewness
enormously, whereas in the real series extreme returns cluster inside already-high-variance
windows and are normalized away by the m2**1.5 denominator. That makes real rolling skew
*less* variable than its own IID null -- a ratio below 1.0 that says nothing about signal.
Both quantities are still recorded in the JSON as descriptive statistics; neither is a verdict.

THE NULL ARM (the control that makes the identifiability numbers interpretable)
------------------------------------------------------------------------------
Every (axis, window, K) configuration is ALSO fit on features built from the IID-permuted
series -- a series that contains no regime by construction. If the null arm clears the
agreement/kappa bars just as cleanly as the real arm, then those bars are not discriminating
for that axis and a passing real-arm number is worth nothing on its own.

This control exists because the smoke run made the risk concrete: a two-state HMM on a
stationary noise series is a deterministic threshold split of that series. It is perfectly
reproducible across disjoint seed pools (agreement 1.0000), well separated (the two clusters
sit either side of the threshold), and healthily occupied (~50/50) -- it clears every gate this
project currently has while encoding nothing. That is a strictly harder version of the
coincident-means trap the companion study found on the volume axis, and neither
`min_state_separation` nor `_check_occupation_gate` catches it. `block_reliability` and the
null arm are what catch it.

Read-only diagnostic: no `feature_vectors` writes, no `config_state` writes, no
`regime_writer.py` CLI invocation, no modification to `services/regime_writer.py`.

Usage:
    .venv/bin/python scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py
    .venv/bin/python scripts/analysis/hmm_candidate_regime_axes_identifiability_sweep.py \
        --axes tail --axis-windows 'tail:120,250' --symbols SPY TLT --tf 1d
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from scripts.analysis.hmm_regime_axis_decomposition_identifiability_sweep import (  # noqa: E402
    _AGREEMENT_THRESHOLD,
    _KAPPA_THRESHOLD,
    _fetch_ohlcv,
    _load_config,
    _passes,
    _run_config_cell,
)
from services._batch_utils import make_worker_pool as _make_worker_pool  # noqa: E402
from services.ic_engine import _build_symbol_regime_class  # noqa: E402
from src.config.settings import Settings  # noqa: E402

# todo 216: BLAS thread cap, see make_worker_pool()/limit_blas_threads(). A bare pool
# construction silently reintroduces the OpenBLAS oversubscription bug (24 cores x N workers x
# default BLAS threads); this is the project-wide fix, applied per-worker via the pool's
# initializer rather than a module-level env-var guess.
_BLAS_THREADS_PER_WORKER = 1

_DEFAULT_SYMBOLS = [
    # Original 8-symbol identifiability scope.
    "SPY",
    "IWM",
    "TLT",
    "GLD",
    "XLE",
    "EEM",
    "FXY",
    "SMH",
    # The 9 added for the widened trend check, kept identical here so the fx/commodity/
    # rates/intl-vs-domestic-equity pattern that check surfaced is testable on these axes.
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "JPM",
    "QQQ",
    "DIA",
    "XLF",
    "XLK",
]
_DEFAULT_TFS = ["1d", "1h"]

# All four candidates are coarse regime concepts by construction (with/without the market;
# trending/reverting; skewed/symmetric; confirming/diverging). K is not swept above 3 unless
# both fail for a reason that more states would plausibly fix.
_DEFAULT_K_VALUES = [2, 3]

# `full` only. The companion study swept full-vs-diag on every 2-D axis and diag never changed
# a verdict; production itself uses full. Re-litigating it here would double the grid for no
# decision value.
_COV_TYPES = ["full"]

_DEFAULT_N_VALUES = [5, 10, 20]

# Benchmark for the `systematic` axis. A single universal reference, deliberately: per-
# regime_group peer averaging is a separate refinement and would confound "does this axis
# identify at all" with "is the peer group right".
_BENCHMARK_SYMBOL = "SPY"

# Lo-MacKinlay aggregation horizon for the variance ratio. q=5 (one week at 1d) rather than
# q=2: VR(2) is an affine function of lag-1 autocorrelation (VR(2) = 1 + AC1), which would make
# the persistence axis's two columns near-duplicates. q=5 aggregates AC1..AC4, so the two
# columns carry genuinely different information.
_VARIANCE_RATIO_Q = 5

# Outlier clips. Each guards a statistic whose denominator can collapse on a near-flat window,
# producing a single 1e4-magnitude value that would dominate StandardScaler and hand the HMM a
# one-bar "state". Clip counts are reported per cell so a clip rate that is not negligible is
# visible rather than silent.
_BETA_CLIP = 5.0  # |beta| vs SPY beyond 5 is a variance-degenerate window, not an exposure
_VARIANCE_RATIO_CLIP = 4.0  # VR is >= 0; empirical range is ~0.5-1.5
_SKEW_CLIP = 8.0  # 250-bar skew of fat-tailed returns can legitimately reach ~+-6

# A cell whose forward-filled (non-finite) interior fraction exceeds this is reported loudly --
# the statistic is undefined too often for its result to mean anything.
_MAX_INTERIOR_FILL_FRACTION = 0.01

_MIN_OBS = 250

# Median block_reliability an axis must exceed to be called real. 0.10 means "at least 10% of
# the statistic's variation survives a full non-overlapping window boundary". [initial_estimate]
# -- this is a reasoned floor, not a calibrated one; the measured value is always printed
# alongside the verdict so a reader can apply a different bar without re-running.
_RELIABILITY_FLOOR = 0.10

_PROBE_WINDOWS = [20, 60, 120, 250]
_PROBE_REPLICATES = 2
# The probe measures a statistical property of the series, not a corpus census; the most
# recent N bars are sufficient and keep the permutation replicates cheap.
_PROBE_MAX_BARS = 20000

_RESULTS_PATH = Path("cache/hmm_candidate_regime_axes_identifiability_sweep.json")


@dataclass
class _AxisSpec:
    """One candidate regime axis.

    `builder` returns a (n, 2) float array aligned to the context's series, NaN in the
    warm-up prefix. Column 0 is the axis's PRIMARY dimension -- the one `_build_label_map`
    rank-orders states by, so it must be the quantity whose ordering defines the regime
    semantics.
    """

    name: str
    columns: tuple[str, str]
    gloss: str
    default_windows: tuple[int, ...]
    needs_benchmark: bool
    window_rationale: str


# ---------------------------------------------------------------------------
# Rolling primitives. All are right-aligned with a NaN warm-up prefix, matching the
# `_rolling` convention in regime_writer.py (which zero-pads instead; NaN is used here so an
# undefined statistic is never confused with a genuine zero correlation/skew).
# ---------------------------------------------------------------------------


def _sliding(arr: np.ndarray, window: int) -> np.ndarray | None:
    if len(arr) < window:
        return None
    return np.lib.stride_tricks.sliding_window_view(arr, window)


def _place(values: np.ndarray | None, n: int, window: int) -> np.ndarray:
    """Right-align a (n-window+1,) reduction into a full-length NaN-prefixed array."""
    out = np.full(n, np.nan)
    if values is not None:
        out[window - 1 :] = values
    return out


def _safe_divide(num: np.ndarray, den: np.ndarray, floor: float) -> np.ndarray:
    """num/den, NaN wherever |den| is below `floor` -- an undefined ratio must stay
    undefined rather than silently become a large finite number."""
    return np.where(np.abs(den) > floor, num / np.where(np.abs(den) > floor, den, 1.0), np.nan)


def _rolling_moments(a: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray] | None:
    """(mean, centered windows) for one series; the centered view is reused by callers."""
    sw = _sliding(a, window)
    if sw is None:
        return None
    mean = sw.mean(axis=1)
    return mean, sw - mean[:, None]


def _rolling_corr(a: np.ndarray, b: np.ndarray, window: int) -> np.ndarray:
    n = len(a)
    moments_a = _rolling_moments(a, window)
    moments_b = _rolling_moments(b, window)
    if moments_a is None or moments_b is None:
        return np.full(n, np.nan)
    _, da = moments_a
    _, db = moments_b
    cov = (da * db).mean(axis=1)
    sd_a = np.sqrt((da * da).mean(axis=1))
    sd_b = np.sqrt((db * db).mean(axis=1))
    return _place(_safe_divide(cov, sd_a * sd_b, 1e-24), n, window)


def _rolling_cov_and_var(
    a: np.ndarray, b: np.ndarray, window: int
) -> tuple[np.ndarray, np.ndarray]:
    n = len(a)
    moments_a = _rolling_moments(a, window)
    moments_b = _rolling_moments(b, window)
    if moments_a is None or moments_b is None:
        return np.full(n, np.nan), np.full(n, np.nan)
    _, da = moments_a
    _, db = moments_b
    cov = (da * db).mean(axis=1)
    var_b = (db * db).mean(axis=1)
    return _place(cov, n, window), _place(var_b, n, window)


def _rolling_var(a: np.ndarray, window: int) -> np.ndarray:
    n = len(a)
    moments = _rolling_moments(a, window)
    if moments is None:
        return np.full(n, np.nan)
    _, da = moments
    return _place((da * da).mean(axis=1), n, window)


def _rolling_sum(a: np.ndarray, window: int) -> np.ndarray:
    sw = _sliding(a, window)
    return _place(None if sw is None else sw.sum(axis=1), len(a), window)


def _rolling_skew(a: np.ndarray, window: int) -> np.ndarray:
    """Fisher-Pearson sample skewness g1 = m3 / m2**1.5, the same estimator scipy.stats.skew
    returns with bias=True. Kept inline rather than calling scipy so the sliding-window view is
    reduced in one pass instead of once per window."""
    n = len(a)
    moments = _rolling_moments(a, window)
    if moments is None:
        return np.full(n, np.nan)
    _, da = moments
    m2 = (da * da).mean(axis=1)
    m3 = (da * da * da).mean(axis=1)
    return _place(_safe_divide(m3, np.power(np.maximum(m2, 0.0), 1.5), 1e-30), n, window)


def _rolling_semideviation_asymmetry(a: np.ndarray, window: int) -> np.ndarray:
    """log(downside semideviation / upside semideviation) over the window.

    Semideviations are lower/upper partial moments about zero (`sqrt(mean(min(r,0)**2))` and
    `sqrt(mean(max(r,0)**2))`), so both frequency and magnitude of one-sided moves contribute.
    This is a SECOND-moment asymmetry measure -- far better conditioned than skewness at the
    same window -- and is the reason the tail axis is not left resting on a third moment alone.
    The log makes it symmetric about zero and scale-free.
    """
    n = len(a)
    sw = _sliding(a, window)
    if sw is None:
        return np.full(n, np.nan)
    down = np.sqrt(np.square(np.minimum(sw, 0.0)).mean(axis=1))
    up = np.sqrt(np.square(np.maximum(sw, 0.0)).mean(axis=1))
    ratio = _safe_divide(down, up, 1e-30)
    return _place(np.log(np.where(ratio > 0, ratio, np.nan)), n, window)


def _clip_and_count(values: np.ndarray, limit: float) -> tuple[np.ndarray, int]:
    finite = np.isfinite(values)
    n_clipped = int(np.count_nonzero(finite & (np.abs(values) > limit)))
    return np.clip(values, -limit, limit), n_clipped


# ---------------------------------------------------------------------------
# Series context + axis feature builders
# ---------------------------------------------------------------------------


@dataclass
class _SeriesContext:
    """Per-(symbol, tf) inputs every axis builder draws on.

    All arrays are aligned to `log_returns` (one shorter than the raw close series, since the
    first bar has no predecessor). `bench_returns` is the benchmark's log return over the SAME
    timestamps -- built by inner-joining on timestamp, since `market_data_ohlcv_tradeable`
    filters zero-volume bars and two symbols' bar sets are therefore not identical.
    """

    symbol: str
    tf: str
    log_returns: np.ndarray
    rel_volume: np.ndarray
    bench_returns: np.ndarray | None


def _build_systematic(ctx: _SeriesContext, window: int) -> tuple[np.ndarray, dict]:
    """[R-squared vs benchmark, beta vs benchmark].

    R-squared (= squared rolling correlation) is the primary dimension: it is the fraction of
    the name's return variance explained by the market, which is precisely "systematic
    dominance", and it is sign-agnostic -- a reliably NEGATIVE-beta instrument (TLT, FXY in
    risk-off) is strongly systematic even though its correlation is negative. Rank ordering
    therefore reads idiosyncratic (low R-squared) -> systematic (high).

    Beta is the second column because R-squared alone cannot distinguish a 0.3-beta name whose
    moves are fully market-explained from a 1.5-beta one; the pair is the market model's two
    free parameters.
    """
    assert ctx.bench_returns is not None
    corr = _rolling_corr(ctx.log_returns, ctx.bench_returns, window)
    cov, var_bench = _rolling_cov_and_var(ctx.log_returns, ctx.bench_returns, window)
    beta_raw = _safe_divide(cov, var_bench, 1e-24)
    beta, n_clipped = _clip_and_count(beta_raw, _BETA_CLIP)
    return np.column_stack([np.square(corr), beta]), {"n_clipped_beta": n_clipped}


def _build_persistence(ctx: _SeriesContext, window: int) -> tuple[np.ndarray, dict]:
    """[Lo-MacKinlay variance ratio VR(q), lag-1 return autocorrelation].

    VR(q) = Var(q-period returns) / (q * Var(1-period returns)), overlapping estimator. Under a
    random walk VR == 1; VR > 1 means moves persist (momentum/trending), VR < 1 means they snap
    back (mean reversion). It is the primary dimension because it aggregates autocorrelation at
    lags 1..q-1 rather than lag 1 alone, and because its unit scale (1.0 = random walk) makes
    the state ordering directly interpretable: mean-reverting -> random-walk -> trending.
    """
    returns = ctx.log_returns
    q_sums = _rolling_sum(returns, _VARIANCE_RATIO_Q)
    var_q = _rolling_var(q_sums, window)
    var_1 = _rolling_var(returns, window)
    vr_raw = _safe_divide(var_q, _VARIANCE_RATIO_Q * var_1, 1e-30)
    variance_ratio, n_clipped = _clip_and_count(vr_raw, _VARIANCE_RATIO_CLIP)

    autocorr = np.full(len(returns), np.nan)
    if len(returns) > window:
        autocorr[1:] = _rolling_corr(returns[1:], returns[:-1], window)
    return np.column_stack([variance_ratio, autocorr]), {"n_clipped_variance_ratio": n_clipped}


def _build_tail(ctx: _SeriesContext, window: int) -> tuple[np.ndarray, dict]:
    """[rolling skewness, log(downside/upside semideviation)].

    Skewness is the primary dimension so the state ordering reads crash-prone (left-skewed) ->
    symmetric -> right-skewed. It is a third moment and is the noisiest statistic in this
    study; the semideviation asymmetry is deliberately paired with it as a much better
    conditioned second-moment measure of the same underlying asymmetry, so the axis is not
    resting on the third moment alone.
    """
    skew = _rolling_skew(ctx.log_returns, window)
    skew_clipped, n_clipped = _clip_and_count(skew, _SKEW_CLIP)
    asymmetry = _rolling_semideviation_asymmetry(ctx.log_returns, window)
    return np.column_stack([skew_clipped, asymmetry]), {"n_clipped_skew": n_clipped}


def _build_volume_price(ctx: _SeriesContext, window: int) -> tuple[np.ndarray, dict]:
    """[corr(|return|, rel_volume), corr(return, rel_volume)].

    This is the RELATIONSHIP between volume and price, not the volume level -- the level was
    already tested standalone and never identifies at any K. The magnitude correlation is
    primary: high = moves are accompanied by participation (confirmation), near-zero or
    negative = price is moving on thin or contrarian volume (divergence/exhaustion). The signed
    correlation is the second column and separates accumulation (volume expands on up moves)
    from distribution (volume expands on down moves), which the magnitude correlation cannot
    see.
    """
    magnitude_corr = _rolling_corr(np.abs(ctx.log_returns), ctx.rel_volume, window)
    signed_corr = _rolling_corr(ctx.log_returns, ctx.rel_volume, window)
    return np.column_stack([magnitude_corr, signed_corr]), {}


_AXIS_SPECS: dict[str, _AxisSpec] = {
    "systematic": _AxisSpec(
        name="systematic",
        columns=("r_squared_vs_benchmark", "beta_vs_benchmark"),
        gloss="idiosyncratic (low R^2) .. systematic (high R^2)",
        default_windows=(60,),
        needs_benchmark=True,
        window_rationale=(
            "Rolling correlation's sampling SE is ~(1-rho^2)/sqrt(n-3): ~0.22 at n=20 (the "
            "vol_window default), ~0.13 at n=60. A regression statistic needs materially more "
            "history than a raw return for the estimate to carry more signal than noise; 60 is "
            "the shortest window at which the probe shows real variation clearly exceeding the "
            "permutation null on both timeframes."
        ),
    ),
    "persistence": _AxisSpec(
        name="persistence",
        columns=("variance_ratio_q5", "return_autocorr_lag1"),
        gloss="mean-reverting (VR<1) .. random walk (VR=1) .. trending (VR>1)",
        default_windows=(60,),
        needs_benchmark=False,
        window_rationale=(
            "Autocorrelation SE is ~1/sqrt(n): 0.22 at n=20, 0.13 at n=60. The variance ratio "
            "additionally consumes q=5 bars per aggregated observation, so a 20-bar window "
            "holds only ~4 independent q-sums -- not enough to estimate a variance. 60 is the "
            "shortest window that leaves ~12 independent q-period observations."
        ),
    ),
    "tail": _AxisSpec(
        name="tail",
        columns=("skewness", "log_downside_upside_semidev"),
        gloss="left-skewed/crash-prone .. symmetric .. right-skewed",
        default_windows=(120, 250),
        needs_benchmark=False,
        window_rationale=(
            "Skewness is a THIRD moment: its SE under normality is ~sqrt(6/n) = 0.55 at n=20, "
            "0.32 at n=60, 0.22 at n=120, 0.15 at n=250 -- and fat tails inflate all of these. "
            "At 20 bars the estimator's own noise exceeds any plausible regime signal by "
            "construction. TWO windows (120 and 250) are swept so a negative result can be "
            "attributed: failing at both, with a probe persistence_ratio near 1.0 at both, is "
            "'no persistent skew regime'; failing at 120 while passing at 250 would have been "
            "'the window was too short'."
        ),
    ),
    "volume_price": _AxisSpec(
        name="volume_price",
        columns=("corr_absreturn_relvolume", "corr_return_relvolume"),
        gloss="divergent (low corr) .. confirming (high corr)",
        default_windows=(60,),
        needs_benchmark=False,
        window_rationale=(
            "Same correlation-SE argument as the systematic axis. rel_volume itself is built on "
            "production's own 20-bar log-volume baseline (`feature.hmm.vol_window`), so the "
            "60-bar correlation window sits on top of that, not instead of it."
        ),
    ),
}

_AXIS_BUILDERS = {
    "systematic": _build_systematic,
    "persistence": _build_persistence,
    "tail": _build_tail,
    "volume_price": _build_volume_price,
}


def _build_context(
    timestamps: list,
    closes: list[float],
    volumes: list[float],
    vol_window: int,
    symbol: str,
    tf: str,
    bench_by_ts: dict | None,
) -> _SeriesContext | None:
    """Log returns + rel_volume (+ benchmark returns on the intersecting timestamps).

    `rel_volume` is built exactly as `_build_obs_matrix` builds column 4 -- log volume minus its
    own `vol_window` rolling mean -- so the volume_price axis measures a relationship involving
    production's own volume anomaly, not a new definition of it.
    """
    closes_arr = np.asarray(closes, dtype=float)
    volumes_arr = np.maximum(np.asarray(volumes, dtype=float), 1.0)
    if len(closes_arr) < 2:
        return None

    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))
    log_volumes = np.log(volumes_arr[1:])
    ts_shifted = timestamps[1:]

    volume_windows = _sliding(log_volumes, vol_window)
    rolling_mean_logvol = _place(
        None if volume_windows is None else volume_windows.mean(axis=1),
        len(log_volumes),
        vol_window,
    )
    rel_volume = log_volumes - rolling_mean_logvol

    bench_returns = None
    if bench_by_ts is not None:
        keep = np.array([ts in bench_by_ts for ts in ts_shifted], dtype=bool)
        if not keep.any():
            return None
        log_returns = log_returns[keep]
        rel_volume = rel_volume[keep]
        bench_returns = np.array(
            [bench_by_ts[ts] for ts, k in zip(ts_shifted, keep, strict=True) if k], dtype=float
        )

    return _SeriesContext(
        symbol=symbol,
        tf=tf,
        log_returns=log_returns,
        rel_volume=rel_volume,
        bench_returns=bench_returns,
    )


def _finalize_features(raw: np.ndarray) -> tuple[np.ndarray, dict]:
    """Trim the warm-up prefix, forward-fill any residual interior gaps, report both.

    Interior non-finite values are forward-filled rather than dropped: dropping breaks the
    contiguity an HMM's transition matrix is estimated from, and filling with a constant would
    invent a value the statistic never took. Forward-fill is the natural choice for a
    slowly-varying rolling statistic. The fill fraction is reported so a cell whose statistic is
    undefined too often is visible rather than silent.
    """
    finite_rows = np.isfinite(raw).all(axis=1)
    if not finite_rows.any():
        return np.empty((0, raw.shape[1])), {"n_warmup": len(raw), "interior_fill_fraction": 1.0}
    start = int(np.argmax(finite_rows))
    trimmed = raw[start:].copy()

    gaps = ~np.isfinite(trimmed).all(axis=1)
    n_gaps = int(np.count_nonzero(gaps))
    if n_gaps:
        for col in range(trimmed.shape[1]):
            column = trimmed[:, col]
            bad = ~np.isfinite(column)
            if bad.any():
                idx = np.where(~bad, np.arange(len(column)), 0)
                np.maximum.accumulate(idx, out=idx)
                trimmed[:, col] = column[idx]
    return trimmed, {
        "n_warmup": start,
        "interior_fill_fraction": n_gaps / max(len(trimmed), 1),
    }


# ---------------------------------------------------------------------------
# Window-stability probe
# ---------------------------------------------------------------------------


def _lag1_autocorr(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if len(finite) < 3:
        return float("nan")
    centered = finite - finite.mean()
    denom = float((centered * centered).sum())
    if denom <= 0:
        return float("nan")
    return float((centered[1:] * centered[:-1]).sum() / denom)


_MIN_PROBE_BLOCKS = 10


def _block_reliability(statistic: np.ndarray, window: int) -> tuple[float, int]:
    """Correlation between the statistic on ADJACENT DISJOINT windows, and the pair count.

    A right-aligned rolling statistic evaluated at index `i*window - 1` is exactly the
    statistic of block [(i-1)*window, i*window). Subsampling at that stride therefore yields a
    sequence of estimates on non-overlapping data; correlating it with its own one-step lag
    measures only structure that survives a full block boundary. Sampling noise cannot
    contribute, because no observation is shared between the two members of a pair.
    """
    values = statistic[window - 1 :: window]
    values = values[np.isfinite(values)]
    n_pairs = len(values) - 1
    if n_pairs < _MIN_PROBE_BLOCKS:
        return float("nan"), max(n_pairs, 0)
    first, second = values[:-1], values[1:]
    first_centered = first - first.mean()
    second_centered = second - second.mean()
    denom = float(np.sqrt((first_centered**2).sum() * (second_centered**2).sum()))
    if denom <= 0:
        return float("nan"), n_pairs
    return float((first_centered * second_centered).sum() / denom), n_pairs


def _run_probe_cell(job: dict) -> dict:
    """Split-half reliability of an axis's PRIMARY statistic at one window, plus its null.

    The null jointly permutes every series the axis consumes, so the unconditional
    distribution and any contemporaneous cross-series relationship are preserved exactly while
    all time dependence is destroyed; its reliability must come out ~0. Compute-only: no DB
    handle, no writes.
    """
    ctx: _SeriesContext = job["ctx"]
    window = job["window"]
    builder = _AXIS_BUILDERS[job["axis"]]

    real_raw, _ = builder(ctx, window)
    real_primary = real_raw[:, 0]
    real_finite = real_primary[np.isfinite(real_primary)]
    reliability, n_pairs = _block_reliability(real_primary, window)
    if len(real_finite) < 3 or not np.isfinite(reliability):
        return {
            "symbol": ctx.symbol,
            "tf": ctx.tf,
            "axis": job["axis"],
            "window": window,
            "insufficient": True,
            "n_block_pairs": n_pairs,
        }

    rng = np.random.default_rng(job["seed"])
    null_reliabilities: list[float] = []
    null_stds: list[float] = []
    null_ac1s: list[float] = []
    for _ in range(job["replicates"]):
        order = rng.permutation(len(ctx.log_returns))
        shuffled = _SeriesContext(
            symbol=ctx.symbol,
            tf=ctx.tf,
            log_returns=ctx.log_returns[order],
            rel_volume=ctx.rel_volume[order],
            bench_returns=None if ctx.bench_returns is None else ctx.bench_returns[order],
        )
        null_primary = builder(shuffled, window)[0][:, 0]
        null_finite = null_primary[np.isfinite(null_primary)]
        if len(null_finite) < 3:
            continue
        null_reliability, _ = _block_reliability(null_primary, window)
        if np.isfinite(null_reliability):
            null_reliabilities.append(null_reliability)
        null_stds.append(float(null_finite.std()))
        null_ac1s.append(_lag1_autocorr(null_primary))

    return {
        "symbol": ctx.symbol,
        "tf": ctx.tf,
        "axis": job["axis"],
        "window": window,
        "insufficient": False,
        "n_obs": int(len(ctx.log_returns)),
        "n_block_pairs": n_pairs,
        "block_reliability": reliability,
        "null_block_reliability": (
            float(np.mean(null_reliabilities)) if null_reliabilities else float("nan")
        ),
        # Descriptive only -- see the module docstring for why neither is a verdict.
        "real_std": float(real_finite.std()),
        "null_std": float(np.mean(null_stds)) if null_stds else float("nan"),
        "real_ac1": _lag1_autocorr(real_primary),
        "null_ac1": float(np.mean(null_ac1s)) if null_ac1s else float("nan"),
    }


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def _print_probe_summary(probe_rows: list[dict], axes: list[str], probe_windows: list[int]) -> None:
    print("\n" + "=" * 108)
    print("WINDOW-STABILITY PROBE -- what fraction of the primary statistic's variation is real?")
    print("block_reliability = corr of the statistic across ADJACENT DISJOINT windows. The two")
    print("estimates share no data, so this IS the signal fraction: 0.05 means 95% of what the")
    print("HMM would fit is estimation noise. null = same on an IID-permuted series and must be")
    print("~0.00 -- that is the instrument's calibration check, not a comparison.")
    print("=" * 108)
    print(
        f"{'axis':<13} {'window':>6} {'tf':>4} {'median_reliab':>14} {'min_reliab':>11} "
        f"{'max_reliab':>11} {'median_null':>12} {'med_pairs':>10} {'cells':>6}"
    )
    for axis in axes:
        for window in probe_windows:
            for tf in sorted({r["tf"] for r in probe_rows}):
                rows = [
                    r
                    for r in probe_rows
                    if r["axis"] == axis
                    and r["window"] == window
                    and r["tf"] == tf
                    and not r.get("insufficient")
                ]
                reliabilities = [
                    r["block_reliability"] for r in rows if np.isfinite(r["block_reliability"])
                ]
                if not reliabilities:
                    continue
                nulls = [
                    r["null_block_reliability"]
                    for r in rows
                    if np.isfinite(r["null_block_reliability"])
                ]
                print(
                    f"{axis:<13} {window:>6} {tf:>4} {float(np.median(reliabilities)):>14.3f} "
                    f"{float(min(reliabilities)):>11.3f} {float(max(reliabilities)):>11.3f} "
                    f"{(float(np.median(nulls)) if nulls else float('nan')):>12.3f} "
                    f"{float(np.median([r['n_block_pairs'] for r in rows])):>10.0f} {len(rows):>6}"
                )


def _summarize(
    all_results: list[dict],
    axes: list[str],
    axis_windows: dict[str, list[int]],
    k_values: list[int],
    n_top: int,
    group_by_symbol: dict[str, str],
    probe_rows: list[dict],
) -> list[dict]:
    """Per-axis verdicts. Headline is the MINIMUM across cells and the PASS COUNT, never an
    average -- an average hides exactly the non-identifiable cell this sweep exists to find."""
    results = [r for r in all_results if r["arm"] == "real"]
    print("\n" + "=" * 118)
    print(f"PER-AXIS x WINDOW x K SUMMARY at N={n_top} (min across cells + pass count)")
    print("=" * 118)
    print(
        f"{'axis':<13} {'win':>4} {'K':>2} {'pass/cells':>11} {'min_agree':>10} {'min_kappa':>10} "
        f"{'med_sep':>8} {'min_sep':>8} {'max_sols':>8} {'degen':>7}  worst_cell"
    )
    config_rows: list[dict] = []
    for axis in axes:
        for window in axis_windows[axis]:
            for k in k_values:
                for cov_type in _COV_TYPES:
                    cells = [
                        r
                        for r in results
                        if r["axis"] == axis
                        and r["window"] == window
                        and r["k"] == k
                        and r["cov_type"] == cov_type
                    ]
                    if not cells:
                        continue
                    entries = [(r, r["by_n"].get(str(n_top), {})) for r in cells]
                    valid = [(r, e) for r, e in entries if not e.get("pool_failure", True)]
                    n_pass = sum(1 for _, e in entries if _passes(e))
                    worst = min(entries, key=lambda p: p[1].get("agreement_smoothed", 0.0))
                    seps = [
                        float(e["separation_a"])
                        for _, e in valid
                        if e.get("separation_a") is not None
                        and np.isfinite(float(e["separation_a"]))
                    ]
                    degen = [f"{r['symbol']}/{r['tf']}" for r, e in valid if e.get("degenerate_a")]
                    row = {
                        "axis": axis,
                        "window": window,
                        "k": k,
                        "cov_type": cov_type,
                        "n": n_top,
                        "n_pass": n_pass,
                        "n_cells": len(cells),
                        "min_agreement": worst[1].get("agreement_smoothed", 0.0),
                        "min_kappa": min(e.get("kappa_smoothed", 0.0) for _, e in entries),
                        "median_separation": float(np.median(seps)) if seps else float("nan"),
                        "min_separation": float(min(seps)) if seps else float("nan"),
                        "max_distinct_solutions": max(
                            e.get("distinct_solutions_a", 0) for _, e in entries
                        ),
                        "n_degenerate": len(degen),
                        "degenerate_cells": degen,
                        "failing_cells": [
                            f"{r['symbol']}/{r['tf']}" for r, e in entries if not _passes(e)
                        ],
                        "worst_cell": f"{worst[0]['symbol']}/{worst[0]['tf']}",
                    }
                    config_rows.append(row)
                    print(
                        f"{axis:<13} {window:>4} {k:>2} {n_pass:>5}/{len(cells):<5} "
                        f"{row['min_agreement']:>10.4f} {row['min_kappa']:>10.4f} "
                        f"{row['median_separation']:>8.2f} {row['min_separation']:>8.2f} "
                        f"{row['max_distinct_solutions']:>8} "
                        f"{len(degen):>3}/{len(valid):<3}  {row['worst_cell']}"
                    )

    print("\n" + "=" * 118)
    print("VERDICT PER AXIS (clean = clears BOTH identifiability bars on ALL cells AND is")
    print("0-degenerate on production's own occupation gate AND has non-trivial separation)")
    print("=" * 118)
    for axis in axes:
        rows = [r for r in config_rows if r["axis"] == axis]
        clean = [r for r in rows if r["n_pass"] == r["n_cells"] and r["n_degenerate"] == 0]
        if not clean:
            best = max(rows, key=lambda r: (r["n_pass"], r["min_agreement"]), default=None)
            if best is None:
                continue
            print(
                f"{axis:<13}: NO CONFIG CLEAN -- best is window={best['window']} K={best['k']} at "
                f"{best['n_pass']}/{best['n_cells']} identifiable, {best['n_degenerate']} "
                f"degenerate (min_agree={best['min_agreement']:.4f}, worst={best['worst_cell']})"
            )
            continue
        clean.sort(key=lambda r: (r["k"], -r["min_agreement"]))
        top = clean[0]
        also = ", ".join(f"w{r['window']}/K{r['k']}" for r in clean[1:])
        print(
            f"{axis:<13}: CLEAN at window={top['window']} K={top['k']} "
            f"(min_agree={top['min_agreement']:.4f} min_kappa={top['min_kappa']:.4f} "
            f"min_sep={top['min_separation']:.2f}){'  also: ' + also if also else ''}"
        )

    print("\n" + "=" * 118)
    print("FAILURE / DEGENERACY BY REGIME GROUP (does the fx/commodity/rates/intl split the")
    print("trend axis showed reappear here?  group from ic_engine._build_symbol_regime_class)")
    print("=" * 118)
    groups = sorted({group_by_symbol.get(s, "UNROUTED") for s in {r["symbol"] for r in results}})
    print(f"{'axis':<13} {'win':>4} {'K':>2} " + "".join(f"{g[:11]:>13}" for g in groups))
    for row in config_rows:
        cells_by_group: dict[str, tuple[int, int]] = {}
        for group in groups:
            bad = [
                c
                for c in set(row["failing_cells"]) | set(row["degenerate_cells"])
                if group_by_symbol.get(c.split("/")[0], "UNROUTED") == group
            ]
            total = sum(
                1
                for r in results
                if r["axis"] == row["axis"]
                and r["window"] == row["window"]
                and r["k"] == row["k"]
                and group_by_symbol.get(r["symbol"], "UNROUTED") == group
            )
            cells_by_group[group] = (len(bad), total)
        print(
            f"{row['axis']:<13} {row['window']:>4} {row['k']:>2} "
            + "".join(f"{f'{b}/{t}':>13}" for b, t in (cells_by_group[g] for g in groups))
        )

    print("\n" + "=" * 118)
    print(f"PER-CELL MATRIX at N={n_top} (agreement / kappa; * = clears both bars; D = degenerate)")
    print("=" * 118)
    cells = sorted({(r["symbol"], r["tf"]) for r in results}, key=lambda x: (x[1], x[0]))
    for axis in axes:
        configs = [(w, k) for w in axis_windows[axis] for k in k_values]
        print(f"\n-- axis: {axis}  [{_AXIS_SPECS[axis].gloss}]")
        print(f"{'cell':<12}{'group':<11}" + "".join(f"{f'w{w}/K{k}':>17}" for w, k in configs))
        for symbol, tf in cells:
            group = group_by_symbol.get(symbol, "UNROUTED")
            line = f"{symbol + '/' + tf:<12}{group:<11}"
            for window, k in configs:
                match = next(
                    (
                        r
                        for r in results
                        if r["symbol"] == symbol
                        and r["tf"] == tf
                        and r["axis"] == axis
                        and r["window"] == window
                        and r["k"] == k
                    ),
                    None,
                )
                if match is None:
                    line += f"{'-':>17}"
                    continue
                entry = match["by_n"].get(str(n_top), {})
                mark = "*" if _passes(entry) else " "
                mark += "D" if entry.get("degenerate_a") else " "
                line += (
                    f"{entry.get('agreement_smoothed', 0.0):>7.3f}/"
                    f"{entry.get('kappa_smoothed', 0.0):>6.3f}{mark}"
                )
            print(line)

    print("\n" + "=" * 118)
    print(f"MECHANISM at N={n_top}: is a failure near-tied optima, or something else?")
    print("(near-tied signature = many distinct solutions AND a tiny relative ll spread)")
    print("=" * 118)
    print(
        f"{'axis':<13} {'win':>4} {'K':>2} {'med_sols':>9} {'max_sols':>9} "
        f"{'med_ll_spread':>14} {'med_sep':>8} {'min_occ':>8}"
    )
    for axis in axes:
        for window in axis_windows[axis]:
            for k in k_values:
                entries = [
                    r["by_n"].get(str(n_top), {})
                    for r in results
                    if r["axis"] == axis and r["window"] == window and r["k"] == k
                ]
                entries = [e for e in entries if not e.get("pool_failure", True)]
                if not entries:
                    continue
                seps = [
                    float(e["separation_a"])
                    for e in entries
                    if e.get("separation_a") is not None and np.isfinite(float(e["separation_a"]))
                ]
                print(
                    f"{axis:<13} {window:>4} {k:>2} "
                    f"{float(np.median([e.get('distinct_solutions_a', 0) for e in entries])):>9.1f} "
                    f"{max(e.get('distinct_solutions_a', 0) for e in entries):>9} "
                    f"{float(np.median([e.get('ll_spread_relative_a', 0.0) for e in entries])):>14.6f} "
                    f"{(float(np.median(seps)) if seps else float('nan')):>8.2f} "
                    f"{min(e.get('min_occupation_a', 0.0) for e in entries):>8.3f}"
                )

    null_results = [r for r in all_results if r["arm"] == "null"]
    if null_results:
        print("\n" + "=" * 118)
        print("NULL-ARM CONTROL: the SAME configuration fit on IID-permuted series (no regime")
        print("exists by construction). A null arm that passes as cleanly as the real arm proves")
        print("the agreement/kappa/separation/occupation gates do not discriminate for that axis.")
        print("=" * 118)
        print(
            f"{'axis':<13} {'win':>4} {'K':>2} {'real pass':>10} {'NULL pass':>10} "
            f"{'real min_agree':>15} {'NULL min_agree':>15} {'real med_sep':>13} "
            f"{'NULL med_sep':>13}"
        )
        for row in config_rows:
            null_cells = [
                r
                for r in null_results
                if r["axis"] == row["axis"] and r["window"] == row["window"] and r["k"] == row["k"]
            ]
            if not null_cells:
                continue
            null_entries = [r["by_n"].get(str(n_top), {}) for r in null_cells]
            null_seps = [
                float(e["separation_a"])
                for e in null_entries
                if e.get("separation_a") is not None and np.isfinite(float(e["separation_a"]))
            ]
            print(
                f"{row['axis']:<13} {row['window']:>4} {row['k']:>2} "
                f"{f'{row['n_pass']}/{row['n_cells']}':>10} "
                f"{f'{sum(1 for e in null_entries if _passes(e))}/{len(null_entries)}':>10} "
                f"{row['min_agreement']:>15.4f} "
                f"{min(e.get('agreement_smoothed', 0.0) for e in null_entries):>15.4f} "
                f"{row['median_separation']:>13.2f} "
                f"{(float(np.median(null_seps)) if null_seps else float('nan')):>13.2f}"
            )

    print("\n" + "=" * 118)
    print("DISCRIMINATING SUMMARY. An axis earns a REAL verdict only if it (a) identifies on")
    print("every cell, (b) is clean on production's occupation gate, and (c) has a median")
    print("block_reliability above the signal floor -- (a)+(b) alone are satisfied by a threshold")
    print("split of pure noise, as the null-arm column demonstrates. 'gate informative' records")
    print("whether the identifiability gate separated the real arm from the null arm AT ALL; it")
    print("is evidence about the INSTRUMENT, not a term in the axis's verdict.")
    print(f"signal floor = {_RELIABILITY_FLOOR} [initial_estimate, uncalibrated -- see doc]")
    print("=" * 118)
    print(
        f"{'axis':<13} {'win':>4} {'K':>2} {'identifies':>11} {'occupation':>11} "
        f"{'null arm':>10} {'gate informative':>17} {'med reliability':>16} {'VERDICT':>10}"
    )
    for row in config_rows:
        null_entries = [
            r["by_n"].get(str(n_top), {})
            for r in null_results
            if r["axis"] == row["axis"] and r["window"] == row["window"] and r["k"] == row["k"]
        ]
        null_pass = sum(1 for e in null_entries if _passes(e))
        reliabilities = [
            r["block_reliability"]
            for r in probe_rows
            if r["axis"] == row["axis"]
            and r["window"] == row["window"]
            and not r.get("insufficient")
            and np.isfinite(r.get("block_reliability", np.nan))
        ]
        median_reliability = float(np.median(reliabilities)) if reliabilities else float("nan")
        identifies = row["n_pass"] == row["n_cells"]
        occupation_ok = row["n_degenerate"] == 0
        row["median_block_reliability"] = median_reliability
        row["null_arm_pass"] = null_pass
        row["null_arm_cells"] = len(null_entries)
        row["verdict"] = (
            "REAL"
            if identifies and occupation_ok and median_reliability > _RELIABILITY_FLOOR
            else "NOT REAL"
        )
        gate_informative = (
            "n/a"
            if not null_entries
            else ("yes" if null_pass / len(null_entries) < row["n_pass"] / row["n_cells"] else "NO")
        )
        print(
            f"{row['axis']:<13} {row['window']:>4} {row['k']:>2} "
            f"{('yes' if identifies else f'{row["n_pass"]}/{row["n_cells"]}'):>11} "
            f"{('clean' if occupation_ok else f'{row["n_degenerate"]} degen'):>11} "
            f"{(f'{null_pass}/{len(null_entries)}' if null_entries else 'n/a'):>10} "
            f"{gate_informative:>17} {median_reliability:>16.3f} {row['verdict']:>10}"
        )
    print("=" * 118)
    return config_rows


def _load_regime_groups(conn: psycopg.Connection, symbols: list[str]) -> dict[str, str]:
    """symbol -> regime_group via the SAME mechanism ic_engine uses (`alpha.regime.groups`
    tag_filter prefixes over `instrument_tags`), so any group-specific recommendation this
    sweep makes is expressed in the routing that already exists rather than a new one."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_value FROM config_state WHERE config_key = 'alpha.regime.groups'"
        )
        row = cur.fetchone()
        group_configs = json.loads(row[0]) if row and row[0] else []
        cur.execute(
            "SELECT symbol, array_agg(tag) FROM instrument_tags WHERE symbol = ANY(%s) "
            "GROUP BY symbol",
            (symbols,),
        )
        tags_by_symbol = {symbol: set(tags) for symbol, tags in cur.fetchall()}
    conn.commit()
    return _build_symbol_regime_class(tags_by_symbol, group_configs)


def _parse_axis_windows(raw: str | None, axes: list[str]) -> dict[str, list[int]]:
    grid = {axis: list(_AXIS_SPECS[axis].default_windows) for axis in axes}
    if not raw:
        return grid
    for chunk in raw.split(";"):
        if not chunk.strip():
            continue
        axis, _, values = chunk.partition(":")
        grid[axis.strip()] = [int(v) for v in values.split(",") if v.strip()]
    return grid


def main() -> None:  # noqa: C901
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--tf", nargs="+", default=_DEFAULT_TFS)
    parser.add_argument("--axes", nargs="+", default=list(_AXIS_SPECS))
    parser.add_argument(
        "--axis-windows",
        default=None,
        help="Override per-axis window grid, e.g. 'tail:120,250;systematic:60'.",
    )
    parser.add_argument("--k-values", nargs="+", type=int, default=_DEFAULT_K_VALUES)
    parser.add_argument("--n-values", nargs="+", type=int, default=_DEFAULT_N_VALUES)
    parser.add_argument("--max-n", type=int, default=None)
    parser.add_argument("--pool-a-base", type=int, default=None)
    parser.add_argument("--pool-b-base", type=int, default=1000)
    parser.add_argument("--benchmark", default=_BENCHMARK_SYMBOL)
    parser.add_argument("--probe-windows", nargs="+", type=int, default=_PROBE_WINDOWS)
    parser.add_argument("--probe-replicates", type=int, default=_PROBE_REPLICATES)
    parser.add_argument("--skip-probe", action="store_true")
    parser.add_argument(
        "--skip-null-arm",
        action="store_true",
        help="Skip the IID-permutation control arm. Halves runtime; do NOT use for a verdict "
        "run -- without it a passing identifiability number cannot be distinguished from a "
        "reproducible threshold split of noise.",
    )
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--results-path", default=str(_RESULTS_PATH))
    args = parser.parse_args()

    axis_windows = _parse_axis_windows(args.axis_windows, args.axes)
    max_n = args.max_n if args.max_n is not None else max(args.n_values)
    settings = Settings()
    conn = psycopg.connect(settings.database_url)
    cfg = _load_config(conn)

    n_iter = int(cfg["feature.hmm.n_iter"])
    full_cov_min_obs = int(cfg["feature.hmm.full_cov_min_obs"])
    min_hold_bars = int(cfg["feature.hmm.min_hold_bars"])
    min_state_occupation = float(cfg["feature.hmm.min_state_occupation"])
    vol_window = int(cfg["feature.hmm.vol_window"])
    pool_a_base = (
        args.pool_a_base if args.pool_a_base is not None else int(cfg["alpha.hmm.random_state"])
    )
    group_by_symbol = _load_regime_groups(conn, list(args.symbols))

    print("=" * 108)
    print("Candidate single-security regime AXES: standalone identifiability sweep")
    print("=" * 108)
    for axis in args.axes:
        spec = _AXIS_SPECS[axis]
        print(
            f"  axis {axis:<13} cols={spec.columns} windows={axis_windows[axis]} "
            f"K={args.k_values}  [{spec.gloss}]"
        )
    print(f"symbols={len(args.symbols)} tf={args.tf} benchmark={args.benchmark}")
    print(f"n_values={args.n_values} max_n={max_n}  standardize=True (production parity)")
    print(
        f"n_iter={n_iter} full_cov_min_obs={full_cov_min_obs} min_hold_bars={min_hold_bars} "
        f"min_state_occupation={min_state_occupation} vol_window={vol_window}"
    )
    print(f"pool_a_base={pool_a_base} pool_b_base={args.pool_b_base}")
    print(f"bars: agreement>={_AGREEMENT_THRESHOLD} AND kappa>={_KAPPA_THRESHOLD} (both required)")
    print(
        "regime groups: "
        + ", ".join(f"{s}={group_by_symbol.get(s, 'UNROUTED')}" for s in args.symbols)
    )
    print("=" * 108)

    needs_benchmark = any(_AXIS_SPECS[a].needs_benchmark for a in args.axes)
    contexts: dict[tuple[str, str], _SeriesContext] = {}
    contexts_with_bench: dict[tuple[str, str], _SeriesContext] = {}
    for tf in args.tf:
        bench_by_ts: dict | None = None
        if needs_benchmark:
            bench_ts, bench_closes, _ = _fetch_ohlcv(conn, args.benchmark, tf)
            if len(bench_ts) < 2:
                print(f"SKIP benchmark {args.benchmark}/{tf}: no OHLCV rows")
            else:
                bench_arr = np.asarray(bench_closes, dtype=float)
                bench_returns = np.log(bench_arr[1:] / np.maximum(bench_arr[:-1], 1e-12))
                bench_by_ts = dict(zip(bench_ts[1:], bench_returns, strict=True))

        for symbol in args.symbols:
            timestamps, closes, volumes = _fetch_ohlcv(conn, symbol, tf)
            if len(timestamps) < 2:
                print(f"SKIP {symbol}/{tf}: no OHLCV rows")
                continue
            ctx = _build_context(timestamps, closes, volumes, vol_window, symbol, tf, None)
            if ctx is None or len(ctx.log_returns) < _MIN_OBS:
                print(f"SKIP {symbol}/{tf}: insufficient history")
                continue
            contexts[(symbol, tf)] = ctx
            print(f"loaded {symbol}/{tf}: n_returns={len(ctx.log_returns)}")

            # The benchmark cannot be regressed on itself -- R^2 == 1 and beta == 1 by
            # construction, a degenerate cell that would silently pad the pass count.
            if bench_by_ts is not None and symbol != args.benchmark:
                ctx_bench = _build_context(
                    timestamps, closes, volumes, vol_window, symbol, tf, bench_by_ts
                )
                if ctx_bench is not None and len(ctx_bench.log_returns) >= _MIN_OBS:
                    contexts_with_bench[(symbol, tf)] = ctx_bench
                    print(
                        f"       {symbol}/{tf} joined to {args.benchmark}: "
                        f"n_overlap={len(ctx_bench.log_returns)}"
                    )
    conn.close()

    def _context_for(axis: str, cell: tuple[str, str]) -> _SeriesContext | None:
        return (contexts_with_bench if _AXIS_SPECS[axis].needs_benchmark else contexts).get(cell)

    probe_rows: list[dict] = []
    probe_jobs: list[dict] = []
    if not args.skip_probe:
        for axis in args.axes:
            for cell in sorted(contexts):
                ctx = _context_for(axis, cell)
                if ctx is None:
                    continue
                trimmed = _SeriesContext(
                    symbol=ctx.symbol,
                    tf=ctx.tf,
                    log_returns=ctx.log_returns[-_PROBE_MAX_BARS:],
                    rel_volume=ctx.rel_volume[-_PROBE_MAX_BARS:],
                    bench_returns=(
                        None if ctx.bench_returns is None else ctx.bench_returns[-_PROBE_MAX_BARS:]
                    ),
                )
                for window in args.probe_windows:
                    probe_jobs.append(
                        {
                            "ctx": trimmed,
                            "axis": axis,
                            "window": window,
                            "replicates": args.probe_replicates,
                            "seed": pool_a_base,
                        }
                    )

    sweep_jobs: list[dict] = []
    build_diagnostics: list[dict] = []
    arms = ["real"] if args.skip_null_arm else ["real", "null"]
    print(f"\nbuilding observation matrices for {len(args.axes)} axes, arms={arms}...")
    for axis in args.axes:
        builder = _AXIS_BUILDERS[axis]
        for cell in sorted(contexts):
            ctx = _context_for(axis, cell)
            if ctx is None:
                continue
            # One permutation per cell, shared across that cell's windows and K values, so the
            # null arm is a single coherent counterfactual series rather than a different
            # scramble per configuration.
            order = np.random.default_rng(pool_a_base).permutation(len(ctx.log_returns))
            ctx_by_arm = {
                "real": ctx,
                "null": _SeriesContext(
                    symbol=ctx.symbol,
                    tf=ctx.tf,
                    log_returns=ctx.log_returns[order],
                    rel_volume=ctx.rel_volume[order],
                    bench_returns=None if ctx.bench_returns is None else ctx.bench_returns[order],
                ),
            }
            for window in axis_windows[axis]:
                for arm in arms:
                    raw, build_info = builder(ctx_by_arm[arm], window)
                    obs_raw, trim_info = _finalize_features(raw)
                    build_diagnostics.append(
                        {
                            "symbol": ctx.symbol,
                            "tf": ctx.tf,
                            "axis": axis,
                            "window": window,
                            "arm": arm,
                            "n_obs": int(len(obs_raw)),
                            **build_info,
                            **trim_info,
                        }
                    )
                    if len(obs_raw) < _MIN_OBS:
                        print(
                            f"SKIP {ctx.symbol}/{ctx.tf} axis={axis} w={window} arm={arm}: "
                            f"n_obs={len(obs_raw)}"
                        )
                        continue
                    if (
                        arm == "real"
                        and trim_info["interior_fill_fraction"] > _MAX_INTERIOR_FILL_FRACTION
                    ):
                        print(
                            f"WARN {ctx.symbol}/{ctx.tf} axis={axis} w={window}: statistic "
                            f"undefined on {trim_info['interior_fill_fraction']:.2%} of interior "
                            "bars (forward-filled)"
                        )
                    obs = StandardScaler().fit_transform(obs_raw)
                    for k in args.k_values:
                        for cov_type in _COV_TYPES:
                            sweep_jobs.append(
                                {
                                    "symbol": ctx.symbol,
                                    "tf": ctx.tf,
                                    "axis": axis,
                                    "window": window,
                                    "arm": arm,
                                    "obs": obs,
                                    "k": k,
                                    "cov_type": cov_type,
                                    "n_iter": n_iter,
                                    "full_cov_min_obs": full_cov_min_obs,
                                    "min_hold_bars": min_hold_bars,
                                    "min_state_occupation": min_state_occupation,
                                    "pool_a_base": pool_a_base,
                                    "pool_b_base": args.pool_b_base,
                                    "max_n": max_n,
                                    "n_values": args.n_values,
                                }
                            )

    # Heaviest jobs first: with a fixed worker pool, dispatching the long tail last leaves
    # workers idle at the end.
    sweep_jobs.sort(key=lambda j: -(len(j["obs"]) * j["k"]))
    print(f"{len(probe_jobs)} probe jobs, {len(sweep_jobs)} sweep jobs queued\n")

    results: list[dict] = []
    t_start = time.monotonic()
    with _make_worker_pool(args.max_workers, _BLAS_THREADS_PER_WORKER) as pool:
        if probe_jobs:
            for future in as_completed([pool.submit(_run_probe_cell, j) for j in probe_jobs]):
                probe_rows.append(future.result())
            print(f"probe done in {time.monotonic() - t_start:.0f}s")
            _print_probe_summary(probe_rows, args.axes, args.probe_windows)

        t_sweep = time.monotonic()
        print()
        futures = {pool.submit(_run_config_cell, job): job for job in sweep_jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            result["window"] = futures[future]["window"]
            result["arm"] = futures[future]["arm"]
            results.append(result)
            entry = result["by_n"].get(str(max_n), {})
            print(
                f"[{done}/{len(sweep_jobs)}] {result['symbol']}/{result['tf']} "
                f"axis={result['axis']:<12} w={result['window']:<3} K={result['k']} "
                f"arm={result['arm']:<4} "
                f"agree={entry.get('agreement_smoothed', float('nan')):.4f} "
                f"kappa={entry.get('kappa_smoothed', float('nan')):.4f} "
                f"sep={entry.get('separation_a', float('nan')):.2f} "
                f"sols={entry.get('distinct_solutions_a', -1)} "
                f"occ={entry.get('min_occupation_a', float('nan')):.3f} "
                f"({result['fit_seconds']:.0f}s)",
                flush=True,
            )
    print(
        f"\nsweep done in {time.monotonic() - t_sweep:.0f}s (total {time.monotonic() - t_start:.0f}s)"
    )

    config_rows = _summarize(
        results, args.axes, axis_windows, args.k_values, max_n, group_by_symbol, probe_rows
    )

    out_path = Path(args.results_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(
            {
                "agreement_threshold": _AGREEMENT_THRESHOLD,
                "kappa_threshold": _KAPPA_THRESHOLD,
                "axis_specs": {
                    a: {
                        "columns": list(_AXIS_SPECS[a].columns),
                        "gloss": _AXIS_SPECS[a].gloss,
                        "needs_benchmark": _AXIS_SPECS[a].needs_benchmark,
                        "window_rationale": _AXIS_SPECS[a].window_rationale,
                    }
                    for a in args.axes
                },
                "axis_windows": axis_windows,
                "k_values": args.k_values,
                "cov_types": _COV_TYPES,
                "n_values": args.n_values,
                "max_n": max_n,
                "benchmark": args.benchmark,
                "variance_ratio_q": _VARIANCE_RATIO_Q,
                "pool_a_base": pool_a_base,
                "pool_b_base": args.pool_b_base,
                "regime_group_by_symbol": group_by_symbol,
                "probe": probe_rows,
                "build_diagnostics": build_diagnostics,
                "config_summary": config_rows,
                "results": results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
