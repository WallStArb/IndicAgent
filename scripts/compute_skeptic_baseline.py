"""compute_skeptic_baseline.py -- compute naive baseline failure rates per segment.

Per D-12: baseline = historical failure rate per (regime, tf, setup).
Outputs a table of segments with failure_rate, win_rate, N, suitable for
comparison against LLM predictions in validate_skeptic.py.

Usage:
    python scripts/compute_skeptic_baseline.py [--days 90] [--symbol-filter ESM6,NQM6]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
import pandas as pd

from src.config.settings import Settings


async def compute_baseline(days: int = 90, symbol_filter: list[str] | None = None) -> pd.DataFrame:
    """Compute per-segment failure rates from signal_ledger."""
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)

    try:
        where_clauses = [
            "exit_at IS NOT NULL",
            "outcome IS NOT NULL",
            "timestamp >= NOW() - INTERVAL '1 day' * $1",
            "hmm_regime_at_fire IS NOT NULL",
        ]
        params: list = [days]
        if symbol_filter:
            params.append(symbol_filter)
            where_clauses.append("symbol = ANY($2)")

        where = " AND ".join(where_clauses)
        query = f"""
            SELECT
                hmm_regime_at_fire,
                tf,
                regime_type_at_fire,
                symbol,
                plugin,
                outcome,
                pnl_r,
                COUNT(*) as n_signals,
                SUM(CASE WHEN pnl_r > 0 THEN 1 ELSE 0 END) as n_wins,
                SUM(CASE WHEN pnl_r <= 0 THEN 1 ELSE 0 END) as n_losses,
                AVG(pnl_r) as avg_pnl_r
            FROM signal_ledger
            WHERE {where}
            GROUP BY hmm_regime_at_fire, tf, regime_type_at_fire, symbol, plugin, outcome
            ORDER BY hmm_regime_at_fire, tf, n_signals DESC
        """
        rows = await conn.fetch(query, *params)
        df = pd.DataFrame([dict(r) for r in rows])

        if df.empty:
            return df

        seg = (
            df.groupby(["hmm_regime_at_fire", "tf", "regime_type_at_fire", "plugin"])
            .agg(
                total=("n_signals", "sum"),
                wins=("n_wins", "sum"),
                losses=("n_losses", "sum"),
                pnl_weighted=("avg_pnl_r", lambda x: (x * df.loc[x.index, "n_signals"]).sum()),
            )
            .reset_index()
        )
        seg["avg_pnl_r"] = seg["pnl_weighted"] / seg["total"]
        seg = seg.drop(columns=["pnl_weighted"])
        seg["failure_rate"] = seg["losses"] / seg["total"]
        seg["win_rate"] = seg["wins"] / seg["total"]

        return seg.sort_values("total", ascending=False)

    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute naive baseline failure rates per segment."
    )
    parser.add_argument(
        "--days", type=int, default=90, help="Days of history to query (default: 90)"
    )
    parser.add_argument(
        "--symbol-filter", type=str, default=None, help="Comma-separated symbol filter"
    )
    args = parser.parse_args()

    symbol_filter = (
        [s.strip() for s in args.symbol_filter.split(",") if s.strip()]
        if args.symbol_filter
        else None
    )

    df = asyncio.run(compute_baseline(days=args.days, symbol_filter=symbol_filter))

    if df.empty:
        print("No data found. signal_ledger may not have resolved signals yet.")
        return

    print(f"\nNaive Baseline: {len(df)} segments, {df['total'].sum():.0f} total signals\n")
    print(
        df[
            [
                "hmm_regime_at_fire",
                "tf",
                "regime_type_at_fire",
                "plugin",
                "total",
                "failure_rate",
                "win_rate",
                "avg_pnl_r",
            ]
        ].to_string(index=False)
    )
    print(f"\nSegments with N >= 30: {(df['total'] >= 30).sum()}")


if __name__ == "__main__":
    main()
