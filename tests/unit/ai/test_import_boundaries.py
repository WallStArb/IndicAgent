"""Import boundary enforcement for AI layer.

D-36: src/core/ai/ and src/intelligence/ai/ must NOT import from:
- src.intelligence.pipeline
- src.intelligence.plugins
- Any tier plugin implementation

Only permitted imports:
- src.intelligence.schemas.py
- src.core.stream_keys.py
- Standard library
- Third-party packages

Uses AST-based checking (not grep) per Gemini review recommendation.
"""
import ast
from pathlib import Path

# Directories to check
_CHECK_DIRS = [
    Path("src/core/ai"),
    Path("src/intelligence/ai"),
]

# Forbidden import prefixes
_FORBIDDEN_PREFIXES = (
    "src.intelligence.pipeline",
    "src.intelligence.plugins",
    "src.intelligence.trading",  # I7 plugin implementations
    "src.intelligence.patterns",  # I5 plugin implementations
    "src.intelligence.context",  # I4 plugin implementations
    "src.intelligence.composites",  # I2 plugin implementations
    "src.intelligence.structure",  # I3 plugin implementations
)


def _collect_imports(filepath: Path) -> list[str]:
    """Parse a Python file with AST and extract all import targets."""
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError:
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _find_python_files(directory: Path) -> list[Path]:
    """Find all .py files in directory tree."""
    if not directory.exists():
        return []
    return list(directory.rglob("*.py"))


class TestImportBoundaries:
    def test_no_forbidden_imports_in_core_ai(self):
        """src/core/ai/ must not import from pipeline or tier plugins."""
        violations = []
        for filepath in _find_python_files(Path("src/core/ai")):
            for imp in _collect_imports(filepath):
                for forbidden in _FORBIDDEN_PREFIXES:
                    if imp.startswith(forbidden):
                        violations.append((str(filepath), imp, forbidden))
        assert violations == [], (
            "Forbidden imports found in src/core/ai/:\n"
            + "\n".join(f"  {f}: {i} (forbidden: {p})" for f, i, p in violations)
        )

    def test_no_forbidden_imports_in_intelligence_ai(self):
        """src/intelligence/ai/ must not import from pipeline or tier plugins."""
        violations = []
        for filepath in _find_python_files(Path("src/intelligence/ai")):
            for imp in _collect_imports(filepath):
                for forbidden in _FORBIDDEN_PREFIXES:
                    if imp.startswith(forbidden):
                        violations.append((str(filepath), imp, forbidden))
        assert violations == [], (
            "Forbidden imports found in src/intelligence/ai/:\n"
            + "\n".join(f"  {f}: {i} (forbidden: {p})" for f, i, p in violations)
        )

    def test_shadow_only_true_on_all_agents(self):
        """D-37, D-48: All BaseAIAgent subclasses must have shadow_only=True."""
        import re
        violations = []
        for check_dir in [Path("src/intelligence/ai"), Path("src/core/ai")]:
            for filepath in _find_python_files(check_dir):
                content = filepath.read_text()
                # Check for explicit shadow_only = False
                if re.search(r"shadow_only\s*=\s*False", content):
                    violations.append(str(filepath))
        assert violations == [], (
            "shadow_only = False found (D-37 violation):\n"
            + "\n".join(f"  {v}" for v in violations)
        )
