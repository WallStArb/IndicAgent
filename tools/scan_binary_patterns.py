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
import io
import json
import re
import sys
import tokenize
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

# Allowlist patterns that should NOT be flagged as violations.
# These are legitimate binary usages: direction encoders, detection event flags,
# categorical fields, eligibility gates, guard checks, and docstrings.
ALLOWLIST_PATTERNS: list[re.Pattern[str]] = [
    # --- Direction encoders / sign ---
    re.compile(r"direction", re.IGNORECASE),
    re.compile(r"_dir\b"),
    re.compile(r"_sign\b"),
    re.compile(r"\bsign\s*="),  # direction sign variable assignment
    re.compile(r"signal_type"),
    re.compile(r"obv_slope_sign"),  # direction encoder {-1, 0, 1}
    re.compile(r"cross(ed)?_(up|down)"),  # crossover direction vars
    # --- Crossover/detection events ---
    re.compile(r"\bcross(ed)?\b", re.IGNORECASE),
    re.compile(r"threshold_cross"),  # tested utility function
    re.compile(r"crossover_detect"),  # tested utility function
    # --- Day-of-week / calendar ---
    re.compile(r"is_monday|is_friday|is_\w+day\b"),
    re.compile(r"opex_flag"),  # calendar event flag (options expiration Friday), not a score
    # --- Type/category categorical fields ---
    re.compile(r"fvg_type|sweep_type|swing_high_type|swing_low_type"),
    re.compile(r"ob_type"),  # order block type {-1, 0, 1} categorical
    re.compile(r"high_type|low_type|pattern"),  # swing detector categorical
    re.compile(r"\bhh\b.*==.*\bhl\b"),  # swing structure classification (higher-high/higher-low)
    re.compile(r"price_bounce"),  # bounce event detection flag
    # --- Explicit exemption ---
    re.compile(r"# gradient-exempt"),
    re.compile(r"== 0\.0.*#.*gradient-exempt"),
    # --- Event flags (not scores) ---
    re.compile(r"\bbullish\s*="),  # event flag, not a score
    re.compile(r"\bbearish\s*="),  # event flag, not a score
    re.compile(r"track_bars_ago"),  # counter, not a score
    re.compile(r"inside_bar\b"),  # binary detection event
    re.compile(r"outside_bar\b"),  # binary detection event
    re.compile(r"pin_bar"),  # binary detection event
    re.compile(r"in_discount"),  # zone membership flag
    re.compile(r"in_lvn"),  # low-volume node flag
    re.compile(r"price_in_va|price_above_va|price_below_va"),  # VA position flags
    re.compile(r"price_in_premium"),  # premium/discount zone flag
    re.compile(r"macd_hist_positive|macd_hist_turning"),  # histogram state flags
    re.compile(r"neg_support"),  # support test result flag
    re.compile(r"in_extreme"),  # RSI zone counter flag
    re.compile(r"above_mid|below_mid"),  # BB position flags (internal counters)
    re.compile(r"fired"),  # squeeze fire event
    re.compile(r"squeeze_active"),  # squeeze state flag
    re.compile(r"active\s*="),  # active flag (measured_move)
    re.compile(r"fvg_active"),  # FVG presence flag (cis_scorer)
    re.compile(r"promotion_ready"),  # promotion gate flag (weight_updater)
    re.compile(r"turning_up"),  # MACD turning event
    # --- Eligibility gate checks (if detection == 1.0) ---
    re.compile(r"bos_detected|choch_detected|choch\b"),  # detection gates
    re.compile(r"sweep_detected|sweep_recl"),  # sweep detection gates
    re.compile(r"sweep_reclaimed"),  # reclaim detection gate
    re.compile(r"in_demand\b|in_supply\b"),  # zone membership gates
    re.compile(r"mitigated"),  # mitigation status gate
    re.compile(r"price_in_va"),  # VA position gate (trade_framer)
    re.compile(r"hmm_regime"),  # regime routing (not scoring)
    re.compile(r"is_ranging"),  # regime context label
    re.compile(r"regime_ctx"),  # regime context label assignment
    # --- Guard / zero-checks ---
    re.compile(r"total_weight\s*==\s*0"),  # guard against division by zero
    re.compile(r"== 0\.0:\s*$"),  # guard check (if x == 0.0: return/guard)
    re.compile(r"assert"),  # assertion, not scoring
    re.compile(r"ofi_ewma\s*==\s*0"),  # guard check
    re.compile(r"cvd_div\s*==\s*0"),  # guard check
    # --- Docstring patterns ---
    re.compile(r"Gate:"),  # docstring: gate description
    re.compile(r"Gates on"),  # docstring: gate description
    re.compile(r"Direction:"),  # docstring: direction description
    re.compile(r"Confidence:"),  # docstring: confidence description
    re.compile(r"High conviction"),  # docstring: description
    re.compile(r"-\s+in_lvn"),  # docstring: parameter description
    # --- Counting / aggregation (int() for counting, not scoring) ---
    re.compile(r"int\(\(.*\)\.sum\(\)"),  # numpy count (not score)
    re.compile(r"int\(np\.sum"),  # numpy count (not score)
    re.compile(r"wins\s*="),  # win counting (not score)
    re.compile(r"agreeing"),  # bucket count (not score)
    re.compile(r"int\(np\."),  # numpy count (not score)
]


