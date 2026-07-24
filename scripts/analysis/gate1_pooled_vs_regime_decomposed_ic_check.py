"""Does Gate 1's pooled-across-regime IC survive being broken out by regime?

Read-only reporting script, no DB writes. Answers the Renaissance-council challenge behind
today's (2026-07-24) investigation: how can Gate 1 (EIC-04, `gate1_signal` in
`gate_evaluations`) pass with a 10x margin over its 2% floor while Gate 2 (frame simulation)
and every regime-stratified re-test since (see
regime_eligibility_joint_stratification_validation.py) show zero profitable cells anywhere?

Confirmed by reading `gate1_signal`'s own recorded evidence directly: every one of its 640
cell dicts has keys {tf, scale, symbol, n_valid, p_value, ic_value, reliable, passes_fdr,
ic_ci_lower, ic_ci_upper, bh_adjusted_p, walk_forward_stable} -- no `regime` key anywhere.
640 = 80 symbols x 2 tf (5m/15m) x 4 scales, pooling every regime's bars into one IC per
(symbol, tf, scale). Gate 1 never checked whether that pooled relationship holds up
regime-by-regime.

This script recomputes Gate 1's own qualifying criterion (ic_ci_lower > 0 AND passes_fdr AND
walk_forward_stable) against the live evidence, then for each qualifying cell pulls the SAME
(symbol, tf, lookahead)'s regime-decomposed IC from alpha_ensemble_ic's own is_pooled=false
rows (computed and stored at measurement time, just never consulted by the gate) and
tabulates, per regime: what fraction of cells have the same sign as the pooled IC, and how
many are independently significant on their own (same three-condition bar, applied per
regime instead of pooled).

weight_version note: gate1_signal's evidence was scored under weight_version
'run_2025122405150000'; this script reads regime rows from '143.1-08-champion' instead
(Gate 2's population) because a direct row-level EXCEPT comparison of ensemble_weights
confirmed the two labels carry byte-identical weights -- same underlying ensemble, just two
labels applied at different times, not a stale-weights mismatch.

Usage: .venv/bin/python scripts/analysis/gate1_pooled_vs_regime_decomposed_ic_check.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.settings import Settings  # noqa: E402

_REGIME_ROW_WEIGHT_VERSION = "143.1-08-champion"


def _qualifies(cell: dict[str, Any]) -> bool:
    return bool(cell["ic_ci_lower"] > 0 and cell["passes_fdr"] and cell["walk_forward_stable"])


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        raw_evidence = await conn.fetchval(
            "SELECT evidence FROM gate_evaluations WHERE gate_id = 'gate1_signal'"
        )
        evidence = json.loads(raw_evidence) if isinstance(raw_evidence, str) else raw_evidence
        cells = evidence["cells"]
        qualifying = [c for c in cells if _qualifies(c)]
        print(
            f"gate1_signal evidence: {len(cells)} total cells (pooled across all regimes), "
            f"{len(qualifying)} qualifying under (ic_ci_lower>0, passes_fdr, "
            f"walk_forward_stable) -- recorded verdict was "
            f"{evidence['verdict']['n_qualifying']}/{evidence['verdict']['n_cells']} "
            f"({evidence['verdict']['qualifying_fraction']:.2%})\n"
        )

        regime_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"n_cells": 0, "n_same_sign": 0, "n_independently_significant": 0}
        )
        for cell in qualifying:
            regime_rows = await conn.fetch(
                """
                SELECT regime, ic_value, ic_ci_lower, passes_fdr, walk_forward_stable
                FROM alpha_ensemble_ic
                WHERE weight_version = $1 AND symbol = $2 AND tf = $3 AND lookahead = $4
                  AND is_pooled = false
                """,
                _REGIME_ROW_WEIGHT_VERSION,
                cell["symbol"],
                cell["tf"],
                cell["scale"],
            )
            pooled_sign_positive = cell["ic_value"] > 0
            for row in regime_rows:
                stats = regime_stats[row["regime"]]
                stats["n_cells"] += 1
                if row["ic_value"] is not None and (row["ic_value"] > 0) == pooled_sign_positive:
                    stats["n_same_sign"] += 1
                if (
                    row["ic_ci_lower"] is not None
                    and row["ic_ci_lower"] > 0
                    and row["passes_fdr"]
                    and row["walk_forward_stable"]
                ):
                    stats["n_independently_significant"] += 1
    finally:
        await conn.close()

    print(
        f"{'regime':<14}{'n_cells':>10}{'n_same_sign':>13}{'frac_same_sign':>16}"
        f"{'n_independently_sig':>22}"
    )
    for regime, stats in sorted(
        regime_stats.items(),
        key=lambda item: -item[1]["n_same_sign"] / max(item[1]["n_cells"], 1),
    ):
        frac = stats["n_same_sign"] / stats["n_cells"] if stats["n_cells"] else 0.0
        print(
            f"{regime:<14}{stats['n_cells']:>10}{stats['n_same_sign']:>13}{frac:>16.2%}"
            f"{stats['n_independently_significant']:>22}"
        )

    print(
        "\nVERDICT: whichever regime shows the highest frac_same_sign and "
        "n_independently_sig is where Gate 1's pooled signal actually concentrates. If the "
        "regime dominating live trade volume (mid_bull, per today's frame-population sweep) "
        "is NOT that regime, the pooled gate's apparent strength for a symbol is being "
        "carried by regimes it rarely or never trades, not the regime it's actually firing "
        "into -- the real mechanism behind Gate 1 PASS / Gate 2 FAIL, not a contradiction to "
        "explain away."
    )


if __name__ == "__main__":
    asyncio.run(main())
