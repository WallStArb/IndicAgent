"""One fake psycopg connection for unit tests that script SQL responses.

A responder maps an executed statement to its answer, called lazily on the first fetch (so an
execute that is never fetched costs nothing and consumes nothing): `responder(text, params)`
returns either a list of row tuples (`fetchall` is the list, `fetchone` its first row or None)
or a dict with any of `fetchone`, `fetchall` and `rowcount`. `rows_responder(rows)` answers every
statement with the same rows; `scripted(responses)` answers in order, one dict per fetched
statement, the shape bulk_load's tests are written in.

Every execute, COPY row, commit and rollback lands in one ordered event log, so a test can assert
the statement sequence. `execute_errors` maps a needle to an exception raised by any statement
containing it.

CI-clean: no DB, no network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Responder = Callable[[str, Any], "list[tuple] | dict"]


def statement_text(stmt: Any) -> str:
    if isinstance(stmt, str):
        return stmt
    try:
        return str(stmt.as_string(None))
    except Exception:
        return repr(stmt)


def rows_responder(rows: list[tuple]) -> Responder:
    return lambda _text, _params: rows


def scripted(responses: list[dict] | None = None) -> Responder:
    queue = list(responses or [])
    position = [0]

    def respond(_text: str, _params: Any) -> dict:
        answer = queue[position[0]] if position[0] < len(queue) else {}
        position[0] += 1
        return answer

    return respond


class FakeCopy:
    """Records write_row calls into the conn's event log."""

    def __init__(self, conn: FakeConn, statement: Any) -> None:
        self._conn = conn
        self._statement = statement

    def __enter__(self) -> FakeCopy:
        self._conn.events.append(("copy", statement_text(self._statement), None))
        return self

    def write_row(self, row: Any) -> None:
        self._conn.copied_rows.append(tuple(row))
        self._conn.events.append(("write_row", tuple(row), None))

    def __exit__(self, *exc: Any) -> bool:
        return False


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn
        self._text = ""
        self._params: Any = None
        self._response: dict | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: Any, params: Any = None) -> None:
        self._text = statement_text(sql)
        self._params = params
        self._conn.events.append(("execute", self._text, params))
        for needle, error in self._conn.execute_errors.items():
            if needle in self._text:
                raise error
        self._response = None  # the answer is asked for on the first fetch

    def _answer(self) -> dict:
        if self._response is None:
            answer = self._conn.responder(self._text, self._params)
            if isinstance(answer, dict):
                self._response = answer
            else:
                self._response = {
                    "fetchall": answer,
                    "fetchone": answer[0] if answer else None,
                }
        return self._response

    def fetchone(self) -> Any:
        return self._answer().get("fetchone")

    def fetchall(self) -> Any:
        return self._answer().get("fetchall", [])

    @property
    def rowcount(self) -> int:
        return int(self._answer().get("rowcount", 0))

    def copy(self, statement: Any) -> FakeCopy:
        return FakeCopy(self._conn, statement)


class FakeConn:
    def __init__(self, responder: Responder | None = None) -> None:
        self.responder: Responder = responder or rows_responder([])
        self.events: list[tuple[str, Any, Any]] = []
        self.copied_rows: list[tuple] = []
        self.commits = 0
        self.rollbacks = 0
        self.execute_errors: dict[str, Exception] = {}

    @property
    def statements(self) -> list[tuple[str, Any]]:
        """(text, params) of every executed statement, in order."""
        return [(text, params) for kind, text, params in self.events if kind == "execute"]

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1
        self.events.append(("commit", "", None))

    def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append(("rollback", "", None))

    def index_of(self, kind: str, contains: str | None = None) -> int | None:
        for i, (k, text, _params) in enumerate(self.events):
            if k == kind and (contains is None or contains in text):
                return i
        return None

    def require_index(self, kind: str, contains: str | None = None) -> int:
        idx = self.index_of(kind, contains)
        assert (
            idx is not None
        ), f"no {kind!r} event containing {contains!r} in {[e[0] for e in self.events]}"
        return idx
