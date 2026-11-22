"""The spec-once guard's shared predicate (ledger.RESULTLESS_FAILURE_SQL): both guard sites use
it, the unique index of migration 611 repeats it exactly, and the status sets are unchanged."""

import inspect
import re
from pathlib import Path

from src.intelligence.research import ledger

MIGRATION = Path("production/migrations/611_research_run_spec_once_resultless_failures.sql")


def _flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_has_real_run_and_start_runs_share_one_query():
    assert "PRIOR_REAL_RUN_SQL" in inspect.getsource(ledger.PostgresLedger.has_real_run)
    assert "PRIOR_REAL_RUN_SQL" in inspect.getsource(ledger.PostgresLedger.start_runs)
    assert "kind <> 'subset_refit'" not in inspect.getsource(ledger.PostgresLedger)
    assert ledger.RESULTLESS_FAILURE_SQL in ledger.PRIOR_REAL_RUN_SQL
    assert "AND NOT (" + ledger.RESULTLESS_FAILURE_SQL in ledger.PRIOR_REAL_RUN_SQL


def test_the_unique_index_repeats_the_python_predicate_exactly():
    text = _flat(MIGRATION.read_text())
    assert f"WHERE mode = 'real' AND NOT {ledger.RESULTLESS_FAILURE_SQL};" in text
    assert text.count("DROP INDEX") == 1 and text.count("CREATE UNIQUE INDEX") == 1
    assert text.index("BEGIN;") < text.index("DROP INDEX") < text.index("COMMIT;")


def test_only_a_failed_run_with_no_snapshot_and_no_statistic_is_exempt():
    predicate = ledger.RESULTLESS_FAILURE_SQL
    for clause in (
        "status = 'failed'",
        "snapshot_hash IS NULL",
        "decision_t IS NULL",
        "decision_p IS NULL",
        "gross_sharpe IS NULL",
        "span_start IS NULL",
    ):
        assert clause in predicate
    assert "completed" not in predicate and "started" not in predicate


def test_the_budget_status_sets_are_unchanged():
    assert ledger.UNCHARGED_STATUSES == ("refused", "guard_failed")
    assert ledger.SERIES_STATUSES == ("completed", "failed")
    assert ledger.TERMINAL_STATUSES == ("completed", "guard_failed", "refused", "failed")


def test_the_guard_also_keeps_a_failed_run_with_a_series_or_a_productive_sibling():
    sql = ledger.PRIOR_REAL_RUN_SQL
    assert "FROM research_run_series s WHERE s.run_id = research_run.run_id" in sql
    assert "g.run_group = research_run.run_group" in sql
    assert "g.kind = 'subset_refit' OR g.snapshot_hash IS NOT NULL" in sql
