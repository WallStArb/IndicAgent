"""Bind E17 battery driver results into a stored pass record (research/battery_passes/).

    .venv/bin/python scripts/research/bind_battery_pass.py --battery <module> \\
        --spec research/specs/<primary>.yaml [--spec <core twin>.yaml] \\
        --driver run_part1.json [--driver run_part2.json]

The driver commit (--driver-commit, the commit each driver JSON records) need not be HEAD: the code
key and the input hash are computed from the sources and the spec files as of that commit and again at
the checkout, and the bind refuses unless they are equal (so the code and inputs the simulations ran at
are the ones the record is bound to). It also refuses a dirty tree, a driver part from another commit
or battery, a battery whose own inputs differ from the spec, and a merged result that is not a pass
(battery_pass.make_record). A record is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.intelligence.research import battery_pass  # noqa: E402
from src.intelligence.research.spec import load_spec_from_file, parse_spec_text  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--battery", required=True)
    parser.add_argument("--spec", action="append", required=True, type=Path)
    parser.add_argument("--driver", action="append", required=True, type=Path)
    parser.add_argument("--driver-commit", required=True)
    parser.add_argument("--out-dir", type=Path, default=battery_pass.RECORD_DIR)
    args = parser.parse_args(argv)
    loaded = [load_spec_from_file(p, root=REPO_ROOT) for p in args.spec]
    specs = [item.model for item in loaded]
    if len({battery_pass.battery_input_hash(s) for s in specs}) != 1:
        print("REFUSING: the specs differ in the inputs the battery simulates", file=sys.stderr)
        return 2
    family_module = specs[0].members[0].signal.rsplit(".", 1)[0]
    recorded = datetime.now(UTC).date().isoformat()
    try:
        with battery_pass.sources_at(args.driver_commit, REPO_ROOT):
            then_specs = [
                parse_spec_text(_git("show", f"{args.driver_commit}:{p.as_posix()}"))
                for p in args.spec
            ]
            input_hash_then = battery_pass.battery_input_hash(then_specs[0])
            code_key_then = battery_pass.battery_code_key(args.battery, family_module)
        record = battery_pass.make_record(
            [json.loads(p.read_text()) for p in args.driver],
            spec=specs[0],
            spec_hashes=[item.spec_hash for item in loaded],
            battery_module=args.battery,
            family_module=family_module,
            driver_commit=_git("rev-parse", args.driver_commit).strip(),
            input_hash_then=input_hash_then,
            code_key_then=code_key_then,
            dirty=_git("status", "--porcelain", "--untracked-files=no").split(),
            recorded=recorded,
        )
    except battery_pass.BatteryPassRefused as error:
        print(f"REFUSING: {error}", file=sys.stderr)
        return 2
    out = args.out_dir / f"{specs[0].family}_{recorded}.json"
    if out.exists():
        print(f"REFUSING: {out} exists; a record is never overwritten", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"pass record written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
