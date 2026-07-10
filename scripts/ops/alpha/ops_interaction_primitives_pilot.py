#!/usr/bin/env python3
"""
ops_interaction_primitives_pilot.py -- todo 037 partial-IC pilot.

Answers: do the 8 already-live Renaissance interaction primitives
(feature_registry.tier='1_interaction') carry genuine incremental IC after
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

from src.config.settings import Settings
from src.intelligence.statistics.ic_math import apply_bh_fdr, partial_spearman_ic

_SCALES = ("fast", "mid", "slow", "extended")


async def _load_interaction_features(conn: asyncpg.Connection) -> list[dict]:
    """tier='1_interaction' rows from feature_registry with their parent atomics."""
    rows = await conn.fetch(
        "SELECT feature_name, parent_features FROM feature_registry "
        "WHERE tier = '1_interaction' AND status = 'active' "
        "ORDER BY feature_name"
    )
    return [
        {"feature_name": r["feature_name"], "parents": list(r["parent_features"])} for r in rows
    ]


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


_RETURN_COLS = tuple(f"return_{scale}" for scale in _SCALES)
_COMPLETE_COLS = tuple(f"complete_{scale}" for scale in _SCALES)


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
    once.
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
            ON mr.tf = fv.tf AND mr.ts = fv.bar_ts AND mr.asset_class = 'equity'
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


def _slice_cell(
    dataset: dict[str, dict[str, np.ndarray]],
    feature_name: str,
    parent_1: str,
    parent_2: str,
    regime_label: str,
    lookahead_bars: int,
    subsample_min_stride: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Pure, DB-free slice of one (feature, regime, lookahead) cell out of an
    already-fetched per-tf `dataset` (see `_fetch_tf_dataset()`), pooled across
    symbols. No DB/Kafka dependency -- same constraint as ic_math.py's module
    docstring.

    Per symbol: build a boolean mask (regime match & feature/parent non-null &
    that scale's completeness flag), take `np.nonzero(mask)[0]` to get the ordered
    row-position subset the OLD per-cell SQL WHERE clause would have selected, then
    apply the exact same positional stride subsampling (`idx[::stride]`) to that
    already-filtered, order-preserved sequence -- NOT to the raw unfiltered rows.
    """
    scale = _lookahead_to_scale(lookahead_bars)
    stride = _scale_stride(lookahead_bars, subsample_min_stride)
    return_col = f"return_{scale}"
    complete_col = f"complete_{scale}"

    x_parts, z1_parts, z2_parts, y_parts = [], [], [], []
    for arrays in dataset.values():
        mask = (
            (arrays["regime_label"] == regime_label)
            & ~np.isnan(arrays[feature_name])
            & ~np.isnan(arrays[parent_1])
            & ~np.isnan(arrays[parent_2])
            & arrays[complete_col]
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


_LOOKAHEAD_TO_SCALE_CACHE: dict[int, str] = {}


def _lookahead_to_scale(lookahead_bars: int) -> str:
    """Map a lookahead_bars int back to its scale name (fast/mid/slow/extended) via
    the cached APR values loaded once in main(). Populated by _init_lookahead_map()."""
    if lookahead_bars not in _LOOKAHEAD_TO_SCALE_CACHE:
        raise KeyError(
            f"lookahead_bars={lookahead_bars} not in the loaded APR lookahead map -- "
            "call _init_lookahead_map() before any cell processing."
        )
    return _LOOKAHEAD_TO_SCALE_CACHE[lookahead_bars]


async def _init_lookahead_map(conn: asyncpg.Connection) -> None:
    for scale in _SCALES:
        val = await conn.fetchval(
            "SELECT config_value FROM config_state WHERE config_key = $1",
            f"alpha.ic.lookahead.{scale}",
        )
        default = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}[scale]
        _LOOKAHEAD_TO_SCALE_CACHE[int(val) if val is not None else default] = scale


