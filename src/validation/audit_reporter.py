"""
Generate human-readable and machine-readable audit reports.

Produces console output with colored sections, JSON output for
downstream systems, and tracks passed/failed checks.
"""

from datetime import datetime
from typing import Dict, List


class AuditReporter:
    """Generate audit reports with console and JSON output."""

    def __init__(self):
        """Initialize reporter."""
        self.passed: List[str] = []
        self.failed: List[str] = []
        self.warnings: List[str] = []

    def print_header(self, symbol: str, tf: str, hours: int) -> None:
        """Print audit header.

        Args:
            symbol: Trading symbol
            tf: Timeframe
            hours: Hours of data validated
        """
        print("\n" + "=" * 60)
        print("🔬 RENAISSANCE PIPELINE AUDIT")
        print(f"   Symbol: {symbol}")
        print(f"   Timeframe: {tf}")
        print(f"   Window: Last {hours} hours")
        print(f"   Started: {datetime.utcnow().isoformat()}Z")
        print("=" * 60)

    def print_section(self, title: str) -> None:
        """Print section header.

        Args:
            title: Section title
        """
        print(f"\n{title}")
        print("-" * 60)

    def print_computational_correctness(self, results: Dict[str, Dict]) -> None:
        """Print Layer 1: Computational Correctness results.

        Args:
            results: Validation results from ComputationalCorrectnessValidator
        """
        self.print_section("📊 Layer 1: Computational Correctness")

        for field, result in results.items():
            if result.get("error"):
                print(f"  ❌ {field}: ERROR - {result['error']}")
                self.failed.append(f"{field}: {result['error']}")
                continue

            status = "✅ PASS" if result["passed"] else "❌ FAIL"
            print(f"  {field}: {status}")
            print(f"    Max diff:  {result['max_diff']:.6f} (tolerance: {result['tolerance']})")
            print(f"    Mean diff: {result['mean_diff']:.6f}")
            print(f"    Samples:   {result['samples']}")

            if result["passed"]:
                self.passed.append(field)
            else:
                self.failed.append(field)

    def print_cross_tier_consistency(
        self,
        i1_i4: Dict,
        i6_i7: Dict,
        regime: Dict,
    ) -> None:
        """Print Layer 2: Cross-Tier Consistency results.

        Args:
            i1_i4: I1→I4 correlation results
            i6_i7: I6→I7 completeness results
            regime: Regime agreement results
        """
        self.print_section("📊 Layer 2: Cross-Tier Consistency")

        # I1→I4 Correlation
        corr = i1_i4.get("i1_atr_i4_volatility_correlation", 0)
        status = "✅ PASS" if i1_i4.get("passed") else "❌ FAIL"
        print(f"  I1→I4 Correlation: {corr:.3f} {status}")
        print(f"    Expected: ≥{i1_i4.get('expected_min', 0.5)}")
        print(f"    Samples: {i1_i4.get('samples', 0)}")

        if i1_i4.get("passed"):
            self.passed.append("I1→I4 Correlation")
        else:
            self.failed.append("I1→I4 Correlation")

        # I6→I7 Completeness
        completeness = i6_i7.get("completeness_rate", 0)
        status = "✅ PASS" if i6_i7.get("passed") else "❌ FAIL"
        print(f"\n  I6→I7 Completeness: {completeness:.1%} {status}")
        print(f"    Total rows: {i6_i7.get('total_rows', 0)}")
        print(f"    Complete: {i6_i7.get('complete_rows', 0)}")
        print(f"    Expected: ≥{i6_i7.get('expected_min', 0.95):.0%}")

        if i6_i7.get("missing_field_counts"):
            missing = ", ".join(i6_i7["missing_field_counts"].keys())
            print(f"    ⚠️  Missing fields: {missing}")
            self.warnings.append(f"Missing I6 fields: {missing}")

        if i6_i7.get("passed"):
            self.passed.append("I6→I7 Completeness")
        else:
            self.failed.append("I6→I7 Completeness")

        # Regime Agreement
        agreement = regime.get("agreement_rate", 0)
        status = "✅ PASS" if regime.get("passed") else "❌ FAIL"
        print(f"\n  I4↔I7 Regime Agreement: {agreement:.1%} {status}")
        print(f"    Expected: ≥{regime.get('expected_min', 0.90):.0%}")

        if regime.get("passed"):
            self.passed.append("Regime Agreement")
        else:
            self.failed.append("Regime Agreement")

    def print_summary(self) -> None:
        """Print audit summary with final pass/fail status."""
        print("\n" + "=" * 60)

        if not self.failed:
            print("✅ AUDIT PASSED")
            print(f"   Passed checks: {len(self.passed)}")
            if self.warnings:
                print(f"   Warnings: {len(self.warnings)}")
                for w in self.warnings:
                    print(f"     • {w}")
            print("\n✅ All calculations are correct.")
            print("✅ Cross-tier consistency validated.")
            print("✅ Pipeline is computationally sound.")
        else:
            print("❌ AUDIT FAILED")
            print(f"   Failed checks: {len(self.failed)}")
            print(f"   Passed checks: {len(self.passed)}")
            print("\n❌ Investigate failed validations:")
            for f in self.failed:
                print(f"   • {f}")

        print("=" * 60 + "\n")
