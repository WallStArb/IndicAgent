"""Shared library for the nonlinear_interaction_combiner falsification test's per-tf scripts
(named nonlinear_interaction_combiner in earlier prose -- see docs/research/data-edge-source-thesis.md's 2026-08-03 rename
from ticket numbers to descriptive concept names).

Not runnable on its own (no `main()`/`if __name__ == "__main__"`) -- imported by
`nonlinear_interaction_combiner_lightgbm_check.py` (1h, the original finding) and
`nonlinear_interaction_combiner_replication_{15m,1d,5m}.py` (independent replications at other
timeframes). Same "leading-underscore filename marks an internal shared module, not a
standalone script" convention as `services/_batch_utils.py`.

Extracted 2026-08-02 (todo 232's remaining scope) after three tf-specific scripts had grown
90%+ identical `main()` bodies via copy-paste-and-recalibrate, with the imports pulling 7
underscore-prefixed "private" symbols out of the 1h script's own module namespace across
two sibling scripts -- a real separation-of-concerns violation, not just a style nit: the 1h
script was simultaneously an executable entry point and the de facto shared library for its
own replications, so a change to either role risked silently breaking the other.

`run_nonlinear_interaction_combiner_check()` is the single orchestration path every script now calls -- fetch (via
`fetch_training_matrix`, which also does the causal demeaning and feature selection),
walk-forward train, per-symbol IC, BH-FDR correction, cross-sectional rigor pass, CSV write,
verdict. Extracting it fixed two real methodological inconsistencies
the copy-paste had let drift, not just duplication: the 1h script never applied BH-FDR
correction (its own replications at 1d/15m did, and the research doc's own nonlinear_interaction_combiner bar requires it
everywhere) -- an uncorrected headline number sitting next to two corrected confirmatory
replications is a multiple-comparisons blind spot on the single most-cited nonlinear_interaction_combiner result. And 1h/1d
used an inline `df.groupby("symbol")["return_fast"].apply(lambda s: s.shift(1).expanding(...))`
for causal per-symbol demeaning while 15m used `ic_math.py`'s vectorized
`causal_entity_expanding_mean` -- two implementations of the identical causal fix, now one.
"""

from __future__ import annotations

import gc
import math
import resource
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import lightgbm as lgb
import numpy as np
import pandas as pd

from src.intelligence.ensemble.covariance import (
    compute_shrinkage_covariance,
    covariance_to_correlation,
)
from src.intelligence.ensemble.weights import (
    cluster_deflate_weights,
    derive_weights,
    mean_variance_weights,
)
from src.intelligence.statistics.ic_math import (
    _p_values_from_ic,
    apply_bh_fdr,
    build_walk_forward_folds,
    causal_entity_expanding_mean,
    circular_block_bootstrap_ic_serial,
    compute_ic_vectorized,
)

# Mirror the live APR defaults ensemble_trainer.py reads via ConfigService (verified in
# config_state 2026-08-03: alpha.ensemble.max_feature_weight=0.20, max_cluster_correlation=0.80,
# max_cluster_weight=0.40, mv_condition_max=1000, alpha.ic.shrinkage_k=100). This module is
# offline/DB-independent research code (no ConfigService dependency anywhere else in it), so
# these are hardcoded literals -- same pattern every other tf-calibrated constant in the sibling
# per-tf scripts already uses, not a fresh guess.
_LINEAR_MAX_FEATURE_WEIGHT = 0.20
_LINEAR_MAX_CLUSTER_CORR = 0.80
_LINEAR_MAX_CLUSTER_WEIGHT = 0.40
_LINEAR_MV_CONDITION_MAX = 1000.0
_LINEAR_SHRINKAGE_K = 100.0

EXCLUDE_COLS = {
    "symbol",
    "tf",
    "bar_ts",
    "feature_vector_id",
    "feature_factory_version",
    "bar_close_ts",
    "regime",
    "regime_rolling",
    "canary_acausal_placebo",
    "canary_constant",
    "canary_near_constant",
    "canary_noise_gaussian",
    "canary_noise_uniform",
    # Root-caused and cleaned at the data layer (todo 236, 2026-08-03): stale values from a
    # since-deleted K3 FeatureCache counter (dead code removed by todo 207, 2026-07-30) had
    # implausible magnitudes at every tf (e.g. 1h's max was 30,077 bars, ~13 years of continuous
    # same-regime) specifically on rows regime_writer.py's K5-authoritative fit had never
    # successfully labeled (`regime IS NULL`). `ops_stale_k3_hmm_fields_cleanup.py --apply`
    # nulled all ~10.06M affected rows corpus-wide; wherever `regime IS NOT NULL`, hmm_duration
    # was already a correct K5 value (confirmed live: max(abs()) there is 345-2284 bars across
    # every tf, entirely plausible) and was untouched. The column is data-clean now, not still
    # broken -- still excluded here as a deliberate, conservative choice: it was never a
    # meaningful driver of the already-published nonlinear_interaction_combiner results (re-verified via actual LightGBM
    # feature_importances_ on the real fitted 1h models: rank 89-233/248 across all 5 folds,
    # importance 0-3 vs ctf_momentum's 400+), so re-including it now would require re-running
    # every published number for no demonstrated benefit.
    "hmm_duration",
}

FV_FROM = """
    FROM feature_vectors fv
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
    JOIN instruments i ON i.symbol = fv.symbol
    WHERE fv.tf = $1
      AND fr.return_type = 'executable_open_to_open'
      AND fr.complete_fast = true
      AND i.is_active = true
      AND i.contract_details->>'asset_class' = 'equity'
    ORDER BY fv.bar_ts ASC, fv.symbol ASC
"""

# Wide query. Only ever PREPARED (for its column schema), never executed -- `fetch_training_matrix`
# executes the two narrower queries it derives instead. `ORDER BY (bar_ts, symbol)` is the order
# the walk-forward folds need directly, and it is a total order here because feature_vectors' PK
# is (symbol, tf, bar_ts) and tf is fixed by the $1 filter -- so both passes below see identical
# row sequences, which is what makes the two-pass split safe.
FV_SQL = "SELECT fv.*, fr.return_fast" + FV_FROM
KEY_SQL = "SELECT fv.symbol, fv.bar_ts, fr.return_fast" + FV_FROM

# Rows held in memory at once per cursor batch. Each asyncpg Record for the wide query boxes 264
# Python objects, measured at 10.3 MB per 1000 rows -- 9.4x the bytes of the float32 DataFrame
# those rows become. The old `prefetch=500_000` therefore cost 5.13GB in the cursor's own buffer
# plus another 5.13GB in the caller's accumulation list; at 25k the pair costs ~0.5GB.
_CURSOR_ROWS = 25_000


@dataclass
class TrainingMatrix:
    """What the nonlinear_interaction_combiner pipeline actually needs out of the database, and nothing else."""

    X: (
        np.ndarray
    )  # [n_valid, n_features] dtype per fetch_training_matrix's feature_dtype arg, bar_ts-major
    y: np.ndarray  # [n_valid] float64, the causally per-symbol-demeaned target
    meta: pd.DataFrame  # [n_valid] symbol + bar_ts, row-aligned with X
    feature_cols: list[str]
    n_raw: int  # rows before the causal-demeaning warmup drop
    n_symbols: int
    n_bar_ts: int


