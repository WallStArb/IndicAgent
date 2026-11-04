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

import psycopg
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

# The expected per-tf lookahead grid is the IC writer's own configuration, the APR key
# services/ic_measure.py reads (HORIZONS_KEY), so the gate and the writer cannot disagree. Read
# here as a raw config_state value: src/observability/ is Ring 0 and must not import services/.
_APR_KEY_IC_HORIZONS = "alpha.ic_measure.horizons"


def _open_db_conn() -> Any:
    """Open a sync psycopg connection using standard project credentials."""
    return psycopg.connect(**_DB_DEFAULTS)


def _load_apr_values(conn: Any) -> dict[str, Any]:
    """Load APR-controlled thresholds from config_state.

    Falls back to hardcoded defaults when a threshold key is absent. The lookahead grid has no
    fallback: it is the IC writer's `alpha.ic_measure.horizons`, and a missing or malformed
    value raises (a guessed grid would let the gate pass or halt on the wrong expectation).
    """
    keys = [
        _APR_KEY_IC_HORIZONS,
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

    raw_horizons = rows.get(_APR_KEY_IC_HORIZONS)
    if raw_horizons is None:
        raise RuntimeError(f"{_APR_KEY_IC_HORIZONS} is missing from config_state")
    try:
        lookaheads_by_tf: dict[str, set[int]] = {
            tf: {int(h) for h in horizons} for tf, horizons in json.loads(raw_horizons).items()
        }
    except (ValueError, TypeError, AttributeError) as error:
        raise RuntimeError(f"{_APR_KEY_IC_HORIZONS} is malformed: {raw_horizons!r}") from error

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
    ) -> None:
        """Verify data quality checks (CORPUS-01 from Phase 141).

        Crashes loud if any check fails.

        Checks:
        - Symbol coverage (distinct symbol count per TF >= len(required_symbols))
        - Schema completeness (POOLED rows for all TFs, no missing lookaheads)
        - Feature distribution (NULL rate < APR threshold per feature column, per-TF sampled)
        - Consistency (no empty regime label)
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
                WHERE symbol = 'POOLED' AND regime_scope = 'unstratified'
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
                WHERE symbol = 'POOLED' AND regime_scope = 'unstratified'
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

        # Check 5: no empty regime label (NOT NULL covers NULL; an empty string would read as
        # a real regime_volatility label).
        _logger.info("corpus_verification.checking_regime_labels")
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM feature_ic_scores WHERE regime = ''")
            empty_regime_count = cur.fetchone()[0]
            if empty_regime_count > 0:
                raise RuntimeError(
                    f"{empty_regime_count} feature_ic_scores rows have an empty regime"
                )

        _logger.info("corpus_verification.data_quality_verified")


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

# D1 rule 2 (todo 584 4b-2 group 4): the four columns below are None wherever
# their object does not exist -- the session-VP pair has no object on daily
# bars (no intraday session), and an SR side with no qualifying cluster
# in-window has no distance -- so the strict max_null_rate tier would fail
# honest data. They are gated only against being ENTIRELY NULL on a TF where
# the object can exist (a dead kernel or a dropped writer column); their
# value-level correctness is carried by the kernel parity tests. The mapped
# TFs are the structurally-absent ones, exempt from even the dead-column
# check (poc_dist_atr/va_position are legitimately 100% NULL on 1d).
_ABSENCE_EXEMPT_TFS: dict[str, frozenset[str]] = {
    "poc_dist_atr": frozenset({"1d"}),
    "va_position": frozenset({"1d"}),
    "sr_support_dist": frozenset(),
    "sr_resist_dist": frozenset(),
}


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
    exceeds the threshold. Columns in _ABSENCE_EXEMPT_TFS (D1 rule 2) are
    instead gated only against being entirely NULL on TFs where their object
    can exist, and skipped entirely on their exempt TFs.
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
            if col in _ABSENCE_EXEMPT_TFS:
                if tf in _ABSENCE_EXEMPT_TFS[col]:
                    continue  # the object cannot exist on this TF (D1 rule 2)
                if null_count == total:
                    violations.append(
                        f"tf={tf} col={col} entirely NULL ({null_count}/{total}) - "
                        "object-existence column produced no values where the object "
                        "can exist (D1 rule 2, todo 584 4b-2 group 4)"
                    )
                continue
            if null_rate > max_null_rate:
                violations.append(
                    f"tf={tf} col={col} null_rate={null_rate:.1%} ({null_count}/{total})"
                )

    if violations:
        raise RuntimeError(
            f"Feature NULL rate gate failed (max_null_rate={max_null_rate:.0%}; "
            "absence-legit columns must not be entirely NULL):\n"
            + "\n".join(f"  {v}" for v in violations)
        )
