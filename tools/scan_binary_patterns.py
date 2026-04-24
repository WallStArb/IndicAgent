#!/usr/bin/env python3
"""Binary pattern scanner for plugin source files.

Scans all Python files under src/intelligence/ for binary scoring patterns
that should be replaced with continuous gradient functions. Outputs a JSON
list of violations with file, line number, matched pattern, and context.

Exit code 0 if zero violations found, 1 if any found.

Usage:
    python tools/scan_binary_patterns.py
    python tools/scan_binary_patterns.py --verbose
    python tools/scan_binary_patterns.py --baseline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --- Configuration ---

# Directories to scan (relative to project root)
SCAN_DIRS = [
    "src/intelligence/features",
    "src/intelligence/composites",
    "src/intelligence/context",
    "src/intelligence/trading",
    "src/intelligence/confluence",
    "src/intelligence",
]

# Regex patterns to detect binary scoring
BINARY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "binary_assignment_1_if_else_0",
        re.compile(r"=\s*1\.?\d*\s+if\s+.+\s+else\s+0\.?\d*"),
    ),
    (
        "binary_assignment_0_if_else_1",
        re.compile(r"=\s*0\.?\d*\s+if\s+.+\s+else\s+1\.?\d*"),
    ),
    (
        "numpy_where_binary",
        re.compile(r"np\.where\(.+,\s*1\.?\d*,\s*0\.?\d*\)"),
    ),
    (
        "numpy_where_binary_inverted",
        re.compile(r"np\.where\(.+,\s*0\.?\d*,\s*1\.?\d*\)"),
    ),
    (
        "int_condition_as_score",
        re.compile(r"=\s*int\([^)]*(?:>|<|==|!=|>=|<=)[^)]*\)"),
    ),
    (
        "equality_check_continuous_1",
        re.compile(r"==\s*1\.0(?!\d)"),
    ),
    (
        "equality_check_continuous_0",
        re.compile(r"==\s*0\.0(?!\d)"),
    ),
]

# Allowlist patterns that should NOT be flagged as violations
ALLOWLIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"direction", re.IGNORECASE),
    re.compile(r"_dir\b"),
    re.compile(r"_sign\b"),
    re.compile(r"signal_type"),
    re.compile(r"\bcross(ed)?\b", re.IGNORECASE),
    re.compile(r"is_monday|is_friday|is_\w+day\b"),
    re.compile(r"fvg_type|sweep_type|swing_high_type|swing_low_type"),
    re.compile(r"# gradient-exempt"),
    re.compile(r"threshold_cross"),  # tested utility function
    re.compile(r"crossover_detect"),  # tested utility function
    re.compile(r"\bbullish\s*="),  # event flag, not a score
    re.compile(r"\bbearish\s*="),  # event flag, not a score
    re.compile(r"track_bars_ago"),  # counter, not a score
    re.compile(r"== 0\.0.*#.*gradient-exempt"),
]


def _project_root() -> Path:
    """Find project root by walking up from this script's location."""
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents):
        if (parent / "src" / "intelligence").is_dir():
            return parent
    print("ERROR: Cannot find project root (src/intelligence/ not found)", file=sys.stderr)
    sys.exit(2)


def _is_allowed(line: str) -> bool:
    """Check if a line matches any allowlist pattern (legitimate binary usage)."""
    # Skip lines inside docstrings (triple-quoted strings used as documentation)
    stripped = line.strip()
    if stripped.startswith(('"""', "'''")) or '"""' in stripped or "'''" in stripped:
        return True
    # Skip lines that are documentation examples of patterns to replace.
    # These appear as prose or backtick-wrapped code in docstrings.
    if stripped.startswith(("Replaces patterns", "Replace patterns")):
        return True
    if stripped.startswith("``") and "``" in stripped[2:]:
        return True
    return any(pat.search(line) for pat in ALLOWLIST_PATTERNS)


def _get_context(lines: list[str], idx: int, radius: int = 2) -> list[str]:
    """Extract surrounding lines for context."""
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    return [f"L{i + 1}: {lines[i].rstrip()}" for i in range(start, end)]


def scan_file(filepath: Path) -> list[dict]:
    """Scan a single Python file for binary pattern violations."""
    violations = []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return violations

    lines = text.splitlines()
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue

        # Check allowlist first
        if _is_allowed(stripped):
            continue

        for pattern_name, pattern in BINARY_PATTERNS:
            if pattern.search(stripped):
                violations.append(
                    {
                        "file": str(filepath),
                        "line": line_idx + 1,
                        "pattern": pattern_name,
                        "matched": stripped,
                        "context": _get_context(lines, line_idx),
                    }
                )
                break  # One violation per line (first match wins)

    return violations


def scan_all(root: Path) -> list[dict]:
    """Scan all configured directories for binary pattern violations."""
    all_violations: list[dict] = []
    seen_files: set[Path] = set()

    for scan_dir in SCAN_DIRS:
        dir_path = root / scan_dir
        if not dir_path.is_dir():
            continue
        for py_file in sorted(dir_path.rglob("*.py")):
            if py_file in seen_files:
                continue
            seen_files.add(py_file)
            all_violations.extend(scan_file(py_file))

    return all_violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan plugin source files for binary scoring patterns"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full context for each violation",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Save current violation count to tools/.binary_baseline.json",
    )
    args = parser.parse_args()

    root = _project_root()
    violations = scan_all(root)

    # Output results
    if args.verbose:
        for v in violations:
            print(f"\n{v['file']}:{v['line']} [{v['pattern']}]")
            print(f"  {v['matched']}")
            for ctx_line in v["context"]:
                print(f"    {ctx_line}")
    else:
        for v in violations:
            print(f"{v['file']}:{v['line']} [{v['pattern']}] {v['matched']}")

    print(f"\nTotal violations: {len(violations)}")

    # Save baseline if requested
    if args.baseline:
        baseline_path = root / "tools" / ".binary_baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_data = {
            "count": len(violations),
            "files_affected": len({v["file"] for v in violations}),
            "violations": [
                {"file": v["file"], "line": v["line"], "pattern": v["pattern"]}
                for v in violations
            ],
        }
        baseline_path.write_text(json.dumps(baseline_data, indent=2) + "\n")
        print(f"Baseline saved to {baseline_path}")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