async def fetch_training_matrix(
    db_dsn: str, tf: str, target_min_periods: int, feature_dtype: type = np.float32
) -> TrainingMatrix:
    """Build X/y/meta directly, without ever materializing a wide DataFrame of every feature.

    This is the `services/ensemble_trainer.py:909-928` shape (training matrix straight from
    asyncpg rows), adopted here after the DataFrame-based path OOM-killed 15m five times in a
    row. The earlier objection -- that these scripts lean on pandas for column introspection and
    filtering -- turned out to be answerable without the wide frame: the feature-column list
    comes from the PREPARED STATEMENT's column attributes (schema, not inferred from data), and
    the only genuinely pandas-shaped step left (causal per-symbol demeaning) needs three narrow
    columns, not all 248 features.

    Why the wide frame could not be made to fit, measured rather than estimated (8.52M rows x
    264 cols at 15m, on a 29GB host shared with Postgres, kernel OOM at ~21.8GB anon-rss):

      | irreducible: X alone, float32              |  8.63 GB |
      | the wide DataFrame                         |  9.34 GB |
      | asyncpg Record buffers during fetch        | ~10.3 GB |
      | one full-frame reorder copy (`.iloc[...]`) | +9.34 GB |
      | frame + X coexisting at extraction         | 17.97 GB |

    Every full-frame pandas operation costs another ~9.3GB, and three of them were unavoidable in
    that design (fetch concat, the bar_ts-major reorder, the X extraction). Fixing them one at a
    time just moved the kill to the next one -- five OOMs at five different lines. Peak here is
    X plus one 25k-row cursor batch, ~9.2GB, which is within a factor of ~1.07 of the theoretical
    floor.

    `feature_dtype` defaults to float32, matching every already-published 1h/1d/15m nonlinear_interaction_combiner number --
    do not change the default, it would silently perturb those results. 5m (2026-08-03) briefly
    passed `np.float16` here as a memory-saving attempt and OOM-killed regardless -- root-caused
    via `superpowers:systematic-debugging`, not re-guessed: LightGBM's Python bridge
    (`lightgbm/basic.py`'s `_np2d_to_np1d`) silently upcasts any non-float32/float64 array to a
    full float32 COPY before every `Dataset` construction and `predict()` call (confirmed by
    reading the source and reproducing it directly -- `is_copy=True` on a float16 input every
    time). float16 storage therefore doesn't reduce what LightGBM actually trains on; it adds a
    second, transient float32 copy of whatever fold slice is being fit ON TOP of the resident
    float16 array, which is strictly worse than storing float32 to begin with. The prior
    "zero measurable RSS" claim was real but scale-blind: it was checked at a 2M-row synthetic
    array, where the extra float32 copy (~2GB) is noise on a 29GB host; at 5m's ~20M-row final
    fold the same copy is ~20GB, becoming the dominant term. `feature_dtype` stays a real
    parameter (float64 columns still need explicit downcasting at the source), but nothing in
    this module should ever pass float16 to it again -- LightGBM's own bridge makes that
    strictly a memory *cost*, not a saving, regardless of tf/row count.

    Two passes, both over the same total row order:

      1. KEY_SQL -- symbol, bar_ts, return_fast only. Enough to compute the causal per-symbol
         demeaned target and therefore which rows survive the warmup drop, so `X` can be
         allocated once at exactly its final size and filled in place. ~0.7GB of narrow arrays.
      2. The wide query, streamed in `_CURSOR_ROWS` batches, each scattered straight into the
         preallocated `X` at the destination row the first pass computed.

    Correctness of the split rests on both passes returning rows in the same sequence, which
    `ORDER BY (bar_ts, symbol)` guarantees (see FV_SQL). That guarantee is also checked rather
    than assumed: pass 2 re-selects symbol/bar_ts and asserts every row matches pass 1's, so a
    future query change that broke the ordering fails loudly instead of silently training on
    a row-shuffled matrix.
    """
    conn = await asyncpg.connect(db_dsn)
    try:
        # Session-scoped only (SET, not ALTER SYSTEM) -- reverts when this connection closes,
        # never touches the live default (8MB) any other backend sees. Found live at 5m's scale
        # (2026-08-03): the default forced Postgres into a heavily disk-spilled external sort for
        # `ORDER BY (bar_ts, symbol)` over ~24.6M rows (confirmed via `pg_stat_activity`'s
        # `wait_event=BuffileRead`, not guessed), on pace to take hours. `max_parallel_workers_per_gather`
        # is 12 on this host; capping at 128MB keeps the worst case (every worker spilling
        # simultaneously) under ~900MB Postgres-side, deliberately conservative given the fetch's
        # own X allocation needs the bulk of this host's free memory concurrently.
        await conn.execute("SET work_mem = '128MB'")
        schema = await conn.prepare(FV_SQL)
        feature_cols = [
            attr.name
            for attr in schema.get_attributes()
            if attr.type.name in ("float4", "float8")
            and attr.name not in EXCLUDE_COLS
            and attr.name != "return_fast"
        ]

        # ---- Pass 1: keys + target.
        sym_parts: list[np.ndarray] = []
        ts_parts: list[np.ndarray] = []
        ret_parts: list[np.ndarray] = []

        def _flush_keys(records: list[asyncpg.Record]) -> None:
            sym_parts.append(np.array([r[0] for r in records], dtype=object))
            # int64 epoch-ns, not datetime objects: 8 bytes/row instead of ~48 for a boxed
            # tz-aware datetime, which matters at 8.5M rows.
            ts_parts.append(pd.DatetimeIndex([r[1] for r in records]).asi8)
            # float32, matching every other float column: the target is demeaned against a
            # float32 return series, so keeping the raw float8 precision here would silently
            # shift the published per-symbol ICs in their 6th significant figure relative to
            # the numbers already recorded in docs/research/data-edge-source-thesis.md.
            ret_parts.append(
                np.fromiter(
                    (np.nan if r[2] is None else r[2] for r in records),
                    dtype=np.float32,
                    count=len(records),
                )
            )

        buffer: list[asyncpg.Record] = []
        async with conn.transaction():
            async for record in conn.cursor(KEY_SQL, tf, prefetch=_CURSOR_ROWS):
                buffer.append(record)
                if len(buffer) >= _CURSOR_ROWS:
                    _flush_keys(buffer)
                    buffer = []
            if buffer:
                _flush_keys(buffer)

        symbol_raw = np.concatenate(sym_parts) if sym_parts else np.array([], dtype=object)
        bar_ts_raw = np.concatenate(ts_parts) if ts_parts else np.array([], dtype=np.int64)
        returns = np.concatenate(ret_parts) if ret_parts else np.array([], dtype=np.float32)
        # `.clear()` rather than `del`: the per-chunk pieces are ~0.9GB once concatenated and
        # there is no reason to hold both copies, but `_flush_keys` closes over these names.
        sym_parts.clear()
        ts_parts.clear()
        ret_parts.clear()
        n_raw = len(symbol_raw)

        # Causal per-symbol demeaning. `causal_entity_expanding_mean` requires (entity, time)-major
        # input, but rows arrive bar_ts-major -- so permute into symbol-major, compute, and scatter
        # the result back to the original positions. A STABLE argsort on the symbol codes alone is
        # sufficient and cheaper than a lexsort: the input is already globally time-ordered, so
        # stability preserves ascending time within each symbol. The permuted arrays are narrow
        # (~68MB each), never the feature matrix.
        symbol_codes, symbol_uniques = pd.factorize(symbol_raw)
        symbol_major = np.argsort(symbol_codes, kind="stable")
        expanding_mean = np.empty(n_raw, dtype=np.float64)
        expanding_mean[symbol_major] = causal_entity_expanding_mean(
            symbol_codes[symbol_major], returns[symbol_major], min_periods=target_min_periods
        )
        demeaned = returns - expanding_mean
        valid = ~np.isnan(demeaned)
        del expanding_mean, symbol_major, symbol_codes

        n_valid = int(valid.sum())
        # Source row -> destination row in X, or -1 for rows dropped by the warmup.
        dest = np.full(n_raw, -1, dtype=np.int64)
        dest[valid] = np.arange(n_valid, dtype=np.int64)

        y = demeaned[valid]
        symbol_valid = symbol_raw[valid]
        meta = pd.DataFrame(
            {
                "symbol": symbol_valid,
                "bar_ts": pd.DatetimeIndex(bar_ts_raw[valid]).tz_localize("UTC"),
            }
        )

        # ---- Pass 2: fill X in place.
        X = np.empty((n_valid, len(feature_cols)), dtype=feature_dtype)
        block_cols = ["symbol", "bar_ts", *feature_cols]
        feature_sql = (
            "SELECT fv.symbol, fv.bar_ts, " + ", ".join(f'fv."{c}"' for c in feature_cols) + FV_FROM
        )

        def _scatter(records: list[asyncpg.Record], row: int) -> int:
            end = row + len(records)
            block = pd.DataFrame(records, columns=block_cols)
            if not np.array_equal(block["symbol"].to_numpy(), symbol_raw[row:end]):
                raise RuntimeError(
                    f"row order diverged between fetch passes at rows {row}:{end} (symbol)"
                )
            if not np.array_equal(pd.DatetimeIndex(block["bar_ts"]).asi8, bar_ts_raw[row:end]):
                raise RuntimeError(
                    f"row order diverged between fetch passes at rows {row}:{end} (bar_ts)"
                )
            targets = dest[row:end]
            keep = targets >= 0
            if keep.any():
                # `.astype` rather than `to_numpy(dtype=...)`: a feature that is all-NULL across
                # this batch arrives as an object column of Nones, which numpy cannot cast but
                # pandas maps to NaN -- and NaN is what LightGBM wants for a missing feature.
                cast = block[feature_cols].astype(feature_dtype).to_numpy()[keep]
                X[targets[keep]] = cast
            return end

        row = 0
        buffer = []
        async with conn.transaction():
            async for record in conn.cursor(feature_sql, tf, prefetch=_CURSOR_ROWS):
                buffer.append(record)
                if len(buffer) >= _CURSOR_ROWS:
                    row = _scatter(buffer, row)
                    buffer = []
            if buffer:
                row = _scatter(buffer, row)
        if row != n_raw:
            raise RuntimeError(f"fetch passes disagree on row count: {n_raw} then {row}")
    finally:
        await conn.close()

    return TrainingMatrix(
        X=X,
        y=y,
        meta=meta,
        feature_cols=feature_cols,
        n_raw=n_raw,
        n_symbols=len(symbol_uniques),
        n_bar_ts=len(np.unique(bar_ts_raw)),
    )


