"""Regression test: no plugin source file may access frames["features"] as actual code.

Walks all .py files under src/intelligence/ (composites, confluence, context,
features/*, trading, indicators, pipeline) and asserts that NONE contains the
frames["features"] flat-dict access pattern as executable code (not in comments
or docstrings).

This test is the boundary proof that the Phase 112 Wave 4 (task 4-1B) migration
from flat frames["features"] to typed tier access is complete.

Allowlist: intentionally empty. Any file failing this test must either be
migrated or documented as INVESTIGATION NEEDED with a TODO comment.
"""

from __future__ import annotations

import ast
import pathlib


def _has_frames_features_code(source: str) -> bool:
    """Return True if the source contains frames["features"] or frames.get("features")
    as actual code (AST-level), not in comments or docstrings."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        # frames["features"]  or  frames['features']
        if isinstance(node, ast.Subscript):
            val = node.value
            slice_ = node.slice
            if (
                isinstance(val, ast.Name)
                and val.id == "frames"
                and isinstance(slice_, ast.Constant)
                and slice_.value == "features"
            ):
                return True

        # frames.get("features", ...)
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Name)
                and func.value.id == "frames"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "features"
            ):
                return True

    return False


def test_no_legacy_features_access() -> None:
    """Assert no plugin under src/intelligence/ reads frames["features"] as code."""
    root = pathlib.Path("src/intelligence")
    assert root.exists(), "src/intelligence not found from cwd; run from project root"

    offenders: list[str] = []
    for py_file in sorted(root.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        if _has_frames_features_code(source):
            offenders.append(str(py_file))

    assert offenders == [], (
        f"The following {len(offenders)} file(s) still read frames['features'] as code "
        f"(Phase 112 migration incomplete):\n"
        + "\n".join(f"  {f}" for f in offenders)
        + "\n\nMigrate each file to typed tier access per "
        "112-PLUGIN-FIELD-MAP.md or add a TODO comment if the field is "
        "INVESTIGATION NEEDED."
    )