async def main() -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            await _init_lookahead_map(conn)

            subsample_min_stride_raw = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.subsample_min_stride'"
            )
            subsample_min_stride = int(subsample_min_stride_raw) if subsample_min_stride_raw else 5

            condition_max_raw = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.partial_control_condition_max'"
            )
            if condition_max_raw is None:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: "
                    "alpha.ic.partial_control_condition_max missing -- run migration 214 first."
                )
                return 0
            condition_max = float(condition_max_raw)

            partial_fdr_alpha_raw = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.partial_fdr_alpha'"
            )
            if partial_fdr_alpha_raw is None:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: "
                    "alpha.ic.partial_fdr_alpha missing -- run migration 214 first."
                )
                return 0
            partial_fdr_alpha = float(partial_fdr_alpha_raw)

            fetch_flush_rows_raw = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = "
                "'infra.interaction_primitives_pilot.fetch_flush_rows'"
            )
            # Memory-safety tuning knob, not a correctness gate (unlike the two
            # hard-FAIL checks above for migration 214's keys) -- a sane fallback
            # if the row is ever missing is fine.
            fetch_flush_rows = int(fetch_flush_rows_raw) if fetch_flush_rows_raw else 500_000

            features = await _load_interaction_features(conn)
            if not features:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: no "
                    "tier='1_interaction' rows found in feature_registry."
                )
                return 0
            feature_names = [f["feature_name"] for f in features]
            parents_by_feature = {f["feature_name"]: f["parents"] for f in features}

            cells = await _load_pooled_cells(conn, feature_names)
            if not cells:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: no reliable "
                    "cross-sectional (symbol='POOLED', regime != '_pooled') feature_ic_scores "
                    "rows found for the interaction-primitive cohort -- run ic_engine.py first."
                )
                return 0

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
                    continue

                for cell in tf_cells:
                    fname = cell["feature_name"]
                    parent_1, parent_2 = parents_by_feature[fname]
                    try:
                        x, controls, y, n = _slice_cell(
                            dataset,
                            fname,
                            parent_1,
                            parent_2,
                            cell["regime"],
                            cell["lookahead_bars"],
                            subsample_min_stride,
                        )
                    except Exception as error:  # CLAUDE.md: exception variable name is `error`
                        print(
                            f"  SKIP {fname}/{tf}/{cell['regime']}/{cell['lookahead_bars']}: {error}"
                        )
                        continue

                    if n < 10:
                        continue
                    partial_ic, p_value, n_used = partial_spearman_ic(
                        x, y, controls, condition_max=condition_max
                    )
                    results.append(
                        {
                            "feature_name": fname,
                            "tf": tf,
                            "regime": cell["regime"],
                            "lookahead_bars": cell["lookahead_bars"],
                            "training_window_end": cell["training_window_end"],
                            "partial_ic": partial_ic,
                            "partial_ic_p_value": p_value,
                            "partial_ic_n": n_used,
                        }
                    )

            valid = [r for r in results if not np.isnan(r["partial_ic_p_value"])]
            if valid:
                p_values = [r["partial_ic_p_value"] for r in valid]
                reject, p_corrected = apply_bh_fdr(p_values, partial_fdr_alpha)
                for r, rej, p_corr in zip(valid, reject, p_corrected, strict=True):
                    r["passes_partial_fdr"] = bool(rej)
                    r["partial_ic_p_corrected"] = float(p_corr)

            async with conn.transaction():
                for r in results:
                    await conn.execute(
                        "UPDATE feature_ic_scores SET partial_ic = $1, partial_ic_p_value = $2, "
                        "partial_ic_n = $3, passes_partial_fdr = $4 "
                        "WHERE feature_name = $5 AND tf = $6 AND lookahead_bars = $7 "
                        "AND training_window_end = $8 AND symbol = 'POOLED' "
                        "AND is_pooled = true AND regime = $9",
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

        n_measured = len(results)
        n_valid = len(valid)
        n_pass = sum(1 for r in valid if r.get("passes_partial_fdr"))
        frac_pass = (n_pass / n_valid) if n_valid else 0.0

        print("## Todo 037 Interaction Primitives Pilot")
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
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