def _project_root() -> Path:
    """Find project root by walking up from this script's location."""
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents):
        if (parent / "src" / "intelligence").is_dir():
            return parent
    print("ERROR: Cannot find project root (src/intelligence/ not found)", file=sys.stderr)
    sys.exit(2)


def _string_token_lines(text: str) -> set[int]:
    """Return every line number (1-indexed) that falls inside a STRING token.

    A prior line-local heuristic (checking whether a line itself contains a
    triple-quote delimiter) only caught the first/last line of a docstring,
    not its body, letting prose lines inside a multi-line docstring (e.g. one
    describing a return-value invariant in the "sum equals one" sense) get
    scanned as if they were code. tokenize walks real Python string literals
    regardless of how many lines they span, so this is correct instead of
    line-local.

    Falls back to an empty set (scan every line) if the file doesn't
    tokenize, e.g. a syntax error, so a bad file degrades to the old
    behavior rather than crashing the whole scan.
    """
    try:
        tokens = tokenize.tokenize(io.BytesIO(text.encode("utf-8")).readline)
        string_lines: set[int] = set()
        for tok in tokens:
            if tok.type == tokenize.STRING:
                string_lines.update(range(tok.start[0], tok.end[0] + 1))
        return string_lines
    except (tokenize.TokenizeError, SyntaxError, IndentationError):
        return set()


def _is_allowed(line: str) -> bool:
    """Check if a line matches any allowlist pattern (legitimate binary usage)."""
    stripped = line.strip()
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
    string_lines = _string_token_lines(text)
    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            continue

        # Skip lines that are entirely inside a string literal (docstrings,
        # multi-line SQL, etc.), not executable code, so not a real scoring
        # pattern regardless of what substrings they contain.
        if (line_idx + 1) in string_lines:
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
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output violations as JSON (machine-readable for CI)",
    )
    args = parser.parse_args()

    root = _project_root()
    violations = scan_all(root)

    # Output results
    if args.json_output:
        json_violations = [
            {"file": v["file"], "line": v["line"], "pattern": v["pattern"]} for v in violations
        ]
        print(json.dumps(json_violations, indent=2))
    elif args.verbose:
        for v in violations:
            print(f"\n{v['file']}:{v['line']} [{v['pattern']}]")
            print(f"  {v['matched']}")
            for ctx_line in v["context"]:
                print(f"    {ctx_line}")
    else:
        for v in violations:
            print(f"{v['file']}:{v['line']} [{v['pattern']}] {v['matched']}")

    if not args.json_output:
        print(f"\nTotal violations: {len(violations)}")

    # Save baseline if requested
    if args.baseline:
        baseline_path = root / "tools" / ".binary_baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_data = {
            "count": len(violations),
            "files_affected": len({v["file"] for v in violations}),
            "violations": [
                {"file": v["file"], "line": v["line"], "pattern": v["pattern"]} for v in violations
            ],
        }
        baseline_path.write_text(json.dumps(baseline_data, indent=2) + "\n")
        print(f"Baseline saved to {baseline_path}")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
