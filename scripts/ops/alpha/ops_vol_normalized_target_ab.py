#!/usr/bin/env python3
"""
ops_vol_normalized_target_ab.py -- Component F (todo 097, Phase 143.1-03) explicit A/B:
vol-normalized vs. raw-return POOLED-strata IC target.

Design: 143.1-CONTEXT.md Component F, 143.1-RESEARCH.md Component F section,
docs/plans/methodology-change-ledger.md Component F entry.

Recomputes POOLED-strata IC (symbol='POOLED', all 58 equity ETFs pooled -- the exact
population the ensemble trains on: ensemble_trainer.py's eligibility queries at lines
317, 430-431, 469, 540) using the vol-normalized target (return_x / true_range_pct, via
src.intelligence.statistics.ic_math.vol_normalized_return -- Task 1's epsilon-guarded
helper) and compares the resulting qualifying-feature ranking directly against the raw-
return baseline already stored in feature_ic_scores for the same (tf, regime,
lookahead_bars) strata.

Per the locked validation contract (143.1-CONTEXT.md Component F), this is an EXPLICIT
A/B, never a silent production-target swap: `return_fast/mid/slow/extended` stay raw in
`forward_returns`/`feature_ic_scores`. If vol-normalized rankings are materially
identical to raw, the recommendation is to retire the transform rather than keep it on
theory alone -- this script's report is the evidence that recommendation is based on.

Scope note (this script's own runtime, not the eventual A/B verdict): fully recomputing
POOLED IC for every (tf, regime) stratum is corpus-scale work (the same chunked
feature_vectors x forward_returns fetch _compute_cross_sectional_tf uses). By default
this script samples a bounded number of regimes per tf (--max-regimes-per-tf, default 2)
so it can be exercised cheaply as part of this plan. Component F's ACTUAL A/B verdict for
the full corpus is recorded in Plan 07, after Component E's corpus-wide re-run already
rebuilds feature_ic_scores under the corrected pipeline -- Plan 07 re-invokes this same
script with --all-regimes for the definitive, full-corpus comparison. Sequenced after A,
before E, per 143.1-CONTEXT.md's locked ordering (rides the same corpus load).

Qualifying-feature criterion:
  - raw baseline: feature_ic_scores.passes_fdr (already computed by production, whatever
    CI/gate machinery was live when that row was written -- this script does not
    recompute it).
  - vol-normalized: BH-FDR at --fdr-alpha (default 0.05) applied to THIS script's own
    freshly-computed p-values, pooled into ONE family across every evaluated stratum in
    the run -- mirroring production's single corpus-wide family, per Fable 5's 2026-07-19
    review (docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md,
    Q3a). Prior to that review this used one family per (tf, regime, lookahead_bars)
    stratum, which inflated the vol-normalized qualifying count relative to raw by
    weakening the correction -- not evidence of more real signal. The CI/bootstrap gate
    itself is intentionally NOT recomputed here, since a full bootstrap-CI recompute
    across every (tf, regime) stratum's full feature set would turn this cheap diagnostic
    into a second corpus-wide re-run, defeating its purpose of a fast pre-Plan-07 sanity
    check.

Invariant 1 (executable returns only, CLAUDE.md): unaffected -- reads
forward_returns.return_type = 'executable_open_to_open' only, same filter production
uses. No new query beyond what this diagnostic needs; no write path at all.

No production writes -- read-only against feature_vectors / forward_returns /
market_regimes / feature_ic_scores. Recomputed vol-normalized IC values are NOT persisted
anywhere; this script's stdout report plus the methodology-change-ledger entry are the
record (per this project's pre-commitment convention for gate-affecting decisions).

Exit code is always 0 -- informational, not a gate (matches ops_ic_null_calibration.py's
house style).

Never logs per-row inside the corpus loop (CLAUDE.md convention): accumulates one row per
(tf, regime, lookahead_bars) stratum and prints once per stratum, never per underlying
observation.

Usage:
    python scripts/ops/alpha/ops_vol_normalized_target_ab.py
    python scripts/ops/alpha/ops_vol_normalized_target_ab.py --tf 5m --max-regimes-per-tf 3
    python scripts/ops/alpha/ops_vol_normalized_target_ab.py --all-regimes   # Plan 07 use
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np
from scipy.stats import rankdata, spearmanr

from services._batch_utils import LOOKAHEAD_FALLBACKS_BY_TF
from services.ic_engine import _CROSS_SECTIONAL_SYMBOL, _FEATURE_NAMES, _SCALES
from src.config.settings import Settings
from src.intelligence.statistics.ic_math import (
    _p_values_from_ic,
    _vectorized_ic,
    apply_bh_fdr,
    vol_normalized_return,
)

_TFS = ("5m", "15m", "1h", "1d")
_DEFAULT_MAX_REGIMES_PER_TF = 2
_CS_CHUNK_TS_DEFAULT = 5000
_FDR_ALPHA_DEFAULT = 0.05
_SUBSAMPLE_MIN_STRIDE_DEFAULT = 5

_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"


# asyncpg (unlike psycopg2, used elsewhere in this project) only supports positional
# $1/$2/... parameters -- no %(name)s named-parameter binding.
_REGIMES_SQL = """
    SELECT DISTINCT regime FROM feature_ic_scores
    WHERE symbol = $1 AND is_pooled = true AND regime != '_pooled'
      AND training_window_end = $2 AND tf = $3
    ORDER BY regime
