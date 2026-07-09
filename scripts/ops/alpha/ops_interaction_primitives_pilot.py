#!/usr/bin/env python3
"""
ops_interaction_primitives_pilot.py -- todo 037 partial-IC pilot.

Answers: do the 8 already-live Renaissance interaction primitives
(feature_registry.tier='1_interaction') carry genuine incremental IC after
controlling for their parent atomics, or is their naive IC fully explained by the
parents? Reuses already-measured pooled-aggregate feature_ic_scores rows
(is_pooled=true, regime='_pooled', symbol='POOLED' -- the highest-power
cross-sectional population, see project memory's EIC-04 diagnosis) as the input
population, rather than re-deriving IC from scratch.

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
    """Already-measured pooled-aggregate cells (symbol='POOLED', is_pooled=true,
    regime='_pooled') for the given features -- the highest-power population, and
    the same one used for the EIC-04 sparse-signal cross-check."""
    rows = await conn.fetch(
        "SELECT feature_name, tf, lookahead_bars, training_window_end, n_independent "
        "FROM feature_ic_scores "
        "WHERE feature_name = ANY($1::text[]) "
        "  AND symbol = 'POOLED' AND is_pooled = true AND regime = '_pooled' "
        "  AND reliable = true "
        "ORDER BY feature_name, tf, lookahead_bars",
        feature_names,
    )
    return [dict(r) for r in rows]


def _scale_stride(lookahead_bars: int, subsample_min_stride: int) -> int:
    return max(subsample_min_stride, lookahead_bars)


async def _fetch_cell_arrays(
    conn: asyncpg.Connection,
    feature_name: str,
    parents: list[str],
    tf: str,
    lookahead_bars: int,
    training_window_end,
    subsample_min_stride: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Stream (feature, parent_1, parent_2, return) rows across all symbols for one
    (feature, tf, lookahead) pooled cell, subsampling positionally within each
    symbol's row block, then pooling across symbols.

    Named server-side cursor + itersize batching -- the same OOM-avoidance shape as
    migrations 183/209/212 (see CLAUDE.md "ProcessPoolExecutor workers are compute-
    only" gotcha and its three prior sibling fixes). This pooled cell can be up to
    ~1.5M raw rows before subsampling.
    """
    parent_1, parent_2 = parents[0], parents[1]
    stride = _scale_stride(lookahead_bars, subsample_min_stride)
    complete_col = f"complete_{_lookahead_to_scale(lookahead_bars)}"
    return_col = f"return_{_lookahead_to_scale(lookahead_bars)}"

    sql = f"""
        SELECT fv.symbol, fv.bar_ts, fv.{feature_name} AS x,
               fv.{parent_1} AS z1, fv.{parent_2} AS z2,
               fr.{return_col} AS y
        FROM feature_vectors fv
        INNER JOIN forward_returns fr
            ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
            AND fr.return_type = 'executable_open_to_open'
        WHERE fv.tf = $1 AND fv.bar_ts <= $2 AND fr.{complete_col} = true
          AND fv.{feature_name} IS NOT NULL AND fv.{parent_1} IS NOT NULL AND fv.{parent_2} IS NOT NULL
        ORDER BY fv.symbol, fv.bar_ts
    """
    x_by_symbol: dict[str, list[float]] = {}
    z1_by_symbol: dict[str, list[float]] = {}
    z2_by_symbol: dict[str, list[float]] = {}
    y_by_symbol: dict[str, list[float]] = {}

    async with conn.transaction():
        async for record in conn.cursor(sql, tf, training_window_end, prefetch=5000):
            sym = record["symbol"]
            x_by_symbol.setdefault(sym, []).append(record["x"])
            z1_by_symbol.setdefault(sym, []).append(record["z1"])
            z2_by_symbol.setdefault(sym, []).append(record["z2"])
            y_by_symbol.setdefault(sym, []).append(record["y"])

    x_parts, z1_parts, z2_parts, y_parts = [], [], [], []
    for sym in x_by_symbol:
        idx = np.arange(0, len(x_by_symbol[sym]), stride)
        x_parts.append(np.asarray(x_by_symbol[sym])[idx])
        z1_parts.append(np.asarray(z1_by_symbol[sym])[idx])
        z2_parts.append(np.asarray(z2_by_symbol[sym])[idx])
        y_parts.append(np.asarray(y_by_symbol[sym])[idx])

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
                    "pooled (symbol='POOLED', regime='_pooled') feature_ic_scores rows "
                    "found for the interaction-primitive cohort -- run ic_engine.py first."
                )
                return 0

            results = []
            for cell in cells:
                fname = cell["feature_name"]
                parents = parents_by_feature[fname]
                try:
                    x, controls, y, n = await _fetch_cell_arrays(
                        conn,
                        fname,
                        parents,
                        cell["tf"],
                        cell["lookahead_bars"],
                        cell["training_window_end"],
                        subsample_min_stride,
                    )
                except Exception as error:  # CLAUDE.md: exception variable name is `error`
                    print(f"  SKIP {fname}/{cell['tf']}/{cell['lookahead_bars']}: {error}")
                    continue

                if n < 10:
                    continue
                partial_ic, p_value, n_used = partial_spearman_ic(
                    x, y, controls, condition_max=condition_max
                )
                results.append(
                    {
                        "feature_name": fname,
                        "tf": cell["tf"],
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
                        "AND is_pooled = true AND regime = '_pooled'",
                        r["partial_ic"],
                        r["partial_ic_p_value"],
                        r["partial_ic_n"],
                        r.get("passes_partial_fdr"),
                        r["feature_name"],
                        r["tf"],
                        r["lookahead_bars"],
                        r["training_window_end"],
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
        for r in sorted(valid, key=lambda r: (r["feature_name"], r["tf"], r["lookahead_bars"])):
            verdict = "PASS" if r.get("passes_partial_fdr") else "fail"
            print(
                f"  {verdict:5s} {r['feature_name']:22s} tf={r['tf']:5s} "
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
