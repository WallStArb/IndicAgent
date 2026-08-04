#!/usr/bin/env python3
"""
ops_interaction_primitives_pilot.py -- todo 037 partial-IC pilot.

Answers: do the 8 already-live Renaissance interaction primitives
(concept_registry.metadata->>'tier'='1_interaction', domain='feature') carry genuine incremental IC after
controlling for their parent atomics, or is their naive IC fully explained by the
parents? Reuses already-measured cross-sectional feature_ic_scores rows
(is_pooled=true, symbol='POOLED', regime=<real regime label> -- the highest-power
cross-sectional population, one row per real regime, see project memory's EIC-04
diagnosis) as the input population, rather than re-deriving IC from scratch.

Note: symbol='POOLED' rows are always regime-stratified into real cross-sectional
regime labels -- they are never written with regime='_pooled'. That sentinel marks
a *different* pooling axis: a per-symbol row pooled across regimes (real symbol,
e.g. symbol='SPY'). The two pooling axes never co-occur in one row (confirmed via
services/ic_engine.py's _compute_cross_sectional_tf(), which always writes
symbol=_CROSS_SECTIONAL_SYMBOL with regime=regime_label, the actual label).

Pilot-scoped approximation (see docs/plans/2026-07-09-interaction-primitives-
partial-ic-pilot-plan.md "Global Constraints"): subsampling reuses ic_engine.py's
stride formula (max(subsample_min_stride, lookahead_bars)) applied positionally
within each symbol's row block before pooling across symbols -- a faithful analog
of, not a byte-identical replay of, ic_engine.py's own chunk-internal subsampling.
This is a decision-gate measurement, not a promotion-grade one.

Decision rule (todo 037): genuine incremental IC (passes_partial_fdr=true) for a
meaningful fraction of the 8-feature cohort -> trigger to plan the full Interaction
Factory. Near-zero -> shelve Interaction Factory outright.

Exit code: 0 on a clean, full-cohort run. 1 if any precondition failed (missing
config/registry rows) or if any timeframe's fetch failed and had to be skipped --
in the latter case the printed pass fraction covers only the successfully-fetched
timeframes, not the full cohort, so a caller must not treat it as the final answer.

Usage:
    python scripts/ops/alpha/ops_interaction_primitives_pilot.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np

from services._batch_utils import LOOKAHEAD_FALLBACKS_BY_TF
from services._batch_utils import bars_to_scale_map as _bars_to_scale_map
from services._batch_utils import cfg as _cfg
from src.config.settings import Settings
from src.intelligence.statistics.ic_math import apply_bh_fdr, partial_spearman_ic

_SCALES = ("fast", "mid", "slow", "extended")
# Todo 211 part 2: this previously read the pre-todo-146 flat global
# alpha.ic.lookahead.{scale} keys (no {tf} component) via one shared lookahead_bars ->
# scale map applied across every tf's cells -- post-146, lookahead_bars for a given
# scale name differs per tf (e.g. 1h's "mid" is 2 bars, 5m's "mid" is 6), so a single
# global map silently mis-resolved or dropped cells whose tf's real bar count wasn't
# among the four flat values. Fixed by mirroring ICEngineConfig.from_apr()'s per-tf
# resolution, via the same shared services._batch_utils helpers ops_ensemble_ablation.py
# already migrated to (todo 211 part 1).
_LOOKAHEAD_KEYS = tuple(
    f"alpha.ic.lookahead.{tf}.{scale}"
    for tf, fallbacks in LOOKAHEAD_FALLBACKS_BY_TF.items()
    for scale in fallbacks
)
_CONFIG_KEYS = (
    "alpha.ic.subsample_min_stride",
    "alpha.ic.partial_control_condition_max",
    "alpha.ic.partial_fdr_alpha",
    "infra.interaction_primitives_pilot.fetch_flush_rows",
    *_LOOKAHEAD_KEYS,
)

_RETURN_COLS = tuple(f"return_{scale}" for scale in _SCALES)
_COMPLETE_COLS = tuple(f"complete_{scale}" for scale in _SCALES)


def _fail(msg: str) -> int:
    print(f"## Todo 037 Interaction Primitives Pilot\n\nFAILED: {msg}")
    return 1


async def _load_config(conn: asyncpg.Connection) -> dict[str, str]:
    """One round trip for every APR key this script needs, instead of one
    fetchval() per key -- 8 sequential single-key round trips collapsed to 1."""
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])",
        list(_CONFIG_KEYS),
    )
    return {r["config_key"]: r["config_value"] for r in rows}


def _build_lookahead_map(config: dict[str, str], tf: str) -> dict[int, str]:
    """lookahead_bars -> scale name for ONE timeframe, from the loaded APR config.

    Valid only within the tf it was built for -- post-todo-146, the same scale name
    (e.g. "mid") resolves to a different lookahead_bars value per tf, so this map must
    never be reused across tfs (see module-level _LOOKAHEAD_KEYS comment). Collision
    detection (same-tf lookahead.{tf}.* keys misconfigured to the same lookahead_bars
    value) lives in the shared services._batch_utils.bars_to_scale_map -- see its
    docstring for why this must never silently let the second overwrite the first."""
    fallbacks = LOOKAHEAD_FALLBACKS_BY_TF[tf]
    scale_to_bars = {
        scale: _cfg(config, f"alpha.ic.lookahead.{tf}.{scale}", fallbacks[scale])
        for scale in _SCALES
    }
    return _bars_to_scale_map(scale_to_bars, context=tf)


def _lookahead_to_scale(lookahead_bars: int, lookahead_scale_map: dict[int, str]) -> str:
    if lookahead_bars not in lookahead_scale_map:
        raise KeyError(
            f"lookahead_bars={lookahead_bars} not in the loaded APR lookahead map -- "
            "call _build_lookahead_map() before any cell processing."
        )
    return lookahead_scale_map[lookahead_bars]


async def _load_interaction_features(conn: asyncpg.Connection) -> list[dict]:
    """metadata->>'tier'='1_interaction' rows from concept_registry (domain='feature')
    with their parent atomics, joined through concept_parent.

    Validated here, once, before any per-tf work starts: every Renaissance
    interaction primitive has exactly 2 parent atomics (the partial_spearman_ic
    call below assumes and unpacks exactly 2). Failing loudly here rather than via
    an implicit tuple-unpack deep in the per-cell loop means a future registry row
    with a different arity can never silently corrupt or crash a partially-completed
    run -- it fails before any DB fetch or measurement work begins. The arity check
    now comes from FK-enforced concept_parent edges rather than an unvalidated
    TEXT[] column, so a malformed edge set is structurally harder to produce in the
    first place -- this check remains as defense-in-depth, not the sole guard.

    Parent ORDER (Phase 170 Plan 07): concept_parent carries no ordinality column
    (migration 283's header), so parents come back sorted alphabetically via
    array_agg(... ORDER BY p.name), which is NOT necessarily the original
    retired dimension table's bare TEXT[] insertion order. This is proven inert,
    not assumed inert -- see tests/unit/test_interaction_primitives_parent_order.py,
    which asserts partial_spearman_ic and _compute_not_null_mask are invariant
    under a parent swap. If that test ever fails, the fix is an explicit
    ordinality column on concept_parent, not silently accepting a changed
    statistic.
    """
    rows = await conn.fetch("""
        SELECT c.name AS feature_name,
               array_agg(p.name ORDER BY p.name) AS parent_features
        FROM concept_registry c
        JOIN concept_parent cp ON cp.child_concept_id = c.concept_id
        JOIN concept_registry p ON p.concept_id = cp.parent_concept_id
        WHERE c.domain = 'feature' AND c.metadata->>'tier' = '1_interaction'
          AND c.status = 'active'
        GROUP BY c.name
        ORDER BY c.name
        """)
    features = []
    for r in rows:
        parents = list(r["parent_features"])
        if len(parents) != 2:
            raise ValueError(
                f"concept_registry row {r['feature_name']!r} has {len(parents)} "
                f"parent_features ({parents!r}) via concept_parent -- partial_spearman_ic's "
                "2-control shape assumes exactly 2 parent atomics per interaction primitive. "
                "Update this script's cell-processing logic if that invariant ever changes."
            )
        features.append({"feature_name": r["feature_name"], "parents": parents})
    return features


async def _load_pooled_cells(conn: asyncpg.Connection, feature_names: list[str]) -> list[dict]:
    """Already-measured cross-sectional cells (symbol='POOLED', is_pooled=true,
    regime=<real regime label>) for the given features -- the highest-power
    population, and the same one used for the EIC-04 sparse-signal cross-check.

    `regime != '_pooled'` excludes the unrelated per-symbol-pooled-across-regimes
    sentinel (which only ever appears with a real symbol, never symbol='POOLED'),
    returning the real regime-stratified rows written by
    services/ic_engine.py's _compute_cross_sectional_tf() -- 9 regime labels per
    feature/tf/lookahead combination."""
    rows = await conn.fetch(
        "SELECT feature_name, tf, regime, lookahead_bars, training_window_end, n_independent "
        "FROM feature_ic_scores "
        "WHERE feature_name = ANY($1::text[]) "
        "  AND symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled' "
        "  AND reliable = true "
        "ORDER BY feature_name, tf, lookahead_bars",
        feature_names,
    )
    return [dict(r) for r in rows]


def _scale_stride(lookahead_bars: int, subsample_min_stride: int) -> int:
    return max(subsample_min_stride, lookahead_bars)


def _flush_symbol_buffers(
    raw_by_symbol: dict[str, dict[str, list]],
    chunk_arrays_by_symbol: dict[str, dict[str, list[np.ndarray]]],
    float_cols: list[str],
) -> None:
    """Convert whatever's currently buffered per symbol into numpy chunk-arrays,
    appended to chunk_arrays_by_symbol, then clear raw_by_symbol in place. Pure/
    DB-free -- the only inputs are already-fetched Python values, no DB/Kafka
    dependency.

    Correctness note: the SQL's `ORDER BY fv.symbol, fv.bar_ts` guarantees a
    symbol's rows arrive in one contiguous run (never interleaved with another
    symbol's rows reappearing later), so a symbol's data may be split across 2+
    flush events but always in increasing bar_ts order -- appending each flush's
    per-symbol chunk-array (in flush order) and concatenating at the end preserves
    that order exactly, matching what a single one-shot conversion would produce.
    """
    for sym, cols in raw_by_symbol.items():
        chunks = chunk_arrays_by_symbol.setdefault(sym, {})
        chunks.setdefault("regime_label", []).append(np.asarray(cols["regime_label"], dtype=object))
        for col in float_cols:
            chunks.setdefault(col, []).append(
                np.array([np.nan if v is None else v for v in cols[col]], dtype=np.float64)
            )
        for col in _COMPLETE_COLS:
            chunks.setdefault(col, []).append(np.asarray(cols[col], dtype=bool))
    raw_by_symbol.clear()


async def _fetch_tf_dataset(
    conn: asyncpg.Connection,
    tf: str,
    feature_names: list[str],
    parent_cols: list[str],
    training_window_end,
    flush_rows: int = 500_000,
) -> dict[str, dict[str, np.ndarray]]:
    """Stream every (feature, parent, return, regime) column needed by ANY cell for
    this `tf` in ONE full scan of that tf's feature_vectors partition, keyed by
    symbol. Replaces the old per-cell `_fetch_cell_arrays()`, which re-scanned the
    same partition once per (feature, tf, regime, lookahead) cell -- 864 redundant
    scans total, the ~80-hour bug this rewrite fixes (see module docstring's
    pilot-scoped-approximation note and todo 037's Task 3 v2 fix).

    No NULL filter and no regime filter in this SQL, unlike the old per-cell query:
    both are cell-specific (different features have independent NULL patterns; each
    cell wants a different regime_label), so they move to `_slice_cell()` below,
    which slices this per-tf dataset down to one cell's rows in memory. The only
    filters here are the ones every cell for this tf shares: tf itself and the
    global `training_window_end` cutoff.

    Named server-side cursor + prefetch=5000 -- same OOM-avoidance shape as
    migrations 183/209/212 (see CLAUDE.md's "ProcessPoolExecutor workers are
    compute-only" gotcha family). ~25M rows for tf='5m' must never be materialized
    via one giant asyncpg `fetch()` list; this streams and buckets by symbol
    instead, one tf fetched (and released) at a time.

    Bounded-memory chunked accumulation (Task 3 v3 fix): the earlier version of
    this function accumulated every row of the tf's partition into unbounded
    Python-object lists (`raw_by_symbol`) before a one-shot numpy conversion at the
    end -- for tf='5m' (25.35M rows) this drove system MemAvailable to ~1.4GB and
    swap-out to ~98MB/s within 7 minutes (see task-3-v3-brief.md). Every
    `flush_rows` rows (a running counter across the whole tf, not per-symbol),
    `_flush_symbol_buffers()` converts whatever's buffered to numpy chunk-arrays
    and clears `raw_by_symbol`, bounding peak Python-list memory regardless of
    total tf row count. The final per-symbol arrays are built by concatenating
    each symbol's chunk-array list after the loop (plus one final flush for any
    remainder) -- identical to what a single one-shot conversion would have
    produced, just never holding more than `flush_rows` rows of Python objects at
    once. Note: this bounds only the transient accumulation buffer, not the final
    concatenated per-symbol arrays themselves (~4.3GB resident for tf='5m') -- a
    future tf/symbol/column-count increase would still raise that resident ceiling
    with no APR knob to mitigate it; accepted as a known scope limit for this
    one-shot pilot rather than a full query-level chunking rewrite (see migration
    215's own comments).
    """
    select_cols = ", ".join(f"fv.{col} AS {col}" for col in [*feature_names, *parent_cols])
    float_cols = [*feature_names, *parent_cols, *_RETURN_COLS]
    sql = f"""
        SELECT fv.symbol, mr.regime_label,
               {select_cols},
               fr.{", fr.".join(_RETURN_COLS)},
               fr.{", fr.".join(_COMPLETE_COLS)}
        FROM feature_vectors fv
        INNER JOIN forward_returns fr
            ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
            AND fr.return_type = 'executable_open_to_open'
        INNER JOIN market_regimes mr
            ON mr.tf = fv.tf AND mr.ts = fv.bar_ts AND mr.regime_group = 'equity'
        WHERE fv.tf = $1 AND fv.bar_ts <= $2
        ORDER BY fv.symbol, fv.bar_ts
    """
    raw_by_symbol: dict[str, dict[str, list]] = {}
    chunk_arrays_by_symbol: dict[str, dict[str, list[np.ndarray]]] = {}
    rows_since_flush = 0

    async with conn.transaction():
        async for record in conn.cursor(sql, tf, training_window_end, prefetch=5000):
            sym_cols = raw_by_symbol.setdefault(record["symbol"], {})
            sym_cols.setdefault("regime_label", []).append(record["regime_label"])
            for col in float_cols:
                sym_cols.setdefault(col, []).append(record[col])
            for col in _COMPLETE_COLS:
                sym_cols.setdefault(col, []).append(record[col])

            rows_since_flush += 1
            if rows_since_flush >= flush_rows:
                _flush_symbol_buffers(raw_by_symbol, chunk_arrays_by_symbol, float_cols)
                rows_since_flush = 0

    _flush_symbol_buffers(raw_by_symbol, chunk_arrays_by_symbol, float_cols)

    dataset: dict[str, dict[str, np.ndarray]] = {}
    for sym, chunks in chunk_arrays_by_symbol.items():
        dataset[sym] = {col: np.concatenate(arrs) for col, arrs in chunks.items()}
    return dataset


def _compute_not_null_mask(
    dataset: dict[str, dict[str, np.ndarray]],
    feature_name: str,
    parent_1: str,
    parent_2: str,
) -> dict[str, np.ndarray]:
    """Per-symbol non-null mask for (feature, parent_1, parent_2) -- fixed for a
    given feature across every regime/lookahead cell that shares it (up to 36 cells:
    9 regimes x 4 lookahead scales), so this is computed once per (tf, feature) pair
    in main() and reused across all of that feature's cells, instead of _slice_cell
    recomputing the same isnan() passes over the full per-symbol tf arrays on every
    single cell call."""
    return {
        sym: (
            ~np.isnan(arrays[feature_name])
            & ~np.isnan(arrays[parent_1])
            & ~np.isnan(arrays[parent_2])
        )
        for sym, arrays in dataset.items()
    }


def _slice_cell(
    dataset: dict[str, dict[str, np.ndarray]],
    not_null_by_symbol: dict[str, np.ndarray],
    feature_name: str,
    parent_1: str,
    parent_2: str,
    regime_label: str,
    lookahead_bars: int,
    subsample_min_stride: int,
    lookahead_scale_map: dict[int, str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Pure, DB-free slice of one (feature, regime, lookahead) cell out of an
    already-fetched per-tf `dataset` (see `_fetch_tf_dataset()`), pooled across
    symbols. No DB/Kafka dependency -- same constraint as ic_math.py's module
    docstring.

    Per symbol: build a boolean mask (precomputed feature/parent non-null &
    regime match & that scale's completeness flag & that scale's return-column
    non-null), take `np.nonzero(mask)[0]` to get the ordered row-position subset
    the OLD per-cell SQL WHERE clause would have selected, then apply the exact
    same positional stride subsampling (`idx[::stride]`) to that already-filtered,
    order-preserved sequence -- NOT to the raw unfiltered rows.

    The return-column non-null check matters independently of `complete_col`:
    `complete_{scale}` (see services/forward_return_writer.py) only guarantees
    `open_{scale} IS NOT NULL` (+ same-session-date for intraday); `return_{scale}`
    is separately NULL whenever `open_entry <= 0 OR open_{scale} <= 0` -- a
    non-positive-price edge case `complete_{scale}` does not cover. Without this
    check, such a row's NaN would flow into partial_spearman_ic's rankdata(y),
    which does not raise on NaN -- it silently ranks it, corrupting the partial
    correlation with no error.
    """
    scale = _lookahead_to_scale(lookahead_bars, lookahead_scale_map)
    stride = _scale_stride(lookahead_bars, subsample_min_stride)
    return_col = f"return_{scale}"
    complete_col = f"complete_{scale}"

    x_parts, z1_parts, z2_parts, y_parts = [], [], [], []
    for sym, arrays in dataset.items():
        mask = (
            not_null_by_symbol[sym]
            & (arrays["regime_label"] == regime_label)
            & arrays[complete_col]
            & ~np.isnan(arrays[return_col])
        )
        idx = np.nonzero(mask)[0]
        sub_idx = idx[::stride]
        if sub_idx.size == 0:
            continue
        x_parts.append(arrays[feature_name][sub_idx])
        z1_parts.append(arrays[parent_1][sub_idx])
        z2_parts.append(arrays[parent_2][sub_idx])
        y_parts.append(arrays[return_col][sub_idx])

    if not x_parts:
        return np.array([]), np.array([]), np.array([]), 0
    x = np.concatenate(x_parts)
    controls = np.column_stack([np.concatenate(z1_parts), np.concatenate(z2_parts)])
    y = np.concatenate(y_parts)
    return x, controls, y, len(x)


def _process_cell(
    dataset: dict[str, dict[str, np.ndarray]],
    not_null_by_symbol: dict[str, np.ndarray],
    cell: dict,
    parent_1: str,
    parent_2: str,
    subsample_min_stride: int,
    condition_max: float,
    lookahead_scale_map: dict[int, str],
) -> dict | None:
    """One cell's full slice-and-measure step, isolated behind its own try/except so
    that any single cell's failure (including from partial_spearman_ic itself, not
    just _slice_cell) skips only that cell -- never the whole run. Persistence in
    main() happens only after every tf/cell has been processed, so an unguarded
    exception here would otherwise discard every already-computed result."""
    fname = cell["feature_name"]
    try:
        x, controls, y, n = _slice_cell(
            dataset,
            not_null_by_symbol,
            fname,
            parent_1,
            parent_2,
            cell["regime"],
            cell["lookahead_bars"],
            subsample_min_stride,
            lookahead_scale_map,
        )
        if n < 10:
            return None
        partial_ic, p_value, n_used = partial_spearman_ic(
            x, y, controls, condition_max=condition_max
        )
    except Exception as error:  # CLAUDE.md: exception variable name is `error`
        print(f"  SKIP {fname}/{cell['tf']}/{cell['regime']}/{cell['lookahead_bars']}: {error}")
        return None
    return {
        "feature_name": fname,
        "tf": cell["tf"],
        "regime": cell["regime"],
        "lookahead_bars": cell["lookahead_bars"],
        "training_window_end": cell["training_window_end"],
        "partial_ic": partial_ic,
        "partial_ic_p_value": p_value,
        "partial_ic_n": n_used,
    }


async def main() -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    skipped_tfs: list[str] = []
    try:
        async with pool.acquire() as conn:
            config = await _load_config(conn)

            subsample_min_stride_raw = config.get("alpha.ic.subsample_min_stride")
            subsample_min_stride = int(subsample_min_stride_raw) if subsample_min_stride_raw else 5

            condition_max_raw = config.get("alpha.ic.partial_control_condition_max")
            if condition_max_raw is None:
                return _fail(
                    "alpha.ic.partial_control_condition_max missing -- run migration 214 first."
                )
            condition_max = float(condition_max_raw)

            partial_fdr_alpha_raw = config.get("alpha.ic.partial_fdr_alpha")
            if partial_fdr_alpha_raw is None:
                return _fail("alpha.ic.partial_fdr_alpha missing -- run migration 214 first.")
            partial_fdr_alpha = float(partial_fdr_alpha_raw)

            fetch_flush_rows_raw = config.get("infra.interaction_primitives_pilot.fetch_flush_rows")
            # Memory-safety tuning knob, not a correctness gate (unlike the two
            # hard-FAIL checks above for migration 214's keys) -- a sane fallback
            # if the row is ever missing is fine.
            fetch_flush_rows = int(fetch_flush_rows_raw) if fetch_flush_rows_raw else 500_000

            features = await _load_interaction_features(conn)
            if not features:
                return _fail("no tier='1_interaction' rows found in concept_registry.")
            feature_names = [f["feature_name"] for f in features]
            parents_by_feature = {f["feature_name"]: f["parents"] for f in features}

            cells = await _load_pooled_cells(conn, feature_names)
            if not cells:
                return _fail(
                    "no reliable cross-sectional (symbol='POOLED', regime != '_pooled') "
                    "feature_ic_scores rows found for the interaction-primitive cohort -- "
                    "run ic_engine.py first."
                )

            # A single global training_window_end is a verified fact of the live
            # 864-cell cohort (see module docstring / task-3-v2-brief.md), not an
            # assumption -- fail loudly rather than silently pick one value if that
            # ever stops being true.
            distinct_window_ends = {cell["training_window_end"] for cell in cells}
            if len(distinct_window_ends) != 1:
                raise RuntimeError(
                    f"Expected a single global training_window_end across all "
                    f"{len(cells)} cells, found {len(distinct_window_ends)}: "
                    f"{sorted(distinct_window_ends)}"
                )
            training_window_end = next(iter(distinct_window_ends))

            # Dedup the parent-atomic column set once (e.g. volume_z is a parent of
            # 5 of the 8 features) so _fetch_tf_dataset() fetches each column once
            # per tf, not once per feature.
            parent_cols = sorted({p for parents in parents_by_feature.values() for p in parents})

            cells_by_tf: dict[str, list[dict]] = {}
            for cell in cells:
                cells_by_tf.setdefault(cell["tf"], []).append(cell)

            results = []
            for tf, tf_cells in cells_by_tf.items():
                try:
                    lookahead_scale_map = _build_lookahead_map(config, tf)
                    dataset = await _fetch_tf_dataset(
                        conn,
                        tf,
                        feature_names,
                        parent_cols,
                        training_window_end,
                        flush_rows=fetch_flush_rows,
                    )
                except Exception as error:  # CLAUDE.md: exception variable name is `error`
                    print(f"  SKIP tf={tf}: {error}")
                    skipped_tfs.append(tf)
                    continue

                cells_by_feature: dict[str, list[dict]] = {}
                for cell in tf_cells:
                    cells_by_feature.setdefault(cell["feature_name"], []).append(cell)

                for fname, feature_cells in cells_by_feature.items():
                    parent_1, parent_2 = parents_by_feature[fname]
                    not_null_by_symbol = _compute_not_null_mask(dataset, fname, parent_1, parent_2)
                    for cell in feature_cells:
                        result = _process_cell(
                            dataset,
                            not_null_by_symbol,
                            cell,
                            parent_1,
                            parent_2,
                            subsample_min_stride,
                            condition_max,
                            lookahead_scale_map,
                        )
                        if result is not None:
                            results.append(result)

            valid = [r for r in results if not np.isnan(r["partial_ic_p_value"])]
            if valid:
                p_values = [r["partial_ic_p_value"] for r in valid]
                reject, p_corrected = apply_bh_fdr(p_values, partial_fdr_alpha)
                for r, rej, p_corr in zip(valid, reject, p_corrected, strict=True):
                    r["passes_partial_fdr"] = bool(rej)
                    r["partial_ic_p_corrected"] = float(p_corr)

            async with conn.transaction():
                await conn.executemany(
                    "UPDATE feature_ic_scores SET partial_ic = $1, partial_ic_p_value = $2, "
                    "partial_ic_n = $3, passes_partial_fdr = $4 "
                    "WHERE feature_name = $5 AND tf = $6 AND lookahead_bars = $7 "
                    "AND training_window_end = $8 AND symbol = 'POOLED' "
                    "AND is_pooled = true AND regime = $9",
                    [
                        (
                            r["partial_ic"],
                            r["partial_ic_p_value"],
                            r["partial_ic_n"],
                            r.get("passes_partial_fdr"),
                            r["feature_name"],
                            r["tf"],
                            r["lookahead_bars"],
                            r["training_window_end"],
                            r["regime"],
                        )
                        for r in results
                    ],
                )

        n_measured = len(results)
        n_valid = len(valid)
        n_pass = sum(1 for r in valid if r.get("passes_partial_fdr"))
        frac_pass = (n_pass / n_valid) if n_valid else 0.0

        print("## Todo 037 Interaction Primitives Pilot")
        print()
        if skipped_tfs:
            print(
                f"WARNING: {len(skipped_tfs)} timeframe(s) skipped due to fetch failure: "
                f"{sorted(skipped_tfs)} -- the results below cover only the successfully-"
                "fetched timeframes and do NOT represent the full cohort. Do not treat the "
                "pass fraction below as the todo 037 decision-gate answer until this is "
                "re-run clean."
            )
            print()
        print(f"Cells measured: {n_measured} (numerically valid: {n_valid})")
        print(
            f"Cells passing partial-IC BH-FDR (alpha={partial_fdr_alpha}): {n_pass}/{n_valid} ({frac_pass:.1%})"
        )
        print()
        for r in sorted(
            valid, key=lambda r: (r["feature_name"], r["tf"], r["regime"], r["lookahead_bars"])
        ):
            verdict = "PASS" if r.get("passes_partial_fdr") else "fail"
            print(
                f"  {verdict:5s} {r['feature_name']:22s} tf={r['tf']:5s} regime={r['regime']:12s} "
                f"lookahead={r['lookahead_bars']:3d} partial_ic={r['partial_ic']:+.4f} "
                f"p_corrected={r['partial_ic_p_corrected']:.4f} n={r['partial_ic_n']}"
            )
        print()
        print("Decision rule (todo 037): a meaningful fraction of the cohort with genuine ")
        print("incremental IC surviving FDR -> plan the full Interaction Factory. ")
        print("Near-zero -> shelve Interaction Factory outright.")
        print(f"-> Observed: {frac_pass:.1%} of numerically valid cells pass.")
    finally:
        await pool.close()
    return 1 if skipped_tfs else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
