"""Unit tests: ic_engine incremental per-cell writes + DB-driven BH-FDR backfill
(todo 130, 2026-07-17).

Prior behavior: ic_engine held every computed row for the entire corpus in memory
(corpus_pooled_rows/corpus_regime_rows/corpus_cs_rows) and wrote nothing to
feature_ic_scores until one corpus-wide multipletests() call finished -- a crash
anywhere in a 30+ hour run (e.g. the 143.1-07 corpus re-run's two crashes, both in
the cross-sectional pass) lost the *entire* run's compute, including the already-
complete per-symbol pass.

New behavior: each unit of compute (one symbol's rows, one cross-sectional cell's
rows) is written to feature_ic_scores immediately, with bh_adjusted_p/passes_fdr
left NULL for cluster-representative rows (non-representatives already get their
final passes_fdr=False at compute time -- unchanged, see _compute_symbol_tf/
_compute_cross_sectional_tf). The corpus-wide BH-FDR correction (which genuinely
needs the whole corpus's representative p-values ranked together -- the P2 fix)
becomes a separate UPDATE-only backfill pass, driven by querying the DB for
whatever rows are currently pending (passes_fdr IS NULL) rather than by in-memory
bookkeeping from a single process invocation. This is safe to rerun after a crash
regardless of which run wrote the pending rows.

No DB, no Kafka. Fake cursor/connection doubles for _backfill_bh_fdr's SQL
interaction; signature/docstring/source inspection for the rest.
"""

from __future__ import annotations

import inspect
import sys
from datetime import UTC, datetime
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import services.ic_engine as ic_module

# ---------------------------------------------------------------------------
# Fakes for _backfill_bh_fdr
# ---------------------------------------------------------------------------


class _FakeBackfillCursor:
    def __init__(self, conn: _FakeBackfillConn):
        self.conn = conn
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.conn.executed_sql.append(sql)
        self.conn.executed_params.append(params)
        if "passes_fdr IS NULL" in sql:
            self._rows = list(self.conn.pending_rows)
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


class _FakeBackfillConn:
    """Simulates enough of a psycopg2 connection for _backfill_bh_fdr."""

    def __init__(self, pending_rows: list[tuple]):
        self.pending_rows = pending_rows
        self.executed_sql: list[str] = []
        self.executed_params: list[tuple | None] = []
        self.committed = False

    def cursor(self):
        return _FakeBackfillCursor(self)

    def commit(self):
        self.committed = True


_TWE = datetime(2026, 7, 17, tzinfo=UTC)


def test_backfill_bh_fdr_queries_only_pending_rows(monkeypatch):
    """The SELECT must scope to this training_window_end and passes_fdr IS NULL --
    non-representative rows (already locked to passes_fdr=False at compute time)
    must never be re-touched."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        ic_module.psycopg2.extras,
        "execute_values",
        lambda cur, sql, argslist, **kw: calls.append((sql, argslist)),
    )
    conn = _FakeBackfillConn(pending_rows=[])

    updates = ic_module._backfill_bh_fdr(conn, _TWE, fdr_alpha=0.05)

    assert updates == []
    assert any("passes_fdr IS NULL" in sql for sql in conn.executed_sql)
    assert any("training_window_end" in sql for sql in conn.executed_sql)
    # Nothing pending -> no UPDATE attempted, no wasted round trip.
    assert calls == []
    assert conn.committed is False


def test_backfill_bh_fdr_applies_one_corpus_wide_multipletests_call(monkeypatch):
    """10 low-p, 190 null-p representative rows (mirrors
    test_ensemble_ic_bh_fdr's synthetic split) -- exactly 10 must pass BH-FDR,
    and the UPDATE payload must carry those precise pass/fail labels."""
    import numpy as np

    calls: list[tuple] = []
    monkeypatch.setattr(
        ic_module.psycopg2.extras,
        "execute_values",
        lambda cur, sql, argslist, **kw: calls.append((sql, argslist)),
    )

    rng = np.random.default_rng(11)
    low_p = rng.uniform(0.0, 0.001, size=10)
    high_p = np.full(190, 0.5)
    pvals = np.concatenate([low_p, high_p]).tolist()
    pending_rows = [(f"feat_{i}", "SPY", "5m", "_pooled", 1, pvals[i]) for i in range(len(pvals))]
    conn = _FakeBackfillConn(pending_rows)

    updates = ic_module._backfill_bh_fdr(conn, _TWE, fdr_alpha=0.05)

    assert len(updates) == 200
    n_passing = sum(1 for u in updates if u["passes_fdr"])
    assert n_passing == 10
    assert all(u["passes_fdr"] for u in updates[:10])
    assert not any(u["passes_fdr"] for u in updates[10:])
    assert conn.committed is True

    # Exactly one batched UPDATE call carrying every pending row.
    assert len(calls) == 1
    sql, argslist = calls[0]
    assert "UPDATE feature_ic_scores" in sql
    assert "FROM (VALUES" in sql
    assert len(argslist) == 200


def test_backfill_bh_fdr_update_rows_key_on_primary_key_columns():
    """UPDATE...FROM(VALUES) rows must carry the exact feature_ic_scores primary
    key column set (feature_name, symbol, tf, regime, lookahead_bars,
    training_window_end) so the join can't silently mismatch a row."""
    source = inspect.getsource(ic_module._backfill_bh_fdr)
    for col in ("feature_name", "symbol", "tf", "regime", "lookahead_bars", "training_window_end"):
        assert f"t.{col} = v.{col}" in source, f"UPDATE join must match on t.{col} = v.{col}"


# ---------------------------------------------------------------------------
# _write_symbol_results / _write_cs_cell_results: per-unit immediate writes
# ---------------------------------------------------------------------------


def test_write_symbol_results_exists_with_immediate_write_docstring():
    assert hasattr(ic_module, "_write_symbol_results")
    doc = ic_module._write_symbol_results.__doc__
    assert doc is not None
    assert "immediately" in doc.lower()


def test_write_symbol_results_skips_connection_when_nothing_to_write(monkeypatch):
    """An all-skipped symbol (every cell already in existing_keys) must not pay
    for a DB round trip it doesn't need."""

    def _boom(settings):
        raise AssertionError("_connect_db must not be called when there are no rows")

    monkeypatch.setattr(ic_module, "_connect_db", _boom)

    n_written = ic_module._write_symbol_results(settings=object(), pooled_rows=[], regime_rows=[])

    assert n_written == 0


def test_write_symbol_results_opens_and_closes_its_own_connection(monkeypatch):
    class _FakeConn:
        def __init__(self):
            self.closed = False

        def cursor(self):
            class _Cur:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc):
                    return False

            return _Cur()

        def commit(self):
            pass

        def close(self):
            self.closed = True

    fake_conn = _FakeConn()
    monkeypatch.setattr(ic_module, "_connect_db", lambda settings: fake_conn)
    monkeypatch.setattr(ic_module.psycopg2.extras, "execute_batch", lambda cur, sql, rows: None)

    n_written = ic_module._write_symbol_results(
        settings=object(),
        pooled_rows=[{"dummy": 1}],
        regime_rows=[],
    )

    assert n_written == 1
    assert fake_conn.closed is True


