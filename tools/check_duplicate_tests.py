#!/usr/bin/env python3
"""CI guard: fail if any test function name appears in more than one file under tests/unit/.

Duplicate test function names indicate either copy-paste drift (two files testing the same
thing with diverging logic) or a merge that was never completed. Both are noise.

Usage:
    python tools/check_duplicate_tests.py

Exit 0 if clean, exit 1 with a report if duplicates found.
"""

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEST_DIR = ROOT / "tests" / "unit"


def collect_test_names() -> dict[str, list[str]]:
    name_to_files: dict[str, list[str]] = defaultdict(list)
    for path in TEST_DIR.rglob("test_*.py"):
        rel = str(path.relative_to(ROOT))
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("def test_"):
                name = stripped.split("(")[0][4:]  # strip "def "
                name_to_files[name].append(rel)
    return name_to_files


def main() -> int:
    name_to_files = collect_test_names()
    duplicates = {name: files for name, files in name_to_files.items() if len(files) > 1}

    if not duplicates:
        print("check_duplicate_tests: OK — no duplicate test function names")
        return 0

    print(
        f"check_duplicate_tests: FAIL — {len(duplicates)} duplicate test function name(s) found\n"
    )
    for name, files in sorted(duplicates.items()):
        print(f"  {name}:")
        for f in files:
            print(f"    {f}")
    print("\nFix: rename the test to distinguish its purpose, or consolidate into one file.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
