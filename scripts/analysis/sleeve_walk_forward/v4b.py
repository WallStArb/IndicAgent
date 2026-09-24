"""V4b: size deviation D7, the harness's pooled-only IC shrinkage prior.

Pre-registration section 10 (V4b) and section 13 (D7). Production shrinks each IC row toward a
leave-one-out prior over its (concept group_name, regime, tf) bucket, and that bucket holds
per-symbol rows as well as pooled ones; the harness computes pooled cells only, so its prior
comes from pooled rows alone. This check takes production's stored 1d IC rows at the latest
window, computes ic_shrunk both ways with production's own compute_shrinkage_updates, runs the
same eligibility, meta-FDR and select_stratum for every equity label under each, and compares.

Gate (pinned): any equity stratum whose selected feature set differs means S1 gets a per-symbol
1d pass before the freeze. The quality-weight rank correlation is reported, never gating.

Read-only. Run: python -m scripts.analysis.sleeve_walk_forward.v4b [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from scipy.stats import spearmanr

from scripts.analysis.sleeve_walk_forward.refit import _fdr_pass_rows, eligible
from scripts.ops.alpha.ops_ic_shrinkage import compute_shrinkage_updates
from services._batch_utils import resolve_per_tf
from services.ensemble_trainer import EnsembleConfig, _meta_eligible, _resolve_ic_input_column
from src.intelligence.ensemble.stratum_fit import select_stratum

_TF = "1d"
_ROWS_SQL = """
SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end, n_independent,
       ic_sharpe_hac, ic_sign, ic_ci_lower, ic_ci_upper, reliable, regime_scope, is_pooled,
       passes_walkforward, passes_fdr
FROM feature_ic_scores
WHERE tf = '1d' AND training_window_end = (
    SELECT max(training_window_end) FROM feature_ic_scores WHERE tf = '1d' AND is_pooled
)
"""


def _shrunk(rows: list[dict], feature_to_group: dict[str, str], k: float) -> dict[tuple, float]:
    reliable = [
        r
        for r in rows
        if r["reliable"] is True
        and r["ic_sharpe_hac"] is not None
        and r["regime_scope"] != "earnings_season"
    ]
    return {
        (u[2], u[3], u[5], u[6]): u[0]
        for u in compute_shrinkage_updates(reliable, feature_to_group, k)
    }


def _pooled(r: dict) -> bool:
    return r["symbol"] == "POOLED" and r["is_pooled"] is True


def compare_priors(
    rows: list[dict], feature_to_group: dict[str, str], raw: dict[str, str], *, labels: list[str]
) -> dict:
    ens = EnsembleConfig.from_apr(raw)
    k = float(raw.get("alpha.ic.shrinkage_k", "100"))
    variants = {
        "production": _shrunk(rows, feature_to_group, k),
        "harness": _shrunk([r for r in rows if _pooled(r)], feature_to_group, k),
    }
    pooled = [r for r in rows if _pooled(r)]
    meta = _meta_eligible(
        _fdr_pass_rows(pooled, ens.sign_symmetric),
        raw,
        ens.meta_fdr_min_fraction,
        ens.meta_fdr_min_cells,
    ).get(_TF, set())
    ic_col = _resolve_ic_input_column(ens.ic_input)
    min_features = resolve_per_tf(
        raw, "alpha.ensemble.min_passing_features", _TF, ens.min_passing_features
    )
    feature_cols = sorted({r["feature_name"] for r in rows})
    strata: dict[str, dict] = {}
    examples: dict[str, dict] = {}
    for label in labels:
        picked: dict[str, dict[str, float]] = {}
        for name, shrunk in variants.items():
            candidates = []
            for r in pooled:
                if (
                    r["regime"] != label
                    or r["feature_name"] not in meta
                    or not eligible(r, ens.sign_symmetric)
                ):
                    continue
                value = shrunk.get(
                    (r["feature_name"], r["symbol"], r["regime"], r["lookahead_bars"])
                )
                if ic_col == "ic_shrunk" and value is None:
                    continue
                candidates.append({**r, "ic_shrunk": value})
            selection, _reason, _n = select_stratum(
                candidates,
                ic_input_column=ic_col,
                sharpe_floor=ens.sharpe_floor,
                feature_cols=feature_cols,
                min_passing_features=min_features,
            )
            picked[name] = (
                {}
                if selection is None
                else dict(zip(selection.feature_names, selection.quality_weights.tolist()))
            )
        prod, harn = picked["production"], picked["harness"]
        common = sorted(set(prod) & set(harn))
        corr = (
            1.0
            if len(common) < 3 and prod == harn
            else (
                float(spearmanr([prod[f] for f in common], [harn[f] for f in common])[0])
                if len(common) >= 3
                else float("nan")
            )
        )
        strata[label] = {
            "production": sorted(prod),
            "harness": sorted(harn),
            "only_production": sorted(set(prod) - set(harn)),
            "only_harness": sorted(set(harn) - set(prod)),
            "quality_rank_corr": corr,
        }
        examples[label] = {
            f: {name: variants[name].get((f, "POOLED", label, 1)) for name in variants}
            for f in sorted({r["feature_name"] for r in pooled if r["regime"] == label})[:20]
        }
    return {
        "sets_differ": any(s["only_production"] or s["only_harness"] for s in strata.values()),
        "strata": strata,
        "ic_shrunk_examples": examples,
    }


async def _fetch(dsn: str) -> tuple[list[dict], dict[str, str], dict[str, str], list[str]]:
    from scripts.analysis.sleeve_walk_forward.snapshot import read_only_pool

    pool = await read_only_pool(dsn)
    try:
        async with pool.acquire() as conn:
            rows = [dict(r) for r in await conn.fetch(_ROWS_SQL)]
            f2g = {
                n: g
                for n, g in await conn.fetch(
                    "SELECT cr.name, cr.group_name FROM concept_registry cr "
                    "JOIN concept_gate cg ON cg.concept_id = cr.concept_id WHERE cr.domain = 'feature'"
                )
                if g
            }
            raw = {
                k: v
                for k, v in await conn.fetch("SELECT config_key, config_value FROM config_state")
            }
            labels = [
                r[0]
                for r in await conn.fetch(
                    "SELECT DISTINCT regime_label FROM market_regimes "
                    "WHERE regime_group = 'equity' AND tf = '1d' ORDER BY 1"
                )
            ]
    finally:
        await pool.close()
    return rows, f2g, raw, labels


def main(argv: list[str] | None = None) -> int:
    from src.config.settings import Settings

    parser = argparse.ArgumentParser(description="V4b: IC shrinkage prior sizing (D7)")
    parser.add_argument("--out-dir", type=Path, default=Path("logs/phase179"))
    args = parser.parse_args(argv)
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    rows, f2g, raw, labels = asyncio.run(_fetch(dsn))
    window = str(max(r["training_window_end"] for r in rows))
    out = {
        "training_window_end": window,
        "n_rows": len(rows),
        **compare_priors(rows, f2g, raw, labels=labels),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"v4b_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(path)
    print(
        f"V4b: selected sets {'DIFFER' if out['sets_differ'] else 'identical'} across {len(labels)} equity strata"
    )
    for label, s in out["strata"].items():
        print(
            f"  {label}: n={len(s['production'])}/{len(s['harness'])} "
            f"only_prod={s['only_production']} only_harness={s['only_harness']} rank_corr={s['quality_rank_corr']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
