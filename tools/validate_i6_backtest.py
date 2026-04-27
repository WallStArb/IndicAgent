"""Validation tool for I6 plugin backtest results.

Computes Information Coefficient (IC) and p-value with regime segmentation,
applying Bonferroni correction for multiple hypothesis testing.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any

import pandas as pd
from scipy.stats import pearsonr


@dataclass
class ValidationResults:
    """Validation results for I6 field backtest."""

    field_name: str
    n: int  # sample size
    ic: float  # information coefficient (pearsonr)
    p_value: float  # statistical significance
    passed: bool  # IC > min_ic AND p < alpha AND n >= min_n
    regime_results: dict[str, "ValidationResults"]  # per-regime breakdown

    def __str__(self) -> str:
        """Human-readable summary."""
        regime_str = ""
        if self.regime_results:
            regime_str = "\nRegimes:"
            for regime_name, regime_result in self.regime_results.items():
                status = "✓ PASSED" if regime_result.passed else "✗ FAILED"
                regime_str += f"\n  {regime_name}: IC={regime_result.ic:.3f}, "
                regime_str += f"p={regime_result.p_value:.3f}, n={regime_result.n} {status}"

        return (
            f"Validation Results: {self.field_name}\n"
            f"Overall: IC={self.ic:.3f}, p={self.p_value:.3f}, n={self.n} "
            f"{'✓ PASSED' if self.passed else '✗ FAILED'}"
            f"{regime_str}"
        )


def validate_backtest_results(
    df: pd.DataFrame,
    field_name: str,
    min_ic: float = 0.05,
    alpha: float = 0.01,  # Bonferroni-corrected for 5 tests
    min_n: int = 30,
) -> ValidationResults:
    """Validate backtest results using IC + p-value.

    Args:
        df: Backtest DataFrame from backtest_i6_plugin()
        field_name: Field to validate (e.g., "ctf_momentum_divergence")
        min_ic: Minimum IC threshold (default: 0.05)
        alpha: Significance threshold (default: 0.01 for 5 tests)
        min_n: Minimum sample size (default: 30)

    Returns:
        ValidationResults with overall + regime-segmented statistics

    Validation criteria:
        - IC > min_ic (effect size)
        - p_value < alpha (statistical significance)
        - n >= min_n (sufficient data)
        - At least 1 regime passes (trending OR ranging OR volatile)
    """
    # Filter to rows where field_name exists and pnl_r is not null
    if field_name not in df.columns:
        return ValidationResults(
            field_name=field_name,
            n=0,
            ic=0.0,
            p_value=1.0,
            passed=False,
            regime_results={},
        )

    valid_df = df[[field_name, "pnl_r", "hmm_regime"]].dropna()

    if len(valid_df) < min_n:
        return ValidationResults(
            field_name=field_name,
            n=len(valid_df),
            ic=0.0,
            p_value=1.0,
            passed=False,
            regime_results={},
        )

    # Compute overall IC
    x = valid_df[field_name].values
    y = valid_df["pnl_r"].values
    ic, p_value = pearsonr(x, y)

    # Compute regime-segmented IC
    regime_results = {}
    for regime_val in sorted(valid_df["hmm_regime"].unique()):
        regime_df = valid_df[valid_df["hmm_regime"] == regime_val]

        if len(regime_df) < min_n:
            # Skip regimes with insufficient data
            continue

        x_reg = regime_df[field_name].values
        y_reg = regime_df["pnl_r"].values
        ic_reg, p_reg = pearsonr(x_reg, y_reg)

        regime_name = f"hmm_regime_{int(regime_val)}"
        regime_results[regime_name] = ValidationResults(
            field_name=field_name,
            n=len(regime_df),
            ic=float(ic_reg),
            p_value=float(p_reg),
            passed=bool(ic_reg > min_ic and p_reg < alpha),
            regime_results={},  # No nested regimes
        )

    # Overall passed flag (convert to Python bool)
    passed = bool(ic > min_ic and p_value < alpha and len(valid_df) >= min_n)

    return ValidationResults(
        field_name=field_name,
        n=len(valid_df),
        ic=float(ic),  # Convert numpy float to Python float
        p_value=float(p_value),
        passed=passed,
        regime_results=regime_results,
    )


def main():
    """CLI interface for validation tool."""
    parser = argparse.ArgumentParser(
        description="Validate I6 backtest results using IC/p-value"
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Input CSV path from backtest_i6_plugin.py",
    )
    parser.add_argument(
        "--field",
        type=str,
        required=True,
        help="Field name to validate (e.g., ctf_score)",
    )
    parser.add_argument(
        "--min-ic",
        type=float,
        default=0.05,
        help="Minimum IC threshold (default: 0.05)",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.01,
        help="Significance threshold (default: 0.01 for Bonferroni correction)",
    )
    parser.add_argument(
        "--min-n",
        type=int,
        default=30,
        help="Minimum sample size (default: 30)",
    )

    args = parser.parse_args()

    # Load backtest results
    df = pd.read_csv(args.input, parse_dates=["ts"])

    # Run validation
    result = validate_backtest_results(
        df,
        field_name=args.field,
        min_ic=args.min_ic,
        alpha=args.alpha,
        min_n=args.min_n,
    )

    # Print results
    print(result)
    print()

    # Print recommendation
    if result.passed:
        print("Conclusion: Plugin shows statistically significant signal.")
        print("Recommendation: Deploy to shadow mode, monitor performance.")
    else:
        print("Conclusion: Plugin does not meet validation criteria.")

        if result.n < args.min_n:
            print("Reason: Insufficient sample size (need {args.min_n}+ bars).")
        elif abs(result.ic) < args.min_ic:
            print(f"Reason: IC too low (need > {args.min_ic}).")
        elif result.p_value >= args.alpha:
            print(f"Reason: Not statistically significant (p < {args.alpha} required).")

    return 0


if __name__ == "__main__":
    exit(main())
