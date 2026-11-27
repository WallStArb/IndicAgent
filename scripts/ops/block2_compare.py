#!/usr/bin/env python3
"""Compare a block 2 battery rerun with the recorded block and print the one status line the launchers gate on.

Usage: block2_compare.py <recorded.json> <rerun.json> <battery commit>

Prints `block2 compare: IDENTICAL|DIFFERENT [differing fields] commit=<battery commit>`. Every field is compared except
`seconds`. The `commit=` token is the pin: guarded_run_common.sh's block2_gate accepts a comparison only for its own
BLOCK2_COMMIT, so a line from another battery commit (or an old line with no pin) never satisfies a launcher.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

_IGNORED = ("seconds",)


def compare_line(recorded: Mapping[str, object], rerun: Mapping[str, object], commit: str) -> str:
    a = {k: v for k, v in recorded.items() if k not in _IGNORED}
    b = {k: v for k, v in rerun.items() if k not in _IGNORED}
    verdict = "IDENTICAL" if a == b else "DIFFERENT"
    differing = [k for k in a if a.get(k) != b.get(k)]
    return f"block2 compare: {verdict} {differing} commit={commit}"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print(__doc__, file=sys.stderr)
        return 64
    recorded, rerun = (json.loads(Path(p).read_text()) for p in args[:2])
    print(compare_line(recorded, rerun, args[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
