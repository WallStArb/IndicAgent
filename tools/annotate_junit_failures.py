#!/usr/bin/env python3
"""Print GitHub Actions annotations for a JUnit XML file: an error per failed test, and one notice
with the skip count by reason, so a silent drop in what CI runs (tests that skip without a database or
git history) is readable from the checks API like a failure.

The CI test reporter trims its summary past a size limit and CI logs need a login, so a red unit
test job gave no readable cause. Annotations are readable from the checks API without one.
GitHub shows at most 10 error annotations per step, so the first failures are printed one each and
the rest are counted in a final line.

Usage: python tools/annotate_junit_failures.py test-results.xml [--max N]
Exit 0 always: it only reports; the test step's own exit code fails the job.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

MAX_ANNOTATIONS = 9  # one slot is left for the summary line
MESSAGE_CHARS = 400


def failures(xml_path: Path) -> Iterator[tuple[str, str]]:
    """(test id, first line of the failure message) for each failed or errored test case."""
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is not None:
                message = (node.get("message") or node.text or "").strip().splitlines()
                yield f"{case.get('classname')}::{case.get('name')}", (
                    message[0] if message else ""
                )
                break


def skip_counts(xml_path: Path) -> Counter[str]:
    """Skipped tests by reason (the first line of the skip message)."""
    counts: Counter[str] = Counter()
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        node = case.find("skipped")
        if node is not None:
            message = (node.get("message") or node.text or "").strip().splitlines()
            counts[message[0] if message else "no reason given"] += 1
    return counts


def skip_summary(xml_path: Path) -> str:
    """One line a silent drop in coverage shows up in: the total skipped and the count per reason."""
    counts = skip_counts(xml_path)
    detail = "; ".join(f"{n} x {reason}" for reason, n in counts.most_common())
    return f"::notice title=unit test skips::{_escape(f'{sum(counts.values())} skipped. {detail}'.strip())}"


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(xml_path: Path, limit: int = MAX_ANNOTATIONS) -> list[str]:
    found = list(failures(xml_path))
    lines = [
        f"::error title={_escape(test_id)}::{_escape(message[:MESSAGE_CHARS])}"
        for test_id, message in found[:limit]
    ]
    if found:
        lines.append(f"::error title=unit test failures::{len(found)} failed or errored in total")
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("xml", type=Path)
    parser.add_argument("--max", type=int, default=MAX_ANNOTATIONS)
    args = parser.parse_args(argv)
    if not args.xml.exists():
        print(f"::warning::{args.xml} was not written; pytest stopped before the report")
        return 0
    print("\n".join([*annotations(args.xml, args.max), skip_summary(args.xml)]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
