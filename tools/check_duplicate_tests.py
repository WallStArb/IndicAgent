#!/usr/bin/env python3
"""CI guard: fail if any test function name appears in more than one file within the same directory.

Cross-directory duplicates are intentional — plugin/service test files in different subdirectories
legitimately share test function names (e.g. test_compute_next_delegates). Only within-directory
duplicates indicate copy-paste drift or an incomplete consolidation.

Also flags true intra-file shadows: bare `def test_x` defined twice at module level in the same
file (the second definition silently overrides the first in Python).

Usage:
    python tools/check_duplicate_tests.py

Exit 0 if clean, exit 1 with a report if duplicates found.
"""

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEST_DIR = ROOT / "tests" / "unit"
ALLOWLIST_FILE = Path(__file__).parent / "duplicate_test_allowlist.txt"


def load_allowlist() -> set[tuple[str, str]]:
    """Return set of (directory_prefix, test_name) pairs that are exempt."""
    if not ALLOWLIST_FILE.exists():
        return set()
    allowed: set[tuple[str, str]] = set()
    for line in ALLOWLIST_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            allowed.add((parts[0], parts[1]))
    return allowed


def collect() -> tuple[
    dict[str, dict[str, list[str]]],  # dir -> name -> distinct files
    dict[str, list[int]],              # "rel:name" -> line numbers (intra-file shadows)
]:
    dir_name_files: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    intra_shadows: dict[str, list[int]] = defaultdict(list)

    for path in sorted(TEST_DIR.rglob("test_*.py")):
        rel = str(path.relative_to(ROOT))
        dir_key = str(path.parent.relative_to(ROOT))
        name_lines: dict[str, list[int]] = defaultdict(list)

        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            # Only bare module-level defs (not indented inside a class)
            if line.startswith("def test_") and "(" in line:
                name = line.split("(")[0][4:]  # strip "def "
                name_lines[name].append(lineno)

        for name, lines in name_lines.items():
            if len(lines) > 1:
                intra_shadows[f"{rel}:{name}"] = lines
            # Register the file once per name for cross-file tracking
            files = dir_name_files[dir_key][name]
            if rel not in files:
                files.append(rel)

    return dir_name_files, intra_shadows


def main() -> int:
    dir_name_files, intra_shadows = collect()
    allowlist = load_allowlist()

    cross_file = {
        (dir_key, name): files
        for dir_key, name_map in dir_name_files.items()
        for name, files in name_map.items()
        if len(files) > 1
        and not any(dir_key.startswith(prefix) for prefix, n in allowlist if n == name)
    }

    if not cross_file and not intra_shadows:
        print("check_duplicate_tests: OK — no duplicate test function names")
        return 0

    failures = 0

    if cross_file:
        print(
            f"check_duplicate_tests: FAIL — {len(cross_file)} within-directory duplicate(s)\n"
        )
        for (dir_key, name), files in sorted(cross_file.items()):
            print(f"  {name}  [{dir_key}]:")
            for f in files:
                print(f"    {f}")
        failures += len(cross_file)

    if intra_shadows:
        print(
            f"\ncheck_duplicate_tests: FAIL — {len(intra_shadows)} intra-file shadow(s) "
            f"(second def silently overrides first)\n"
        )
        for key, lines in sorted(intra_shadows.items()):
            rel, name = key.rsplit(":", 1)
            print(f"  {name}  in {rel}  lines {lines}")
        failures += len(intra_shadows)

    print("\nFix: rename tests to distinguish purpose, or consolidate into one file.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