def _pooled_panel_folds(
    bar_ts: np.ndarray,
    n_folds: int,
    embargo_bars: int,
    min_reliable_n: int,
) -> list[tuple[int, int, int]]:
    """Map build_walk_forward_folds' BAR-unit boundaries onto row-index slices for a pooled
    (symbol x bar_ts) panel.

    Todo 239: this module's callers used to pass `n_valid=len(X)` -- a pooled-panel ROW count,
    ~80 symbols per bar_ts -- directly to `build_walk_forward_folds`, which does all of its
    boundary arithmetic in whatever unit `n_valid` is expressed in. Every `_EMBARGO_BARS`
    constant in the sibling per-tf scripts is documented as a BAR count (e.g. "24 = 1 day of 1h
    bars"), so on an ~80-symbol panel an intended 24-bar embargo was actually ~0.3 bars of real
    train/test separation. `build_walk_forward_folds` itself is untouched (it is correct and
    shared with ic_engine.py/ensemble_ic_engine.py, where n_valid genuinely IS a bar count) --
    this function fixes only how this module's pooled-panel usage feeds it: build the fold
    boundaries over the distinct bar_ts index (where embargo_bars means what it says), then map
    each bar-index boundary back to the row index where that bar's block of rows begins. This
    also removes the split-inside-a-bar behavior the row-unit version had, where a fold boundary
    could land between two symbols of the identical bar_ts.

    Parameters
    ----------
    bar_ts:
        The panel's bar_ts column as a sortable 1-D array (e.g. int64 epoch-ns), already sorted
        ascending with every bar_ts's rows contiguous -- guaranteed by this module's
        `ORDER BY bar_ts ASC, symbol ASC` fetch (FV_SQL).

    Returns
    -------
    list[(train_end_row, test_start_row, test_end_row)]
        Row-index boundaries, one tuple per surviving fold (folds too small in BAR units are
        already dropped inside build_walk_forward_folds).
    """
    unique_bar_ts, first_row_of_bar = np.unique(bar_ts, return_index=True)
    n_bar_ts = len(unique_bar_ts)
    n_rows = len(bar_ts)

    def _bar_to_row(bar_index: int) -> int:
        if bar_index <= 0:
            return 0
        if bar_index >= n_bar_ts:
            return n_rows
        return int(first_row_of_bar[bar_index])

    folds_bar = build_walk_forward_folds(
        n_valid=n_bar_ts,
        n_folds=n_folds,
        embargo_bars=embargo_bars,
        min_reliable_n=min_reliable_n,
    )

    row_folds = []
    for test_start_bar, test_end_bar in folds_bar:
        train_end_bar = test_start_bar - embargo_bars
        if train_end_bar < min_reliable_n:
            continue
        row_folds.append(
            (_bar_to_row(train_end_bar), _bar_to_row(test_start_bar), _bar_to_row(test_end_bar))
        )
    return row_folds


def _median_impute(X: np.ndarray, median: np.ndarray) -> np.ndarray:
    """Fill NaN entries of X with the given per-column median. Returns X itself (no copy) when
    there is nothing to fill -- avoids an unconditional copy of what can be a multi-GB array at
    this module's scale. Computes the NaN mask once, reused for both the emptiness check and the
    fill, rather than scanning X for NaN twice."""
    nan_mask = np.isnan(X)
    if nan_mask.any():
        return np.where(nan_mask, median, X)
    return X


@dataclass
class LinearEnsembleFit:
    """Everything needed to score a held-out slice with fit_linear_ensemble_weights' output.
    Bundled rather than a bare weights array because scoring needs the SAME impute/standardize
    values the fit used -- see score_linear_ensemble()."""

    weights: np.ndarray
    impute_median: np.ndarray
    feature_mean: np.ndarray
    feature_std: np.ndarray


