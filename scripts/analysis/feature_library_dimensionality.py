#!/usr/bin/env python3
"""Workstream 0a of docs/plans/2026-09-02-personal-scale-edge-determination-plan.md:
how many INDEPENDENT signals does the ~298-feature library actually contain?

Two measures, chosen because the data supports them (checked live before writing this
script, same discipline as every staged design in this repo):

1. **IC-profile independence** (feature_ic_scores, per-symbol): a feature's per-symbol IC
   profile (mean IC across regime-stratified cells, per symbol) is an 85-dimensional
   "where does this feature win/lose" fingerprint. Two features that are the same signal
   in different clothes have highly correlated fingerprints; independent signals have
   near-zero profile correlation. Eigendecomposition of the feature x feature profile
   correlation matrix + Marchenko-Pastur noise ceiling (same unsupervised method as
   statistical_factor_residual's K-selection, reused deliberately) + participation ratio
   gives the effective number of independent PREDICTIVE signals.

   Known limitation, stated: the per-symbol table covers only the 85 routed symbols
   (todos 280/283 -- unrouted expansion symbols are absent from feature_ic_scores), so
   this measures independence ON THE ROUTED SUBSET. Workstream 1 of the program fixes
   coverage; until then this number is a floor for the routed universe, not the full one.

2. **Value-space effective rank** (feature_vectors, sampled): PCA-style eigendecomposition
   of the feature correlation matrix over sampled (symbol, bar_ts) rows measures how many
   orthogonal INFORMATION directions the library spans -- redundancy of inputs, a
   different question from redundancy of predictive evidence, reported alongside because
   they can disagree (many features can share information but load it into one predictive
   direction, or vice versa).

Pre-registered interpretation bands (written BEFORE running, same discipline as every
staged design):
- Library effective rank (either measure): MP-K <= 5 = "concentrated", 6-15 = "moderate",
  > 15 = "broad".
- Range/vol family called INDEPENDENT of the momentum family iff mean cross-family
  IC-profile correlation < 0.3 (the same weak-correlation convention as
  alpha.regime_stratification.max_correlation, migration 327 -- read from APR, not
  hardcoded, per the APR mandate).
- Breadth math reported honestly: implied IR ceiling = IC x sqrt(universe_breadth x
  library_rank), universe breadth cited from effective_breadth_diagnostic.py's measured
  ~4.5-8.4. This is the "is the requirement satisfiable at all" number the program doc
  demands before more research spend.

Read-only. No writes. Deterministic: Postgres setseed(0.42) for the feature_vectors
sample, numpy seed 42 throughout.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.analysis.statistical_factor_residual_k_selection_pilot import (  # noqa: E402
    _marchenko_pastur_k,
)
from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_TF = "1d"
_LOOKAHEAD = 5  # the signal-mass peak per the program doc's driving observation
_MIN_SYMBOLS_PER_FEATURE = 40  # min common-symbol overlap for a pairwise profile corr
_MIN_FEATURES_PER_FEATURE_SET = 50  # min symbols covered for a feature to enter the matrix
_SAMPLE_FRACTION = 0.15  # of feature_vectors 1d rows, via setseed'd random()
_MIN_COL_NONNULL_FRAC = 0.5
_PG_SAMPLE_SEED = 0.42
_NP_SEED = 42

# Universe breadth measured by scripts/analysis/effective_breadth_diagnostic.py (2026-08-07),
# cited rather than recomputed -- this script's question is the LIBRARY axis of breadth.
_UNIVERSE_BREADTH_LOW = 4.5
_UNIVERSE_BREADTH_HIGH = 8.4

# Family assignment by first-match name pattern, priority order matters (a name matching
# two patterns lands in the earlier one). Derived from the corpus's own naming, not
# theory: this classifies what was BUILT, which is the library whose rank we are measuring.
_FAMILY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "momentum",
        ("momentum", "ret_lag", "ret_div", "ctf_momentum", "hma_slope", "aroon", "rsi_", "cci_"),
    ),
    ("range_vol", ("range", "atr", "vol", "hurst", "yang_zhang", "garch", "shannon", "realized")),
    (
        "structure_level",
        (
            "dist",
            "since_high",
            "since_low",
            "poc",
            "vah",
            "val_",
            "support",
            "resist",
            "swing",
            "fib",
            "gap",
            "52w",
            "opening_range",
        ),
    ),
    ("flow_volume", ("volume", "vwap", "obv", "cvd", "amihud", "flow", "body", "wick")),
    (
        "regime_macro",
        (
            "regime",
            "vix",
            "hyg",
            "tip_",
            "tlt",
            "lqd",
            "yield",
            "flight",
            "dollar",
            "uup",
            "breadth",
        ),
    ),
    (
        "calendar_session",
        ("dow_", "month_", "hour_", "session", "power_hour", "quarter", "tdom", "minute_"),
    ),
]
_CANARY_PREFIX = "canary_"
_EXCLUDE_SUFFIXES = ("_rolling",)  # VP rolling variants still belong to their family; not excluded


def _family_of(name: str) -> str:
    for family, patterns in _FAMILY_PATTERNS:
        if any(p in name for p in patterns):
            return family
    return "other"


def _fetch_ic_profiles(conn) -> pd.DataFrame:
    """feature x symbol matrix of mean per-symbol IC (regime cells averaged within
    regime_scope='cross_sectional'). Pre-registered dedupe: equal-weight mean across
    regime-stratified cells; strata with no rows for a symbol contribute nothing."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT feature_name, symbol, avg(ic_value) AS ic
            FROM feature_ic_scores
            WHERE tf = %s AND is_pooled = false AND lookahead_bars = %s
              AND reliable AND ic_value IS NOT NULL
              AND regime_scope = 'cross_sectional'
            GROUP BY feature_name, symbol
            """,
            (_TF, _LOOKAHEAD),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["feature", "symbol", "ic"])
    return df.pivot_table(index="symbol", columns="feature", values="ic", aggfunc="last")


def _nearest_psd(corr: pd.DataFrame) -> pd.DataFrame:
    """Project a pairwise-complete correlation matrix to the nearest PSD matrix
    (simplified Higham 2002: eigenvalue clipping, then rescale to unit diagonal).
    Pairwise-deletion correlations with min_periods need not be PSD -- observed live
    (eigvalsh LinAlgError on the first run) -- and MP thresholds assume a valid
    correlation spectrum, so the projection is required for correctness, not cosmetic.
    """
    arr = corr.to_numpy()
    eigvals, vecs = np.linalg.eigh((arr + arr.T) / 2)
    clipped = (vecs * np.clip(eigvals, 0.0, None)) @ vecs.T
    d = np.sqrt(np.clip(np.diag(clipped), 1e-12, None))
    psd = clipped / np.outer(d, d)
    np.fill_diagonal(psd, 1.0)
    return pd.DataFrame(psd, index=corr.index, columns=corr.columns)


def _effective_rank(corr: pd.DataFrame, label: str, profile_dim: int) -> dict:
    psd = _nearest_psd(corr)
    eigvals = np.linalg.eigvalsh(psd.to_numpy())[::-1]
    eigvals = np.clip(eigvals, 0.0, None)
    n, t = corr.shape[1], profile_dim
    mp_k, mp_ceiling = _marchenko_pastur_k(eigvals, n, t)
    participation_ratio = float(eigvals.sum() ** 2 / (eigvals**2).sum())
    print(f"\n=== {label} ===")
    print(f"features (N): {n}, profile dimension (T): {t}")
    print(f"top 10 eigenvalues: {np.round(eigvals[:10], 3).tolist()}")
    print(f"Marchenko-Pastur ceiling: {mp_ceiling:.3f} -> K={mp_k}")
    print(f"participation ratio: {participation_ratio:.2f}")
    return {"mp_k": mp_k, "pr": participation_ratio, "n": n}


def _family_correlations(profile_corr: pd.DataFrame, threshold: float) -> None:
    fams = {c: _family_of(c) for c in profile_corr.columns}
    fam_counts = pd.Series(fams).value_counts()
    print("\n=== family sizes (name-pattern assignment) ===")
    print(fam_counts.to_string())

    print("\n=== mean IC-profile correlation, within vs across families ===")
    fam_names = [f for f in fam_counts.index if f != "other"]
    for i, fa in enumerate(fam_names):
        for fb in fam_names[i:]:
            cols_a = [c for c in profile_corr.columns if fams[c] == fa]
            cols_b = [c for c in profile_corr.columns if fams[c] == fb]
            sub = profile_corr.loc[cols_a, cols_b]
            if fa == fb:
                mask = np.triu(np.ones(sub.shape), k=1).astype(bool)
                vals = sub.to_numpy()[mask]
            else:
                vals = sub.to_numpy().ravel()
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                continue
            print(
                f"  {fa:16s} vs {fb:16s}: mean={vals.mean():+.3f}  median={np.median(vals):+.3f}  n={len(vals)}"
            )

    # The program's specific question: range/vol vs momentum independence
    cols_rv = [c for c in profile_corr.columns if fams[c] == "range_vol"]
    cols_mo = [c for c in profile_corr.columns if fams[c] == "momentum"]
    sub = profile_corr.loc[cols_rv, cols_mo].to_numpy().ravel()
    sub = sub[~np.isnan(sub)]
    mean_cross = float(sub.mean())
    verdict = "INDEPENDENT" if mean_cross < threshold else "NOT INDEPENDENT"
    print(
        f"\nRange/vol vs momentum: mean cross-family IC-profile correlation = "
        f"{mean_cross:+.3f} vs APR threshold {threshold} -> {verdict}"
        f" (pre-registered rule in module docstring)"
    )


def _value_space_rank(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT setseed(%s)", (_PG_SAMPLE_SEED,))
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'feature_vectors' AND data_type IN
                  ('double precision', 'real', 'integer', 'smallint', 'bigint')
            """)
        numeric_cols = [r[0] for r in cur.fetchall()]
    exclude = {
        "bar_ts",
        "symbol",
        "tf",
        "lookahead_bars",
        "pipeline_version",
        "regime_label_source",
        "chunk_id",
        "regime_volatility_id",
    }
    feature_cols = [
        c for c in numeric_cols if c not in exclude and not c.startswith(_CANARY_PREFIX)
    ]
    quoted = ", ".join(f'"{c}"' for c in feature_cols)
    with conn.cursor() as cur:
        cur.execute("SELECT setseed(%s)", (_PG_SAMPLE_SEED,))
        cur.execute(
            f"""
            SELECT {quoted} FROM feature_vectors
            WHERE tf = %s AND random() < %s
            """,
            (_TF, _SAMPLE_FRACTION),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=feature_cols).astype(float)
    keep = [c for c in df.columns if df[c].notna().mean() >= _MIN_COL_NONNULL_FRAC]
    df = df[keep].dropna()
    # Constant/near-constant columns make .corr() emit NaN (0/0), and NaN anywhere in the
    # matrix makes LAPACK fail (observed live on the first run). Drop them before corr.
    nondegenerate = df.std() > 1e-12
    dropped = int((~nondegenerate).sum())
    if dropped:
        print(f"Dropped {dropped} constant/near-constant columns")
    df = df[nondegenerate[nondegenerate].index]
    print(f"\nValue-space sample: {df.shape[0]} rows x {df.shape[1]} complete columns")
    corr = df.corr()
    if corr.isna().any().any():
        bad = corr.columns[corr.isna().any()].tolist()
        print(f"Dropping {len(bad)} columns with unresolvable NaN correlations")
        cols = [c for c in corr.columns if c not in bad]
        corr = df[cols].corr()
    return _effective_rank(
        corr, "Value-space effective rank (feature_vectors, sampled)", df.shape[0]
    )


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache
    threshold = float(_cfg(apr_dict, "alpha.regime_stratification.max_correlation", 0.3))
    rng = np.random.default_rng(_NP_SEED)
    del rng  # pinned for reproducibility documentation; MP/PR are deterministic

    ic_matrix = _fetch_ic_profiles(conn)
    print(f"IC-profile matrix: {ic_matrix.shape[1]} features x {ic_matrix.shape[0]} symbols")

    counts = ic_matrix.notna().sum()
    keep_features = counts[counts >= _MIN_FEATURES_PER_FEATURE_SET].index
    print(f"Features with >= {_MIN_FEATURES_PER_FEATURE_SET} symbols covered: {len(keep_features)}")
    ic_matrix = ic_matrix[keep_features]
    # Degenerate-profile guard: a feature with (near-)zero variance across symbols has no
    # meaningful correlation and makes the PSD projection ill-conditioned.
    nondegenerate = ic_matrix.std(skipna=True) > 1e-12
    dropped = int((~nondegenerate).sum())
    if dropped:
        print(f"Dropped {dropped} degenerate (near-zero-variance profile) features")
    ic_matrix = ic_matrix[nondegenerate[nondegenerate].index]

    profile_dim = int(ic_matrix.notna().sum().median())
    profile_corr = ic_matrix.corr(min_periods=_MIN_SYMBOLS_PER_FEATURE)
    ic_rank = _effective_rank(
        profile_corr, "IC-profile effective rank (feature_ic_scores, per-symbol)", profile_dim
    )

    _family_correlations(profile_corr, threshold)

    value_rank = _value_space_rank(conn)
    conn.close()

    print("\n=== Breadth math (the program's go/no-go framing) ===")
    for label, rank in (
        ("IC-profile", ic_rank["mp_k"]),
        ("value-space", value_rank["mp_k"] if value_rank else 0),
    ):
        if rank <= 0:
            continue
        for breadth in (_UNIVERSE_BREADTH_LOW, _UNIVERSE_BREADTH_HIGH):
            total = rank * breadth
            for ic in (0.03, 0.05, 0.10):
                ir = ic * np.sqrt(total)
                print(
                    f"  {label} rank={rank}, universe breadth={breadth}: "
                    f"total bets={total:.0f}, IC={ic} -> implied IR ceiling={ir:.2f}"
                )
    print(
        "\nInterpretation bands (pre-registered): MP-K <=5 concentrated, 6-15 moderate, "
        ">15 broad. IR ceiling = IC x sqrt(universe_breadth x library_rank); "
        "IR < ~0.5 at realistic IC means no construction on this library can carry the "
        "endgame regardless of ingenuity (fundamental law of active management)."
    )


if __name__ == "__main__":
    main()
