"""The E18 selection set: Romano-Wolf StepM over every counted attempt of a vintage.

Unified design 7.3.2 (phase 187 plan 06). A read, never a verdict: the set is computed on demand
from the stored D_s series (research_run_series) and printed; nothing is written. The universe is
every attempt a person could have seen (7.1): evidence runs, book tests and pod books in real or
exploration mode, in every status the ledger charges (refused and guard_failed computed no
statistic). A charged run without a series is a gap in the universe: a pre-515 run the backfill
could not replay, a run that failed or an interrupted run left `started`. The command refuses
unless --disclose-missing, which prints each such run and its status beside the set.

Each attempt's holding horizon comes from its recorded spec (a book's: the longest of its
families' at its code commit), and the bootstrap's mean block must exceed the longest in the
universe. Parameters are APR keys
alpha.selection.stepm.{fwer, block_mean_sessions, reps, seed}.

    .venv/bin/python scripts/research/select_books.py [--vintage <id>] [--disclose-missing]
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402
from src.intelligence.research.ledger import UNCHARGED_STATUSES  # noqa: E402
from src.intelligence.research.provenance import repo_root  # noqa: E402
from src.intelligence.research.spec import BookSpec, parse_spec_text  # noqa: E402
from src.intelligence.statistics.stepm import stepm  # noqa: E402

APR_KEYS = (
    "alpha.selection.stepm.fwer",
    "alpha.selection.stepm.block_mean_sessions",
    "alpha.selection.stepm.reps",
    "alpha.selection.stepm.seed",
    "alpha.research.vintage_id",
)

_COUNTED_SQL = """
SELECT r.run_id::text AS run_id, c.name AS concept, r.status, r.spec_blob, r.code_commit,
       s.sessions, s.d_s
FROM research_run r
JOIN concept_registry c USING (concept_id)
LEFT JOIN research_run_series s USING (run_id)
WHERE r.vintage = $1 AND NOT (r.status = ANY($2::text[]))
  AND r.kind IN ('evidence', 'book_test', 'pod_book')
ORDER BY r.started_at, c.name
"""


def universe_matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """(calendar [S] datetime64[D], matrix [S, K]) over the union of the attempts' sessions;
    a session an attempt did not test is NaN, never filled."""
    calendar = np.unique(
        np.concatenate([np.asarray(r["sessions"], dtype="datetime64[D]") for r in rows])
    )
    matrix = np.full((len(calendar), len(rows)), np.nan)
    for k, r in enumerate(rows):
        pos = np.searchsorted(calendar, np.asarray(r["sessions"], dtype="datetime64[D]"))
        matrix[pos, k] = np.asarray(r["d_s"], dtype=np.float64)
    return calendar, matrix


def horizon_sessions(spec_text: str, family_text_at) -> int:
    """The spec's holding horizon in sessions (a book's: the longest of its families')."""
    model = parse_spec_text(spec_text)
    if isinstance(model, BookSpec):
        return max(horizon_sessions(family_text_at(path), None) for path in model.families)
    return math.ceil(model.horizon / model.panel.analysis_bars_per_session)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


async def _load(dsn: str, vintage: str | None) -> tuple[list[dict], dict, str]:
    cfg = ConfigService(dsn)
    await cfg.initialize()
    try:
        apr = {k: await cfg.get(k) for k in APR_KEYS}
    finally:
        await cfg.close()
    missing = [k for k, v in apr.items() if v is None]
    if missing:
        raise SystemExit(f"APR keys missing: {missing}")
    vintage = vintage or str(apr["alpha.research.vintage_id"])
    conn = await connect_with_codecs(dsn)
    try:
        rows = [dict(r) for r in await conn.fetch(_COUNTED_SQL, vintage, list(UNCHARGED_STATUSES))]
    finally:
        await conn.close()
    return rows, apr, vintage


async def main(args: argparse.Namespace) -> int:
    dsn = args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    root = repo_root(Path.cwd())
    rows, apr, vintage = await _load(dsn, args.vintage)
    with_series = [r for r in rows if r["sessions"] is not None]
    missing = [r for r in rows if r["sessions"] is None]
    if missing and not args.disclose_missing:
        raise SystemExit(
            f"{len(missing)} counted runs have no series; rerun with --disclose-missing to "
            "select over the rest and list them"
        )
    if not with_series:
        raise SystemExit("no counted attempt has a series")
    git = functools.cache(functools.partial(_git, root))
    horizons = [
        horizon_sessions(
            git("cat-file", "-p", r["spec_blob"]),
            lambda path, c=r["code_commit"]: git("show", f"{c}:{path}"),
        )
        for r in with_series
    ]
    calendar, matrix = universe_matrix(with_series)
    out = stepm(
        matrix,
        block_mean=float(apr["alpha.selection.stepm.block_mean_sessions"]),
        max_horizon_sessions=max(horizons),
        reps=int(apr["alpha.selection.stepm.reps"]),
        fwer=float(apr["alpha.selection.stepm.fwer"]),
        seed=int(apr["alpha.selection.stepm.seed"]),
    )
    report = {
        "vintage": vintage,
        "attempts": len(with_series),
        "sessions": [str(calendar[0]), str(calendar[-1]), len(calendar)],
        "fwer": out.fwer,
        "block_mean": out.block_mean,
        "reps": out.reps,
        "max_horizon_sessions": max(horizons),
        "selection_set": [
            {
                "run_id": r["run_id"],
                "concept": r["concept"],
                "t": float(out.t[k]),
                "adjusted_p": float(out.adjusted_p[k]),
            }
            for k, r in enumerate(with_series)
            if out.selected[k]
        ],
        "not_selected": len(with_series) - int(out.selected.sum()),
        "missing_series": [
            {"run_id": r["run_id"], "concept": r["concept"], "status": r["status"]} for r in missing
        ],
    }
    print(json.dumps(report, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vintage", default=None, help="default: APR alpha.research.vintage_id")
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--disclose-missing", action="store_true")
    return parser


if __name__ == "__main__":
    sys.exit(asyncio.run(main(_parser().parse_args())))