def score_linear_ensemble(fit: LinearEnsembleFit, X: np.ndarray) -> np.ndarray:
    """Impute (fit's own median) then standardize (fit's own mean/std) then dot -- the fit-time
    transform applied identically to whatever slice is being scored, never re-derived from the
    scored slice itself (that would leak information about held-out rows into their own score's
    normalization). Single expression so the intermediate imputed-but-unstandardized array isn't
    kept alive as a second full-size copy alongside the standardized one (CPython drops its
    refcount to zero as soon as this expression finishes using it)."""
    return (
        (_median_impute(X, fit.impute_median) - fit.feature_mean) / fit.feature_std
    ) @ fit.weights


def fit_linear_ensemble_weights(
    X_train: np.ndarray,
    y_train: np.ndarray,
    *,
    max_fit_rows: int = 200_000,
    rng_seed: int = 42,
) -> LinearEnsembleFit:
    """Todo 240's pre-registered comparison arm: a causally-fit, shrunk-IC-weighted linear
    combination over X_train's columns, reusing ensemble_trainer.py's own weighting primitives
    verbatim (compute_shrinkage_covariance, covariance_to_correlation, mean_variance_weights,
    derive_weights, cluster_deflate_weights) rather than inventing a fresh combination scheme for
    this test -- this is the number docs/research/data-edge-source-thesis.md's falsification
    criterion actually asks for ("must show uplift over the existing linear ensemble", not over
    one hand-picked column).

    Deliberate, documented scope reduction from the live pipeline (not a silent gap): production
    ensemble_trainer.py selects features from BH-FDR-passing `feature_ic_scores` rows, applies a
    staleness-decayed quality weight, and shrinks each feature's IC toward a category-specific
    (e.g. cross_tf, macro) leave-one-out peer-group prior sourced from that table. None of that
    exists inside a single walk-forward fold's raw feature matrix -- there is no independent
    peer-group category available here. This function uses the one defensible simplification
    available: shrink each feature's raw in-fold IC toward the mean IC of every OTHER feature in
    the same fold (one global peer group), with n_eff = the actual number of rows the fit used --
    same empirical-Bayes shrink_ic()/leave_one_out_group_prior() formula (src/intelligence/
    ensemble/shrinkage.py), a smaller peer group, not a different algorithm, but inlined
    VECTORIZED across all features at once rather than calling those two scalar functions once
    per feature: `n_eff` is identical for every feature in a given fold, so
    `leave_one_out_group_prior`'s per-call `np.sum(group_ic_values)` (the same ~250-element array
    every time) collapses to one array-level sum, and `shrink_ic`'s `w = n_eff / (n_eff + k)` is
    one scalar shared by every feature -- calling either function ~250 times per fold (5 folds x
    every nonlinear_interaction_combiner run) bought nothing the vectorized form doesn't already
    give byte-identically.

    Features are z-scored (fit sample's own mean/std) before covariance/IC-weighting and before
    scoring -- required, not optional: `compute_alpha_score`'s own module docstring states the
    live composite formula `alpha = sum(w_i * ic_sign_i * z_i)` assumes "z_i are already z-scored
    features", and this corpus's raw feature_vectors columns span a ~150x scale range (measured:
    momentum_z_fast stddev 1.02 vs resistance_age_bars stddev 31.6 on a real 1h sample) with
    several genuinely unbounded/unnormalized columns (rsi_*, adx, *_age_bars, *_duration_bars,
    trend/pool counters). Feeding raw scale into sum-to-1-normalized weights lets whichever
    column happens to have the largest raw variance dominate the score regardless of its IC --
    confirmed empirically pre-fix: the single strongest feature by |IC| contributed 114x less to
    the raw-scale score's variance than a ~4x-weaker-IC, high-variance column, and the resulting
    pooled IC roughly doubled once the identical function was re-run on z-scored inputs. IC
    itself (`compute_ic_vectorized`, Spearman/rank-based) is scale-invariant either way -- this
    only changes the covariance/weight-derivation and the final dot-product scale, but that is
    exactly where the bug was.

    Standardizing also indirectly fixes the mean-variance branch's condition-number gate: an
    unstandardized covariance's condition number scales with the raw feature-variance spread and
    structurally exceeded `_LINEAR_MV_CONDITION_MAX` on every real corpus sample checked (1424 vs
    a gate of 1000, on 300K real 1h rows) -- meaning the "try mean-variance, fall back to
    IC-proportional" structure below was silently never taking its first branch. Standardized
    covariance is far better conditioned, so the mean-variance path can now actually engage.

    Sign convention (matches services/ensemble_trainer.py's resolve_stratum_weights() exactly,
    not just its overall shape): `ic_signs = sign(ic_shrunk)` is this fold's own reference
    direction per feature (there is no separately-persisted historical IC sign available inside
    a single walk-forward fold, so this fold's own shrunk estimate IS the reference). The
    mean-variance branch signs mv_raw's OUTPUT by ic_signs BEFORE the positive-magnitude cap
    (`derive_weights(ic_signs * mv_raw, ...)`), which zeroes -- not sign-flips -- any feature
    where the unconstrained Sigma^-1.mu solve disagrees with that feature's own reference
    direction (BLOCKER 3 in ensemble_trainer.py's resolve_stratum_weights docstring: pre-signing
    the INPUT instead, or re-deriving the sign from mv_raw's own sign, is mathematically wrong
    once correlated features are involved). The IC-proportional fallback signs `|ic_shrunk|`'s
    positive-magnitude weights by the same `ic_signs` at the end, for the same reason
    aged_quality_weights is already positive-convention in production.

    `max_fit_rows` bounds the rows used to estimate IC/covariance (LedoitWolf + rankdata cost
    scale with n_obs, and the expanding-window folds' training slice is the near-entire corpus by
    the last fold -- tens of millions of rows at 5m/15m, the scale that already forced this
    module's OOM-avoidance design elsewhere). Measured directly (not estimated): this function on
    a 1M-row x 247-col float32 array peaks ~8.1GB transient above baseline, mostly
    compute_ic_vectorized's rankdata rank/sorter buffers plus LedoitWolf's internal copies. At
    15m's real scale (~8.82M rows, ~1.47M-row largest test slice, X itself ~8.7GB resident) that
    8.1GB stacks on top of the fold's live LightGBM Booster and lands within ~2GB of the exact
    OOM this module was already killed at once (todo 234, ~21.8GB anon-rss, 29GB host). 200_000
    rows (this default) is still ~800x oversampled relative to ~250 features for a Ledoit-Wolf
    shrinkage estimator explicitly designed to be stable well below n>>p, at roughly 1/5 the
    transient cost. A fixed-seed random subsample of the (already causally-bounded, strictly-
    before-the-test-fold) training slice introduces no leakage, only a smaller effective N for
    the shrinkage estimate -- which is exactly what n_eff communicates to the shrinkage formula.
    Scoring still runs on the FULL held-out test slice via score_linear_ensemble(); only
    weight-FITTING is bounded.

    NaN features (a real condition in this corpus -- LightGBM handles them natively, this linear
    combination cannot) are median-imputed using only the fit sample's own per-feature median.

    Returns
    -------
    LinearEnsembleFit
        weights: shape [n_features], to be applied to STANDARDIZED features (see
            score_linear_ensemble -- never dot this directly against raw feature values).
        impute_median, feature_mean, feature_std: the fit sample's own values, to be applied
            identically to whatever slice is later scored (score_linear_ensemble does this),
            never re-derived from the scored slice itself.
    """
    n_train = X_train.shape[0]
    if n_train > max_fit_rows:
        rng = np.random.default_rng(rng_seed)
        sample_idx = rng.choice(n_train, size=max_fit_rows, replace=False)
        X_fit = X_train[sample_idx]
        y_fit = y_train[sample_idx]
    else:
        X_fit = X_train
        y_fit = y_train

    impute_median = np.nanmedian(X_fit, axis=0)
    impute_median = np.where(np.isfinite(impute_median), impute_median, 0.0)
    X_filled = _median_impute(X_fit, impute_median)

    feature_mean = X_filled.mean(axis=0)
    feature_std = X_filled.std(axis=0)
    feature_std = np.where(feature_std > 1e-12, feature_std, 1.0)  # constant-column guard
    X_std = (X_filled - feature_mean) / feature_std

    # Spearman IC is rank-based, hence scale-invariant -- identical whether computed on X_filled
    # or X_std. Computed on X_std anyway so there is exactly one "the features used here" array
    # in this function, not two large float arrays alive simultaneously.
    ic_raw = compute_ic_vectorized(X_std, y_fit)
    ic_raw = np.where(np.isfinite(ic_raw), ic_raw, 0.0)

    # Vectorized shrink_ic()/leave_one_out_group_prior() -- see docstring above for why this is
    # the identical formula, not a fresh one.
    n_eff = float(X_std.shape[0])
    loo_prior = (ic_raw.sum() - ic_raw) / max(len(ic_raw) - 1, 1)
    shrink_weight = n_eff / (n_eff + _LINEAR_SHRINKAGE_K) if n_eff > 0 else 0.0
    ic_shrunk = shrink_weight * ic_raw + (1.0 - shrink_weight) * loo_prior
    ic_signs = np.sign(ic_shrunk)

    cov, _shrinkage = compute_shrinkage_covariance(X_std)
    corr = covariance_to_correlation(cov)

    mv_raw, _cond = mean_variance_weights(cov, ic_shrunk, _LINEAR_MV_CONDITION_MAX)
    if mv_raw is not None:
        weights = derive_weights(ic_signs * mv_raw, _LINEAR_MAX_FEATURE_WEIGHT) * ic_signs
    else:
        magnitude = derive_weights(np.abs(ic_shrunk), _LINEAR_MAX_FEATURE_WEIGHT)
        magnitude = cluster_deflate_weights(
            magnitude, corr, _LINEAR_MAX_CLUSTER_CORR, _LINEAR_MAX_CLUSTER_WEIGHT
        )
        weights = magnitude * ic_signs

    return LinearEnsembleFit(weights, impute_median, feature_mean, feature_std)


