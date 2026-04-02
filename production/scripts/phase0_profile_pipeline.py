#!/usr/bin/env python3
"""
Phase 0: Pipeline Profiling - Measure Before Optimizing

Renaissance principle: "Profile first, then optimize. Don't guess - measure."

This script runs all measurements to determine the best optimization strategy:
1. Delta Distribution - How much do prices move bar-to-bar?
2. Information Rate - How often do plugin outputs change?
3. Economic Value - Which symbols generate the most profit? (TODO: needs signal outcomes)

Based on measurement results, recommends:
- Delta-based filtering (skip noise bars)
- Incremental computation (cache stable outputs)
- Symbol prioritization (focus on high-value symbols)
- Parallelization (last resort, if simple fixes fail)
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running from project root: python production/scripts/phase0_profile_pipeline.py
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # project root for src.*

from measure_delta_distribution import measure_delta_distribution  # noqa: E402
from measure_information_rate import measure_information_rate  # noqa: E402


async def run_phase0_profiling(
    symbols: list[str] | None = None,
    timeframe: str = "1m",
    output_file: str = "production/scripts/phase0_results.json"
):
    """Run all Phase 0 measurements and generate recommendations.

    Args:
        symbols: Symbols to analyze (None = all)
        timeframe: Timeframe to analyze
        output_file: Where to save results

    Returns:
        Dictionary with all measurements and recommendations
    """
    print("="*80)
    print("PHASE 0: PIPELINE PROFILING")
    print("="*80)
    print(f"Time: {datetime.now(UTC).isoformat()}")
    print(f"Timeframe: {timeframe}")
    if symbols:
        print(f"Symbols: {', '.join(symbols)}")
    else:
        print("Symbols: ALL")
    print("="*80)

    results = {
        "timestamp": datetime.now(UTC).isoformat(),
        "timeframe": timeframe,
        "symbols": symbols,
        "measurements": {},
        "recommendations": {}
    }

    # Measurement 1: Delta Distribution
    print("\n" + "="*80)
    print("MEASUREMENT 1: DELTA DISTRIBUTION")
    print("="*80)
    print("Question: How much do prices actually move bar-to-bar?\n")

    delta_results = await measure_delta_distribution(
        symbols=symbols,
        timeframe=timeframe,
        sample_size=10000
    )

    results["measurements"]["delta_distribution"] = delta_results

    # Measurement 2: Information Rate
    print("\n" + "="*80)
    print("MEASUREMENT 2: INFORMATION RATE")
    print("="*80)
    print("Question: How often do plugin outputs actually change?\n")

    info_results = await measure_information_rate(
        symbols=symbols,
        timeframe=timeframe,
        sample_size=5000
    )

    results["measurements"]["information_rate"] = info_results

    # Generate recommendations
    print("\n" + "="*80)
    print("RENAISSANCE RECOMMENDATIONS")
    print("="*80)

    recommendations = _generate_recommendations(delta_results, info_results)
    results["recommendations"] = recommendations

    # Save results
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Results saved to: {output_path}")

    # Print summary
    print("\n" + "="*80)
    print("PHASE 0 SUMMARY")
    print("="*80)

    print("\n1. DELTA DISTRIBUTION:")
    p90 = delta_results.get("p90")
    print(f"   - 90% of bars move < {p90*100:.4f}%" if p90 is not None else "   - 90th percentile: N/A (no data)")
    if delta_results.get("recommendation") == "filter":
        print("   - ✓ RECOMMEND: Delta-based filtering")
    else:
        print("   - ✗ NOT RECOMMEND: Filtering")

    print("\n2. INFORMATION RATE:")
    i1_rate = info_results.get("i1", {}).get("weighted_change_rate", 1.0)
    i7_rate = info_results.get("i7", {}).get("weighted_change_rate", 1.0)
    print(f"   - I1 changes: {i1_rate*100:.1f}% of the time")
    print(f"   - I7 changes: {i7_rate*100:.1f}% of the time")

    print("\n3. OVERALL STRATEGY:")
    print(f"   {recommendations['primary_strategy']}")
    print(f"   Expected improvement: {recommendations['expected_improvement']}")
    print(f"   Implementation complexity: {recommendations['complexity']}")

    print("\n" + "="*80)

    return results


def _generate_recommendations(delta_results: dict, info_results: dict) -> dict:
    """Generate optimization recommendations based on measurements.

    Renaissance decision tree:
    1. If 90% of bars move < 0.1% → delta filtering
    2. If I1/I7 change rate < 30% → incremental computation
    3. If both fail → parallelization
    """
    recommendations = {
        "primary_strategy": None,
        "secondary_strategies": [],
        "expected_improvement": None,
        "complexity": None,
        "rationale": []
    }

    # Check 1: Delta filtering
    _p90 = delta_results.get("p90")
    _p75 = delta_results.get("p75")
    if _p90 is not None and _p90 < 0.001:  # 90% of bars move < 0.1%
        recommendations["primary_strategy"] = "Delta-based filtering"
        recommendations["expected_improvement"] = "10x throughput (90% fewer bars)"
        recommendations["complexity"] = "Low (1-2 days)"
        recommendations["rationale"].append(
            f"90% of bars move < {_p90*100:.3f}% (noise)"
        )
    # Check 2: Incremental computation
    elif (info_results.get("i1", {}).get("weighted_change_rate", 1.0) < 0.3 or
          info_results.get("i7", {}).get("weighted_change_rate", 1.0) < 0.3):

        i1_rate = info_results.get("i1", {}).get("weighted_change_rate", 1.0)
        i7_rate = info_results.get("i7", {}).get("weighted_change_rate", 1.0)

        recommendations["primary_strategy"] = "Incremental computation (caching)"
        cache_hit_rate = 100 - max(i1_rate, i7_rate) * 100
        recommendations["expected_improvement"] = (
            f"2-5x throughput ({cache_hit_rate:.0f}% cache hit rate)"
        )
        recommendations["complexity"] = "Medium (2-3 days)"
        recommendations["rationale"].append(
            f"Plugin outputs stable: I1={i1_rate*100:.0f}%, I7={i7_rate*100:.0f}% change rate"
        )
    # Check 3: Parallelization
    else:
        recommendations["primary_strategy"] = "Parallelization (I1 + I7)"
        recommendations["expected_improvement"] = "10x throughput (adaptive thread pool)"
        recommendations["complexity"] = "High (5-7 days)"
        recommendations["rationale"].append(
            "High delta distribution + high information rate → parallelization required"
        )

    # Secondary strategies
    if _p75 is not None and _p75 < 0.002:  # 75% of bars move < 0.2%
        recommendations["secondary_strategies"].append(
            "Conservative delta filtering (75% threshold)"
        )

    if info_results.get("i1", {}).get("weighted_change_rate", 1.0) < 0.5:
        recommendations["secondary_strategies"].append(
            "Partial I1 caching (even at 50% change rate, helps)"
        )

    return recommendations


async def main():
    """Run Phase 0 profiling."""
    await run_phase0_profiling(
        symbols=None,  # All symbols
        timeframe="1m",
        output_file="production/scripts/phase0_results.json"
    )

    print("\nNext steps:")
    print("1. Review phase0_results.json")
    print("2. Implement recommended strategy")
    print("3. Measure improvement")
    print("4. Iterate if needed")


if __name__ == "__main__":
    asyncio.run(main())
