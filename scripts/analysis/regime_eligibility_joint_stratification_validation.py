"""Todo 179 Tier-1 validation: does a regime-conditional expectancy floor exist anywhere?

Read-only reporting script. Reuses counterfactual_tracker.py's evaluate_frame_gate/
frame_gate_passes verbatim (no reimplementation) -- same day-clustered block-bootstrap
machinery as FRAME-04 and the todo-165 OOS regime-stratified promotion gate.

Neither ensemble_trainer.py's eligibility predicate nor alpha_publisher.py's emission gate
validates a (regime, tf, direction) stratum's actual realized OOS outcome -- both operate
purely on feature-level IC significance (confirmed by direct code read, 2026-07-24). This
script answers the actual open question: if such a stratum-level check existed, would it
ever pass? Stratifies jointly on (tf, direction, cross_sectional_regime, symbol_hmm_regime)
per STATE.md's "Current focus" -- the per-symbol HMM axis reveals real within-cross-sectional-
regime heterogeneity (a `mid_bull` `ranging` sub-bucket vs `trending_up`/`transition_down`)
that a cross-sectional-only cut blurs.

Population: champion weight_epoch (143.1-08-champion, the live default -- sign_symmetric
stays false), OOS window only (bar_ts >= alpha.validation.oos_start), frame_variant='primary',
closed frames with a measured counterfactual_pnl_r. Rows lacking a per-symbol HMM label
(feature_vectors.regime IS NULL -- the todo 168/092/167 Layer-1 coverage gap, still open for
several symbols at 5m/15m) are excluded from the joint cut and reported separately, not
silently dropped.

Usage: .venv/bin/python scripts/analysis/regime_eligibility_joint_stratification_validation.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import cfg as _cfg  # noqa: E402
from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
)
from src.config.settings import Settings  # noqa: E402

_CHAMPION_WEIGHT_EPOCH = "143.1-08-champion"

_JOINT_QUERY_SQL = """
    SELECT af.tf, af.direction, af.regime AS cross_regime, fv.regime AS symbol_regime,
           af.bar_ts::date AS cluster_id, af.counterfactual_pnl_r AS pnl_r
    FROM alpha_frames af
    JOIN feature_vectors fv
      ON fv.symbol = af.symbol AND fv.tf = af.tf AND fv.bar_ts = af.bar_ts
    WHERE af.weight_epoch = $1
      AND af.frame_variant = 'primary'
      AND af.status != 'open'
      AND af.bar_ts >= $2
      AND af.counterfactual_pnl_r IS NOT NULL
      AND fv.regime IS NOT NULL
    ORDER BY af.bar_ts ASC
"""

_UNLABELED_COUNT_SQL = """
    SELECT count(*)
    FROM alpha_frames af
    LEFT JOIN feature_vectors fv
      ON fv.symbol = af.symbol AND fv.tf = af.tf AND fv.bar_ts = af.bar_ts
    WHERE af.weight_epoch = $1
      AND af.frame_variant = 'primary'
      AND af.status != 'open'
      AND af.bar_ts >= $2
      AND af.counterfactual_pnl_r IS NOT NULL
      AND (fv.regime IS NULL OR fv.bar_ts IS NULL)
