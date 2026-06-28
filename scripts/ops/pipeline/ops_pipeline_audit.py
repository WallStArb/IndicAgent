#!/usr/bin/env python3
"""Renaissance Pipeline Audit — Computational Correctness + Latency Tracking

Version: 1.0
Status: current
Last Updated: 2026-04-29

Validates that every calculation in the pipeline is mathematically correct,
tracks per-hop latency, and measures cross-tier consistency.

Usage:
    python pipeline_audit.py --symbol ES --tf 5m --hours 24

Exit codes:
    0 = Audit passed
    1 = Audit failed
"""

import argparse
import asyncio
import sys

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.validation.audit_reporter import AuditReporter
from src.validation.cross_tier_validation import CrossTierValidator
from src.validation.validation_engine import ComputationalCorrectnessValidator


async def main():
    """Run pipeline audit."""
    parser = argparse.ArgumentParser(
        description="Renaissance Pipeline Audit — Computational Correctness + Latency"
    )
    parser.add_argument("--symbol", default="ES", help="Symbol to audit (default: ES)")
    parser.add_argument("--tf", default="5m", help="Timeframe to audit (default: 5m)")
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours of data to validate (default: 24)",
    )
    args = parser.parse_args()

    settings = Settings()
    reporter = AuditReporter()
    reporter.print_header(args.symbol, args.tf, args.hours)

    db = DatabaseManager(settings.database_url)
    await db.initialize()

    try:
        # Layer 1: Computational Correctness
        validator = ComputationalCorrectnessValidator(db.pool)
        correctness_results = await validator.run_validation(args.symbol, args.tf, args.hours)
        reporter.print_computational_correctness(correctness_results)

        # Layer 2: Cross-Tier Consistency
        cross_validator = CrossTierValidator(db.pool)

        i1_i4_results = await cross_validator.validate_i1_to_i4_consistency(args.symbol, args.tf)
        i6_i7_results = await cross_validator.validate_i6_to_i7_completeness(args.symbol, args.tf)
        regime_results = await cross_validator.validate_regime_agreement(args.symbol, args.tf)

        reporter.print_cross_tier_consistency(i1_i4_results, i6_i7_results, regime_results)

        # Summary
        reporter.print_summary()

        return 0 if not reporter.failed else 1

    finally:
        await db.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