def bootstrap_ic_stats(
    score: np.ndarray, actual: np.ndarray, block_size: int, n_boot: int, seed: int
) -> dict[str, float | bool]:
    """Point Spearman IC + circular-block-bootstrap CI for one (score, actual) series,
    reusing ic_math.py's circular_block_bootstrap_ic_serial verbatim. Shared by the
    per-symbol loop and the pooled within-bar_ts rigor pass -- same statistic, different
    granularity, one implementation."""
    rng = np.random.default_rng(seed)
    ci_lower, ci_upper = circular_block_bootstrap_ic_serial(
        score.reshape(-1, 1), actual, block_size=block_size, n_boot=n_boot, rng=rng
    )
    point_ic = float(pd.Series(score).rank().corr(pd.Series(actual).rank()))
    return {
        "point_ic": point_ic,
        "ci_lower": float(ci_lower[0]),
        "ci_upper": float(ci_upper[0]),
        "passes": bool(ci_lower[0] > 0),
    }


def paired_bootstrap_ic_difference(
    score_a: np.ndarray,
    score_b: np.ndarray,
    actual: np.ndarray,
    block_size: int,
    n_boot: int,
    seed: int,
) -> dict[str, float | bool]:
    """Bootstrap CI of the PAIRED IC difference (IC(score_a) - IC(score_b) against the same
    actual), using IDENTICAL resampled row indices for both scores on every iteration -- not two
    independently bootstrapped marginal CIs.

    Why this exists rather than comparing two bootstrap_ic_stats() calls by CI non-overlap: when
    both scores are measured on the SAME rows (as tree_score and linear_score are here), their
    bootstrap ICs are strongly positively correlated -- non-overlap of two marginal CIs is a
    conservative, systematically underpowered test for whether their difference is significant
    (same reasoning as a paired vs. independent-samples t-test). The paired difference's own CI
    is the correctly-powered test for exactly this comparison.

    Reuses the same circular-block resampling mechanic ic_math.py's
    circular_block_bootstrap_ic_serial / _circular_block_bootstrap_ic use internally (shared
    block-start draw per iteration, re-rank the resampled subset every iteration -- per that
    module's own documented correctness requirement: Spearman IC is defined on ranks WITHIN THE
    SAMPLE being correlated, so reusing global pre-computed ranks across a resampled, non-
    contiguous subset silently narrows the CI). Implemented here via the public
    compute_ic_vectorized (fed a 2-column [score_a, score_b] matrix so both are re-ranked and
    correlated against the identically-resampled actual in one call) rather than importing
    ic_math.py's private _circular_block_bootstrap_ic, since that function only returns
    per-column marginal percentiles -- it discards the paired per-iteration values this needs.
    """
    n = len(actual)
    n_blocks = math.ceil(n / block_size)
    offsets = np.arange(block_size)
    X = np.column_stack([score_a, score_b])

    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = (starts[:, None] + offsets).ravel()[:n] % n
        ic_pair = compute_ic_vectorized(X[idx], actual[idx])
        diffs[b] = ic_pair[0] - ic_pair[1]

    point_a = float(pd.Series(score_a).rank().corr(pd.Series(actual).rank()))
    point_b = float(pd.Series(score_b).rank().corr(pd.Series(actual).rank()))
    ci_lower = float(np.percentile(diffs, 2.5))
    ci_upper = float(np.percentile(diffs, 97.5))
    return {
        "point_diff": point_a - point_b,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "a_significantly_better": bool(ci_lower > 0),
        "b_significantly_better": bool(ci_upper < 0),
    }


def per_symbol_ic_ci(
    df: pd.DataFrame,
    score_col: str,
    return_col: str,
    block_size: int,
    n_boot: int,
    seed: int,
    min_symbol_rows: int,
) -> pd.DataFrame:
    """Per-symbol circular-block-bootstrap IC CI. One row per symbol with sufficient
    held-out rows; symbols below `min_symbol_rows` are skipped, not zero-filled."""
    records = []
    for symbol, group in df.groupby("symbol"):
        group = group.dropna(subset=[score_col, return_col])
        if len(group) < min_symbol_rows:
            continue
        stats = bootstrap_ic_stats(
            group[score_col].to_numpy(dtype=float),
            group[return_col].to_numpy(dtype=float),
            block_size,
            n_boot,
            seed,
        )
        records.append({"symbol": symbol, "n": len(group), **stats})
    return pd.DataFrame.from_records(records)


