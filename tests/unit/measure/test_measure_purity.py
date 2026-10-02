"""Source lint: the measure package is pure and decoupled from the old engine (D-17, T-186-10)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "src" / "intelligence" / "measure"
FILES = sorted(PACKAGE.glob("*.py"))
_SQL_WORDS = ("INSERT", "UPDATE", "DELETE", "COPY", "SELECT")
_FORBIDDEN_NAMES = {
    "execute",
    "executemany",
    "ConfigService",
    "get_sync",
    "config_state",
    "prometheus_client",
}
_STRATIFIER_PARAMS = {"regime", "regime_label", "stratifier", "strata"}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_package_files_exist():
    assert {f.name for f in FILES} >= {
        "targets.py",
        "ic.py",
        "proposer.py",
        "term_structure.py",
        "monitoring.py",
        "regime_disclosure.py",
        "params.py",
    }


def test_no_database_write_apr_read_or_metrics():
    for path in FILES:
        tree = ast.parse(path.read_text())
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docs:
                    continue
                upper = node.value.upper()
                assert not any(w in upper.split() for w in _SQL_WORDS), (path.name, node.value)
            names = set()
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.update(node.name.split("."))
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.update(node.module.split("."))
            assert not (names & _FORBIDDEN_NAMES), (path.name, names & _FORBIDDEN_NAMES)


def test_nothing_imports_services_or_asyncpg_writers():
    for path in FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            assert not module.startswith("services"), (path.name, module)


def test_no_generic_regime_stratifier():
    for path in FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                args = node.args
                names = {a.arg for a in args.args + args.kwonlyargs + args.posonlyargs}
                assert not (names & _STRATIFIER_PARAMS), (path.name, node.name)
