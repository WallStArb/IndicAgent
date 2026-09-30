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

import pytest

from services._batch_utils import bar_content_digests, kernel_code_key, kernel_code_modules
from tests.unit._responder_fakes import FakeConn, rows_responder


def _conn(rows: list[tuple]) -> FakeConn:
    return FakeConn(rows_responder(rows))


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


_START = datetime(2026, 1, 1, tzinfo=UTC)
_END = datetime(2026, 4, 1, tzinfo=UTC)  # exclusive: Jan, Feb, Mar
_JAN, _FEB, _MAR = (datetime(2026, m, 1, tzinfo=UTC) for m in (1, 2, 3))


class TestBarContentDigests:
    def test_one_statement_against_the_current_view_only(self) -> None:
        conn = _conn([("SPY", _JAN, "d1")])
        bar_content_digests(conn, "1d", ["SPY"], _START, _END)
        assert len(conn.statements) == 1
        sql, params = conn.statements[0]
        assert "bar_content_digest_current" in sql
        assert "market_data_ohlcv" not in sql
        assert "timeframe" in sql and "ANY" in sql
        assert params[0] == "1d"

    def test_composed_per_symbol_hex_and_absent_symbol(self) -> None:
        conn = _conn([("SPY", _JAN, "d1"), ("SPY", _FEB, "d2"), ("SPY", _MAR, "d3")])
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
        one = bar_content_digests(_conn(base), "1d", ["SPY", "QQQ"], _START, _END)
        two = bar_content_digests(_conn(changed), "1d", ["SPY", "QQQ"], _START, _END)
        assert one["SPY"] != two["SPY"]
        assert one["QQQ"] == two["QQQ"]

    def test_month_hole_is_the_empty_sentinel_and_filling_it_flips_the_digest(self) -> None:
        holey = [("SPY", _JAN, "a"), ("SPY", _MAR, "c")]
        filled = holey + [("SPY", _FEB, "b")]
        one = bar_content_digests(_conn(holey), "1d", ["SPY"], _START, _END)
        two = bar_content_digests(_conn(filled), "1d", ["SPY"], _START, _END)
        assert one["SPY"] != two["SPY"]
        assert one["SPY"] != "absent"

    def test_row_order_of_the_fetch_does_not_matter(self) -> None:
        rows = [("SPY", _JAN, "a"), ("SPY", _FEB, "b")]
        one = bar_content_digests(_conn(rows), "1d", ["SPY"], _START, _END)
        two = bar_content_digests(_conn(rows[::-1]), "1d", ["SPY"], _START, _END)
        assert one == two

    def test_naive_datetime_and_empty_range_raise(self) -> None:
        with pytest.raises(ValueError):
            bar_content_digests(_conn([]), "1d", ["SPY"], datetime(2026, 1, 1), _END)
        with pytest.raises(ValueError):
            bar_content_digests(_conn([]), "1d", ["SPY"], _END, _START)


class TestImportClosure:
    """kernel_code_key walks the first-party import closure of its entry modules."""

    @pytest.fixture
    def tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        root = tmp_path / "kpkg_closure"
        (root / "sub").mkdir(parents=True)
        (root / "__init__.py").write_text("from kpkg_closure import hub_target\n")
        (root / "sub" / "__init__.py").write_text("")
        (root / "entry.py").write_text(
            "import os\nimport numpy\nfrom kpkg_closure import direct\n"
            "from kpkg_closure.sub import leaf\nfrom . import sibling\n\n\n"
            "def lazy():\n    import kpkg_closure.in_function\n    return kpkg_closure.in_function\n"
        )
        for name in ("direct", "sibling", "in_function", "hub_target", "outside"):
            (root / f"{name}.py").write_text(f"NAME = {name!r}\n")
        (root / "direct.py").write_text("from kpkg_closure.chain import deep\nNAME = 'direct'\n")
        (root / "chain.py").write_text("")
        (root / "chain").mkdir()
        (root / "chain" / "__init__.py").write_text("")
        (root / "chain" / "deep.py").write_text("VALUE = 1\n")
        (root / "chain.py").unlink()
        (root / "sub" / "leaf.py").write_text("VALUE = 2\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        yield root
        for name in [n for n in sys.modules if n.startswith("kpkg_closure")]:
            del sys.modules[name]

    def test_closure_follows_imports_in_functions_and_relative_imports_and_skips_others(
        self, tree: Path
    ) -> None:
        mods = kernel_code_modules(["kpkg_closure.entry"], packages=("kpkg_closure",))
        assert set(mods) == {
            "kpkg_closure",  # the package __init__ runs on import
            "kpkg_closure.entry",
            "kpkg_closure.direct",
            "kpkg_closure.sibling",
            "kpkg_closure.in_function",
            "kpkg_closure.chain",
            "kpkg_closure.chain.deep",
            "kpkg_closure.sub",
            "kpkg_closure.sub.leaf",
        }
        assert "kpkg_closure.outside" not in mods
        assert "kpkg_closure.hub_target" not in mods  # an __init__'s own imports are not followed

    def test_editing_a_module_on_the_closure_moves_the_key_and_one_outside_does_not(
        self, tree: Path
    ) -> None:
        packages = ("kpkg_closure",)
        before = kernel_code_key(["kpkg_closure.entry"], packages=packages)
        _rewrite(tree / "outside.py", "NAME = 'changed'\n")
        _rewrite(tree / "hub_target.py", "NAME = 'changed'\n")
        assert kernel_code_key(["kpkg_closure.entry"], packages=packages) == before
        _rewrite(tree / "chain" / "deep.py", "VALUE = 99\n")
        moved = kernel_code_key(["kpkg_closure.entry"], packages=packages)
        assert moved != before
        _rewrite(tree / "in_function.py", "NAME = 'changed'\n")
        assert kernel_code_key(["kpkg_closure.entry"], packages=packages) != moved

    def test_own_modules_are_hashed_without_following_their_imports(self, tree: Path) -> None:
        mods = kernel_code_modules(
            ["kpkg_closure.sub.leaf"], own=["kpkg_closure.entry"], packages=("kpkg_closure",)
        )
        assert "kpkg_closure.entry" in mods
        assert "kpkg_closure.direct" not in mods

    def test_an_import_of_a_missing_first_party_module_raises(self, tree: Path) -> None:
        (tree / "broken.py").write_text("import kpkg_closure.gone\n")
        with pytest.raises(ModuleNotFoundError, match="gone"):
            kernel_code_modules(["kpkg_closure.broken"], packages=("kpkg_closure",))

    def test_normalizer_matches_ic_engine_copy(self) -> None:
        """services/ic_engine.py keeps a verbatim copy until 186-23 deletes it; the two must
        agree or the two engines' keys are not comparable. Delete with ic_engine."""
        ic_engine = pytest.importorskip("services.ic_engine")
        from src.core.code_identity import normalized_source_for_hash

        for path in (Path(__file__), Path(ic_engine.__file__).with_name("_batch_utils.py")):
            source = path.read_bytes()
            assert normalized_source_for_hash(source) == ic_engine._normalized_source_for_hash(
                source
            )
