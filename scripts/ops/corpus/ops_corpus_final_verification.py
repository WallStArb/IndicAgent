#!/usr/bin/env python3
"""
ops_corpus_final_verification.py — crash-loud corpus completeness gate

Verifies corpus pipeline completeness and data quality: all steps emitted manifests
(ic_measure writes .planning/corpus_manifests/ic_measure.json on every real run),
all TFs present in outputs, and CORPUS-01 data quality checks passed.
Run after ops_corpus_pipeline_run.sh completes to validate the corpus before
research consumes it. Requires the manifest dir and output tables populated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
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

REQUIRED_STEPS = ["ic_measure"]
REQUIRED_TFS = ["5m", "15m", "1h", "1d"]


def main() -> None:
    _logger.info("corpus_verification.starting")

    settings = Settings()
    manifest_dir = Path(".planning/corpus_manifests")

    verifier = CorpusManifestVerifier(manifest_dir)

    try:
        verifier.verify_all(REQUIRED_STEPS, REQUIRED_TFS)
        _logger.info("corpus_verification.all_manifests_verified")
    except RuntimeError as error:
        print(f"\nFAIL: {error}")
        sys.exit(1)

    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg.connect(db_dsn)
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
    print("  - Per-TF lookahead grids present")
    print("  - Data quality checks passed")
    print("\nCorpus is safe to consume.")
    print("=" * 70)


if __name__ == "__main__":
    main()
