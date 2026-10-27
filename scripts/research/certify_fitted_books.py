"""Write the E17 fitted-book certificate from a battery record (plan 187-08).

    .venv/bin/python scripts/research/certify_fitted_books.py <record.json> [--commit <sha>]

The battery's commit comes from the record (the driver writes it, with any uncommitted change to
the certified code, which refuses); `--commit` is accepted only for a record written before the
driver recorded it. The certificate is written only when the certified code
(certificate.CERTIFIED_CODE) is the same at that commit and in the checkout the runner imports
(certificate.CODE_ROOT), so it describes the code that will execute. The record is copied into
research/certificates/records/ so the counts behind the certificate are committed and
auditable. Each cell's book arm is recorded with its rejections and bound per level and whether
it holds, plus the ridge configuration the battery ran; the runner's admission check decides
from that. Commit both files.
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.intelligence.research import certificate as cert  # noqa: E402


def book_cells(record: dict) -> dict[str, dict]:
    """{cell: {level: {rejected, bound, holds}}} for each cell's book arm; a cell with more than
    one book arm refuses, since which one the certificate means would be ambiguous."""
    out = {}
    for row in record["report"]:
        if not row["arm"].startswith("book_"):
            continue
        if row["cell"] in out:
            raise SystemExit(f"cell {row['cell']} has more than one book arm")
        out[row["cell"]] = {
            level: {
                "rejected": v["rejected"],
                "bound": v["bound"],
                "holds": v["rejected"] <= v["bound"],
            }
            for level, v in row["levels"].items()
        }
    return out


def record_sessions(record: dict) -> int:
    lengths = {sc["sessions"] for sc in record["scenarios"]}
    if len(lengths) != 1:
        raise SystemExit(f"cells ran at different lengths: {sorted(lengths)}")
    return lengths.pop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("record")
    parser.add_argument(
        "--commit", default=None, help="only for a record that does not carry its commit"
    )
    args = parser.parse_args()
    root = cert.CODE_ROOT
    record = json.loads(Path(args.record).read_text())
    if record.get("dirty_certified_code"):
        raise SystemExit(f"battery ran on uncommitted code: {record['dirty_certified_code']}")
    commit = record.get("commit") or args.commit
    if commit is None:
        raise SystemExit("the record carries no commit; pass --commit")
    if record.get("commit") and args.commit and args.commit != record["commit"]:
        raise SystemExit(f"--commit {args.commit} is not the record's {record['commit']}")

    def at_commit(path: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{path}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    then = cert.code_fingerprint(at_commit)
    now = cert.working_tree_fingerprint(root)
    changed = sorted(k for k in now if now[k] != then.get(k))
    if changed:
        raise SystemExit(f"certified code changed since {commit}: {changed}")
    copy = root / "research/certificates/records" / Path(args.record).name
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.record, copy)
    out = {
        "schema": cert.SCHEMA,
        "record": str(copy.relative_to(root)),
        "commit": commit,
        "ridge": cert.ridge_config(importlib.import_module(record["battery"])),
        "battery": record["battery"],
        "sims_per_cell": record["sims_per_cell"],
        "sessions": record_sessions(record),
        "code": now,
        "cells": book_cells(record),
    }
    path = root / cert.CERTIFICATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({c: {k: v["holds"] for k, v in lv.items()} for c, lv in out["cells"].items()}))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
