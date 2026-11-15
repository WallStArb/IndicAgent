"""Unit tests for services/batch_support/write_session.py (compressed-hypertable write sessions, headroom guard)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.batch_support.write_session import (
    _validate_compressed_hypertable,
    compressed_hypertable_write_session,
    compressed_hypertable_write_session_or_noop,
)


class TestValidateCompressedHypertable:
    """This is the hand-curated allow-list for compressed_hypertable_write_session's own
    heavy machinery, deliberately NOT the live-queried `_known_compressed_hypertables` set
    below (code review, 2026-09-17): the live DB has 26 compressed hypertables today, but
    this mechanism has only been built/incident-hardened for one of them -- a pure static
    check, no conn involved."""

    def test_the_hardened_table_does_not_raise(self) -> None:
        _validate_compressed_hypertable("feature_ic_scores")

    def test_feature_vectors_is_refused_since_migration_570(self) -> None:
        """The table under the name has one writer, bulk_load; no in-place UPDATE session may
        open on it (the legacy regime writers would overwrite the rebuild's labels)."""
        with pytest.raises(ValueError, match="feature_vectors"):
            _validate_compressed_hypertable("feature_vectors")

    def test_a_live_compressed_table_outside_the_hardened_set_still_raises(self) -> None:
        """The regression this class exists to prevent (code review, 2026-09-17): a table
        that IS genuinely compressed in production -- market_data_ohlcv, confirmed live to
        be one of the DB's other 24 compressed hypertables -- must still be rejected here.
        This allow-list answers "has this mechanism been validated for this table," not "is
        this table compressed" -- those are different questions with opposite-direction
        risk, and must never share one live-queried set."""
        with pytest.raises(ValueError, match="market_data_ohlcv"):
            _validate_compressed_hypertable("market_data_ohlcv")


def _mock_sync_conn(
    n_decompressed: int = 0,
    n_recompressed: int = 0,
    compression_jobs: list[tuple[int, bool]] | None = None,
) -> MagicMock:
    """A psycopg-shaped connection mock: `cursor()` returns the same cursor mock on every
    call (so all cur.execute() calls across the session land in one call_args_list).
    `cur.rowcount` is scripted by which collapsed statement was just executed (decompress-
    all vs. compress-all) -- matching how compressed_hypertable_write_session actually
    reads the affected-row count (a single server-side statement per phase, not a
    list-then-loop), not an assumption about it. `compression_jobs` seeds the
    (job_id, scheduled) rows returned for the hypertable's compression-policy lookup --
    defaults to none found (todo 314's pause/resume logic is then a no-op, matching every
    pre-existing test that doesn't care about it)."""
    conn = MagicMock()
    conn.autocommit = False
    cur = conn.cursor.return_value.__enter__.return_value

    def _execute(sql: str, params: tuple | None = None) -> None:
        if sql.startswith("SELECT job_id, scheduled FROM timescaledb_information.jobs"):
            cur.fetchall.return_value = compression_jobs or []
        elif sql.startswith("SELECT config_key, config_value FROM config_state"):
            # No rows seeded -- the session falls back to its own defaults for every GUC
            # in _SESSION_GUC_OVERRIDES (combined into one ANY(%s) lookup, not one query
            # per key).
            cur.fetchall.return_value = []
        elif sql.startswith("SELECT current_setting("):
            # One combined round trip reads all _SESSION_GUC_OVERRIDES priors at once, in
            # (statement_timeout, idle_session_timeout, idle_in_transaction_session_timeout)
            # order -- values are arbitrary but distinguishable, only their round-trip
            # (captured, restored) is tested.
            cur.fetchone.return_value = ("30min", "1h", "1h")
        elif sql.startswith("SELECT decompress_chunk"):
            cur.rowcount = n_decompressed
        elif sql.startswith("SELECT compress_chunk"):
            cur.rowcount = n_recompressed
        # SELECT set_config(...), set_config(...), set_config(...) (both the entry
        # override and the exit restore use this identical shape): no return value
        # consumed by the real code, nothing to script here.

    cur.execute.side_effect = _execute
    return conn


class TestCompressedHypertableWriteSession:
    def test_decompresses_on_entry_before_yield(self) -> None:
        conn = _mock_sync_conn(n_decompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            calls_at_entry = [c.args[0] for c in cur.execute.call_args_list]
            assert any(sql.startswith("SELECT decompress_chunk") for sql in calls_at_entry)
            assert not any(sql.startswith("SELECT compress_chunk") for sql in calls_at_entry)
            assert not any(sql.startswith("VACUUM") for sql in calls_at_entry)

    def test_decompress_and_compress_are_single_collapsed_statements_not_per_chunk(self) -> None:
        """Regression: the original design listed chunks then issued one execute() per
        chunk (N round trips). The fix collapses each phase into one server-side statement
        -- exactly 8 execute() calls total for the whole session regardless of how many
        chunks are actually affected: the compression-policy-jobs lookup (1, todo 314 --
        zero jobs found here, so no pause/restore alter_job() calls follow), the combined
        _SESSION_GUC_OVERRIDES APR lookup (1), one combined current_setting() read for all
        3 GUCs (1), one combined set_config() write for all 3 GUCs (1), decompress-all (1),
        compress-all (1), VACUUM (1), and one combined set_config() restore for all 3 GUCs
        at exit (1)."""
        conn = _mock_sync_conn(n_decompressed=40, n_recompressed=40)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        assert cur.execute.call_count == 8

    def test_recompresses_and_vacuums_on_clean_exit(self) -> None:
        conn = _mock_sync_conn(n_decompressed=1, n_recompressed=2)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        decompress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT decompress"))
        compress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT compress"))
        vacuum_idx = next(i for i, s in enumerate(sqls) if s.startswith("VACUUM"))

        assert decompress_idx < compress_idx < vacuum_idx
        assert sqls[vacuum_idx] == "VACUUM feature_ic_scores"

    def test_recompresses_and_vacuums_even_when_body_raises(self) -> None:
        """The finally guarantee -- a caller's write loop raising mid-batch must not leave
        the hypertable stuck decompressed."""
        conn = _mock_sync_conn(n_recompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value

        with pytest.raises(RuntimeError, match="boom"):
            with compressed_hypertable_write_session(conn, "feature_ic_scores"):
                raise RuntimeError("boom")

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any(s.startswith("SELECT compress_chunk") for s in sqls)
        assert any(s.startswith("VACUUM") for s in sqls)

    def test_rolls_back_before_recompressing_when_body_raises(self) -> None:
        """Regression (2026-08-14 code review): without a rollback here, a body that
        raised a real DB-level error would leave the connection in Postgres's aborted-
        transaction state, and the very next statement (the recompress attempt) would
        itself raise (psycopg.errors.InFailedSqlTransaction in production, not
        reproducible with this mock -- what IS reproducible and asserted here is that
        rollback() happens, and happens before compress_chunk is attempted)."""
        conn = _mock_sync_conn(n_recompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value
        call_order: list[str] = []
        conn.rollback.side_effect = lambda: call_order.append("rollback")
        original_execute = cur.execute.side_effect

        def _tracked_execute(sql: str, *args: object) -> None:
            original_execute(sql, *args)
            if sql.startswith("SELECT compress_chunk"):
                call_order.append("compress")

        cur.execute.side_effect = _tracked_execute

        with pytest.raises(RuntimeError, match="boom"):
            with compressed_hypertable_write_session(conn, "feature_ic_scores"):
                raise RuntimeError("boom")

        assert call_order == ["rollback", "compress"]

    def test_rolls_back_on_clean_exit_too_defensively_harmless(self) -> None:
        """rollback() runs unconditionally in `finally`, including the success path --
        must not raise/misbehave when there's nothing to roll back (the caller's own
        conn.commit() already ran)."""
        conn = _mock_sync_conn()

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        conn.rollback.assert_called_once()

    def test_vacuum_runs_with_autocommit_true_then_restores_prior_value(self) -> None:
        conn = _mock_sync_conn()
        cur = conn.cursor.return_value.__enter__.return_value
        autocommit_during_vacuum: list[bool] = []
        original_execute = cur.execute.side_effect

        def _record_autocommit_and_pass(sql: str, *args: object) -> None:
            original_execute(sql, *args)
            if sql.startswith("VACUUM"):
                autocommit_during_vacuum.append(conn.autocommit)

        cur.execute.side_effect = _record_autocommit_and_pass

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        assert autocommit_during_vacuum == [True]
        assert conn.autocommit is False  # restored

    def test_no_chunks_is_a_safe_no_op(self) -> None:
        """A fully-uncompressed (or already-clean) table must not error -- the collapsed
        statements simply affect zero rows, VACUUM still runs (cheap on a small/empty
        table)."""
        conn = _mock_sync_conn(n_decompressed=0, n_recompressed=0)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any(s.startswith("VACUUM") for s in sqls)

    def test_rejects_unknown_hypertable_before_touching_connection(self) -> None:
        conn = MagicMock()
        with pytest.raises(ValueError, match="not_a_real_table"):
            with compressed_hypertable_write_session(conn, "not_a_real_table"):
                pass

    def test_compression_policy_job_paused_for_duration_and_restored_after(self) -> None:
        """todo 314: a live compression-policy job racing this session's own decompress/
        recompress deadlocked in production (Columnstore Policy [1065] vs. regime_writer.py,
        2026-08-14). The job must be paused (alter_job(scheduled => false)) before this
        session touches any chunk, and restored to its PRIOR scheduled value (not
        unconditionally re-enabled -- a job an operator had already paused for other
        reasons must stay paused) once this session is done."""
        conn = _mock_sync_conn(compression_jobs=[(1065, True)])
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            calls_at_entry = [c.args for c in cur.execute.call_args_list]
            assert ("SELECT alter_job(%s, scheduled => false)", (1065,)) in calls_at_entry
            assert not any(a[0] == "SELECT alter_job(%s, scheduled => %s)" for a in calls_at_entry)

        all_calls = [c.args for c in cur.execute.call_args_list]
        assert ("SELECT alter_job(%s, scheduled => %s)", (1065, True)) in all_calls

    def test_compression_policy_job_already_paused_stays_paused(self) -> None:
        """The restore step must write back the job's actual prior `scheduled` value, not
        assume it was always true -- an operator-paused job (scheduled=False before this
        session ever started) must not get silently re-enabled on exit."""
        conn = _mock_sync_conn(compression_jobs=[(1065, False)])
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        all_calls = [c.args for c in cur.execute.call_args_list]
        assert ("SELECT alter_job(%s, scheduled => %s)", (1065, False)) in all_calls

    def test_entry_phase_failure_restores_paused_job_before_raising(self) -> None:
        """Code review finding (2026-08-20): the job is paused at the very start of the
        entry phase -- if the decompress that follows it fails (statement-timeout kill
        2026-08-14, idle-session kill 2026-08-15 are both documented as having actually
        happened at exactly this call), the exception used to propagate straight out of
        the function, before `try: yield` was ever reached, so the normal exit `finally`
        never ran and the job stayed at scheduled=false forever. Must now be restored by
        the entry-phase except-clause instead."""
        conn = _mock_sync_conn(compression_jobs=[(1065, True)])
        cur = conn.cursor.return_value.__enter__.return_value
        original_execute = cur.execute.side_effect

        def _fail_on_decompress(sql: str, params: tuple | None = None) -> None:
            if sql.startswith("SELECT decompress_chunk"):
                raise RuntimeError("statement timeout")
            original_execute(sql, params)

        cur.execute.side_effect = _fail_on_decompress

        with pytest.raises(RuntimeError, match="statement timeout"):
            with compressed_hypertable_write_session(conn, "feature_ic_scores"):
                pytest.fail("body must never run -- entry phase failed first")

        all_calls = [c.args for c in cur.execute.call_args_list]
        assert ("SELECT alter_job(%s, scheduled => %s)", (1065, True)) in all_calls
        conn.rollback.assert_called_once()

    def test_no_compression_policy_job_is_a_safe_no_op(self) -> None:
        """A hypertable with no compression policy at all (or one already covered by the
        default empty-list mock) must not error -- the lookup finds zero jobs, pause/
        restore loops do nothing."""
        conn = _mock_sync_conn()
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        assert not any("alter_job" in str(c.args[0]) for c in cur.execute.call_args_list)

    # Expected combined set_config() call shape -- both the entry override and the exit
    # restore use this identical SQL text, differing only in the bound values, matching
    # _SESSION_GUC_OVERRIDES's (statement_timeout, idle_session_timeout,
    # idle_in_transaction_session_timeout) order.
    _SET_CONFIG_SQL = "SELECT " + ", ".join("set_config(%s, %s, false)" for _ in range(3))

    def test_idle_timeouts_set_at_entry_and_restored_at_exit(self) -> None:
        """todo 318: idle_session_timeout AND idle_in_transaction_session_timeout must both
        be overridden for the session's duration (default disabled -- '0') and restored to
        the connection's prior values on exit -- the exact protection the missing form of
        this let regime_writer.py's connection get killed mid-run (confirmed live
        2026-08-15, see this function's docstring). One combined set_config() call covers
        all three GUCs (statement_timeout too) per direction, not one call per GUC."""
        conn = _mock_sync_conn()
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            calls_at_entry = [
                (c.args[0], c.args[1] if len(c.args) > 1 else None)
                for c in cur.execute.call_args_list
            ]
            assert (
                self._SET_CONFIG_SQL,
                (
                    "statement_timeout",
                    "14400000",
                    "idle_session_timeout",
                    "0",
                    "idle_in_transaction_session_timeout",
                    "0",
                ),
            ) in calls_at_entry

        all_calls = [
            (c.args[0], c.args[1] if len(c.args) > 1 else None) for c in cur.execute.call_args_list
        ]
        assert (
            self._SET_CONFIG_SQL,
            (
                "statement_timeout",
                "30min",
                "idle_session_timeout",
                "1h",
                "idle_in_transaction_session_timeout",
                "1h",
            ),
        ) in all_calls

    def test_idle_timeouts_set_before_decompress_and_restored_after_vacuum(self) -> None:
        """Ordering matters: the override must be active for the ENTIRE bracket (including
        the caller's own work between decompress and compress), not just around the
        decompress/compress calls themselves -- restoring too early would reopen the exact
        idle-kill window this fix exists to close."""
        conn = _mock_sync_conn(n_decompressed=1, n_recompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        set_config_indices = [i for i, s in enumerate(sqls) if s == self._SET_CONFIG_SQL]
        decompress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT decompress"))
        vacuum_idx = next(i for i, s in enumerate(sqls) if s.startswith("VACUUM"))

        assert len(set_config_indices) == 2  # entry override, exit restore
        entry_idx, restore_idx = set_config_indices
        assert entry_idx < decompress_idx
        assert restore_idx > vacuum_idx


class TestCompressedHypertableWriteSessionOrNoop:
    def test_returns_real_session_when_apply_true(self) -> None:
        conn = _mock_sync_conn()
        with compressed_hypertable_write_session_or_noop(conn, "feature_ic_scores", apply=True):
            assert conn.cursor.called

    def test_returns_noop_when_apply_false(self) -> None:
        conn = MagicMock()
        with compressed_hypertable_write_session_or_noop(conn, "feature_ic_scores", apply=False):
            pass
        conn.cursor.assert_not_called()


class TestDecompressHeadroomGuard:
    """Todo 426: refuse before decompressing when the disk can't hold the decompressed chunks."""

    _TB = 10**12

    def _usage(self, total, free):
        import shutil as _shutil

        return _shutil._ntuple_diskusage(total, total - free, free)

    def test_raises_when_decompress_would_eat_the_reserve(self):
        from services.batch_support.write_session import check_decompress_headroom

        with patch(
            "services.batch_support.write_session.shutil.disk_usage",
            return_value=self._usage(914e9, 414e9),
        ):
            with pytest.raises(RuntimeError, match="refused"):
                check_decompress_headroom("feature_ic_scores", int(491e9), "/", 0.10)

    def test_passes_with_room_to_spare(self):
        from services.batch_support.write_session import check_decompress_headroom

        with patch(
            "services.batch_support.write_session.shutil.disk_usage",
            return_value=self._usage(914e9, 414e9),
        ):
            check_decompress_headroom("feature_ic_scores", int(6e9), "/", 0.10)

    @pytest.mark.real_headroom_check
    def test_sync_session_refuses_before_touching_anything(self):
        from services.batch_support.write_session import compressed_hypertable_write_session

        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (int(491e9),)
        cur.fetchall.return_value = []
        with patch(
            "services.batch_support.write_session.shutil.disk_usage",
            return_value=self._usage(914e9, 414e9),
        ):
            with pytest.raises(RuntimeError, match="refused"):
                with compressed_hypertable_write_session(conn, "feature_ic_scores"):
                    pass
        sql = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
        assert "alter_job" not in sql and "decompress_chunk" not in sql


class TestNativeDmlWriteMode:
    """Todo 426: decompress=False pauses jobs and sets GUCs but never decompresses,
    recompresses or VACUUMs, and skips the decompress headroom pre-flight."""

    @pytest.mark.real_headroom_check
    def test_no_decompress_statements(self):
        from services.batch_support.write_session import compressed_hypertable_write_session

        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        cur.fetchone.return_value = ("0", "0", "0")
        with patch("services.batch_support.write_session.shutil.disk_usage") as usage:
            with compressed_hypertable_write_session(conn, "feature_ic_scores", decompress=False):
                pass
        usage.assert_not_called()
        sql = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
        assert "decompress_chunk" not in sql
        assert "compress_chunk" not in sql
        assert "VACUUM" not in sql
        assert "set_config" in sql
