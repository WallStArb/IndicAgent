"""Unit tests for services/ohlcv_ingress_contract.py (plan 185-39).

A fake cursor scripts the stored rows and records every statement; no database (todo 494).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.ohlcv_ingress_contract import (
    DESTINATION_ARCHIVE,
    DESTINATION_GRID,
    ContractParams,
    RevisionRefused,
    apply_ingress_contract,
    read_params,
)

_T0 = datetime(2026, 10, 1, 13, 30, tzinfo=UTC)
_PARAMS = ContractParams(max_ratio=0.02, min_stored=500)


def _row(i: int, close: float = 10.5, volume: int = 100, symbol: str = "ZZ185A") -> tuple:
    return (_T0 + timedelta(minutes=5 * i), symbol, "5m", 10.0, 11.0, 9.0, close, volume, "ibkr")


def _stored(rows: list[tuple]) -> list[tuple]:
    """The (timestamp, open, high, low, close, volume, source) rows a SELECT returns."""
    return [(r[0], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows]


class FakeCursor:
    def __init__(self, stored: list[tuple] | None = None, config: dict | None = None) -> None:
        self.stored = stored or []
        self.config = config
        self.statements: list[tuple[str, object]] = []
        self._result: list[tuple] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.statements.append((sql, params))
        if sql.lstrip().startswith("SELECT config_key"):
            self._result = list((self.config or {}).items())
        elif sql.lstrip().startswith("SELECT"):
            self._result = self.stored

    def fetchall(self) -> list[tuple]:
        return self._result

    def sql_starting(self, prefix: str) -> list[tuple[str, object]]:
        return [(s, p) for s, p in self.statements if s.startswith(prefix)]


class Writers:
    def __init__(self) -> None:
        self.new: list[tuple] = []
        self.changed: list[tuple] = []

    def write_new(self, cur: object, rows: list[tuple]) -> None:
        self.new.extend(rows)

    def write_changed(self, cur: object, rows: list[tuple]) -> None:
        self.changed.extend(rows)


def _apply(cur: FakeCursor, rows: list[tuple], writers: Writers, **kwargs) -> int:
    return apply_ingress_contract(
        cur,
        rows,
        destination=kwargs.pop("destination", DESTINATION_GRID),
        caller="ibkr-history-fetch",
        write_new=writers.write_new,
        write_changed=writers.write_changed,
        params=kwargs.pop("params", _PARAMS),
    )


def test_the_same_answer_twice_writes_no_bar_and_no_revision_but_one_load_row():
    rows = [_row(i) for i in range(10)]
    cur, writers = FakeCursor(_stored(rows)), Writers()
    assert _apply(cur, rows, writers) == 10
    assert writers.new == [] and writers.changed == []
    assert cur.sql_starting("INSERT INTO ohlcv_revision") == []
    (load,) = cur.sql_starting("INSERT INTO ohlcv_load")
    params = load[1]
    # outcome applied, n_bars 10, n_new 0, n_changed 0, source ibkr, n_unchanged 10, n_removed 0
    assert params[3] == "ibkr" and params[6] == "applied" and params[7:10] == (10, 0, 0)
    assert params[13] == "ibkr-history-fetch" and params[14] == "market_data_ohlcv"
    assert params[15:] == (10, 0)


def test_one_changed_bar_writes_one_row_and_one_revision_with_old_values():
    old = [_row(i) for i in range(10)]
    incoming = [_row(i) if i != 4 else _row(4, close=10.75) for i in range(10)]
    cur, writers = FakeCursor(_stored(old)), Writers()
    _apply(cur, incoming, writers)
    assert writers.new == [] and writers.changed == [incoming[4]]
    (revision,) = cur.sql_starting("INSERT INTO ohlcv_revision")
    values = tuple(revision[1])
    # load_id, symbol, timeframe, timestamp, old_open..old_close, old_volume, old_source, origin
    assert values[1:4] == ("ZZ185A", "5m", old[4][0])
    assert values[4:10] == (10.0, 11.0, 9.0, 10.5, 100, "ibkr") and values[10] == "load"
    load_params = cur.sql_starting("INSERT INTO ohlcv_load")[0][1]
    assert load_params[0] == values[0]  # the revision hangs off the load row
    assert load_params[7:10] == (10, 0, 1) and load_params[15] == 9


def test_new_keys_go_to_the_insert_writer_and_changed_to_the_replace_writer():
    stored = [_row(0), _row(1)]
    incoming = [_row(0), _row(1, close=11.0), _row(2)]
    cur, writers = FakeCursor(_stored(stored)), Writers()
    _apply(cur, incoming, writers)
    assert writers.new == [incoming[2]] and writers.changed == [incoming[1]]


def test_tail_window_below_the_floor_is_written_and_recorded_not_refused():
    stored = [_row(i) for i in range(78)]
    incoming = [_row(i, close=10.9) if i in (10, 11) else _row(i) for i in range(78)]
    cur, writers = FakeCursor(_stored(stored)), Writers()
    _apply(cur, incoming, writers)  # 2/78 = 2.6% > 2%, but 78 < min_stored 500
    assert len(writers.changed) == 2
    assert len(cur.sql_starting("INSERT INTO ohlcv_revision")) == 1  # one batched statement
    assert len(cur.sql_starting("INSERT INTO ohlcv_revision")[0][1]) == 2 * 11


def test_a_breach_at_the_floor_is_refused_before_any_write():
    stored = [_row(i) for i in range(1000)]
    incoming = [_row(i, close=10.9) if i < 30 else _row(i) for i in range(1000)]
    cur, writers = FakeCursor(_stored(stored)), Writers()
    with pytest.raises(RevisionRefused) as caught:
        _apply(cur, incoming, writers)
    assert writers.new == [] and writers.changed == []
    assert cur.sql_starting("INSERT") == []
    assert caught.value.load.n_changed == 30 and caught.value.load.n_stored == 1000
    assert "0.0300" in caught.value.detail


def test_at_the_threshold_exactly_is_written():
    stored = [_row(i) for i in range(1000)]
    incoming = [_row(i, close=10.9) if i < 20 else _row(i) for i in range(1000)]  # 2.0%
    cur, writers = FakeCursor(_stored(stored)), Writers()
    _apply(cur, incoming, writers)
    assert len(writers.changed) == 20


def test_a_chunk_of_new_rows_is_never_refused():
    cur, writers = FakeCursor([]), Writers()
    _apply(cur, [_row(i) for i in range(2000)], writers)
    assert len(writers.new) == 2000


def test_duplicate_timestamps_in_a_chunk_resolve_last_wins():
    cur, writers = FakeCursor([]), Writers()
    first, second = _row(0, close=10.0), _row(0, close=10.25)
    assert _apply(cur, [first, second], writers) == 2  # rows offered
    assert writers.new == [second]


def test_a_source_change_alone_is_a_change():
    stored = _stored([_row(0)])
    incoming = _row(0)[:8] + ("other",)
    cur, writers = FakeCursor(stored), Writers()
    _apply(cur, [incoming], writers)
    assert writers.changed == [incoming]


def test_archive_destination_reads_the_archive_table():
    cur, writers = FakeCursor([]), Writers()
    _apply(cur, [_row(0) + (None,)], writers, destination=DESTINATION_ARCHIVE)
    select = cur.sql_starting("SELECT")[0][0]
    assert "FROM ohlcv_intraday_raw_archive" in select
    assert cur.sql_starting("INSERT INTO ohlcv_load")[0][1][14] == "archive"


def test_nan_in_an_incoming_row_raises_instead_of_writing():
    cur, writers = FakeCursor([]), Writers()
    bad = _row(0)[:6] + (float("nan"),) + _row(0)[7:]
    with pytest.raises(ValueError, match="NaN"):
        _apply(cur, [bad], writers)
    assert writers.new == []


def test_an_empty_chunk_issues_no_sql_and_an_unknown_destination_is_refused():
    cur, writers = FakeCursor(), Writers()
    assert _apply(cur, [], writers) == 0 and cur.statements == []
    with pytest.raises(ValueError, match="destination"):
        _apply(cur, [_row(0)], writers, destination="d1")


def test_thresholds_come_from_config_state_and_a_missing_key_is_loud():
    keys = {
        "threshold.bar_integrity.max_revision_ratio": "0.02",
        "threshold.bar_integrity.revision_ratio_min_stored": "500",
    }
    assert read_params(FakeCursor(config=keys)) == ContractParams(0.02, 500)
    with pytest.raises(RuntimeError, match="missing from config_state"):
        read_params(FakeCursor(config={}))


def test_params_are_read_from_the_cursor_when_not_passed():
    cur, writers = (
        FakeCursor(
            [],
            config={
                "threshold.bar_integrity.max_revision_ratio": "0.02",
                "threshold.bar_integrity.revision_ratio_min_stored": "500",
            },
        ),
        Writers(),
    )
    apply_ingress_contract(
        cur,
        [_row(0)],
        destination=DESTINATION_GRID,
        caller="c",
        write_new=writers.write_new,
        write_changed=writers.write_changed,
    )
    assert cur.statements[0][0].startswith("SELECT config_key")
