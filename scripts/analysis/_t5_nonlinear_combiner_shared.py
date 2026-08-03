"""Shared library for the T5 non-linear-combiner falsification test's per-tf scripts.

Not runnable on its own (no `main()`/`if __name__ == "__main__"`) -- imported by
`t5_nonlinear_combiner_lightgbm_check.py` (1h, the original finding) and
`t5_nonlinear_combiner_replication_{15m,1d}.py` (independent replications at other
timeframes). Same "leading-underscore filename marks an internal shared module, not a
standalone script" convention as `services/_batch_utils.py`.

Extracted 2026-08-02 (todo 232's remaining scope) after three tf-specific scripts had grown
90%+ identical `main()` bodies via copy-paste-and-recalibrate, with the imports pulling 7
underscore-prefixed "private" symbols out of the 1h script's own module namespace across
two sibling scripts -- a real separation-of-concerns violation, not just a style nit: the 1h
script was simultaneously an executable entry point and the de facto shared library for its
own replications, so a change to either role risked silently breaking the other.

`run_t5_check()` is the single orchestration path every script now calls -- fetch (via
`fetch_training_matrix`, which also does the causal demeaning and feature selection),
walk-forward train, per-symbol IC, BH-FDR correction, cross-sectional rigor pass, CSV write,
verdict. Extracting it fixed two real methodological inconsistencies
the copy-paste had let drift, not just duplication: the 1h script never applied BH-FDR
correction (its own replications at 1d/15m did, and the research doc's own T5 bar requires it
everywhere) -- an uncorrected headline number sitting next to two corrected confirmatory
replications is a multiple-comparisons blind spot on the single most-cited T5 result. And 1h/1d
used an inline `df.groupby("symbol")["return_fast"].apply(lambda s: s.shift(1).expanding(...))`
for causal per-symbol demeaning while 15m used `ic_math.py`'s vectorized
`causal_entity_expanding_mean` -- two implementations of the identical causal fix, now one.
"""

from __future__ import annotations

import gc
import resource
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import lightgbm as lgb
import numpy as np
import pandas as pd

from src.intelligence.statistics.ic_math import (
    _p_values_from_ic,
    apply_bh_fdr,
    build_walk_forward_folds,
    causal_entity_expanding_mean,
    circular_block_bootstrap_ic_serial,
)

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
    # meaningful driver of the already-published T5 results (re-verified via actual LightGBM
    # feature_importances_ on the real fitted 1h models: rank 89-233/248 across all 5 folds,
    # importance 0-3 vs ctf_momentum's 400+), so re-including it now would require re-running
    # every published number for no demonstrated benefit.
    "hmm_duration",
}

# Nothing currently needs float16-only exclusion (hmm_duration graduated to EXCLUDE_COLS above,
# 2026-08-03, once its overflow turned out to be a universal data defect rather than a tf-scoped
# numeric-range issue). Kept as an extension point for a future column that IS legitimately
# large -- like weekly_r1_dist_atr/weekly_r2_dist_atr below, which get clipped rather than
# excluded -- but only overflows float16's range at 5m specifically.
FLOAT16_UNSAFE_COLS: set[str] = set()

