"""CI guard: no code path builds a synthetic_fill bar for market_data_ohlcv (plan 185-32).

The store holds real rows only since the 185-25 swap (sources ibkr_named, derived_5m, tradier;
zero synthetic_fill). Migration 444 makes the database refuse a synthetic_fill row; this test
fences the code side, so a new fill path fails CI before it ever reaches the database:

1. normalize_bars, the calendar-grid fill, has no caller outside the allow-list below. Calls are
   found by AST (a call whose function is the name or attribute `normalize_bars`), so comments
   and docstrings that mention it do not count.
2. No module builds a row whose `source` is synthetic_fill (a dict entry `"source": ...`, a
   `source=` keyword, or a `["source"] = ...` assignment) outside the builder allow-list.
3. Every other module that names SOURCE_SYNTHETIC_FILL or the literal 'synthetic_fill' (outside
   docstrings) is on an allow-list with the reason it is a read, a refusal or a comparison.

Every allow-list fails when stale (file gone or reference gone). CI-clean: no DB, no network.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_SEARCH_DIRS = ("services", "scripts", "src")
_SYNTHETIC = "synthetic_fill"
_SYNTHETIC_NAME = "SOURCE_SYNTHETIC_FILL"
_MIGRATION = _REPO_ROOT / "production/migrations/444_market_data_ohlcv_no_synthetic_fill.sql"

# file -> reason. The only production callers of normalize_bars.
_NORMALIZE_CALLERS: dict[str, str] = {
    "scripts/infrastructure/backfill/_history_fetch_item.py": (
        "TEMPORARY (retire: todo 499): phase 189's fetcher item keeps a fill branch behind "
        "`not real_bars_only_for(tf)`, unreachable since plan 185-32 put 4h in the pipeline's "
        "real-bars-only set. The 189 session drops the call, then deletes normalize_bars' fill "
        "path and this entry. The fetcher is stopped and disabled (owner decision), and "
        "migration 444 refuses the row."
    ),
}

# file -> reason. The only modules that build a row with source synthetic_fill.
_SYNTHETIC_BUILDERS: dict[str, str] = {
    "src/core/bar_normalizer.py": (
        "TEMPORARY (retire: todo 499): normalize_bars itself, retired for market_data_ohlcv; deleted "
        "with its last caller. Its output is refused by migration 444."
    ),
}

# file -> reason. Every module that names synthetic_fill, builders included.
_SYNTHETIC_REFERENCES: dict[str, str] = {
    **_SYNTHETIC_BUILDERS,
    "services/intraday_raw_archive.py": (
        "Refusal and read filter: the archive insert raises on a synthetic_fill row and its "
        "copy statement excludes the source (the filter goes with 185-39's archive statements)."
    ),
    "services/bar_reconciliation_audit.py": (
        "Reads and comparisons: D7 counts rows by source and excludes synthetic rows from its "
        "real-row comparisons; nothing is written with the source."
    ),
    "scripts/ops/bars/ops_real_rows_swap.py": (
        "Reads: the 185-25 swap that removed every synthetic row; it copies rows whose source "
        "IS DISTINCT FROM synthetic_fill and counts the rest."
    ),
    "scripts/ops/bars/ops_masked_slot_baseline.py": (
        "Reads: counts synthetic slots for the masked-slot baseline; read-only."
    ),
}


def _python_files() -> list[Path]:
    return sorted(
        path for search_dir in _SEARCH_DIRS for path in (_REPO_ROOT / search_dir).rglob("*.py")
    )


@functools.cache
def _trees() -> dict[str, ast.AST]:
    return {
        str(path.relative_to(_REPO_ROOT)): ast.parse(path.read_text(encoding="utf-8"))
        for path in _python_files()
    }


def _docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                nodes.add(id(body[0].value))
    return nodes


def _is_synthetic_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == _SYNTHETIC
    if isinstance(node, ast.Name):
        return node.id == _SYNTHETIC_NAME
    if isinstance(node, ast.Attribute):
        return node.attr == _SYNTHETIC_NAME
    return False


def _is_source_key(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value == "source"


def normalize_bars_calls(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "normalize_bars") or (
                isinstance(func, ast.Attribute) and func.attr == "normalize_bars"
            ):
                count += 1
    return count


def synthetic_builds(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            count += sum(
                1
                for key, value in zip(node.keys, node.values, strict=True)
                if _is_source_key(key) and _is_synthetic_value(value)
            )
        elif isinstance(node, ast.keyword):
            count += int(node.arg == "source" and _is_synthetic_value(node.value))
        elif isinstance(node, ast.Assign) and _is_synthetic_value(node.value):
            count += sum(
                1
                for target in node.targets
                if isinstance(target, ast.Subscript) and _is_source_key(target.slice)
            )
    return count


def synthetic_references(tree: ast.AST) -> int:
    docstrings = _docstring_nodes(tree)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Name | ast.Attribute) and _is_synthetic_value(node):
            count += 1
        elif isinstance(node, ast.alias) and node.name == _SYNTHETIC_NAME:
            count += 1
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _SYNTHETIC in node.value
            and id(node) not in docstrings
        ):
            count += 1
    return count


def _hits(counter) -> dict[str, int]:
    return {path: n for path, tree in _trees().items() if (n := counter(tree))}


def _assert_matches_allow_list(hits: dict[str, int], allow: dict[str, str], what: str) -> None:
    unlisted = sorted(set(hits) - set(allow))
    assert not unlisted, (
        f"{what} outside the allow-list: {unlisted}. market_data_ohlcv holds real rows only "
        "(plan 185-25, migration 444); store the provider's bars as they arrived."
    )
    stale = sorted(set(allow) - set(hits))
    assert (
        not stale
    ), f"Stale allow-list entries (file gone or reference gone): {stale}. Remove them here."


def test_normalize_bars_has_no_unlisted_caller():
    _assert_matches_allow_list(
        _hits(normalize_bars_calls), _NORMALIZE_CALLERS, "normalize_bars calls"
    )


def test_no_unlisted_module_builds_a_synthetic_fill_row():
    _assert_matches_allow_list(
        _hits(synthetic_builds), _SYNTHETIC_BUILDERS, "synthetic_fill row builds"
    )


def test_every_synthetic_fill_reference_is_a_listed_read_or_refusal():
    _assert_matches_allow_list(
        _hits(synthetic_references), _SYNTHETIC_REFERENCES, "synthetic_fill references"
    )


def test_the_scanners_see_what_they_claim():
    """The detectors themselves: calls, not mentions; every build form; docstrings skipped."""
    tree = ast.parse(
        '"""normalize_bars( in a docstring; synthetic_fill too."""\n'
        "# normalize_bars(bars) in a comment\n"
        "import x\n"
        "from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL\n"
        "a = normalize_bars(bars)\n"
        "b = x.normalize_bars(bars)\n"
        "c = {'source': SOURCE_SYNTHETIC_FILL}\n"
        "d = dict(source='synthetic_fill')\n"
        "row['source'] = x.SOURCE_SYNTHETIC_FILL\n"
        "e = \"SELECT 1 WHERE source <> 'synthetic_fill'\"\n"
    )
    assert normalize_bars_calls(tree) == 2
    assert synthetic_builds(tree) == 3
    # alias + two value references + two string constants (the docstring is skipped)
    assert synthetic_references(tree) == 5


def test_migration_444_refuses_synthetic_fill():
    sql = _MIGRATION.read_text()
    assert "market_data_ohlcv_no_synthetic_fill" in sql
    assert _SYNTHETIC in sql
