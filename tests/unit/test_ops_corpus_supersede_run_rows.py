"""ops_corpus_supersede_run_rows: a run's stored feature_vectors units cleared through the sanctioned
completed -> superseded flip and the unit's replace_where delete, per unit, with the row_count assertion;
a dry run by default that writes nothing."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.ops.ops_corpus_supersede_run_rows as tool

START, END = datetime(2003, 1, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)
RUN = "eca9e854-c51e-41b4-a9ec-9258f1286742"


def _unit(key: str, count: int, *symbols: str) -> tool.Unit:
    return tool.Unit(key, "1d", START, END, symbols or ("AAA", "BBB"), count)


class FakeConn:
    """provenance rows by batch key, stored feature_vectors row counts by unit key; records every write."""

    def __init__(self, units: list[tool.Unit], stored: dict[str, int]):
        self.units = {u.batch_key: u for u in units}
        self.stored = dict(stored)
        self.status = {u.batch_key: "completed" for u in units}
        self.writes: list[str] = []
        self.rolled_back: list[str] = []
        self._pending: list[tuple[str, Any]] = []

    def _key_for(self, params) -> str:
        symbols, tf, start, end = params
        return next(
            k
            for k, u in self.units.items()
            if list(u.symbols) == symbols and (u.tf, u.range_start, u.range_end) == (tf, start, end)
        )

    def execute(self, sql, params=()):
        if sql.lstrip().startswith("SELECT count"):
            return SimpleNamespace(fetchone=lambda: (self.stored[self._key_for(params)],))
        if sql.lstrip().startswith("UPDATE"):
            self._pending.append(("flip", params[0]))
            return SimpleNamespace(rowcount=1)
        if sql.lstrip().startswith("DELETE"):
            key = self._key_for(params)
            self._pending.append(("delete", key))
            return SimpleNamespace(rowcount=self.stored[key])
        raise AssertionError(sql)

    @contextmanager
    def transaction(self):
        self._pending = []
        try:
            yield
        except Exception:
            self.rolled_back.extend(f"{what}:{key[:6]}" for what, key in self._pending)
            raise
        for what, key in self._pending:
            self.writes.append(f"{what}:{key}")
            if what == "flip":
                self.status[key] = "superseded"
            else:
                self.stored[key] = 0


def _world(counts: dict[str, int], stored: dict[str, int] | None = None):
    units = [
        _unit(key, n, *syms)
        for (key, n), syms in zip(counts.items(), [("AAA",), ("BBB",), ("CCC",)])
    ]
    return FakeConn(units, stored or counts), units


def test_a_dry_run_lists_every_unit_and_writes_nothing():
    conn, units = _world({"k1" * 8: 100, "k2" * 8: 200})
    plans = tool.plan(conn, units)
    lines, clean = tool.render(plans, apply=False)
    assert clean and conn.writes == []
    assert "2 units, 300 stored rows, 0 mismatched" in "\n".join(lines)
    assert any("dry run: nothing written" in line for line in lines)


def test_apply_flips_and_deletes_each_unit_and_reports_the_total():
    conn, units = _world({"k1" * 8: 100, "k2" * 8: 200})
    done = tool.supersede_and_delete(conn, tool.plan(conn, units))
    assert conn.status == {"k1" * 8: "superseded", "k2" * 8: "superseded"}
    assert conn.stored == {"k1" * 8: 0, "k2" * 8: 0}
    assert done[-1] == "deleted 300 rows in 2 units"


def test_a_unit_whose_stored_rows_differ_from_its_row_count_is_refused_and_nothing_is_deleted():
    conn, units = _world({"k1" * 8: 100, "k2" * 8: 200}, stored={"k1" * 8: 100, "k2" * 8: 250})
    lines, clean = tool.render(tool.plan(conn, units), apply=True)
    assert not clean and conn.writes == []
    text = "\n".join(lines)
    assert "FAIL" in text and "1 mismatched" in text and "nothing is deleted" in text


def test_a_mismatch_found_at_delete_time_rolls_that_unit_back_and_stops():
    conn, units = _world({"k1" * 8: 100, "k2" * 8: 200})
    plans = tool.plan(conn, units)
    conn.stored["k2" * 8] = 201  # a row arrived between the count and the delete
    with pytest.raises(RuntimeError, match="rolled back"):
        tool.supersede_and_delete(conn, plans)
    assert conn.status["k1" * 8] == "superseded" and conn.status["k2" * 8] == "completed"
    assert conn.rolled_back == ["flip:k2k2k2", "delete:k2k2k2"]


def test_main_refuses_a_run_id_that_is_not_a_uuid_and_a_live_run(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        tool.main(["not-a-run"])
    monkeypatch.setattr(tool, "_live_run_refusal", lambda: "a corpus run is live")
    assert tool.main([RUN]) == 1
    assert "refused: a corpus run is live" in capsys.readouterr().err
