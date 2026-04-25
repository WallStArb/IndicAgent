"""validate_skeptic.py -- CLI wrapper for swarm agent graduation validation.

Validation dimensions (per src.intelligence.swarm.graduation):
  - Spearman rank correlation: multiplier vs pnl_r (positive correlation)
  - Calibration: predicted failure rate vs actual failure rate per decile
  - CVaR: expected shortfall of bottom-decile multiplier trades
  - Walk-forward: temporal train/validation split
  - Value-add: Sharpe ratio improvement from high-confidence filter

Usage:
    python scripts/validate_skeptic.py --agent skeptic_v1 [--days 90] [--symbol-filter ESM6]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
import pandas as pd

from src.config.settings import Settings
from src.intelligence.swarm.graduation import (
    GATE_CALIBRATION_MAX_ERROR,
    GATE_CVAR_BOTTOM_DECILE,
    GATE_SPEARMAN_RHO,
    evaluate_all,
)


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
                s.predicted_multiplier AS multiplier,
                s.confidence,
                s.ts,
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
            df["multiplier"] = pd.to_numeric(df["multiplier"], errors="coerce")
            df["pnl_r"] = pd.to_numeric(df["pnl_r"], errors="coerce")

        return df

    finally:
        await conn.close()


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

    print(
        f"\nValidation: {args.agent} | {len(df)} predictions matched to outcomes"
        f"\nGates: rho>={GATE_SPEARMAN_RHO}, calib_err<{GATE_CALIBRATION_MAX_ERROR},"
        f" cvar<={GATE_CVAR_BOTTOM_DECILE}\n"
    )

    result = evaluate_all(
        df, transform_id=args.agent, transform_version="v1", segment_key="__global__"
    )
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["is_graduated"] else 1)


if __name__ == "__main__":
    main()
