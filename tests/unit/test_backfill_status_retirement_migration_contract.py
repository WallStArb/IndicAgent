"""Source-level contract for migration 459 (plan 185-43): drop backfill_status and the reader-less
tables, retire every APR key the data layer and the 185-45 removals left unread.

The migration deletes each key from config_history, then config_state, then config_schema, by
literal key inside one transaction, and drops the bookkeeping and leftover tables IF EXISTS
(idempotent: a rerun changes nothing). Raw market data is never named. CI-clean: reads files only.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._migration_catalog import migration_catalog, strip_sql_comments
from tests.unit._source_grep_helpers import read_source

_MIGRATION = ("production", "migrations", "459_drop_backfill_status_retire_superseded_apr.sql")
_REPO_ROOT = Path(__file__).parent.parent.parent

_DROPPED_TABLES = {
    "backfill_status",
    "batch_job_checkpoints",
    "ic_cell_fingerprints",
    "market_data_ohlcv_new",
    "market_data_ohlcv_old",
}

# Raw market data and the 1d policy: never dropped or touched by a cleanup migration.
_NEVER_TOUCHED = (
    "market_data_ohlcv",
    "market_data_ohlcv_tradeable",
    "ohlcv_observation",
    "ohlcv_request",
    "ohlcv_revision",
    "ohlcv_load",
    "ohlcv_coverage",
    "corporate_action",
    "bar_source_policy",
    "intraday_raw_archive",
)

# Named by the plans that orphaned them (185-42 and 185-45 _PENDING_RETIREMENT entries, the 185-45
# SUMMARY's alert.lag list, this plan's deleted pilot draw).
_NAMED_KEYS = {
    "infra.tradier.max_changed_bar_ratio",
    "infra.real_rows_swap.copy_statement_timeout_s",
    "infra.real_rows_swap.disk_margin",
    "infra.real_rows_swap.lock_timeout_s",
    "infra.real_rows_swap.masked_audit_max_age_hours",
    "infra.real_rows_swap.statement_timeout_s",
    "infra.real_rows_swap.stats_flush_wait_s",
    "threshold.bar_integrity.cutover_max_removed_share",
    "threshold.bar_integrity.cutover_max_refused_share",
    "ai.agent.correlation_v1.shadow_mode",
    "ai.agent.counterfactual_v1.shadow_mode",
    "ai.agent.ml_scorer_v1.shadow_mode",
    "ai.agent.regime_coherence_v1.shadow_mode",
    "swarm.max_concurrent_calls",
    "swarm.min_confidence",
    "swarm.min_tf_minutes",
    "swarm.weight_floor",
    "swarm.weight_min_samples",
    "feature.lifecycle_writer.batch_size",
    "feature.lifecycle_writer.flush_interval_secs",
    "feature.lifecycle_writer.max_buffer_size",
    "feature.signal_writer.batch_size",
    "feature.signal_writer.flush_interval_secs",
    "feature.signal_writer.max_buffer_size",
    "feature.signal_tracker.bootstrap_active_window_days",
    "feature.signal_tracker.bootstrap_dedup_window_days",
    "feature.signal_tracker.bootstrap_max_attempts",
    "feature.signal_tracker.bootstrap_pending_window_days",
    "feature.signal_auditor.audit_lookback_hours",
    "infra.signal_auditor.audit_interval_seconds",
    "threshold.signal_tracker.staleness_score",
    "alpha.universe.pilot_sample_size",
    "alpha.publisher.is_shadow",
    "infra.alpha_publisher.chunk_size",
    "infra.ensemble_trainer.workers",
    "infra.cross_sectional_spread_tracker.chunk_size",
    "infra.cross_sectional_spread_tracker.itersize",
    "infra.interaction_primitives_pilot.fetch_flush_rows",
} | {
    f"alert.lag.{unit}"
    for unit in (
        "alpha-swarm",
        "feature-writer",
        "graduation-compute",
        "graduation-writer",
        "intelligence-pipeline",
        "lifecycle-writer",
        "lineage-writer",
        "llm-writer",
        "narrative-compute",
        "signal-metrics-writer",
        "signal-tracker-compute",
        "signal-writer",
        "swarm-ledger-writer",
    )
}

# Whole families with no reader anywhere: the v2.x trade frame geometry (6 base keys, 6 frozen
# keys and 108 regime-by-timeframe cells) and the deleted signal auditor's thresholds.
_FAMILY_COUNTS = {"alpha.frame.": 120, "threshold.signal_audit.": 6}


def _statements() -> list[str]:
    sql = strip_sql_comments(read_source(*_MIGRATION))
    return [" ".join(part.split()) for part in sql.split(";") if part.strip()]


def _keys(statement: str) -> list[str]:
    return re.findall(r"'([^']+)'", statement)


def test_one_transaction_history_then_state_then_schema_then_drops():
    statements = _statements()
    assert statements[0] == "BEGIN" and statements[-1] == "COMMIT"
    body = statements[1:-1]
    deletes = [s for s in body if s.startswith("DELETE FROM ")]
    assert [s.split()[2] for s in deletes] == ["config_history", "config_state", "config_schema"]
    drops = [s for s in body if s.startswith("DROP TABLE ")]
    assert len(deletes) + len(drops) == len(body)
    assert body.index(deletes[-1]) < body.index(drops[0])
    for statement in deletes:
        assert "LIKE" not in statement.upper()
    key_sets = [_keys(s) for s in deletes]
    assert key_sets[0] == key_sets[1] == key_sets[2]
    assert len(set(key_sets[0])) == len(key_sets[0])


def test_drops_are_if_exists_and_name_only_retired_tables():
    dropped: set[str] = set()
    for statement in _statements():
        if statement.startswith("DROP TABLE "):
            assert statement.startswith("DROP TABLE IF EXISTS ")
            assert "CASCADE" not in statement.upper()
            dropped.update(name.strip() for name in statement[21:].split(","))
    assert dropped == _DROPPED_TABLES
    body = " ".join(_statements())
    for raw in _NEVER_TOUCHED:
        assert not re.search(rf"\b{raw}\b", body), raw


def test_retires_every_named_key_and_the_two_families():
    keys = set(_keys(next(s for s in _statements() if s.startswith("DELETE FROM config_schema"))))
    assert _NAMED_KEYS <= keys
    for prefix, count in _FAMILY_COUNTS.items():
        assert sum(key.startswith(prefix) for key in keys) == count, prefix
    family = {key for key in keys if key.startswith(tuple(_FAMILY_COUNTS))}
    assert keys == _NAMED_KEYS | family


def test_no_retired_key_or_dropped_table_is_left_in_code():
    keys = set(_keys(next(s for s in _statements() if s.startswith("DELETE FROM config_schema"))))
    for search_dir in ("services", "src", "scripts"):
        for path in (_REPO_ROOT / search_dir).rglob("*"):
            if path.suffix not in {".py", ".sh", ".sql"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for key in keys:
                assert key not in text, (key, path)
            for table in _DROPPED_TABLES:
                assert not re.search(rf"\b{table}\b", text), (table, path)


def test_catalog_no_longer_creates_or_seeds_them():
    tables, keys = migration_catalog()
    assert not (_DROPPED_TABLES & tables)
    assert not (_NAMED_KEYS & keys)


def test_header_cites_the_plan_the_dumps_and_the_grep():
    header = read_source(*_MIGRATION).split("BEGIN;")[0]
    assert "185-43" in header
    assert "data/backups/185-43/backfill_status.dump" in header
    assert "grep -rn" in header
