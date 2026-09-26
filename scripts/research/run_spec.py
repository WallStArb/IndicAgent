"""Run a committed research spec through the runner (architecture step 4).

The only layer of the research runner that imports services (the worker pool) and reads APR;
src/intelligence/research stays Ring 1. Every real-data number goes through here and lands in
the research_run ledger.

    .venv/bin/python scripts/research/run_spec.py --spec research/specs/<spec>.yaml
    .venv/bin/python scripts/research/run_spec.py --mode synthetic --spec <file> --panel <dir>

Exit codes: 0 when every row reached a terminal status (completed, guard_failed and refused
are recorded outcomes), 2 when the run was refused before any row was written, 1 on an error.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from services._batch_utils import make_worker_pool  # noqa: E402
from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research.families.intraday_periodicity import SameSlotPlant  # noqa: E402
from src.intelligence.research.ledger import PostgresLedger  # noqa: E402
from src.intelligence.research.provenance import repo_root  # noqa: E402
from src.intelligence.research.runner import (  # noqa: E402
    BudgetConfig,
    RunContext,
    RunRefused,
    run_book,
    run_family,
)
from src.intelligence.research.spec import (  # noqa: E402
    BookSpec,
    load_spec_from_file,
    load_spec_from_head,
)
from src.intelligence.research.synthetic import (  # noqa: E402
    synthetic_price_panel,
)

_BUDGET_KEYS = (
    "alpha.research.vintage_id",
    "alpha.research.budget_m",
    "alpha.research.screen_alpha",
)


async def _apr(dsn: str) -> dict:
    cfg = ConfigService(dsn)
    await cfg.initialize()
    try:
        keys = (*_BUDGET_KEYS, "infra.research_runner.workers", "infra.blas_threads_per_worker")
        values = {k: await cfg.get(k) for k in keys}
    finally:
        await cfg.close()
    missing = [k for k in _BUDGET_KEYS if values[k] is None]
    if missing:
        raise SystemExit(f"APR keys missing (migration 366): {missing}")
    return values


def _print_book(result: dict, loaded, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ev = result["evidence"] or {}
    print(
        "RESULT "
        + json.dumps(
            {
                "book": loaded.model.book,
                "status": result["status"],
                "run_id": result["run_id"],
                "t": (ev.get("decision") or {}).get("t"),
                "p": (ev.get("decision") or {}).get("p"),
                "p_below_bar": (ev.get("screen") or {}).get("p_below_bar"),
                "powered": (ev.get("power") or {}).get("powered"),
            }
        ),
        flush=True,
    )
    (out_dir / f"{loaded.spec_hash[:16]}_{loaded.model.book}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True)
    )


def _synthetic_panel(args: argparse.Namespace, loaded):
    if args.panel:
        return panel_mod.load(Path(args.panel))
    fam = loaded.families[0].model if loaded.families else loaded.model
    power = getattr(loaded.model, "power", None)
    synth = SameSlotPlant(
        bars_per_session=fam.panel.bars_per_session,
        participation_ratio=power.participation_ratio if power else 60.0,
        n_common_factors=power.n_common_factors if power else 10,
        plant_lags_sessions=power.plant_lags_sessions if power else 40,
    )
    return synthetic_price_panel(
        synth,
        n_sessions=args.synthetic_sessions,
        n_names=args.synthetic_names,
        plant_coef=args.synthetic_plant,
        seed=args.synthetic_seed,
        start="2006-07-03",
        missing_fraction=0.02,
    )


def _print(results: dict, loaded, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for member, row in results.items():
        ev = row["evidence"] or {}
        print(
            "RESULT "
            + json.dumps(
                {
                    "member": member,
                    "status": row["status"],
                    "run_id": row["run_id"],
                    "t": (ev.get("decision") or {}).get("t"),
                    "p": (ev.get("decision") or {}).get("p"),
                }
            ),
            flush=True,
        )
        (out_dir / f"{loaded.spec_hash[:16]}_{member}.json").write_text(
            json.dumps(row, indent=2, sort_keys=True)
        )


async def _main(args: argparse.Namespace) -> int:
    snapshot_dir = Path(args.snapshot_dir)
    if args.mode == "synthetic":
        loaded = load_spec_from_file(Path(args.spec), root=Path.cwd())
        workers = args.workers or 1
        ctx = RunContext(
            root=Path.cwd(),
            budget=BudgetConfig("synthetic", args.budget_m, 0.05),
            workers=workers,
            pool_factory=(
                functools.partial(make_worker_pool, blas_threads_per_worker=1)
                if workers > 1
                else None
            ),
        )
        panel = _synthetic_panel(args, loaded)
        runs = snapshot_dir.parent / "runs"
        if isinstance(loaded.model, BookSpec):
            result = await run_book(
                loaded, ctx, mode="synthetic", panel=panel, power_replicates=args.power_replicates
            )
            _print_book(result, loaded, runs)
        else:
            _print(await run_family(loaded, ctx, mode="synthetic", panel=panel), loaded, runs)
        return 0

    if args.power_replicates is not None:
        raise SystemExit("--power-replicates is synthetic-only: a real book uses its spec's R")

    dsn = args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    root = repo_root(Path.cwd())
    loaded = load_spec_from_head(root, args.spec)
    apr = await _apr(dsn)
    workers = args.workers or int(apr["infra.research_runner.workers"])
    blas = int(apr["infra.blas_threads_per_worker"] or 1)
    ctx = RunContext(
        root=root,
        budget=BudgetConfig(
            vintage_id=str(apr["alpha.research.vintage_id"]),
            budget_m=int(apr["alpha.research.budget_m"]),
            screen_alpha=float(apr["alpha.research.screen_alpha"]),
        ),
        workers=workers,
        pool_factory=functools.partial(make_worker_pool, blas_threads_per_worker=blas),
        ledger=PostgresLedger(dsn),
        dsn=dsn,
        snapshot_dir=snapshot_dir,
        snapshot=Path(args.snapshot) if args.snapshot else None,
    )
    runs = snapshot_dir.parent / "runs"
    if isinstance(loaded.model, BookSpec):
        _print_book(await run_book(loaded, ctx, mode="real"), loaded, runs)
    else:
        _print(await run_family(loaded, ctx, mode="real"), loaded, runs)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", required=True, help="repo-relative spec path")
    parser.add_argument("--mode", choices=("real", "synthetic"), default="real")
    parser.add_argument("--snapshot-dir", default="logs/research/snapshots")
    parser.add_argument("--snapshot", default=None, help="reuse a built snapshot directory")
    parser.add_argument("--panel", default=None, help="synthetic mode: a saved panel directory")
    parser.add_argument("--workers", type=int, default=None, help="default: APR (throughput only)")
    parser.add_argument("--budget-m", type=int, default=1, help="synthetic mode only")
    parser.add_argument("--dsn", default=None, help="default: Settings().database_url")
    parser.add_argument("--synthetic-sessions", type=int, default=400)
    parser.add_argument("--synthetic-names", type=int, default=30)
    parser.add_argument("--synthetic-seed", type=int, default=0)
    parser.add_argument("--synthetic-plant", type=float, default=0.0)
    parser.add_argument(
        "--power-replicates", type=int, default=None, help="synthetic only: override the spec's R"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_main(args))
    except RunRefused as error:
        print(f"REFUSED {error}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
