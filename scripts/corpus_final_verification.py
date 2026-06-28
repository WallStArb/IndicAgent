#!/usr/bin/env python3
"""
Corpus Final Verification - crash-loud gate before Phase 141.

Verifies corpus pipeline completeness and data quality:
1. All steps (ic_engine, ensemble_trainer, alpha_publisher) emitted manifests
2. All TFs (5m, 15m, 1h, 1d) present in outputs
3. Data quality checks (CORPUS-01 from Phase 141)
4. Prints recovery instructions on failure

Usage:
    python scripts/corpus_final_verification.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.observability.corpus_manifest_verifier import CorpusManifestVerifier

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

_logger = structlog.get_logger(__name__)

REQUIRED_STEPS = ["ic_engine", "ensemble_trainer", "alpha_publisher"]
REQUIRED_TFS = ["5m", "15m", "1h", "1d"]
REQUIRED_SYMBOL_COUNT = 58


def main() -> None:
    _logger.info("corpus_verification.starting")

    settings = Settings()
    manifest_dir = Path(".planning/corpus_manifests")

    verifier = CorpusManifestVerifier(manifest_dir)

    try:
        verifier.verify_all(REQUIRED_STEPS, REQUIRED_TFS)
        _logger.info("corpus_verification.all_manifests_verified")
    except RuntimeError as error:
        verifier.print_recovery(failed_step="unknown", missing_items=str(error))
        print(f"\nError: {error}")
        sys.exit(1)

    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_dsn)
    try:
        verifier.verify_data_quality(conn, REQUIRED_TFS, [])
        _logger.info("corpus_verification.data_quality_verified")
    except RuntimeError as error:
        print(f"\nFAILED: {error}")
        sys.exit(1)
    finally:
        conn.close()

    print("\n" + "=" * 70)
    print("VERIFIED: Corpus complete")
    print("=" * 70)
    print(f"\nAll {len(REQUIRED_TFS)} TFs ({', '.join(REQUIRED_TFS)}) verified with:")
    print("  - POOLED rows present for all TFs")
    print("  - All lookaheads [1, 5, 20, 60] present")
    print("  - Data quality checks passed")
    print("\nSafe to proceed to Phase 141.")
    print("=" * 70)


if __name__ == "__main__":
    main()