"""


async def _load_apr(conn: asyncpg.Connection) -> tuple[int, int, int, int]:
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        ["alpha.scoring.%", "alpha.validation.regime_gate_min_clusters"],
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    regime_gate_min_clusters = _cfg(apr_cfg, "alpha.validation.regime_gate_min_clusters", 20)
    return bootstrap_max_n, bootstrap_batch, bootstrap_random_state, regime_gate_min_clusters


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        (
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            min_clusters,
        ) = await _load_apr(conn)
        oos_start = await conn.fetchval(
            "SELECT config_value::timestamptz FROM config_state "
            "WHERE config_key = 'alpha.validation.oos_start'"
        )
        if oos_start is None:
            raise RuntimeError("alpha.validation.oos_start is not set in config_state")

        rows = [
            dict(r) for r in await conn.fetch(_JOINT_QUERY_SQL, _CHAMPION_WEIGHT_EPOCH, oos_start)
        ]
        n_unlabeled = await conn.fetchval(_UNLABELED_COUNT_SQL, _CHAMPION_WEIGHT_EPOCH, oos_start)
    finally:
        await conn.close()

    print(f"weight_epoch={_CHAMPION_WEIGHT_EPOCH}  oos_start={oos_start}")
    print(f"rows with a symbol_hmm label: {len(rows)}")
    print(f"rows excluded (no symbol_hmm label -- Layer-1 coverage gap): {n_unlabeled}")
    print(f"regime_gate_min_clusters floor: {min_clusters}\n")

    # Coarse cut: (tf, direction, cross_regime) only -- what the ensemble/publisher already
    # implicitly assume is the right granularity.
    coarse_cells = evaluate_frame_gate(
        rows,
        min_n=1,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        group_key=lambda row: (row["tf"], (row["direction"], row["cross_regime"])),
        min_clusters=min_clusters,
    )
    print("=== COARSE CUT: (tf, direction, cross_sectional_regime) ===")
    for cell in sorted(coarse_cells, key=lambda c: (c["tf"], str(c["regime"]))):
        direction, cross_regime = cell["regime"]
        print(
            f"  tf={cell['tf']:>3} direction={direction:>5} cross_regime={cross_regime:<13} "
            f"n_frames={cell['n_frames']:>6} n_clusters={cell['n_clusters']:>3} "
            f"coverage={cell['coverage']:<11} passes={cell['passes']} "
            f"ci_lower={cell['ci_lower']} ci_upper={cell['ci_upper']}"
        )

    # Joint cut: (tf, direction, cross_regime, symbol_regime) -- the actual Tier-1 question.
    joint_cells = evaluate_frame_gate(
        rows,
        min_n=1,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        group_key=lambda row: (
            row["tf"],
            (row["direction"], row["cross_regime"], row["symbol_regime"]),
        ),
        min_clusters=min_clusters,
    )
    print("\n=== JOINT CUT: (tf, direction, cross_sectional_regime, symbol_hmm_regime) ===")
    for cell in sorted(joint_cells, key=lambda c: (c["tf"], str(c["regime"]))):
        direction, cross_regime, symbol_regime = cell["regime"]
        print(
            f"  tf={cell['tf']:>3} direction={direction:>5} cross_regime={cross_regime:<13} "
            f"symbol_regime={symbol_regime:<16} n_frames={cell['n_frames']:>6} "
            f"n_clusters={cell['n_clusters']:>3} coverage={cell['coverage']:<11} "
            f"passes={cell['passes']} ci_lower={cell['ci_lower']} ci_upper={cell['ci_upper']}"
        )

    evaluated_coarse = [c for c in coarse_cells if c["coverage"] == "evaluated"]
    evaluated_joint = [c for c in joint_cells if c["coverage"] == "evaluated"]
    any_coarse_pass = any(c["passes"] for c in evaluated_coarse)
    any_joint_pass = any(c["passes"] for c in evaluated_joint)

    print("\n=== SUMMARY ===")
    print(
        f"coarse cut: {len(evaluated_coarse)}/{len(coarse_cells)} cells had sufficient "
        f"coverage; any pass (ci_lower > 0): {any_coarse_pass}"
    )
    print(
        f"joint cut:  {len(evaluated_joint)}/{len(joint_cells)} cells had sufficient "
        f"coverage; any pass (ci_lower > 0): {any_joint_pass}"
    )
    if not any_joint_pass and not any_coarse_pass:
        print(
            "\nVERDICT: no regime-conditional expectancy floor exists anywhere in the "
            "champion's OOS population, at either granularity. A regime_eligibility_gate.py "
            "would find zero eligible cells to emit from at all -- not a partial fix, a full "
            "stop. This is consistent with todo 179's direct finding that mid_bull's raw "
            "forward return is negative at every horizon."
        )
    elif any_joint_pass and not any_coarse_pass:
        print(
            "\nVERDICT: the joint cut finds real conditional edge the coarse cut's blur "
            "hides -- supports building regime_eligibility_gate.py stratified on the full "
            "4-tuple, restricted to the passing cell(s)."
        )
    else:
        print(
            "\nVERDICT: see per-cell detail above -- mixed result, read the passing cells "
            "directly before deciding whether a gate is worth building."
        )


if __name__ == "__main__":
    asyncio.run(main())