def train_and_predict_oos(
    X: np.ndarray,
    y: np.ndarray,
    meta: pd.DataFrame,
    target_col: str,
    n_folds: int,
    embargo_bars: int,
    min_reliable_n: int,
    bootstrap_seed: int,
    return_models: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, list[lgb.LGBMRegressor]]:
    """Walk-forward: train a shallow, regularized LightGBM regressor on each expanding-window
    fold's training slice, predict on that fold's held-out test slice. Returns the full OOS
    (out-of-fold) prediction set -- every row appears in exactly one test fold, never a train
    fold, so this is a legitimate held-out population for the IC measurement above.

    Takes pre-extracted X/y arrays and a trimmed `meta` frame (symbol/bar_ts/baseline, row-aligned
    with X/y) rather than a source DataFrame + a column list. `fetch_training_matrix` never builds
    a wide frame at all, so nothing here is competing with one for memory.

    `fitted_models.append(model)` used to run unconditionally every fold regardless of
    `return_models` (todo 234, 2026-08-03 follow-on) -- every actual nonlinear_interaction_combiner caller uses the default
    `return_models=False`, but each fold's fitted `LGBMRegressor` carries its own internal
    binned `Dataset` (not freed just because the raw numpy `X_train` view is), so by the final,
    largest fold all 5 prior folds' Boosters/Datasets were still live and unreferenced-but-kept
    simultaneously -- confirmed via `journalctl`'s OOM-kill record (~21.7GB anon-rss) not
    matching X's own ~8.6GB estimate alone. Now only retained when the caller actually asked for
    them (todo 184's canary-leakage check); the default path drops each fold's model immediately
    after prediction and forces a GC pass so the next, larger fold isn't training alongside
    every prior fold's dead weight.

    Fold/embargo/seed config is passed explicitly rather than resolved from module globals --
    the sibling replication scripts used to monkeypatch the original module's `_N_FOLDS`/
    `_EMBARGO_BARS`/etc. before calling this function, which only worked because the patch
    happened to run before every call; any future reordering would have silently trained on
    another caller's calibration instead of its own (2026-08-02 follow-on, same session).

    `return_models=True` (used by todo 184's canary-leakage check, not the production path)
    additionally returns the list of per-fold fitted models for feature-importance inspection.

    Folds are expanding-window (nested), so the final fold's training slice is nearly the whole
    corpus by construction -- X necessarily stays fully resident through that last fold
    regardless of how the loop is chunked. The size print below exists so a future corpus growth
    that pushes X past available memory fails loud, with a concrete number, rather than an
    unexplained SIGKILL (CLAUDE.md: silent wrong answers are worse than loud crashes -- an OOM
    kill is already loud but not informative on its own)."""
    n_valid = len(X)
    print(
        f"Training matrix: {X.shape[0]} rows x {X.shape[1]} cols, ~{X.nbytes / 1e9:.2f}GB ({X.dtype})"
    )
    # Todo 239: fold boundaries must be computed in BAR units (this is a pooled symbol x bar_ts
    # panel, ~80 rows per bar_ts) then mapped back to row slices -- not built directly on
    # n_valid=len(X), which are ROWS. See _pooled_panel_folds' docstring for the bug this fixes.
    bar_ts_int = pd.DatetimeIndex(meta["bar_ts"]).asi8
    folds = _pooled_panel_folds(
        bar_ts_int,
        n_folds=n_folds,
        embargo_bars=embargo_bars,
        min_reliable_n=min_reliable_n,
    )
    print(f"Walk-forward folds (expanding window, embargo={embargo_bars} bars): {folds}")

    # Computed once, not per-fold: y never changes across folds, and every fold's train set is
    # a PREFIX of it ([:train_end]), so slicing the prefix first and only isnan-masking that
    # prefix (rather than rebuilding an n_valid-length bool array and re-scanning all of y on
    # every fold) is both cheaper and avoids X[train_mask] scanning the definitely-False tail.
    valid_mask = ~np.isnan(y)

    oos_frames = []
    fitted_models = []
    for k, (train_end, test_start, test_end) in enumerate(folds):
        # `X[:train_end]` alone is a numpy VIEW (zero-copy). Boolean-indexing it with
        # `fold_valid` always allocates a fresh copy, even when the mask is all-True -- which
        # it is in every current caller, since `fetch_training_matrix` drops the causal-demeaning
        # warmup rows before X is ever allocated.
        # At 15m's ~8.5M rows/253 cols, the expanding-window last fold trains on nearly all of
        # X (~8.6GB) -- forcing an unconditional copy here stacks another ~6.9GB on top of X
        # staying resident, right when memory is tightest. Skip the copy when nothing is
        # actually masked; still correct (not just fast) if a future caller feeds NaN-bearing y.
        fold_valid = valid_mask[:train_end]
        if fold_valid.all():
            X_train, y_train = X[:train_end], y[:train_end]
        else:
            X_train = X[:train_end][fold_valid]
            y_train = y[:train_end][fold_valid]

        model = lgb.LGBMRegressor(
            n_estimators=200,
            max_depth=4,
            num_leaves=15,
            min_child_samples=200,
            learning_rate=0.05,
            reg_alpha=1.0,
            reg_lambda=1.0,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=bootstrap_seed,
            verbosity=-1,
        )
        model.fit(X_train, y_train)
        if return_models:
            fitted_models.append(model)

        test_idx = np.arange(test_start, test_end)
        X_test = X[test_idx]
        preds = model.predict(X_test)

        # Todo 240: the pre-registered linear-ensemble arm, fit on this fold's identical
        # training slice (causal -- never sees test_idx). Weight-fitting is bounded to
        # max_fit_rows (see fit_linear_ensemble_weights' docstring); scoring runs on the full
        # held-out test slice, same as the tree.
        linear_fit = fit_linear_ensemble_weights(X_train, y_train, rng_seed=bootstrap_seed)
        linear_preds = score_linear_ensemble(linear_fit, X_test)

        fold_df = meta.iloc[test_idx].copy()
        fold_df[target_col] = y[test_idx]
        fold_df["tree_score"] = preds
        fold_df["linear_score"] = linear_preds
        fold_df["fold"] = k
        oos_frames.append(fold_df)

        if not return_models:
            # Drop this fold's Booster (and its internal binned Dataset) before the next,
            # larger fold trains -- see docstring: leaving all 5 folds' models alive
            # simultaneously OOM-killed the 15m run even after X itself was the only "big"
            # object left resident (todo 234). gc.collect() forces reclaiming it now rather
            # than waiting on Python's allocation-count-triggered cyclic collector, which isn't
            # guaranteed to run between folds on this loop's allocation pattern.
            del model
            gc.collect()

        peak_rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 / 1e9
        print(
            f"  fold {k}: train_n={len(X_train)}  test_n={len(test_idx)}  "
            f"peak_rss={peak_rss_gb:.2f}GB"
        )

    oos_df = pd.concat(oos_frames, ignore_index=True)
    if return_models:
        return oos_df, fitted_models
    return oos_df


