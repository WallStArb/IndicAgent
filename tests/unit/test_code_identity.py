"""Import-closure rules of src.core.code_identity: package re-exports, TYPE_CHECKING blocks and the
reviewed I/O-boundary allow-list.

CI-clean: no DB, no network.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from src.core.code_identity import IO_BOUNDARY_MODULES, code_key, import_closure


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "kpkg_ci"
    root.mkdir()
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield root
    for name in [n for n in sys.modules if n.startswith("kpkg_ci")]:
        del sys.modules[name]


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    importlib.invalidate_caches()


def _closure(entry: str = "kpkg_ci.entry", **kwargs) -> tuple[str, ...]:
    return import_closure([entry], packages=("kpkg_ci",), **kwargs)


class TestPackageReexports:
    def _hub(self, tree: Path) -> None:
        _write(
            tree,
            "__init__.py",
            "from kpkg_ci.models import Thing\nfrom kpkg_ci.other import Unused\n",
        )
        _write(tree, "models.py", "class Thing:\n    value = 1\n")
        _write(tree, "other.py", "class Unused:\n    pass\n")

    def test_a_name_re_exported_by_an_init_pulls_in_its_defining_module(self, tree: Path) -> None:
        self._hub(tree)
        _write(tree, "entry.py", "from kpkg_ci import Thing\n\nX = Thing\n")
        mods = _closure()
        assert "kpkg_ci.models" in mods
        assert "kpkg_ci.other" not in mods  # only what is imported by name, not the whole hub

    def test_editing_the_defining_module_moves_the_key(self, tree: Path) -> None:
        self._hub(tree)
        _write(tree, "entry.py", "from kpkg_ci import Thing\n\nX = Thing\n")
        before = code_key(_closure())
        _write(tree, "models.py", "class Thing:\n    value = 2\n")
        assert code_key(_closure()) != before

    def test_a_relative_reexport_and_a_two_hop_chain_are_followed(self, tree: Path) -> None:
        _write(tree, "__init__.py", "from .sub import Deep\n")
        _write(tree, "sub/__init__.py", "from .leaf import Deep\n")
        _write(tree, "sub/leaf.py", "class Deep:\n    pass\n")
        _write(tree, "entry.py", "from kpkg_ci import Deep\n")
        assert "kpkg_ci.sub.leaf" in _closure()

    def test_an_aliased_reexport_is_found_by_the_name_it_is_imported_as(self, tree: Path) -> None:
        _write(tree, "__init__.py", "from kpkg_ci.models import Thing as Renamed\n")
        _write(tree, "models.py", "class Thing:\n    pass\n")
        _write(tree, "entry.py", "from kpkg_ci import Renamed\n")
        assert "kpkg_ci.models" in _closure()

    def test_a_submodule_import_still_works(self, tree: Path) -> None:
        _write(tree, "__init__.py", "")
        _write(tree, "models.py", "A = 1\n")
        _write(tree, "entry.py", "from kpkg_ci import models\n")
        assert "kpkg_ci.models" in _closure()


class TestTypeCheckingImports:
    def test_imports_under_type_checking_are_not_followed_but_the_else_branch_is(
        self, tree: Path
    ) -> None:
        _write(tree, "__init__.py", "")
        _write(tree, "typed.py", "class T:\n    pass\n")
        _write(tree, "fallback.py", "F = 1\n")
        _write(tree, "runtime.py", "R = 1\n")
        _write(
            tree,
            "entry.py",
            "from typing import TYPE_CHECKING\nimport typing\n\n"
            "if TYPE_CHECKING:\n    from kpkg_ci.typed import T\n"
            "else:\n    from kpkg_ci.fallback import F\n"
            "if typing.TYPE_CHECKING:\n    import kpkg_ci.typed\n"
            "from kpkg_ci import runtime\n",
        )
        mods = _closure()
        assert "kpkg_ci.typed" not in mods
        assert {"kpkg_ci.fallback", "kpkg_ci.runtime"} <= set(mods)


class TestIoBoundaryAllowList:
    def test_the_allow_list_is_exactly_the_reviewed_set_with_a_reason_each(self) -> None:
        assert set(IO_BOUNDARY_MODULES) == {
            "src.core.database_manager",
            "src.observability.metrics",
        }
        assert all(len(reason) > 20 for reason in IO_BOUNDARY_MODULES.values())

    def test_an_exempt_module_registers_by_name_but_its_source_and_imports_do_not_count(
        self, tree: Path
    ) -> None:
        _write(tree, "__init__.py", "")
        _write(tree, "db.py", "from kpkg_ci import deep\nPOOL = 1\n")
        _write(tree, "deep.py", "D = 1\n")
        _write(tree, "entry.py", "from kpkg_ci import db\n")
        boundary = {"kpkg_ci.db": "a connection pool, reviewed"}
        mods = _closure(io_boundary=boundary)
        assert "kpkg_ci.db" in mods and "kpkg_ci.deep" not in mods
        before = code_key(mods, io_boundary=boundary)
        _write(tree, "db.py", "from kpkg_ci import deep\nPOOL = 2\n")
        assert code_key(mods, io_boundary=boundary) == before  # its source is not hashed
        assert code_key(mods, io_boundary={}) != before  # but it is for a non-exempt module
        # dropping the import of the exempt module from the entry still moves the key
        _write(tree, "entry.py", "X = 1\n")
        assert code_key(_closure(io_boundary=boundary), io_boundary=boundary) != before

    def test_the_real_closure_keeps_the_exempt_modules_by_name_and_drops_their_imports(
        self,
    ) -> None:
        mods = import_closure(["src.intelligence.research.snapshot"])
        assert "src.core.database_manager" in mods
        assert "src.core.tier_aliases" not in mods  # only reached through metrics
