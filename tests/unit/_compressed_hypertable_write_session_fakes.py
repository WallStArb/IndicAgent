"""Shared test double for services._batch_utils.compressed_hypertable_write_session
(and its async sibling's call shape).

`_ScriptedConn`/`_ScriptedCursor` replay a pre-scripted sequence of responses in call
order -- the only workable fake for this function, since it isn't a single query but a
fixed internal sequence (compression-job pause, APR lookup, combined current_setting()/
set_config() round trips, decompress-all, on exit: rollback, compress-all, VACUUM,
GUC restore, compression-job resume). Originally local to
tests/unit/scripts/test_ops_regime_null_out_and_verify.py; extracted here (todo 307)
once a second caller (tests/unit/test_ic_engine_incremental_write.py) needed the exact
same fake rather than a second hand-rolled, independently-drifting copy of this same
fragile sequence.

Update _WRITE_SESSION_ENTRY_RESPONSES/_WRITE_SESSION_EXIT_RESPONSES here (not per test
file) whenever compressed_hypertable_write_session's own internal call shape changes --
it already has twice (2026-08-14, 2026-08-15), each time requiring every caller of this
fake to update in lockstep.
"""

from __future__ import annotations


class ScriptedCursor:
    def __init__(self, conn: ScriptedConn) -> None:
        self._conn = conn
        self._response: dict = {}

    def __enter__(self) -> ScriptedCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self._conn.calls.append((sql, params))
        self._response = self._conn.pop_response()

    def executemany(self, sql: str, argslist) -> None:
        self._conn.calls.append((sql, list(argslist)))
        self._conn.executemany_calls.append((sql, list(argslist)))
        self._response = self._conn.pop_response()

    def fetchone(self):
        return self._response.get("fetchone")

    def fetchall(self):
        # compressed_hypertable_write_session's combined statement_timeout +
        # idle_session_timeout APR lookup reads via fetchall(), not fetchone() --
        # default empty (no APR rows scripted) so the session falls back to its own
        # defaults, same shape as _mock_sync_conn in tests/unit/test_batch_utils.py.
        return self._response.get("fetchall", [])

    @property
    def rowcount(self) -> int:
        return self._response.get("rowcount", 0)


class ScriptedConn:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, tuple | None]] = []
        self.executemany_calls: list[tuple[str, list]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.autocommit = False
        self._responses = list(responses or [])
        self._idx = 0

    def cursor(self) -> ScriptedCursor:
        return ScriptedCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def pop_response(self) -> dict:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
        else:
            resp = {}
        self._idx += 1
        return resp


# compressed_hypertable_write_session's fixed call sequence (services/_batch_utils.py) --
# every test that runs a real (non-empty) write session prepends/appends these, so the
# session's own internals only need updating in one place if its call shape changes again
# (as it did 2026-08-14, twice in the same session: the statement_timeout override was
# added, then the config lookup it added was rescoped from a full-table load to a single
# key; and again 2026-08-15, todo 318: idle_session_timeout/idle_in_transaction_session_
# timeout overrides added, then the whole 3-GUC set (statement_timeout included) collapsed
# from 3 separate SHOW/SET pairs into one combined current_setting()/set_config() round
# trip per direction -- see _SESSION_GUC_OVERRIDES and compressed_hypertable_write_
# session's docstring for what each call is).
WRITE_SESSION_ENTRY_RESPONSES: list[dict] = [
    {"fetchall": []},  # compression-policy-jobs lookup (todo 314; no rows -> none found)
    {"fetchall": []},  # combined _SESSION_GUC_OVERRIDES APR key lookup (no rows -> defaults)
    {"fetchone": ("30min", "1h", "1h")},  # combined current_setting() read, all 3 GUCs
    {},  # combined set_config() override, all 3 GUCs
    {"rowcount": 0},  # decompress-all (0 chunks)
]
WRITE_SESSION_EXIT_RESPONSES: list[dict] = [
    {"rowcount": 0},  # compress-all
    {},  # VACUUM
    {},  # combined set_config() restore, all 3 GUCs
]
