"""Audit flat-features consumers in the intelligence pipeline.

Scans src/ and services/ for any code that reads from frames["features"],
frames.get("features"), or frames.setdefault("features"). Used to determine
whether the PERF-02 flat-features dual-write path can be safely removed.

Usage:
    .venv/bin/python scripts/audit_flat_features.py
"""

import re
from pathlib import Path

_PATTERN = re.compile(
    r'frames\["features"\]|frames\.get\("features"|frames\.setdefault\("features"'
)

hits = []
for root in (Path("src"), Path("services")):
    for f in root.rglob("*.py"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if _PATTERN.search(line):
                hits.append((str(f), i, line.strip()))

for h in hits:
    print(h)
print(f"TOTAL: {len(hits)} hits in {len({h[0] for h in hits})} files")
