"""Backtest all 5 cross-TF plugins on historical data.

Uses backtest infrastructure from Plan 64-00 (tools/backtest_i6_plugin.py).
Runs backtests on 6+ months historical data (2025-10-01 to 2026-04-01).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pandas as pd

from tools.backtest_i6_plugin import backtest_i6_plugin
from src.intelligence.confluence.cross_tf_momentum_divergence import (
    CrossTFMomentumDivergencePlugin,
)
from src.intelligence.confluence.cross_tf_sr_confluence import (
    CrossTFSRConfluencePlugin,
)
from src.intelligence.confluence.cross_tf_regime_agreement import (
    CrossTFRegimeAgreementPlugin,
)
from src.intelligence.confluence.squeeze_expansion_divergence import (
    SqueezeExpansionDivergencePlugin,
)
from src.intelligence.confluence.cross_tf_orderflow_alignment import (
    CrossTFOrderFlowAlignmentPlugin,
)

# Explicit field map: primary numeric output field per plugin (used for IC computation)
PLUGIN_PRIMARY_FIELDS: dict[str, str] = {
    "CrossTFMomentumDivergence": "ctf_momentum_divergence",
    "CrossTFSRConfluence": "ctf_sr_confluence",
    "CrossTFRegimeAgreement": "ctf_hmm_regime_agreement",
    "SqueezeExpansionDivergence": "ctf_volatility_divergence",
    "CrossTFOrderFlowAlignment": "ctf_orderflow_alignment",
}

# All 5 plugins for backtest
PLUGINS: list[tuple[str, type]] = [
    ("CrossTFMomentumDivergence", CrossTFMomentumDivergencePlugin),
    ("CrossTFSRConfluence", CrossTFSRConfluencePlugin),
    ("CrossTFRegimeAgreement", CrossTFRegimeAgreementPlugin),
    ("SqueezeExpansionDivergence", SqueezeExpansionDivergencePlugin),
    ("CrossTFOrderFlowAlignment", CrossTFOrderFlowAlignmentPlugin),
]


async def _backtest_all_async(
    start_date: datetime,
    end_date: datetime,
    timeframes: list[str],
) -> dict[str, dict]:
    """Run backtest for all 5 cross-TF plugins (async implementation)."""
    results: dict[str, dict] = {}

    for plugin_name, plugin_class in PLUGINS:
        print(f"\nBacktesting {plugin_name}...")
        print(f"Period: {start_date.date()} to {end_date.date()}")

        try:
            df = await backtest_i6_plugin(
                plugin_class=plugin_class,
                start_date=start_date,
                end_date=end_date,
                symbols=None,  # All active contracts
                timeframes=timeframes,
            )

            if df.empty:
                print(f"  WARNING: No data returned for {plugin_name}")
                results[plugin_name] = {"error": "No data returned from backtest"}
                continue

            # Save results to /tmp for validation step
            output_path = f"/tmp/{plugin_name.lower()}_backtest.csv"
            df.to_csv(output_path, index=False)
            print(f"  Backtest complete: {len(df)} bars")
            print(f"  Results saved to: {output_path}")

            field_name = PLUGIN_PRIMARY_FIELDS[plugin_name]
            results[plugin_name] = {
                "df": df,
                "field": field_name,
                "path": output_path,
            }

        except Exception as e:
            print(f"  ERROR: {e}")
            results[plugin_name] = {"error": str(e)}

    return results


def backtest_all_cross_tf_plugins(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    timeframes: list[str] | None = None,
) -> dict[str, dict]:
    """Run backtest for all 5 cross-TF plugins.

    Args:
        start_date: Backtest start date (UTC). Default: 2025-10-01
        end_date: Backtest end date (UTC). Default: 2026-04-01
        timeframes: Timeframes to backtest. Default: ["5m", "15m", "1h", "4h"]

    Returns:
        Dict mapping plugin_name -> {"df": DataFrame, "field": str, "path": str}
        or {"error": str} if backtest failed.
    """
    if start_date is None:
        start_date = datetime(2025, 10, 1, tzinfo=UTC)
    if end_date is None:
        end_date = datetime(2026, 4, 1, tzinfo=UTC)
    if timeframes is None:
        timeframes = ["5m", "15m", "1h", "4h"]

    return asyncio.run(_backtest_all_async(start_date, end_date, timeframes))


def print_backtest_summary(results: dict[str, dict]) -> None:
    """Print summary of backtest results."""
    print("\n" + "=" * 80)
    print("BACKTEST SUMMARY")
    print("=" * 80)

    for plugin_name, result in results.items():
        if "error" in result:
            print(f"{plugin_name}: FAILED - {result['error']}")
        else:
            df = result["df"]
            bars_with_outcome = df["pnl_r"].notna().sum()
            print(
                f"{plugin_name}: {len(df)} bars total, "
                f"{bars_with_outcome} bars with pnl_r outcome"
            )

    print("=" * 80)


def main() -> dict[str, dict]:
    """Run backtest for all 5 cross-TF plugins (CLI entry point)."""
    results = backtest_all_cross_tf_plugins()
    print_backtest_summary(results)
    return results


if __name__ == "__main__":
    main()
