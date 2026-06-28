"""
CorpusManifestVerifier - crash-loud verification of corpus pipeline completeness.

Reads manifests from corpus pipeline steps and queries database to verify:
1. All required steps emitted manifests
2. All required TFs present in outputs
3. Data quality checks (CORPUS-01 from Phase 141)
4. Consistency across tables

Crashes loud with RuntimeError on any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import structlog

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.observability.corpus_manifest import CorpusManifest

_logger = structlog.get_logger(__name__)


class CorpusManifestVerifier:
    """Crash-loud verifier for corpus pipeline completeness and data quality."""

    def __init__(self, manifest_dir: Path):
        self.manifest_dir = Path(manifest_dir)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)

    def verify_all(
        self,
        required_steps: list[str],
        required_tfs: list[str],
        required_symbols: list[str] | None = None,
    ) -> None:
        """Verify all required steps emitted manifests with expected TF coverage.

        Crashes loud if any step missing or incomplete.
        """
        for step_name in required_steps:
            try:
                manifest = CorpusManifest.read(self.manifest_dir, step_name)
            except FileNotFoundError as err:
                raise RuntimeError(
                    f"Prerequisite step '{step_name}' did not emit a manifest. "
                    "Cannot proceed without verification."
                ) from err

            if manifest.get("status") == "failed":
                raise RuntimeError(
                    f"Prerequisite step '{step_name}' failed. "
                    f"Errors: {manifest.get('errors', [])}"
                )

            outputs = manifest.get("outputs", {})
            for table_name, table_stats in outputs.items():
                rows_by_tf = table_stats.get("rows_by_tf", {})
                missing_tfs = set(required_tfs) - set(rows_by_tf.keys())
                if missing_tfs:
                    raise RuntimeError(
                        f"Table '{table_name}' from step '{step_name}' is missing TFs: {missing_tfs}. "
                        f"Has rows for TFs: {list(rows_by_tf.keys())}"
                    )

                zero_tfs = [tf for tf, count in rows_by_tf.items() if count == 0]
                if zero_tfs:
                    raise RuntimeError(
                        f"Table '{table_name}' from step '{step_name}' has zero rows for TFs: {zero_tfs}"
                    )

            if required_symbols is not None:
                for table_name, table_stats in outputs.items():
                    expected_min_rows = len(required_symbols) * 9
                    actual_rows = table_stats.get("rows_total", 0)
                    if actual_rows < expected_min_rows:
                        raise RuntimeError(
                            f"Table '{table_name}' from step '{step_name}' has only {actual_rows} rows, "
                            f"expected at least {expected_min_rows} rows for "
                            f"{len(required_symbols)} symbols x 9 regimes"
                        )

        _logger.info("corpus_verification.all_manifests_verified", steps=required_steps)

    def verify_data_quality(
        self,
        conn: Any,
        required_tfs: list[str],
        required_symbols: list[str],
        training_window_end: str | None = None,
    ) -> None:
        """Verify data quality checks (CORPUS-01 from Phase 141).

        Crashes loud if any check fails.
        """
        _logger.info("corpus_verification.checking_pooled_rows")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tf, COUNT(*) as count
                FROM feature_ic_scores
                WHERE symbol = 'POOLED' AND regime != '_pooled'
                GROUP BY tf
                ORDER BY tf
                """)
            pooled_rows_by_tf = {r[0]: r[1] for r in cur.fetchall()}
            missing_tfs = set(required_tfs) - set(pooled_rows_by_tf.keys())
            if missing_tfs:
                raise RuntimeError(f"POOLED rows missing for TFs: {missing_tfs}")

        _logger.info("corpus_verification.checking_lookaheads")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tf, lookahead_bars, COUNT(DISTINCT feature_name) as n_features
                FROM feature_ic_scores
                WHERE symbol = 'POOLED' AND regime != '_pooled'
                GROUP BY tf, lookahead_bars
                ORDER BY tf, lookahead_bars
                """)
            lookaheads_by_tf: dict[str, set[int]] = {}
            for r in cur.fetchall():
                tf, lookahead, _ = r
                lookaheads_by_tf.setdefault(tf, set()).add(lookahead)

            expected_lookaheads = {1, 5, 20, 60}
            for tf in required_tfs:
                actual_lookaheads = lookaheads_by_tf.get(tf, set())
                missing = expected_lookaheads - actual_lookaheads
                if missing:
                    raise RuntimeError(f"TF {tf} missing lookaheads: {missing}")

        _logger.info("corpus_verification.checking_regime_labels")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM feature_ic_scores
                WHERE symbol = 'POOLED' AND (regime IS NULL OR regime = '')
                """)
            null_regime_count = cur.fetchone()[0]
            if null_regime_count > 0:
                raise RuntimeError(f"{null_regime_count} POOLED rows have NULL/empty regime labels")

        _logger.info("corpus_verification.checking_ensemble_weights")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM ensemble_weights
                WHERE weight = 0 OR weight IS NULL
                """)
            zero_weight_count = cur.fetchone()[0]
            if zero_weight_count > 0:
                raise RuntimeError(
                    f"{zero_weight_count} ensemble_weights rows have zero/NULL weight"
                )

        if training_window_end:
            _logger.info("corpus_verification.checking_training_window_consistency")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM feature_ic_scores
                    WHERE training_window_end != %s
                    """,
                    (training_window_end,),
                )
                inconsistent_count = cur.fetchone()[0]
                if inconsistent_count > 0:
                    raise RuntimeError(
                        f"{inconsistent_count} feature_ic_scores rows have "
                        f"training_window_end != {training_window_end}"
                    )

        _logger.info("corpus_verification.data_quality_verified")

    def print_recovery(self, failed_step: str | None = None, missing_items: Any = None) -> None:
        """Print clear recovery instructions for human execution."""
        if failed_step == "ic_engine" and isinstance(missing_items, set):
            print("\n" + "=" * 70)
            print("FAILED: Corpus incomplete - missing cross-sectional IC data")
            print("=" * 70)
            print(f"\nMissing TFs: {missing_items}")
            print("\nTo fix:")
            print("  1. Re-run cross-sectional IC:")
            print("     python services/ic_engine.py --cross-sectional-only --tf 5m 15m 1h")
            print("  2. Re-run ensemble trainer:")
            print("     python services/ensemble_trainer.py")
            print("  3. Re-run alpha publisher:")
            print("     python services/alpha_publisher.py")
            print("  4. Re-run verification:")
            print("     python scripts/corpus_final_verification.py")
            print("\n" + "=" * 70)
        elif failed_step == "ensemble_trainer":
            print("\n" + "=" * 70)
            print("FAILED: Ensemble training incomplete or failed")
            print("=" * 70)
            print("\nTo fix:")
            print("  1. Check logs: logs/ensemble_trainer.log")
            print("  2. Re-run: python services/ensemble_trainer.py")
            print("  3. Re-run verification: python scripts/corpus_final_verification.py")
            print("\n" + "=" * 70)
        elif failed_step == "alpha_publisher":
            print("\n" + "=" * 70)
            print("FAILED: Alpha publishing incomplete or failed")
            print("=" * 70)
            print("\nTo fix:")
            print("  1. Check logs: logs/alpha_publisher.log")
            print("  2. Re-run: python services/alpha_publisher.py")
            print("  3. Re-run verification: python scripts/corpus_final_verification.py")
            print("\n" + "=" * 70)
        else:
            print("\nFAILED: Corpus verification failed - check logs for details")
