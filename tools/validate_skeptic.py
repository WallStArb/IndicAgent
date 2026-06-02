"""validate_skeptic.py -- CLI wrapper for swarm agent graduation validation.

Validation dimensions (per src.intelligence.swarm.graduation):
  - Spearman rank correlation: multiplier vs pnl_r (positive correlation)
  - Calibration: predicted failure rate vs actual failure rate per decile
  - CVaR: expected shortfall of bottom-decile multiplier trades
  - Walk-forward: temporal train/validation split
  - Value-add: Sharpe ratio improvement from high-confidence filter

Usage:
    python scripts/validate_skeptic.py --agent skeptic [--days 90] [--symbol-filter ESM6]
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
    """Fetch agent prediction rows from signal_lineage joined to signal_ledger_full."""
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)

    try:
        params: list = [agent_id, f"{days} days"]
        symbol_clause = ""
        if symbol_filter:
            params.append(symbol_filter)
            symbol_clause = "AND sl.symbol = ANY($3)"

        query = f"""
            SELECT
                sl.signal_id::text AS signal_id,
                sl.source          AS agent_id,
                sl.symbol,
                sl.tf,
                sl.multiplier,
                (sl.metadata->'payload'->>'confidence')::float AS confidence,
                sl.ts,
                ledger.outcome,
                ledger.pnl_r
            FROM signal_lineage sl
            JOIN signal_ledger_full ledger ON ledger.signal_id = sl.signal_id
            WHERE sl.event_type = 'agent_prediction'
              AND sl.source = $1
              AND sl.multiplier IS NOT NULL
              AND ledger.outcome IS NOT NULL
              AND ledger.pnl_r IS NOT NULL
              AND sl.ts >= NOW() - $2::interval
              {symbol_clause}
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
    parser.add_argument("--agent", required=True, help="Agent ID to validate (e.g. skeptic)")
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
            "Ensure: (1) SwarmDispatchComputeAgent is running,"
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
