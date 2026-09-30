"""Unit tests of the provenance identity helpers in services._batch_utils (phase 186 plan 14).

kernel_code_key hashes only the named modules (D-23); bar_content_digests composes the
bar_content_digest_current month digests per symbol (D-23 revision detection).

CI-clean: no DB, no network.
"""

from __future__ import annotations

import importlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from services._batch_utils import bar_content_digests, kernel_code_key

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture
def pkg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "kpkg_identity"
    root.mkdir()
    (root / "__init__.py").write_text("")
    (root / "a.py").write_text(
        '"""doc a"""\nLIMIT = 5\n\n\ndef f(x):\n    """f doc"""\n    return x + LIMIT  # note\n'
    )
    (root / "b.py").write_text("VALUE = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield root
    for name in [n for n in sys.modules if n.startswith("kpkg_identity")]:
        del sys.modules[name]


def _rewrite(path: Path, text: str) -> None:
    path.write_text(text)
    importlib.invalidate_caches()


class TestKernelCodeKey:
    def test_returns_64_hex_order_and_duplicates_ignored(self, pkg: Path) -> None:
        one = kernel_code_key(["kpkg_identity.a", "kpkg_identity.b"])
        assert _HEX64.fullmatch(one)
        assert kernel_code_key(["kpkg_identity.b", "kpkg_identity.a"]) == one
        assert kernel_code_key(["kpkg_identity.a", "kpkg_identity.b", "kpkg_identity.a"]) == one

    def test_comment_and_docstring_edits_do_not_move_the_key(self, pkg: Path) -> None:
        before = kernel_code_key(["kpkg_identity.a"])
        _rewrite(
            pkg / "a.py",
            '"""another doc"""\nLIMIT = 5\n\n\ndef f(x):\n    """new f doc"""\n    # new comment\n    return x + LIMIT\n',
        )
        assert kernel_code_key(["kpkg_identity.a"]) == before

    def test_constant_or_expression_edit_moves_the_key(self, pkg: Path) -> None:
        before = kernel_code_key(["kpkg_identity.a"])
        _rewrite(pkg / "a.py", '"""doc a"""\nLIMIT = 6\n\n\ndef f(x):\n    return x + LIMIT\n')
        assert kernel_code_key(["kpkg_identity.a"]) != before

    def test_unrelated_module_edit_leaves_the_key(self, pkg: Path) -> None:
        before = kernel_code_key(["kpkg_identity.a"])
        _rewrite(pkg / "b.py", "VALUE = 2\n")
        assert kernel_code_key(["kpkg_identity.a"]) == before

    def test_empty_list_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            kernel_code_key([])

    def test_unimportable_module_raises_not_skipped(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            kernel_code_key(["kpkg_identity_missing.nope"])

    def test_never_walks_sys_modules(self) -> None:
        import inspect

        source = inspect.getsource(kernel_code_key)
        assert "sys.modules" not in source


class _Cursor:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: tuple) -> None:
        self.conn.statements.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return self.conn.rows


class _Conn:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, tuple]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)


_START = datetime(2026, 1, 1, tzinfo=UTC)
_END = datetime(2026, 4, 1, tzinfo=UTC)  # exclusive: Jan, Feb, Mar
_JAN, _FEB, _MAR = (datetime(2026, m, 1, tzinfo=UTC) for m in (1, 2, 3))


class TestBarContentDigests:
    def test_one_statement_against_the_current_view_only(self) -> None:
        conn = _Conn([("SPY", _JAN, "d1")])
        bar_content_digests(conn, "1d", ["SPY"], _START, _END)
        assert len(conn.statements) == 1
        sql, params = conn.statements[0]
        assert "bar_content_digest_current" in sql
        assert "market_data_ohlcv" not in sql
        assert "timeframe" in sql and "ANY" in sql
        assert params[0] == "1d"

    def test_composed_per_symbol_hex_and_absent_symbol(self) -> None:
        conn = _Conn([("SPY", _JAN, "d1"), ("SPY", _FEB, "d2"), ("SPY", _MAR, "d3")])
        out = bar_content_digests(conn, "1d", ["SPY", "QQQ"], _START, _END)
        assert _HEX64.fullmatch(out["SPY"])
        assert out["QQQ"] == "absent"

    def test_one_month_changing_moves_only_that_symbol(self) -> None:
        base = [
            ("SPY", _JAN, "a"),
            ("SPY", _FEB, "b"),
            ("SPY", _MAR, "c"),
            ("QQQ", _JAN, "a"),
            ("QQQ", _FEB, "b"),
            ("QQQ", _MAR, "c"),
        ]
        changed = [r if r[:2] != ("SPY", _FEB) else ("SPY", _FEB, "B") for r in base]
        one = bar_content_digests(_Conn(base), "1d", ["SPY", "QQQ"], _START, _END)
        two = bar_content_digests(_Conn(changed), "1d", ["SPY", "QQQ"], _START, _END)
        assert one["SPY"] != two["SPY"]
        assert one["QQQ"] == two["QQQ"]

    def test_month_hole_is_the_empty_sentinel_and_filling_it_flips_the_digest(self) -> None:
        holey = [("SPY", _JAN, "a"), ("SPY", _MAR, "c")]
        filled = holey + [("SPY", _FEB, "b")]
        one = bar_content_digests(_Conn(holey), "1d", ["SPY"], _START, _END)
        two = bar_content_digests(_Conn(filled), "1d", ["SPY"], _START, _END)
        assert one["SPY"] != two["SPY"]
        assert one["SPY"] != "absent"

    def test_row_order_of_the_fetch_does_not_matter(self) -> None:
        rows = [("SPY", _JAN, "a"), ("SPY", _FEB, "b")]
        one = bar_content_digests(_Conn(rows), "1d", ["SPY"], _START, _END)
        two = bar_content_digests(_Conn(rows[::-1]), "1d", ["SPY"], _START, _END)
        assert one == two

    def test_naive_datetime_and_empty_range_raise(self) -> None:
        with pytest.raises(ValueError):
            bar_content_digests(_Conn([]), "1d", ["SPY"], datetime(2026, 1, 1), _END)
        with pytest.raises(ValueError):
            bar_content_digests(_Conn([]), "1d", ["SPY"], _END, _START)