def test_write_cs_cell_results_exists_with_immediate_write_docstring():
    assert hasattr(ic_module, "_write_cs_cell_results")
    doc = ic_module._write_cs_cell_results.__doc__
    assert doc is not None
    assert "immediately" in doc.lower()


def test_write_cs_cell_results_skips_connection_when_no_rows(monkeypatch):
    def _boom(settings):
        raise AssertionError("_connect_db must not be called for an empty cell")

    monkeypatch.setattr(ic_module, "_connect_db", _boom)

    n_written = ic_module._write_cs_cell_results(settings=object(), cs_rows=[])

    assert n_written == 0


# ---------------------------------------------------------------------------
# Structural guards: no reintroducing the deferred corpus-wide write
# ---------------------------------------------------------------------------


def test_deferred_corpus_wide_write_helpers_removed():
    """_persist_corpus_results / _accumulate_worker_result held every row in
    memory for the whole run before writing anything -- that's exactly the
    pattern todo 130 removes. Their reintroduction is a regression."""
    assert not hasattr(ic_module, "_persist_corpus_results")
    assert not hasattr(ic_module, "_accumulate_worker_result")


def test_main_writes_symbol_results_inside_the_as_completed_loop():
    """The per-symbol write call must live inside the `for future in
    as_completed(futures):` loop body, not after it -- otherwise rows are still
    buffered corpus-wide before hitting the DB. main() calls the shared
    _record_symbol_result helper, which itself calls _write_symbol_results
    (checked separately below)."""
    import re

    source = inspect.getsource(ic_module.main)
    loop_start = source.index("for future in as_completed(futures):")
    # The loop body ends at the next comment banner line (a run of dashes) after it.
    banner_match = re.search(r"\n\s*# -{20,}\s*\n", source[loop_start:])
    assert banner_match is not None, "expected a comment banner after the as_completed loop"
    loop_end = loop_start + banner_match.start()
    loop_body = source[loop_start:loop_end]
    assert "_record_symbol_result(" in loop_body


def test_record_symbol_result_calls_write_symbol_results():
    source = inspect.getsource(ic_module._record_symbol_result)
    assert "_write_symbol_results(" in source


def test_symbol_result_recorded_unconditionally_even_on_worker_error():
    """Each tf is caught independently inside _run_ic_worker's per-tf try/except
    -- a worker-level error (result["error"] truthy) can still carry successfully
    computed rows from OTHER tfs in result["pooled_rows"]/["regime_rows"]. Those
    must still be written, never silently discarded just because the same
    worker also failed on a different tf (Renaissance: never drop data that
    could contain signal). _record_symbol_result must therefore be called at
    the same indentation as `if result["error"]:` -- i.e. after the if/else
    block, unconditionally -- not only inside the success branch."""
    source = inspect.getsource(ic_module.main)
    if_idx = source.index('if result["error"]:')
    if_line_start = source.rfind("\n", 0, if_idx) + 1
    if_indent = len(source[if_line_start:if_idx]) - len(source[if_line_start:if_idx].lstrip())

    record_idx = source.index("_record_symbol_result(", if_idx)
    record_line_start = source.rfind("\n", 0, record_idx) + 1
    record_indent = len(source[record_line_start:record_idx]) - len(
        source[record_line_start:record_idx].lstrip()
    )
    assert record_indent == if_indent, (
        "_record_symbol_result must be called at the same indentation as "
        'if result["error"]: -- i.e. after the if/else block, unconditionally, '
        "not only in the success branch"
    )


def test_main_calls_backfill_after_cross_sectional_pass():
    """_backfill_bh_fdr must run after both the per-symbol and cross-sectional
    compute passes are done -- it needs the whole corpus's pending rows."""
    source = inspect.getsource(ic_module.main)
    cross_sectional_idx = source.index("ic_engine.starting_cross_sectional_pass")
    backfill_idx = source.index("_backfill_bh_fdr(")
    assert backfill_idx > cross_sectional_idx