"""

_BASELINE_SQL = """
    SELECT feature_name, lookahead_bars, ic_value, ic_sign, passes_fdr
    FROM feature_ic_scores
    WHERE symbol = $1 AND is_pooled = true AND regime = $2
      AND tf = $3 AND training_window_end = $4
"""

_REGIME_TS_SQL = """
    SELECT ts FROM market_regimes
    WHERE regime_group = 'equity' AND tf = $1 AND regime_label = $2
      AND ts <= $3
    ORDER BY ts
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tf", choices=_TFS, default=None, help="Restrict to one timeframe (default: all 4)."
    )
    parser.add_argument(
        "--max-regimes-per-tf",
        type=int,
        default=_DEFAULT_MAX_REGIMES_PER_TF,
        help="Bound the number of (tf, regime) strata recomputed -- keeps this diagnostic "
        "cheap. Ignored if --all-regimes is set.",
    )
    parser.add_argument(
        "--all-regimes",
        action="store_true",
        help="Recompute every (tf, regime) stratum -- the full comparison Plan 07 runs "
        "against the corpus-wide re-run. Corpus-scale runtime; not the default.",
    )
    parser.add_argument(
        "--fdr-alpha",
        type=float,
        default=None,
        help="BH-FDR alpha for the vol-normalized side. Default: alpha.ic.fdr_alpha "
        "(production's live value) -- was a hardcoded 0.05 default with no APR read at "
        "all, unlike this script's lookahead/subsample_min_stride keys, which already "
        "load live; fixed to match (2026-07-19 naming/APR audit).",
    )
    parser.add_argument("--cs-chunk-ts", type=int, default=_CS_CHUNK_TS_DEFAULT)
    parser.add_argument(
        "--min-independent",
        type=int,
        default=None,
        help="Reliability floor on n_independent for the aggregate verdict -- strata "
        "below this are still printed but excluded from the summary median/counts "
        "(Fable 5 Q3b: extended-horizon strata collapse effective N and read as noise, "
        "not real target divergence). Default: alpha.ic.min_reliable_n (production's "
        "own reliability floor, reused here rather than inventing a new threshold).",
    )
    return parser.parse_args()


async def _load_config_int(pool: asyncpg.Pool, key: str, default: int) -> int:
    row = await pool.fetchval("SELECT config_value FROM config_state WHERE config_key = $1", key)
    return int(row) if row is not None else default


async def _load_config_float(pool: asyncpg.Pool, key: str, default: float) -> float:
    row = await pool.fetchval("SELECT config_value FROM config_state WHERE config_key = $1", key)
    return float(row) if row is not None else default


