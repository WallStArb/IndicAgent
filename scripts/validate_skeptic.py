"""validate_skeptic.py -- statistical validation of swarm agent predictions.

Per D-13: Pearson correlation per segment between failure_probability and actual outcome.
Per D-14: Graduation gate: rho >= 0.3 AND p < 0.05 AND N >= 30.

Usage:
    python scripts/validate_skeptic.py --agent skeptic_v1 [--days 90] [--symbol-filter ESM6]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from src.config.settings import Settings


async def fetch_validation_data(
    agent_id: str,
    days: int = 90,
    symbol_filter: list[str] | None = None,
) -> pd.DataFrame:
    """JOIN alpha_multiplier_shadow with signal_ledger for validation."""
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)

    try:
        where_clauses = [
            "s.agent_id = $1",
            "l.exit_at IS NOT NULL",
            "l.outcome IS NOT NULL",
            "s.ts >= NOW() - $2::interval",
        ]
        params: list = [agent_id, f"{days} days"]

        if symbol_filter:
            params.append(symbol_filter)
            where_clauses.append("s.symbol = ANY($3)")

        where = " AND ".join(where_clauses)
        query = f"""
            SELECT
                s.signal_id,
                s.agent_id,
                s.symbol,
                s.tf,
                s.hmm_regime,
                s.predicted_multiplier,
                s.confidence,
                s.features->>'failure_probability' as failure_prob,
                s.features->>'prompt_version' as prompt_version,
                l.outcome,
                l.pnl_r,
                l.regime_type_at_fire,
                l.plugin as setup_plugin
            FROM alpha_multiplier_shadow s
            JOIN signal_ledger l ON s.signal_id::uuid = l.signal_id::uuid
            WHERE {where}
        """
        rows = await conn.fetch(query, *params)
        df = pd.DataFrame([dict(r) for r in rows])

        if not df.empty:
            df["failure_prob"] = pd.to_numeric(df["failure_prob"], errors="coerce")
            df["pnl_r"] = pd.to_numeric(df["pnl_r"], errors="coerce")
            df["win"] = (df["pnl_r"] > 0).astype(int)

        return df

    finally:
        await conn.close()


def compute_segment_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Pearson correlation per segment."""
    segments = []

    for (tf, hmm_regime), group in df.groupby(["tf", "hmm_regime"]):
        valid = group.dropna(subset=["failure_prob", "win"])
        n = len(valid)
        if n < 10:
            continue

        try:
            rho, p_val = pearsonr(valid["failure_prob"].values, valid["win"].values)
        except Exception:
            rho, p_val = float("nan"), float("nan")

        segments.append(
            {
                "tf": tf,
                "hmm_regime": hmm_regime,
                "n": n,
                "rho": round(rho, 4) if not np.isnan(rho) else None,
                "p_value": round(p_val, 6) if not np.isnan(p_val) else None,
                "passes_gate": n >= 30 and not np.isnan(rho) and rho >= 0.3 and p_val < 0.05,
                "avg_failure_prob": round(valid["failure_prob"].mean(), 4),
                "actual_win_rate": round(valid["win"].mean(), 4),
            }
        )

    return pd.DataFrame(segments)


def main() -> None:
    parser = argparse.ArgumentParser(description="Statistical validation gate for swarm agents.")
    parser.add_argument("--agent", required=True, help="Agent ID to validate (e.g. skeptic_v1)")
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

    df = asyncio.run(
        fetch_validation_data(
            agent_id=args.agent,
            days=args.days,
            symbol_filter=symbol_filter,
        )
    )

    if df.empty:
        print(f"No validation data found for agent '{args.agent}'.")
        print(
            "Ensure: (1) SwarmDispatchService is running,"
            " (2) signals have resolved in signal_ledger"
        )
        sys.exit(1)

    print(f"\nValidation: {args.agent} | {len(df)} predictions matched to outcomes\n")

    valid = df.dropna(subset=["failure_prob", "win"])
    rho_global = 0.0
    p_global = 1.0
    if len(valid) >= 10:
        rho_global, p_global = pearsonr(valid["failure_prob"].values, valid["win"].values)
        print(f"Global: rho={rho_global:.4f}, p={p_global:.6f}, N={len(valid)}")
        print(f"Global gate (rho >= 0.2): {'PASS' if rho_global >= 0.2 else 'FAIL'}\n")
    else:
        print(f"Insufficient data for global stats (N={len(valid)})\n")

    seg_df = compute_segment_stats(df)
    if seg_df.empty:
        print("No segments with sufficient data.")
        sys.exit(1)

    print(seg_df.to_string(index=False))
    n_passing = seg_df["passes_gate"].sum()
    n_total = len(seg_df)
    print(f"\nGraduation gate: {n_passing}/{n_total} segments pass (rho>=0.3, p<0.05, N>=30)")

    overall_pass = rho_global >= 0.2 if len(valid) >= 10 else False
    if not overall_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
