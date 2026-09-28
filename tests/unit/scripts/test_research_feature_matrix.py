"""Fake-connection tests for the promoted two-pass feature fetch
(scripts/research/feature_matrix.py, plan 186-04).

The fake asyncpg connection honors the SQL text it is handed (so the tests can assert the
span bounds and the absence of any forward_returns join), serves pass-1 key rows and
pass-2 feature rows from the same underlying table, and records every execute() so the
session-scoped work_mem SET is observable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts.research import feature_matrix as fm

# --------------------------------------------------------------------------- fakes


@dataclass
class _FakeAttr:
    name: str
    type: SimpleNamespace


class _FakePreparedStatement:
    def __init__(self, sql: str, columns: list[tuple[str, str]]):
        self.sql = sql
        self._attrs = [_FakeAttr(n, SimpleNamespace(name=t)) for n, t in columns]

    def get_attributes(self) -> list[_FakeAttr]:
        return self._attrs


class _FakeCursor:
    def __init__(self, records: list[tuple]):
        self._records = records
        self._it = iter(records)

    def __aiter__(self) -> _FakeCursor:
        return self

    async def __anext__(self) -> tuple:
        try:
            return next(self._it)
        except StopIteration as error:
            raise StopAsyncIteration from error


class _FakeTransaction:
    async def __aenter__(self) -> _FakeTransaction:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


SCHEMA_COLUMNS = [
    ("symbol", "text"),
    ("tf", "text"),
    ("bar_ts", "timestamptz"),
    ("feature_vector_id", "int8"),
    ("feature_factory_version", "text"),
    ("bar_close_ts", "timestamptz"),
    ("regime", "text"),
    ("regime_rolling", "text"),
    ("canary_acausal_placebo", "float4"),
    ("canary_constant", "float4"),
    ("canary_near_constant", "float4"),
    ("canary_noise_gaussian", "float4"),
    ("canary_noise_uniform", "float4"),
    ("hmm_duration", "float8"),
    ("f_a", "float4"),
    ("f_b", "float8"),
    ("f_c", "float4"),
]

FEATURE_COLS = ["hmm_duration", "f_a", "f_b", "f_c"]

SYMBOLS = ["AAA", "BBB"]
START = datetime(2024, 1, 1, 9, 30)
END = datetime(2024, 1, 1, 9, 34)


def _table_rows() -> list[tuple]:
    """Eight rows over two symbols x four timestamps, ordered by (bar_ts, symbol).

    Column order matches FEATURE_COLS: (symbol, bar_ts, hmm_duration, f_a, f_b, f_c).
    """
    rows = []
    for i in range(4):
        ts = datetime(2024, 1, 1, 9, 30) + pd.Timedelta(minutes=i).to_pytimedelta()
        for j, sym in enumerate(SYMBOLS):
            hd = float(i * 2 + j)
            fa = float(i * 10 + j)
            fb = None  # all-NULL column: must arrive as NaN, never an error
            fc = float(i) - 0.5 * j
            rows.append((sym, ts, hd, fa, fb, fc))
    return rows


def _key_rows(rows: list[tuple]) -> list[tuple]:
    return [(r[0], r[1]) for r in rows]


class FakeConnection:
    """Minimal asyncpg.Connection stand-in routing cursor() by SQL text."""

    def __init__(
        self,
        schema_columns: list[tuple[str, str]] | None = None,
        rows: list[tuple] | None = None,
        feature_rows: list[tuple] | None = None,
    ):
        self.schema_columns = schema_columns if schema_columns is not None else SCHEMA_COLUMNS
        table = rows if rows is not None else _table_rows()
        self.key_rows = _key_rows(table)
        self.feature_rows = feature_rows if feature_rows is not None else table
        self.prepared_sql: str | None = None
        self.executed: list[str] = []
        self.cursor_calls: list[tuple[str, tuple, int | None]] = []

    async def execute(self, sql: str) -> str:
        self.executed.append(sql)
        return "OK"

    async def prepare(self, sql: str) -> _FakePreparedStatement:
        self.prepared_sql = sql
        return _FakePreparedStatement(sql, self.schema_columns)

    def cursor(self, sql: str, *args: Any, prefetch: int | None = None) -> _FakeCursor:
        self.cursor_calls.append((sql, args, prefetch))
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT fv.symbol, fv.bar_ts FROM"):
            return _FakeCursor(self.key_rows)
        return _FakeCursor(self.feature_rows)

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()


# ----------------------------------------------------------------- select_feature_columns


def test_selects_float_columns_not_in_non_feature_cols() -> None:
    attrs = [("momentum_z_fast", "float4"), ("symbol", "text"), ("bar_ts", "timestamptz")]
    assert fm.select_feature_columns(attrs) == ["momentum_z_fast"]


def test_excludes_module_level_non_feature_cols_by_default() -> None:
    excluded_name = "canary_constant"
    attrs = [("momentum_z_fast", "float4"), (excluded_name, "float4")]
    assert fm.select_feature_columns(attrs) == ["momentum_z_fast"]


def test_extra_exclude_cols_remove_without_touching_module_constant() -> None:
    before = frozenset(fm.NON_FEATURE_COLS)
    attrs = [
        ("momentum_z_fast", "float4"),
        ("ctf_momentum", "float4"),
        ("ctf_vwap_align", "float4"),
        ("ctf_regime_align", "float4"),
    ]
    result = fm.select_feature_columns(
        attrs, extra_exclude_cols=frozenset({"ctf_momentum", "ctf_vwap_align", "ctf_regime_align"})
    )
    assert result == ["momentum_z_fast"]
    assert fm.NON_FEATURE_COLS == before


def test_extra_exclude_cols_default_is_empty() -> None:
    attrs = [("momentum_z_fast", "float4"), ("ctf_momentum", "float4")]
    assert fm.select_feature_columns(attrs) == ["momentum_z_fast", "ctf_momentum"]


def test_preserves_schema_order() -> None:
    attrs = [("z_col", "float4"), ("a_col", "float4"), ("m_col", "float4")]
    assert fm.select_feature_columns(attrs) == ["z_col", "a_col", "m_col"]


def test_force_include_wins_over_exclusions() -> None:
    attrs = [("canary_constant", "float4"), ("ctf_momentum", "float4"), ("keep_me", "float4")]
    result = fm.select_feature_columns(
        attrs,
        extra_exclude_cols=frozenset({"ctf_momentum"}),
        force_include_cols=frozenset({"canary_constant", "ctf_momentum"}),
    )
    assert result == ["canary_constant", "ctf_momentum", "keep_me"]


def test_hmm_duration_is_not_in_non_feature_cols() -> None:
    # A combiner-specific exclusion in the original; here a caller opts out via
    # extra_exclude_cols instead.
    assert "hmm_duration" not in fm.NON_FEATURE_COLS
    attrs = [("hmm_duration", "float8"), ("f_a", "float4")]
    assert fm.select_feature_columns(attrs) == ["hmm_duration", "f_a"]


# -------------------------------------------------------------------- fetch_feature_matrix


def test_fetch_happy_path_all_rows_kept() -> None:
    conn = FakeConnection()
    out = asyncio.run(
        fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=END, cursor_rows=3)
    )
    rows = _table_rows()
    assert out.feature_cols == FEATURE_COLS
    assert out.X.shape == (len(rows), len(FEATURE_COLS))
    assert out.X.dtype == np.float32
    assert out.n_raw == len(rows)
    assert out.n_symbols == 2
    assert out.n_bar_ts == 4
    # meta row-aligned with X: (bar_ts, symbol) order, UTC bar_ts
    assert list(out.meta["symbol"]) == [r[0] for r in rows]
    expected_ts = pd.DatetimeIndex([r[1] for r in rows]).tz_localize("UTC")
    assert list(out.meta["bar_ts"]) == list(expected_ts)
    # f_a values land in the right column, cast to float32
    fa_idx = FEATURE_COLS.index("f_a")
    assert np.array_equal(out.X[:, fa_idx], np.array([r[3] for r in rows], dtype=np.float32))
    # the all-NULL column arrives as NaN, not an error
    fb_idx = FEATURE_COLS.index("f_b")
    assert np.isnan(out.X[:, fb_idx]).all()


def test_fetch_keep_mask_drops_rows() -> None:
    conn = FakeConnection()
    rows = _table_rows()

    def keep(symbols: np.ndarray, bar_ts: np.ndarray) -> np.ndarray:
        # drop the first bar and one mid row
        mask = np.ones(len(symbols), dtype=bool)
        mask[0] = False
        mask[3] = False
        return mask

    out = asyncio.run(
        fm.fetch_feature_matrix(
            conn, "15m", SYMBOLS, start=START, end=END, keep=keep, cursor_rows=3
        )
    )
    survivors = [r for i, r in enumerate(rows) if i not in (0, 3)]
    assert out.X.shape == (len(survivors), len(FEATURE_COLS))
    assert list(out.meta["symbol"]) == [r[0] for r in survivors]
    fa_idx = FEATURE_COLS.index("f_a")
    assert np.array_equal(out.X[:, fa_idx], np.array([r[3] for r in survivors], dtype=np.float32))
    assert out.n_raw == len(rows)


def test_fetch_keep_receives_pass1_key_arrays() -> None:
    conn = FakeConnection()
    seen: dict[str, Any] = {}

    def keep(symbols: np.ndarray, bar_ts: np.ndarray) -> np.ndarray:
        seen["symbols"] = symbols
        seen["bar_ts"] = bar_ts
        return np.ones(len(symbols), dtype=bool)

    asyncio.run(fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=END, keep=keep))
    assert seen["symbols"].dtype == object
    assert list(seen["symbols"]) == [r[0] for r in _table_rows()]
    assert seen["bar_ts"].dtype == np.int64


def test_fetch_rejects_non_boolean_keep_mask() -> None:
    conn = FakeConnection()

    def bad_keep(symbols: np.ndarray, bar_ts: np.ndarray) -> np.ndarray:
        return np.arange(len(symbols))

    with pytest.raises(ValueError, match="keep"):
        asyncio.run(
            fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=END, keep=bad_keep)
        )


def test_fetch_pass2_row_order_divergence_raises() -> None:
    rows = _table_rows()
    swapped = list(rows)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    conn = FakeConnection(feature_rows=swapped)
    with pytest.raises(RuntimeError, match="row order diverged"):
        asyncio.run(fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=END))


def test_fetch_pass2_row_count_mismatch_raises() -> None:
    rows = _table_rows()
    conn = FakeConnection(feature_rows=rows[:-1])
    with pytest.raises(RuntimeError, match="row count"):
        asyncio.run(fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=END))


def test_fetch_sql_shape_and_no_target_join() -> None:
    conn = FakeConnection()
    asyncio.run(fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=END))
    all_sql = " ".join([conn.prepared_sql or ""] + [c[0] for c in conn.cursor_calls])
    assert "fv.bar_ts >= $3" in all_sql
    assert "fv.bar_ts < $4" in all_sql
    assert "symbol = ANY($2)" in all_sql
    assert "forward_returns" not in all_sql
    assert "ORDER BY fv.bar_ts ASC, fv.symbol ASC" in all_sql
    # cursor args: tf, symbols, start, end in that order
    for _sql, args, prefetch in conn.cursor_calls:
        assert args == ("15m", SYMBOLS, START, END)
        assert prefetch == 25_000


def test_fetch_start_and_end_are_required_keyword_arguments() -> None:
    conn = FakeConnection()
    with pytest.raises(TypeError):
        fm.fetch_feature_matrix(conn, "15m", SYMBOLS)  # type: ignore[call-arg]


def test_fetch_rejects_empty_span() -> None:
    conn = FakeConnection()
    with pytest.raises(ValueError, match="end"):
        asyncio.run(fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=START))
    with pytest.raises(ValueError, match="end"):
        asyncio.run(fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=END, end=START))


def test_fetch_work_mem_set_and_skippable() -> None:
    conn = FakeConnection()
    asyncio.run(fm.fetch_feature_matrix(conn, "15m", SYMBOLS, start=START, end=END))
    assert conn.executed == ["SET work_mem = '128MB'"]

    conn_none = FakeConnection()
    asyncio.run(
        fm.fetch_feature_matrix(conn_none, "15m", SYMBOLS, start=START, end=END, work_mem=None)
    )
    assert conn_none.executed == []
    assert "ALTER SYSTEM" not in " ".join(conn_none.executed)