# Safely under float16's ~65504 max magnitude. Applied only to the handful of cells that would
# otherwise overflow (measured: 3 rows in weekly_r1_dist_atr, 6 in weekly_r2_dist_atr, out of
# 25,443,790) -- clipping instead of excluding those columns preserves the feature for every
# other row rather than discarding it corpus-wide over an extreme-tail minority.
_FLOAT16_CLIP_MAGNITUDE = 60_000

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
    """What the T5 pipeline actually needs out of the database, and nothing else."""

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

    `feature_dtype` defaults to float32, matching every already-published 1h/1d/15m T5 number --
    do not change the default, it would silently perturb those results. 5m (2026-08-03) is the
    first caller to pass `np.float16`: at ~24.6M rows, float32's X alone is ~23GB, leaving no
    room for anything else on this 29GB host. LightGBM bins every feature into ~255 histogram
    buckets internally regardless of input precision, so float32's extra mantissa bits were
    already thrown away by the algorithm itself -- confirmed empirically before relying on it:
    `LGBMRegressor.fit()` accepts float16 input directly, and a synthetic-data comparison at 2M
    rows showed `fit()` added zero measurable RSS beyond the input array's own allocation, in
    both dtypes. This is a memory fix, not a data-dropping one -- every row is still used, per
    this project's own "never drop data that could contain signal" principle; row-subsampling
    was considered and rejected on exactly that basis.

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
        unsafe_cols = FLOAT16_UNSAFE_COLS if feature_dtype == np.float16 else set()
        feature_cols = [
            attr.name
            for attr in schema.get_attributes()
            if attr.type.name in ("float4", "float8")
            and attr.name not in EXCLUDE_COLS
            and attr.name not in unsafe_cols
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
                # Clip before cast (float16 only): `.clip()` leaves NaN untouched and is a no-op
                # for the ~25.4M-9 cells already inside range, only bending the ~9 measured
                # extreme cells (see FLOAT16_UNSAFE_COLS's comment) down to a finite, still-huge
                # value instead of `+/-inf` -- preserves the column's signal instead of dropping
                # it, per this project's "never drop data that could contain signal" principle.
                to_cast = block[feature_cols]
                if feature_dtype == np.float16:
                    to_cast = to_cast.clip(
                        lower=-_FLOAT16_CLIP_MAGNITUDE, upper=_FLOAT16_CLIP_MAGNITUDE
                    )
                cast = to_cast.astype(feature_dtype).to_numpy()[keep]
                # Defense in depth beyond FLOAT16_UNSAFE_COLS and the clip above: both were built
                # from a point-in-time full-corpus scan, not a guarantee against a future column
                # (or a future corpus refresh) whose values grow past `_FLOAT16_CLIP_MAGNITUDE`.
                # A downcast that silently turns a finite value into +/-inf is exactly the
                # "silent wrong answer" this project's principles rule out -- confirmed a real,
                # not hypothetical, risk (this exact failure mode is what surfaced
                # FLOAT16_UNSAFE_COLS in the first place, via a `RuntimeWarning: overflow
                # encountered in cast` in a live run). Finite-in must mean finite-out; anything
                # else fails loud, immediately, with the offending columns named, rather than
                # continuing to train on corrupted rows. Scoped to float16 only -- float32's
                # range is wide enough that this has never been an issue for 1h/1d/15m, and the
                # extra float64 comparison array below would be pure overhead on those
                # already-verified paths for no real protection gained.
                if feature_dtype == np.float16:
                    orig = block[feature_cols].to_numpy(dtype=np.float64)[keep]
                    newly_infinite = np.isinf(cast) & np.isfinite(orig)
                    if newly_infinite.any():
                        bad_cols = [
                            feature_cols[j] for j in np.unique(np.nonzero(newly_infinite)[1])
                        ]
                        raise RuntimeError(
                            f"float16 downcast produced +/-inf from finite input in columns "
                            f"{bad_cols} at rows {row}:{end} -- add to FLOAT16_UNSAFE_COLS "
                            f"rather than silently training on corrupted values"
                        )
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
    `return_models` (todo 234, 2026-08-03 follow-on) -- every actual T5 caller uses the default
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
    folds = build_walk_forward_folds(
        n_valid=n_valid,
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
    for k, (test_start, test_end) in enumerate(folds):
        train_end = test_start - embargo_bars
        if train_end < min_reliable_n:
            continue
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
        preds = model.predict(X[test_idx])
        fold_df = meta.iloc[test_idx].copy()
        fold_df[target_col] = y[test_idx]
        fold_df["tree_score"] = preds
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


async def run_t5_check(
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
    """The full T5 falsification pipeline for one timeframe: fetch, causal per-symbol demean,
    feature select, walk-forward train, per-symbol OOS IC with BH-FDR correction, a
    cross-sectional-neutral rigor pass, CSV write, and a verdict print. Every one of the three
    T5 scripts calls this with only its own tf-calibrated constants -- previously each script
    carried its own ~90-140 line copy of this same orchestration, which had let two real
    inconsistencies drift in silently (see module docstring): 1h's copy never applied BH-FDR,
    and 1h/1d's copy used a different causal-demeaning implementation than 15m's.

    `feature_dtype` defaults to float32 (see `fetch_training_matrix`'s docstring) -- only the
    5m script overrides it to float16, a resource necessity at that row count, not a change in
    what any other caller measures.
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
        f"\n=== Per-symbol OOS IC: tree_score vs {baseline_feature} "
        f"(tf={tf}, target=return_fast_demeaned) ==="
    )
    tree_ic = per_symbol_ic_ci(
        oos,
        "tree_score",
        "return_fast_demeaned",
        bootstrap_block_size,
        n_boot,
        bootstrap_seed,
        min_symbol_rows,
    )
    baseline_ic = per_symbol_ic_ci(
        oos,
        baseline_feature,
        "return_fast_demeaned",
        bootstrap_block_size,
        n_boot,
        bootstrap_seed,
        min_symbol_rows,
    )

    # BH-FDR pass across the family of ~80 per-symbol tests, for tree and baseline
    # independently. _p_values_from_ic takes one shared n per call (matches its production
    # usage in ic_engine.py, where a single call covers one symbol's several features at that
    # symbol's own n) -- since each SYMBOL here has its own distinct OOS row count, call it once
    # per symbol with that symbol's own n, not once for the whole vector with an approximated
    # shared n. _p_values_from_ic is TWO-TAILED (significantly different from zero in EITHER
    # direction) -- `reject` alone answers "is this symbol's IC significant," not "is it
    # significantly POSITIVE." Gate on sign too, matching the one-sided ci_lower>0 semantics
    # `passes` already uses, or a symbol with a strong significant NEGATIVE IC would silently
    # count as a "pass" here.
    for label, ic_df in (("tree_score", tree_ic), (baseline_feature, baseline_ic)):
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

    merged = tree_ic.merge(baseline_ic, on="symbol", suffixes=("_tree", "_baseline"))
    uplift = merged["point_ic_tree"] - merged["point_ic_baseline"]
    print(
        f"\nPer-symbol IC uplift (tree - {baseline_feature}): "
        f"mean={uplift.mean():.4f}  median={uplift.median():.4f}  "
        f"n_symbols_tree_better={int((uplift > 0).sum())}/{len(merged)}"
    )

    out_dir = Path("docs/analysis")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / csv_filename
    merged.to_csv(csv_path, index=False)
    print(f"\nFull per-symbol table written to {csv_path}")

    tree_pass_rate = tree_ic["passes"].mean() if len(tree_ic) else 0.0
    baseline_pass_rate = baseline_ic["passes"].mean() if len(baseline_ic) else 0.0
    tree_fdr_rate = tree_ic["passes_fdr"].mean() if len(tree_ic) else 0.0
    if tree_pass_rate > baseline_pass_rate * 1.5 and uplift.mean() > 0 and tree_fdr_rate > 0.5:
        verdict = (
            f"Tree combiner shows a real uplift over the single best standalone feature, "
            f"surviving BH-FDR correction at {tf} -- strong evidence toward T5 being real."
        )
    elif uplift.mean() <= 0:
        verdict = (
            f"Tree combiner does NOT beat the single best standalone feature's own IC on "
            f"identical held-out data at {tf} -- no evidence of a T5 effect at this tf."
        )
    else:
        verdict = (
            f"Mixed/weak result at {tf} -- some uplift but not decisive after BH-FDR "
            f"correction; read the per-symbol table before drawing a conclusion either way."
        )
    print(f"\nVERDICT: {verdict}")

    # Rigor pass: decompose common-market-factor vs genuine within-symbol (cross-sectional,
    # dollar-neutral-relevant) signal, then bootstrap CI the latter properly. The naive
    # per-symbol IC above pools across correlated ETFs -- averaging effects can inflate apparent
    # correlation even under a constant true idiosyncratic IC (the IR ~ IC*sqrt(breadth)
    # arithmetic docs/research/data-edge-source-thesis.md names as this universe's binding
    # constraint). The within-bar_ts component, after subtracting each bar_ts's cross-sectional
    # mean from both prediction and actual, isolates the part actually relevant to a T3-style
    # dollar-neutral construction.
    print("\n\n=== Rigor pass: within-bar_ts (cross-sectional-neutral) component, bootstrap CI ===")
    oos_sorted = oos.sort_values(["bar_ts", "symbol"]).reset_index(drop=True)
    for score_col in ("tree_score", baseline_feature):
        work = oos_sorted.dropna(subset=[score_col, "return_fast_demeaned"]).copy()
        bar_mean_score = work.groupby("bar_ts")[score_col].transform("mean")
        bar_mean_actual = work.groupby("bar_ts")["return_fast_demeaned"].transform("mean")
        within_score = (work[score_col] - bar_mean_score).to_numpy(dtype=float)
        within_actual = (work["return_fast_demeaned"] - bar_mean_actual).to_numpy(dtype=float)

        n_symbols_per_bar = work.groupby("bar_ts").size().median()
        block_size = max(10, int(n_symbols_per_bar * cross_sectional_block_bars))
        stats = bootstrap_ic_stats(within_score, within_actual, block_size, n_boot, bootstrap_seed)
        print(
            f"\n{score_col}: n={len(work)}  block_size={block_size} (~{cross_sectional_block_bars} "
            f"bar_ts x {n_symbols_per_bar:.0f} symbols)  point_ic={stats['point_ic']:.4f}  "
            f"ci_lower={stats['ci_lower']:.4f}  ci_upper={stats['ci_upper']:.4f}  passes={stats['passes']}"
        )