async def _fetch_regime_timestamps(pool: asyncpg.Pool, tf: str, regime: str, vintage) -> list:
    rows = await pool.fetch(_REGIME_TS_SQL, tf, regime, vintage)
    return [r["ts"] for r in rows]


async def _fetch_pooled_arrays(
    pool: asyncpg.Pool, tf: str, regime_ts: list, cs_chunk_ts: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Chunked fetch of feature_vectors x forward_returns, pooled across all symbols,
    for the given regime timestamps -- mirrors _compute_cross_sectional_tf's chunk_sql
    exactly (same JOIN, same Invariant 1 return_type filter), read-only, no new query
    shape.
    """
    feature_cols = ", ".join(f'fv."{f}"' for f in _FEATURE_NAMES)
    return_cols = ", ".join(f"fr.return_{s}" for s in _SCALES)
    complete_cols = ", ".join(f"fr.complete_{s}" for s in _SCALES)
    chunk_sql = f"""
        SELECT fv.bar_ts, {feature_cols}, {return_cols}, {complete_cols}
        FROM feature_vectors fv
        INNER JOIN forward_returns fr
            ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
            AND fr.return_type = 'executable_open_to_open'
        WHERE fv.tf = $1 AND fv.bar_ts = ANY($2::timestamptz[])
        ORDER BY fv.bar_ts
    """
    n_features = len(_FEATURE_NAMES)
    n_scales = len(_SCALES)
    X_chunks: list[np.ndarray] = []
    ret_chunks: list[np.ndarray] = []
    cmp_chunks: list[np.ndarray] = []

    for chunk_start in range(0, len(regime_ts), cs_chunk_ts):
        ts_chunk = regime_ts[chunk_start : chunk_start + cs_chunk_ts]
        rows = await pool.fetch(chunk_sql, tf, ts_chunk)
        if not rows:
            continue
        n_batch = len(rows)
        X_chunks.append(
            np.array(
                [[r[f] for f in _FEATURE_NAMES] for r in rows],
                dtype=np.float32,
            )
        )
        ret_chunk = np.full((n_batch, n_scales), np.nan)
        cmp_chunk = np.zeros((n_batch, n_scales), dtype=bool)
        for i, row in enumerate(rows):
            for j, scale in enumerate(_SCALES):
                val = row[f"return_{scale}"]
                ret_chunk[i, j] = val if val is not None else np.nan
                cmp_chunk[i, j] = bool(row[f"complete_{scale}"])
        ret_chunks.append(ret_chunk)
        cmp_chunks.append(cmp_chunk)

    if not X_chunks:
        return (
            np.empty((0, n_features), dtype=np.float32),
            np.empty((0, n_scales)),
            np.empty((0, n_scales), dtype=bool),
        )
    return np.vstack(X_chunks), np.vstack(ret_chunks), np.vstack(cmp_chunks)


def _recompute_vol_normalized_ic(
    X_raw: np.ndarray,
    returns_mat: np.ndarray,
    complete_mat: np.ndarray,
    scale_idx: int,
    lookahead_bars: int,
    subsample_min_stride: int,
) -> dict[str, dict] | None:
    """Recompute vol-normalized POOLED IC (and p-value) for every feature at one scale.

    Mirrors _compute_cross_sectional_tf's per-scale stride/valid_mask logic exactly
    (same stride = max(subsample_min_stride, lookahead_bars) convention), then swaps
    the raw return_x target for vol_normalized_return(return_x, true_range_pct) --
    the Task 1 helper -- before computing IC. Returns None if there is not enough
    valid data at this stride (mirrors production's min_reliable_n early-exit, using
    a floor of 4 -- the same n>=4 requirement _fisher_z_ci and _vectorized_ic assume).

    Does NOT apply BH-FDR -- p-values are pooled across every evaluated stratum and
    corrected once in main(), mirroring production's single corpus-wide family (see
    module docstring, Q3a). Reporting passes_fdr per-stratum here would require a
    second, incompatible correction; callers must use the p_value field.
    """
    n_raw = len(X_raw)
    if n_raw == 0:
        return None
    stride = max(subsample_min_stride, lookahead_bars)
    sub_idx = np.arange(0, n_raw, stride)
    X_sub = X_raw[sub_idx]
    returns_sub = returns_mat[sub_idx]
    complete_sub = complete_mat[sub_idx]

    scale_complete = complete_sub[:, scale_idx]
    returns_scale = returns_sub[:, scale_idx]
    valid_mask = scale_complete & np.isfinite(returns_scale)
    n_valid = int(valid_mask.sum())
    if n_valid < 4:
        return None

    tr_idx = _FEATURE_NAMES.index("true_range_pct")
    X_valid = X_sub[valid_mask]
    true_range_pct_scale = X_valid[:, tr_idx]
    Y_scale = returns_scale[valid_mask]

    vol_target = vol_normalized_return(Y_scale, true_range_pct_scale)

    ranks_X = rankdata(X_valid, axis=0)
    ranks_vol = rankdata(vol_target)
    ic_vec = _vectorized_ic(ranks_X, ranks_vol)
    p_vec = _p_values_from_ic(ic_vec, n_valid)

    return {
        feat_name: {
            "ic_value": float(ic_vec[i]) if np.isfinite(ic_vec[i]) else None,
            "p_value": float(p_vec[i]) if np.isfinite(p_vec[i]) else None,
            "n_valid": n_valid,
        }
        for i, feat_name in enumerate(_FEATURE_NAMES)
    }


async def _evaluate_stratum(
    pool: asyncpg.Pool,
    tf: str,
    regime: str,
    vintage,
    lookaheads_by_tf: dict[str, dict[str, int]],
    subsample_min_stride: int,
    cs_chunk_ts: int,
) -> list[dict]:
    """Per-scale stratum results, WITHOUT a finalized vol-normalized qualifying set --
    that requires the pooled BH-FDR pass across every stratum in the run, done once in
    main(). Each result carries raw_qualifying (already final, from production's own
    corpus-wide passes_fdr) plus per-feature vol p-values for main() to pool.
    """
    # Todo 146/202: lookahead grid is per-tf now -- this stratum's own tf is already a
    # parameter, so resolve once here rather than the caller passing one shared dict.
    lookaheads = lookaheads_by_tf[tf]
    baseline_rows = await pool.fetch(_BASELINE_SQL, _CROSS_SECTIONAL_SYMBOL, regime, tf, vintage)
    if not baseline_rows:
        return []
    baseline_by_lookahead: dict[int, dict[str, dict]] = {}
    for r in baseline_rows:
        baseline_by_lookahead.setdefault(r["lookahead_bars"], {})[r["feature_name"]] = dict(r)

    regime_ts = await _fetch_regime_timestamps(pool, tf, regime, vintage)
    if not regime_ts:
        return []
    X_raw, returns_mat, complete_mat = await _fetch_pooled_arrays(pool, tf, regime_ts, cs_chunk_ts)
    if len(X_raw) == 0:
        return []

    results: list[dict] = []
    for scale_idx, scale in enumerate(_SCALES):
        lookahead_bars = lookaheads[scale]
        baseline = baseline_by_lookahead.get(lookahead_bars)
        if not baseline:
            continue
        vol_by_feature = _recompute_vol_normalized_ic(
            X_raw,
            returns_mat,
            complete_mat,
            scale_idx,
            lookahead_bars,
            subsample_min_stride,
        )
        if vol_by_feature is None:
            continue

        raw_ic_vals: list[float] = []
        vol_ic_vals: list[float] = []
        raw_qualifying: set[str] = set()
        vol_pvalues: dict[str, float] = {}
        n_independent = 0
        for feat_name in _FEATURE_NAMES:
            base = baseline.get(feat_name)
            vol = vol_by_feature.get(feat_name)
            if base is None or vol is None:
                continue
            n_independent = vol["n_valid"]
            if base["ic_value"] is None or vol["ic_value"] is None:
                continue
            raw_ic_vals.append(base["ic_value"])
            vol_ic_vals.append(vol["ic_value"])
            if base["passes_fdr"]:
                raw_qualifying.add(feat_name)
            if vol["p_value"] is not None:
                vol_pvalues[feat_name] = vol["p_value"]

        if len(raw_ic_vals) < 3:
            continue

        rank_corr, _ = spearmanr(raw_ic_vals, vol_ic_vals)
        results.append(
            {
                "tf": tf,
                "regime": regime,
                "lookahead_bars": lookahead_bars,
                "n_features_compared": len(raw_ic_vals),
                "n_independent": n_independent,
                "rank_correlation": float(rank_corr) if np.isfinite(rank_corr) else None,
                "raw_qualifying": raw_qualifying,
                "vol_pvalues": vol_pvalues,
            }
        )
    return results


def _apply_pooled_vol_fdr(all_results: list[dict], fdr_alpha: float) -> None:
    """Pool every stratum's vol-normalized p-values into ONE BH-FDR family and write
    raw_only/vol_only/both back onto each result dict in place -- mirrors production's
    single corpus-wide family instead of one family per stratum (Q3a fix).
    """
    pooled_keys: list[tuple[int, str]] = []
    pooled_pvals: list[float] = []
    for i, r in enumerate(all_results):
        for feat_name, p in r["vol_pvalues"].items():
            pooled_keys.append((i, feat_name))
            pooled_pvals.append(p)

    reject = [False] * len(pooled_pvals)
    if pooled_pvals:
        reject, _ = apply_bh_fdr(pooled_pvals, fdr_alpha)

    vol_qualifying_by_stratum: list[set[str]] = [set() for _ in all_results]
    for (i, feat_name), passed in zip(pooled_keys, reject):
        if passed:
            vol_qualifying_by_stratum[i].add(feat_name)

    for i, r in enumerate(all_results):
        raw_q = r["raw_qualifying"]
        vol_q = vol_qualifying_by_stratum[i]
        r["raw_only"] = sorted(raw_q - vol_q)
        r["vol_only"] = sorted(vol_q - raw_q)
        r["both"] = sorted(raw_q & vol_q)


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        vintage = await pool.fetchval(_LATEST_VINTAGE_SQL)
        if vintage is None:
            print("ERROR: feature_ic_scores is empty -- nothing to sample.")
            return 0

        lookaheads_by_tf = {
            tf: {
                scale: await _load_config_int(pool, f"alpha.ic.lookahead.{tf}.{scale}", default)
                for scale, default in fallbacks.items()
            }
            for tf, fallbacks in LOOKAHEAD_FALLBACKS_BY_TF.items()
        }
        subsample_min_stride = await _load_config_int(
            pool, "alpha.ic.subsample_min_stride", _SUBSAMPLE_MIN_STRIDE_DEFAULT
        )
        fdr_alpha = (
            args.fdr_alpha
            if args.fdr_alpha is not None
            else await _load_config_float(pool, "alpha.ic.fdr_alpha", _FDR_ALPHA_DEFAULT)
        )
        min_independent = (
            args.min_independent
            if args.min_independent is not None
            else await _load_config_int(pool, "alpha.ic.min_reliable_n", 100)
        )

        tfs = (args.tf,) if args.tf else _TFS

        print("# Component F A/B Report: vol-normalized vs. raw-return POOLED IC target\n")
        print(f"vintage: {vintage}")
        print(
            f"tfs={tfs}, max_regimes_per_tf="
            f"{'ALL' if args.all_regimes else args.max_regimes_per_tf}, "
            f"fdr_alpha={fdr_alpha}\n"
        )

        all_results: list[dict] = []
        for tf in tfs:
            regime_rows = await pool.fetch(_REGIMES_SQL, _CROSS_SECTIONAL_SYMBOL, vintage, tf)
            regimes = [r["regime"] for r in regime_rows]
            if not args.all_regimes:
                regimes = regimes[: args.max_regimes_per_tf]
            if not regimes:
                print(f"WARNING: no POOLED regimes found for tf={tf}")
                continue

            for regime in regimes:
                stratum_results = await _evaluate_stratum(
                    pool,
                    tf,
                    regime,
                    vintage,
                    lookaheads_by_tf,
                    subsample_min_stride,
                    args.cs_chunk_ts,
                )
                all_results.extend(stratum_results)

        _apply_pooled_vol_fdr(all_results, fdr_alpha)

        print(
            "| tf | regime | lookahead | n_features | n_independent | rank_corr | "
            "raw_only | vol_only | both |"
        )
        print("|---|---|---|---|---|---|---|---|---|")
        for r in all_results:
            rc = f"{r['rank_correlation']:.4f}" if r["rank_correlation"] is not None else "n/a"
            print(
                f"| {r['tf']} | {r['regime']} | {r['lookahead_bars']} | "
                f"{r['n_features_compared']} | {r['n_independent']} | {rc} | "
                f"{len(r['raw_only'])} | {len(r['vol_only'])} | {len(r['both'])} |"
            )

        print("\n## Summary\n")
        if not all_results:
            print("No strata evaluated -- nothing to compare (empty corpus or no baseline rows).")
        else:
            reliable = [r for r in all_results if r["n_independent"] >= min_independent]
            low_reliability = [r for r in all_results if r["n_independent"] < min_independent]
            print(
                f"Reliability floor: n_independent >= {min_independent} "
                f"(alpha.ic.min_reliable_n unless --min-independent overrides). "
                f"{len(low_reliability)}/{len(all_results)} evaluated strata fall below it "
                f"and are EXCLUDED from the aggregate verdict below -- per Fable 5's 2026-07-19 "
                f"review (Q3b), these are almost always extended-horizon strata where "
                f"effective-N collapse makes a rank-correlation read indistinguishable from "
                f"noise, not evidence the return target itself diverges. They remain visible "
                f"in the per-stratum table above.\n"
            )
            if not reliable:
                print(
                    "**No strata cleared the reliability floor -- no aggregate verdict "
                    "possible this run.**"
                )
            else:
                corrs = [
                    r["rank_correlation"] for r in reliable if r["rank_correlation"] is not None
                ]
                total_raw_only = sum(len(r["raw_only"]) for r in reliable)
                total_vol_only = sum(len(r["vol_only"]) for r in reliable)
                total_both = sum(len(r["both"]) for r in reliable)
                median_corr = float(np.median(corrs)) if corrs else float("nan")
                print(
                    f"Reliable strata: {len(reliable)}, median rank correlation: "
                    f"{median_corr:.4f}\n"
                )
                print(
                    f"Qualifying-feature set differences (raw passes_fdr, production's "
                    f"corpus-wide family, vs. vol-normalized BH-FDR pooled into one family "
                    f"across all {len(all_results)} evaluated strata this run, including "
                    f"low-reliability ones -- FDR pooling should see the whole run's evidence "
                    f"even though the aggregate verdict only counts reliable strata): "
                    f"raw_only={total_raw_only}, vol_only={total_vol_only}, both={total_both}\n"
                )
                if corrs and median_corr > 0.95 and total_raw_only == 0 and total_vol_only == 0:
                    print(
                        "**Preliminary signal: vol-normalized rankings look materially "
                        "identical to raw on this sample -- per the locked contract, retire "
                        "the transform unless Plan 07's full-corpus --all-regimes run shows "
                        "otherwise.**"
                    )
                else:
                    print(
                        "**Preliminary signal: vol-normalized rankings diverge from raw on "
                        "this sample -- worth carrying into Plan 07's full-corpus "
                        "--all-regimes run for the definitive verdict.**"
                    )
        print(
            "\n---\nThis is a bounded diagnostic sample (see --max-regimes-per-tf). The "
            "definitive Component F A/B verdict is recorded in Plan 07 after the "
            "corpus-wide re-run, per docs/plans/methodology-change-ledger.md."
        )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