async def run_nonlinear_interaction_combiner_check(
    tf: str,
    db_dsn: str,
    *,
    csv_filename: str,
    embargo_bars: int,
    bootstrap_block_size: int,
    min_symbol_rows: int,
    baseline_feature: str = "ctf_momentum",
    n_folds: int = 5,
    min_reliable_n: int = 50,
    n_boot: int = 500,
    bootstrap_seed: int = 42,
    fdr_alpha: float = 0.05,
    cross_sectional_block_bars: int = 2,
    feature_dtype: type = np.float32,
) -> None:
    """The full nonlinear_interaction_combiner falsification pipeline for one timeframe: fetch, causal per-symbol demean,
    feature select, walk-forward train, per-symbol OOS IC with BH-FDR correction, a
    cross-sectional-neutral rigor pass, CSV write, and a verdict print. Every one of the three
    nonlinear_interaction_combiner scripts calls this with only its own tf-calibrated constants -- previously each script
    carried its own ~90-140 line copy of this same orchestration, which had let two real
    inconsistencies drift in silently (see module docstring): 1h's copy never applied BH-FDR,
    and 1h/1d's copy used a different causal-demeaning implementation than 15m's.

    `feature_dtype` defaults to float32 (see `fetch_training_matrix`'s docstring) and every
    current caller, including 5m, uses that default -- a float16 attempt at 5m was tried and
    reverted (see `fetch_training_matrix`'s docstring for why: LightGBM upcasts it back to
    float32 internally anyway, making float16 storage a pure memory cost, not a saving).
    """
    # Causal per-symbol demeaning (found live 2026-07-26) happens inside fetch_training_matrix,
    # against three narrow columns rather than the full feature frame: the naive pooled-training
    # result showed mean_ic=0.30, 80/80 symbols passing -- ~3x anything else measured in this
    # corpus. Diagnosed as a static per-symbol drift leak: per-symbol MEAN return_fast in the
    # train half correlates with the test half (some ETFs simply have a persistently higher
    # long-run average return than others across the whole sample). A many-feature tree can
    # implicitly recognize "this row's signature looks like <symbol>" and predict that symbol's
    # known-good long-run drift -- correlating with actual returns for a reason that has nothing
    # to do with bar-level signal. Subtracting each symbol's own CAUSAL (shift(1), expanding,
    # never look-ahead) mean return_fast before training/measuring removes that fixed effect.
    data = await fetch_training_matrix(
        db_dsn, tf, target_min_periods=50, feature_dtype=feature_dtype
    )
    print(f"Loaded {data.n_raw} equity {tf} rows.")
    print(f"Distinct symbols: {data.n_symbols}  Distinct bar_ts: {data.n_bar_ts}")
    print(f"Rows after causal per-symbol demeaning warmup drop: {len(data.y)}")
    print(f"Feature columns used: {len(data.feature_cols)}")

    # The baseline feature is one of X's own columns, so carrying it on `meta` (which is already
    # row-aligned with X) hands it to every fold's slice for free. It used to be fetched as a
    # separate frame and merged back onto the OOS predictions afterwards -- an 8.5M-row join to
    # recover values that were never actually misaligned.
    meta = data.meta
    meta[baseline_feature] = data.X[:, data.feature_cols.index(baseline_feature)]

    oos = train_and_predict_oos(
        data.X,
        data.y,
        meta,
        "return_fast_demeaned",
        n_folds,
        embargo_bars,
        min_reliable_n,
        bootstrap_seed,
    )
    print(f"\nTotal OOS (out-of-fold) rows: {len(oos)}")

    print(
        f"\n=== Per-symbol OOS IC: tree_score vs linear_score (PRIMARY, todo 240) vs "
        f"{baseline_feature} (secondary) (tf={tf}, target=return_fast_demeaned) ==="
    )
    arms = {
        "tree_score": "tree_score",
        "linear_score": "linear_score",
        baseline_feature: baseline_feature,
    }
    ic_by_label = {
        label: per_symbol_ic_ci(
            oos,
            col,
            "return_fast_demeaned",
            bootstrap_block_size,
            n_boot,
            bootstrap_seed,
            min_symbol_rows,
        )
        for label, col in arms.items()
    }
    tree_ic = ic_by_label["tree_score"]
    linear_ic = ic_by_label["linear_score"]
    baseline_ic = ic_by_label[baseline_feature]

    # BH-FDR pass across the family of ~80 per-symbol tests, independently per arm.
    # _p_values_from_ic takes one shared n per call (matches its production usage in
    # ic_engine.py, where a single call covers one symbol's several features at that symbol's
    # own n) -- since each SYMBOL here has its own distinct OOS row count, call it once per
    # symbol with that symbol's own n, not once for the whole vector with an approximated shared
    # n. _p_values_from_ic is TWO-TAILED (significantly different from zero in EITHER direction)
    # -- `reject` alone answers "is this symbol's IC significant," not "is it significantly
    # POSITIVE." Gate on sign too, matching the one-sided ci_lower>0 semantics `passes` already
    # uses, or a symbol with a strong significant NEGATIVE IC would silently count as a "pass"
    # here.
    for label, ic_df in ic_by_label.items():
        if len(ic_df) == 0:
            continue
        p_values = np.array(
            [
                float(_p_values_from_ic(np.array([ic]), n=int(n))[0])
                for ic, n in zip(ic_df["point_ic"], ic_df["n"], strict=True)
            ]
        )
        reject, p_corrected = apply_bh_fdr(list(p_values), alpha=fdr_alpha)
        ic_df["p_value"] = p_values
        ic_df["p_value_fdr"] = p_corrected
        ic_df["passes_fdr_significant"] = reject
        ic_df["passes_fdr"] = reject & (ic_df["point_ic"] > 0)
        print(
            f"\n{label}: {len(ic_df)} symbols with sufficient rows -- "
            f"mean point_ic={ic_df['point_ic'].mean():.4f}  "
            f"n_pass(ci_lower>0)={ic_df['passes'].sum()}/{len(ic_df)}  "
            f"n_pass_fdr_significant_either_sign(BH q<{fdr_alpha})="
            f"{int(ic_df['passes_fdr_significant'].sum())}/{len(ic_df)}  "
            f"n_pass_fdr_positive(BH q<{fdr_alpha} AND IC>0)="
            f"{int(ic_df['passes_fdr'].sum())}/{len(ic_df)}"
        )

    merged = tree_ic.merge(linear_ic, on="symbol", suffixes=("_tree", "_linear")).merge(
        baseline_ic.add_suffix("_baseline").rename(columns={"symbol_baseline": "symbol"}),
        on="symbol",
    )
    uplift_vs_linear = merged["point_ic_tree"] - merged["point_ic_linear"]
    uplift_vs_baseline = merged["point_ic_tree"] - merged["point_ic_baseline"]
    print(
        f"\nPer-symbol IC uplift (tree - linear_score, PRIMARY): "
        f"mean={uplift_vs_linear.mean():.4f}  median={uplift_vs_linear.median():.4f}  "
        f"n_symbols_tree_better={int((uplift_vs_linear > 0).sum())}/{len(merged)}"
    )
    print(
        f"Per-symbol IC uplift (tree - {baseline_feature}, secondary): "
        f"mean={uplift_vs_baseline.mean():.4f}  median={uplift_vs_baseline.median():.4f}  "
        f"n_symbols_tree_better={int((uplift_vs_baseline > 0).sum())}/{len(merged)}"
    )

    out_dir = Path("docs/analysis")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / csv_filename
    merged.to_csv(csv_path, index=False)
    print(f"\nFull per-symbol table written to {csv_path}")

    tree_pass_rate = tree_ic["passes"].mean() if len(tree_ic) else 0.0
    baseline_pass_rate = baseline_ic["passes"].mean() if len(baseline_ic) else 0.0
    tree_fdr_rate = tree_ic["passes_fdr"].mean() if len(tree_ic) else 0.0
    if (
        tree_pass_rate > baseline_pass_rate * 1.5
        and uplift_vs_baseline.mean() > 0
        and tree_fdr_rate > 0.5
    ):
        verdict = (
            f"Tree combiner shows a real uplift over the single best standalone feature, "
            f"surviving BH-FDR correction at {tf} -- strong evidence toward nonlinear_interaction_combiner being real."
        )
    elif uplift_vs_baseline.mean() <= 0:
        verdict = (
            f"Tree combiner does NOT beat the single best standalone feature's own IC on "
            f"identical held-out data at {tf} -- no evidence of a nonlinear_interaction_combiner effect at this tf."
        )
    else:
        verdict = (
            f"Mixed/weak result at {tf} -- some uplift but not decisive after BH-FDR "
            f"correction; read the per-symbol table before drawing a conclusion either way."
        )
    print(f"\nSECONDARY VERDICT (tree vs {baseline_feature}): {verdict}")

    # Rigor pass: decompose common-market-factor vs genuine within-symbol (cross-sectional,
    # dollar-neutral-relevant) signal, then bootstrap CI the latter properly. The naive
    # per-symbol IC above pools across correlated ETFs -- averaging effects can inflate apparent
    # correlation even under a constant true idiosyncratic IC (the IR ~ IC*sqrt(breadth)
    # arithmetic docs/research/data-edge-source-thesis.md names as this universe's binding
    # constraint). The within-bar_ts component, after subtracting each bar_ts's cross-sectional
    # mean from both prediction and actual, isolates the part actually relevant to a cross_sectional_relative_value-style
    # dollar-neutral construction.
    print("\n\n=== Rigor pass: within-bar_ts (cross-sectional-neutral) component, bootstrap CI ===")
    oos_sorted = oos.sort_values(["bar_ts", "symbol"]).reset_index(drop=True)
    rigor_stats: dict[str, dict[str, float | bool]] = {}
    for score_col in ("tree_score", "linear_score", baseline_feature):
        work = oos_sorted.dropna(subset=[score_col, "return_fast_demeaned"]).copy()
        bar_mean_score = work.groupby("bar_ts")[score_col].transform("mean")
        bar_mean_actual = work.groupby("bar_ts")["return_fast_demeaned"].transform("mean")
        within_score = (work[score_col] - bar_mean_score).to_numpy(dtype=float)
        within_actual = (work["return_fast_demeaned"] - bar_mean_actual).to_numpy(dtype=float)

        n_symbols_per_bar = work.groupby("bar_ts").size().median()
        block_size = max(10, int(n_symbols_per_bar * cross_sectional_block_bars))
        stats = bootstrap_ic_stats(within_score, within_actual, block_size, n_boot, bootstrap_seed)
        rigor_stats[score_col] = stats
        print(
            f"\n{score_col}: n={len(work)}  block_size={block_size} (~{cross_sectional_block_bars} "
            f"bar_ts x {n_symbols_per_bar:.0f} symbols)  point_ic={stats['point_ic']:.4f}  "
            f"ci_lower={stats['ci_lower']:.4f}  ci_upper={stats['ci_upper']:.4f}  passes={stats['passes']}"
        )

    # PRIMARY VERDICT (todo 240): the pre-registered falsification bar is tree vs the causally-
    # fit linear ensemble, not tree vs one hand-picked column -- and decided via a PAIRED
    # bootstrap of the IC difference, not a non-overlapping-marginal-CI test. Tree and linear
    # score IDENTICAL rows, so their bootstrap ICs are strongly positively correlated; comparing
    # two marginal CIs for non-overlap is conservative and systematically underpowered here (see
    # paired_bootstrap_ic_difference's docstring). Built on a row set common to BOTH arms
    # (dropna on both score columns together), not each arm's own independently-filtered `work`
    # from the loop above -- required for the resampled indices to stay paired row-for-row.
    work_primary = oos_sorted.dropna(subset=["tree_score", "linear_score", "return_fast_demeaned"])
    bar_mean_tree = work_primary.groupby("bar_ts")["tree_score"].transform("mean")
    bar_mean_linear = work_primary.groupby("bar_ts")["linear_score"].transform("mean")
    bar_mean_actual_primary = work_primary.groupby("bar_ts")["return_fast_demeaned"].transform(
        "mean"
    )
    within_tree = (work_primary["tree_score"] - bar_mean_tree).to_numpy(dtype=float)
    within_linear = (work_primary["linear_score"] - bar_mean_linear).to_numpy(dtype=float)
    within_actual_primary = (
        work_primary["return_fast_demeaned"] - bar_mean_actual_primary
    ).to_numpy(dtype=float)
    n_symbols_per_bar_primary = work_primary.groupby("bar_ts").size().median()
    block_size_primary = max(10, int(n_symbols_per_bar_primary * cross_sectional_block_bars))

    paired = paired_bootstrap_ic_difference(
        within_tree,
        within_linear,
        within_actual_primary,
        block_size_primary,
        n_boot,
        bootstrap_seed,
    )
    print(
        f"\nPaired bootstrap (tree - linear), cross-sectional-neutral: n={len(work_primary)}  "
        f"point_diff={paired['point_diff']:.4f}  ci_lower={paired['ci_lower']:.4f}  "
        f"ci_upper={paired['ci_upper']:.4f}"
    )
    tree_point_ic = rigor_stats["tree_score"]["point_ic"]
    linear_point_ic = rigor_stats["linear_score"]["point_ic"]
    if paired["a_significantly_better"]:
        primary_verdict = (
            f"Tree combiner's cross-sectional-neutral point_ic ({tree_point_ic:.4f}) is "
            f"significantly higher than the causally-fit linear ensemble's ({linear_point_ic:.4f}) "
            f"at {tf} (paired bootstrap diff={paired['point_diff']:.4f}, "
            f"ci_lower={paired['ci_lower']:.4f} > 0) -- passes the pre-registered "
            f"nonlinear_interaction_combiner falsification bar."
        )
    elif paired["b_significantly_better"]:
        primary_verdict = (
            f"Linear ensemble's cross-sectional-neutral point_ic ({linear_point_ic:.4f}) is "
            f"significantly higher than the tree's ({tree_point_ic:.4f}) at {tf} (paired bootstrap "
            f"diff={paired['point_diff']:.4f}, ci_upper={paired['ci_upper']:.4f} < 0) -- the "
            f"pre-registered bar FAILS: no evidence non-linearity is the bottleneck here."
        )
    else:
        primary_verdict = (
            f"Tree ({tree_point_ic:.4f}) vs linear ensemble ({linear_point_ic:.4f}) at {tf}: paired "
            f"bootstrap diff={paired['point_diff']:.4f}, CI [{paired['ci_lower']:.4f}, "
            f"{paired['ci_upper']:.4f}] includes zero -- inconclusive on the pre-registered bar, "
            f"read the per-symbol table."
        )
    print(f"\nPRIMARY VERDICT (tree vs linear ensemble, pre-registered): {primary_verdict}")
