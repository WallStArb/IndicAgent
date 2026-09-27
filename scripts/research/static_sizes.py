"""Measure a family spec's E17 static sizes against its H0 battery's gate (todo 447).

The runner performs this check itself before every family's statistic and refuses above the
gate; this driver shows the same measurement ahead of a run, on the same analysis panel (S0
snapshot, members' universe, total return, transform). It computes no statistic of
predictability and writes no ledger row.

    .venv/bin/python scripts/research/static_sizes.py --spec research/specs/<spec>.yaml \\
        [--snapshot <dir>]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from src.config.settings import Settings  # noqa: E402
from src.intelligence.research.provenance import repo_root  # noqa: E402
from src.intelligence.research.runner import (  # noqa: E402
    BudgetConfig,
    RunContext,
    _load_panel,
    static_gate,
    static_precondition,
)
from src.intelligence.research.spec import load_spec_from_head  # noqa: E402


async def _main(args: argparse.Namespace) -> int:
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    root = repo_root(Path.cwd())
    spec = load_spec_from_head(root, args.spec).model
    gate = static_gate(spec)
    ctx = RunContext(
        root=root,
        budget=BudgetConfig("static_sizes", 1, 0.05),
        dsn=dsn,
        snapshot_dir=Path(args.snapshot_dir),
        snapshot=Path(args.snapshot) if args.snapshot else None,
    )
    panel, digest, _ = await _load_panel(spec, ctx)
    block = static_precondition(spec, panel, gate)
    out = {"family": spec.family, "spec": args.spec, "snapshot_hash": digest, **block}
    print(json.dumps(out, indent=2))
    return 0 if block["passes"] else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", required=True, help="repo-relative spec path")
    parser.add_argument("--snapshot-dir", default="logs/research/snapshots")
    parser.add_argument("--snapshot", default=None, help="reuse a built snapshot directory")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
