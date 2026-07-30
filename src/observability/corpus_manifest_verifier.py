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

import json
import sys
from pathlib import Path
from typing import Any

import psycopg2
import structlog

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.observability.corpus_manifest import CorpusManifest

_logger = structlog.get_logger(__name__)

_DB_DEFAULTS = {
    "host": "localhost",
    "dbname": "indicagent",
    "user": "postgres",
    "password": "postgres",
}

# APR keys and their fallback defaults
_APR_KEY_MIN_ROWS_PER_SYMBOL_REGIME = "corpus.min_rows_per_symbol_regime"
_APR_KEY_MAX_NULL_RATE = "corpus.verifier.max_null_rate"
_APR_KEY_NULL_RATE_SAMPLE_SIZE = "infra.corpus_verifier.null_rate_sample_size"
_APR_DEFAULT_MIN_ROWS_PER_SYMBOL_REGIME = 9
_APR_DEFAULT_MAX_NULL_RATE = 0.05
_APR_DEFAULT_NULL_RATE_SAMPLE_SIZE = 10000

# Todo 146: alpha.ic.lookahead.{tf}.{scale} is per-tf, not a single shared grid -- a bar
# count means a different scale on different tfs (e.g. 5 is 15m's old slow AND part of
# nothing consistent post-146). The old alpha.ic.lookaheads (plural) APR key this file
# previously read was never actually seeded in any migration; every lookup silently used
# the hardcoded fallback below, uniformly across all 4 tfs. This mirrors the Ring 2
# services layer's LOOKAHEAD_FALLBACKS_BY_TF dict (services package, _batch_utils
# module) BY VALUE, not by import -- src/observability/ is Ring 0 and must not import
# the services layer, per this repo's pre-commit Ring 0 boundary check. Keep in sync
# with that dict by hand if the grid ever changes.
_LOOKAHEAD_SCALES = ("fast", "mid", "slow", "extended")
_APR_DEFAULT_LOOKAHEADS_BY_TF: dict[str, dict[str, int]] = {
    "5m": {"fast": 1, "mid": 6, "slow": 12, "extended": 39},
    "15m": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
    "1h": {"fast": 1, "mid": 2, "slow": 20, "extended": 60},
    "1d": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
}

# Todo 208/per-tf-active-scale-set design (2026-07-30): alpha.ic.active_scales.{tf}
# controls WHICH of the 4 scales ic_engine actually attempts per tf -- 1h excludes
# slow/extended (0.000 measured forward_returns completeness under the same-session
# gate). Mirrors services/_batch_utils.py's ACTIVE_SCALES_FALLBACKS_BY_TF BY VALUE, not
# by import -- src/observability/ is Ring 0, see this file's Ring-0-boundary comment
# above for _LOOKAHEAD_SCALES. Keep in sync with that dict by hand if it ever changes.
_APR_DEFAULT_ACTIVE_SCALES_BY_TF: dict[str, tuple[str, ...]] = {
    "5m": ("fast", "mid", "slow", "extended"),
    "15m": ("fast", "mid", "slow", "extended"),
    "1h": ("fast", "mid"),
    "1d": ("fast", "mid", "slow", "extended"),
}


def _open_db_conn() -> Any:
    """Open a sync psycopg2 connection using standard project credentials."""
    return psycopg2.connect(**_DB_DEFAULTS)


