"""Re-derive cross-sectional regime labels using the fixed (causal-rank) breadth signal,
entirely offline from already-stored data -- no production market_regimes write.

Read-only reporting script, no DB writes. Todo 092 fix (migration 257,
src/intelligence/regime_signals/breadth_vol.py): breadth_frac is now a causal expanding
percentile rank before bucketing, cut at 0.33/0.67 (symmetric with vix_pct), instead of the
old fixed 0.40/0.60 cut on the raw fraction. This script re-derives what market_regimes.
regime_label WOULD be under the fixed logic, using the raw vix_pct/breadth_frac values
already stored in regime_prob_vector (pre-bucketing), and compares population balance
old-vs-new -- before committing to the expensive live market_regimes recompute + full
downstream re-run (feature_ic_scores/ensemble_weights/ensemble_alpha).

Usage: .venv/bin/python scripts/analysis/recalibrated_breadth_regime_relabel_check.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.cross_sectional_regime_model import _bucket  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.regime_signals.breadth_vol import _causal_expanding_rank  # noqa: E402

_VIX_TIERS = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
_OLD_BREADTH_TIERS = [("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))]
_NEW_BREADTH_TIERS = [("bear", 0.33), ("neutral", 0.67), ("bull", float("inf"))]

_QUERY_SQL = """
    SELECT ts,
           (regime_prob_vector->>'vix_pct')::double precision AS vix_pct,
           (regime_prob_vector->>'breadth_frac')::double precision AS breadth_frac
    FROM market_regimes
    WHERE regime_group = 'equity' AND tf = $1
    ORDER BY ts
"""


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        for tf in ("5m", "15m", "1h", "1d"):
            rows = await conn.fetch(_QUERY_SQL, tf)
            if not rows:
                continue
            ts = [r["ts"] for r in rows]
            vix_pct = np.array([r["vix_pct"] for r in rows], dtype=float)
            breadth_frac = pd.Series([r["breadth_frac"] for r in rows], index=ts, dtype=float)

            breadth_pct = _causal_expanding_rank(breadth_frac).to_numpy()

            old_vix_label = _bucket(vix_pct, _VIX_TIERS)
            old_breadth_label = _bucket(breadth_frac.to_numpy(), _OLD_BREADTH_TIERS)
            old_labels = [f"{v}_{b}" for v, b in zip(old_vix_label, old_breadth_label)]

            new_vix_label = old_vix_label  # vix axis unchanged
            new_breadth_label = _bucket(breadth_pct, _NEW_BREADTH_TIERS)
            new_labels = [f"{v}_{b}" for v, b in zip(new_vix_label, new_breadth_label)]

            old_counts = Counter(old_labels)
            new_counts = Counter(new_labels)
            all_regimes = sorted(set(old_counts) | set(new_counts))

            print(f"=== tf={tf} ({len(rows)} bars) ===")
            print(f"{'regime':<14}{'old_n':>10}{'old_%':>8}{'new_n':>10}{'new_%':>8}")
            for regime in all_regimes:
                old_n = old_counts.get(regime, 0)
                new_n = new_counts.get(regime, 0)
                print(
                    f"{regime:<14}{old_n:>10}{old_n / len(rows):>8.2%}"
                    f"{new_n:>10}{new_n / len(rows):>8.2%}"
                )
            old_max_min_ratio = max(old_counts.values()) / max(min(old_counts.values()), 1)
            new_max_min_ratio = max(new_counts.values()) / max(min(new_counts.values()), 1)
            print(
                f"max/min population ratio: old={old_max_min_ratio:.1f}x "
                f"new={new_max_min_ratio:.1f}x\n"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