def _load_apr_values(conn: Any) -> dict[str, Any]:
    """Load APR-controlled thresholds from config_state.

    Falls back to hardcoded defaults when keys are absent (e.g., before
    migration adds them). Always returns a complete dict.
    """
    lookahead_keys = [
        f"alpha.ic.lookahead.{tf}.{scale}"
        for tf in _APR_DEFAULT_LOOKAHEADS_BY_TF
        for scale in _LOOKAHEAD_SCALES
    ]
    active_scales_keys = [f"alpha.ic.active_scales.{tf}" for tf in _APR_DEFAULT_ACTIVE_SCALES_BY_TF]
    keys = [
        *lookahead_keys,
        *active_scales_keys,
        _APR_KEY_MIN_ROWS_PER_SYMBOL_REGIME,
        _APR_KEY_MAX_NULL_RATE,
        _APR_KEY_NULL_RATE_SAMPLE_SIZE,
    ]
    placeholders = ",".join(["%s"] * len(keys))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT config_key, config_value FROM config_state WHERE config_key IN ({placeholders})",
            keys,
        )
        rows = {r[0]: r[1] for r in cur.fetchall()}

    active_scales_by_tf: dict[str, tuple[str, ...]] = {}
    for tf, default_scales in _APR_DEFAULT_ACTIVE_SCALES_BY_TF.items():
        raw = rows.get(f"alpha.ic.active_scales.{tf}")
        try:
            # None (key absent) -> default_scales. A present-but-empty "[]" is a
            # deliberate "no scales active" configuration and must NOT fall back to
            # the default -- matches canonicalize_active_scales([]) == () in
            # services/_batch_utils.py, the Ring 2 path this Ring 0 copy mirrors.
            parsed = json.loads(raw) if raw is not None else None
            active_scales_by_tf[tf] = default_scales if parsed is None else tuple(parsed)
        except (ValueError, TypeError):
            active_scales_by_tf[tf] = default_scales

    lookaheads_by_tf: dict[str, set[int]] = {}
    for tf, defaults_by_scale in _APR_DEFAULT_LOOKAHEADS_BY_TF.items():
        bars: set[int] = set()
        active_scales = active_scales_by_tf.get(tf, tuple(defaults_by_scale.keys()))
        for scale, default in defaults_by_scale.items():
            if scale not in active_scales:
                continue
            raw = rows.get(f"alpha.ic.lookahead.{tf}.{scale}")
            try:
                bars.add(int(raw) if raw is not None else default)
            except (ValueError, TypeError):
                bars.add(default)
        lookaheads_by_tf[tf] = bars

    raw_min_rows = rows.get(_APR_KEY_MIN_ROWS_PER_SYMBOL_REGIME)
    if raw_min_rows is not None:
        try:
            min_rows_per_symbol_regime = int(raw_min_rows)
        except (ValueError, TypeError):
            min_rows_per_symbol_regime = _APR_DEFAULT_MIN_ROWS_PER_SYMBOL_REGIME
    else:
        min_rows_per_symbol_regime = _APR_DEFAULT_MIN_ROWS_PER_SYMBOL_REGIME

    raw_max_null_rate = rows.get(_APR_KEY_MAX_NULL_RATE)
    if raw_max_null_rate is not None:
        try:
            max_null_rate = float(raw_max_null_rate)
        except (ValueError, TypeError):
            max_null_rate = _APR_DEFAULT_MAX_NULL_RATE
    else:
        max_null_rate = _APR_DEFAULT_MAX_NULL_RATE

    raw_sample_size = rows.get(_APR_KEY_NULL_RATE_SAMPLE_SIZE)
    if raw_sample_size is not None:
        try:
            null_rate_sample_size = int(raw_sample_size)
        except (ValueError, TypeError):
            null_rate_sample_size = _APR_DEFAULT_NULL_RATE_SAMPLE_SIZE
    else:
        null_rate_sample_size = _APR_DEFAULT_NULL_RATE_SAMPLE_SIZE

    return {
        "lookaheads_by_tf": lookaheads_by_tf,
        "min_rows_per_symbol_regime": min_rows_per_symbol_regime,
        "max_null_rate": max_null_rate,
        "null_rate_sample_size": null_rate_sample_size,
    }


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
        """Verify all required steps emitted manifests and have expected TF coverage.

        Crashes loud if any step missing or incomplete. APR config is loaded from
        the database to determine minimum row thresholds.
        """
        apr: dict[str, Any] | None = None
        if required_symbols is not None:
            conn = _open_db_conn()
            try:
                apr = _load_apr_values(conn)
            finally:
                conn.close()

        for step_name in required_steps:
            try:
                manifest = CorpusManifest.read(self.manifest_dir, step_name)
            except FileNotFoundError as err:
                raise RuntimeError(
                    f"Prerequisite step '{step_name}' did not emit a manifest. "
                    f"Cannot proceed without verification."
                ) from err

            # Check status
            if manifest.get("status") == "failed":
                raise RuntimeError(
                    f"Prerequisite step '{step_name}' failed. "
                    f"Errors: {manifest.get('errors', [])}"
                )

            # Check TF coverage
            outputs = manifest.get("outputs", {})
            for table_name, table_stats in outputs.items():
                rows_by_tf = table_stats.get("rows_by_tf", {})
                missing_tfs = set(required_tfs) - set(rows_by_tf.keys())
                if missing_tfs:
                    raise RuntimeError(
                        f"Table '{table_name}' from step '{step_name}' is missing TFs: {missing_tfs}. "
                        f"Has rows for TFs: {list(rows_by_tf.keys())}"
                    )

                # Check row counts (should be > 0 for each TF)
                zero_tfs = [tf for tf, count in rows_by_tf.items() if count == 0]
                if zero_tfs:
                    raise RuntimeError(
                        f"Table '{table_name}' from step '{step_name}' has zero rows for TFs: {zero_tfs}"
                    )

            # Check symbol coverage if specified
            if required_symbols is not None and apr is not None:
                min_rows_per_symbol_regime = apr["min_rows_per_symbol_regime"]
                for table_name, table_stats in outputs.items():
                    expected_min_rows = len(required_symbols) * min_rows_per_symbol_regime
                    actual_rows = table_stats.get("rows_total", 0)
                    if actual_rows < expected_min_rows:
                        raise RuntimeError(
                            f"Table '{table_name}' from step '{step_name}' has only {actual_rows} rows, "
                            f"expected at least {expected_min_rows} rows for "
                            f"{len(required_symbols)} symbols x {min_rows_per_symbol_regime} regimes"
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

        Checks:
        - Symbol coverage (distinct symbol count per TF >= len(required_symbols))
        - Schema completeness (POOLED rows for all TFs, no missing lookaheads)
        - Feature distribution (NULL rate < APR threshold per feature column, per-TF sampled)
        - Consistency (training_window_end consistent, no NULL regimes, no zero-weight strata)
        """
        apr = _load_apr_values(conn)
        expected_lookaheads_by_tf: dict[str, set[int]] = apr["lookaheads_by_tf"]

        # Check 1: Distinct symbol coverage per TF
        _logger.info("corpus_verification.checking_symbol_coverage")
        with conn.cursor() as cur:
            for tf in required_tfs:
                cur.execute(
                    "SELECT COUNT(DISTINCT symbol) FROM feature_vectors WHERE tf = %s",
                    (tf,),
                )
                symbol_count = cur.fetchone()[0]
                if symbol_count < len(required_symbols):
                    raise RuntimeError(
                        f"feature_vectors TF {tf} has only {symbol_count} distinct symbols, "
                        f"expected at least {len(required_symbols)}"
                    )

        # Check 2: POOLED rows exist for all TFs
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

        # Check 3: All lookaheads present per TF
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
                tf, lookahead, _n_features = r
                if tf not in lookaheads_by_tf:
                    lookaheads_by_tf[tf] = set()
                lookaheads_by_tf[tf].add(lookahead)

            for tf in required_tfs:
                actual_lookaheads = lookaheads_by_tf.get(tf, set())
                expected_for_tf = expected_lookaheads_by_tf.get(tf, set())
                missing = expected_for_tf - actual_lookaheads
                if missing:
                    raise RuntimeError(f"TF {tf} missing lookaheads: {missing}")
                unexpected = actual_lookaheads - expected_for_tf
                if unexpected:
                    raise RuntimeError(f"TF {tf} has unexpected lookaheads: {unexpected}")

        # Check 4: Feature NULL rate < threshold per numeric column in feature_vectors
        _logger.info("corpus_verification.checking_feature_null_rates")
        _check_feature_null_rates(
            conn, required_tfs, apr["max_null_rate"], apr["null_rate_sample_size"]
        )

        # Check 5: No NULL regime labels in POOLED rows
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

        # Check 6: No zero-weight strata in ensemble_weights
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

        # Check 7: Training window end consistency
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
            print("FAIL: Corpus incomplete - missing cross-sectional IC data")
            print("=" * 70)
            print(f"\nMissing TFs: {missing_items}")
            print("\nTo fix:")
            print("  1. Re-run cross-sectional IC:")
            print(
                "     python services/ic_engine.py --cross-sectional-only --tf 5m 15m 1h "
                "--training-window-end <ISO8601 UTC>"
            )
            print("  2. Re-run ensemble trainer:")
            print("     python services/ensemble_trainer.py")
            print("  3. Re-run alpha publisher:")
            print("     python services/alpha_publisher.py")
            print("  4. Re-run verification:")
            print("     python scripts/corpus_final_verification.py")
            print("\n" + "=" * 70)
        elif failed_step == "ensemble_trainer":
            print("\n" + "=" * 70)
            print("FAIL: Ensemble training incomplete or failed")
            print("=" * 70)
            print("\nTo fix:")
            print("  1. Check logs: logs/ensemble_trainer.log")
            print("  2. Re-run: python services/ensemble_trainer.py")
            print("  3. Re-run verification: python scripts/corpus_final_verification.py")
            print("\n" + "=" * 70)
        elif failed_step == "alpha_publisher":
            print("\n" + "=" * 70)
            print("FAIL: Alpha publishing incomplete or failed")
            print("=" * 70)
            print("\nTo fix:")
            print("  1. Check logs: logs/alpha_publisher.log")
            print("  2. Re-run: python services/alpha_publisher.py")
            print("  3. Re-run verification: python scripts/corpus_final_verification.py")
            print("\n" + "=" * 70)
        else:
            print("\nFAIL: Corpus verification failed - check logs for details")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FEATURE_COLUMNS = [
    "momentum_z_fast",
    "momentum_z_mid",
    "range_position",
    "bar_close_pos",
    "gap_z",
    "informed_flow",
    "volume_z",
    "ofi_z",
    "cvd_slope_z",
    "cmf",
    "rel_volume",
    "vwap_dev_sigma",
    "atr_z",
    "vol_ratio",
    "poc_dist_atr",
    "va_position",
    "sr_support_dist",
    "sr_resist_dist",
    "hurst",
]
# hmm_regime_prob/hmm_entropy/hmm_duration deliberately excluded here, same
# reason `regime` already is (todo 207, 2026-07-30): regime_writer.py's
# `UPDATE ... WHERE regime IS NULL` pass -- not FeatureFactory -- is what
# populates these, and its coverage is inherently partial (symbols with
# degenerate HMM fits are reasoned exclusions, see todo 168). This gate's
# contract is "did feature computation populate its outputs" -- a
# regime-labeling coverage check is a different question and belongs in its
# own gate with its own threshold, not folded into max_null_rate here.


def _check_feature_null_rates(
    conn: Any,
    required_tfs: list[str],
    max_null_rate: float,
    sample_size: int,
) -> None:
    """Check NULL rate < max_null_rate for numeric feature columns in feature_vectors.

    Runs one query per TF, sampling up to sample_size rows each, so rare TFs
    always get their own sample rather than being crowded out by a global LIMIT.
    Raises RuntimeError if a TF has zero rows (cannot verify) or if any column
    exceeds the threshold.
    """
    null_col_exprs = ", ".join(
        f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_{col}" for col in _FEATURE_COLUMNS
    )
    col_select = ", ".join(_FEATURE_COLUMNS)
    query = f"""
        SELECT
            COUNT(*) AS total_rows,
            {null_col_exprs}
        FROM (
            SELECT {col_select}
            FROM feature_vectors
            WHERE tf = %s
            LIMIT %s
        ) sampled
    """
    violations: list[str] = []
    for tf in required_tfs:
        with conn.cursor() as cur:
            cur.execute(query, (tf, sample_size))
            row = cur.fetchone()
            col_names = [desc[0] for desc in cur.description]

        row_dict = dict(zip(col_names, row))
        total = row_dict["total_rows"]
        if total == 0:
            raise RuntimeError(
                f"feature_vectors has zero rows for TF {tf} - cannot check null rates"
            )
        for col in _FEATURE_COLUMNS:
            null_count = row_dict.get(f"null_{col}", 0) or 0
            null_rate = null_count / total
            if null_rate > max_null_rate:
                violations.append(
                    f"tf={tf} col={col} null_rate={null_rate:.1%} ({null_count}/{total})"
                )

    if violations:
        raise RuntimeError(
            f"Feature NULL rate exceeds {max_null_rate:.0%} threshold:\n"
            + "\n".join(f"  {v}" for v in violations)
        )
