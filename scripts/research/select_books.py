"""The E18 selection set: Romano-Wolf StepM over every counted attempt of a vintage.

Unified design 7.3.2 (phase 187 plan 06). A read, never a verdict: the set is computed on demand
from the stored D_s series (research_run_series) and printed; nothing is written. The universe is
every attempt a person could have seen (7.1): evidence runs, book tests and pod books in real or
exploration mode, in every status the ledger charges (refused and guard_failed computed no
statistic).

A selection set is a result only when every gate holds; otherwise the command refuses, and
--diagnostic prints the set marked `"result": false` with the reasons (exit 3). The gates:
- every charged run has a series. A gap (a pre-515 run the backfill could not replay, a run that
  failed, an interrupted run left `started`) would leave its max-t out of the null and make the
  selection anti-conservative;
- no charged run sits on another vintage: E18 re-evaluates prior attempts on an extended vintage
  and the count does not reset, which is not built, so a second vintage refuses;
- `--battery` names a complete StepM null-battery record (plan 05) with no failing gating cell,
  run on this StepM module (content hash) at the APR's fwer and block mean.

Each attempt's holding horizon comes from its recorded spec (a book's: the longest of its
families' at its code commit), and the bootstrap's mean block must exceed the longest in the
universe. Parameters are APR keys
alpha.selection.stepm.{fwer, block_mean_sessions, reps, seed}.

    .venv/bin/python scripts/research/select_books.py --battery <record.json> [--vintage <id>]
        [--diagnostic]
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

from scripts.research.stepm_null_battery import stepm_source_sha256  # noqa: E402
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


_OTHER_VINTAGES_SQL = """
SELECT DISTINCT vintage FROM research_run
WHERE vintage <> $1 AND NOT (status = ANY($2::text[]))
ORDER BY vintage
"""


def battery_refusals(record: dict | None, apr: dict, stepm_sha256: str) -> list[str]:
    """Why a StepM null-battery record does not attest this selection (empty: it does)."""
    if record is None:
        return ["no StepM null-battery record (--battery)"]
    out = []
    if record.get("schema") != "stepm_null_battery_v1":
        out.append(f"battery schema {record.get('schema')!r} is not stepm_null_battery_v1")
    if record.get("complete") is not True:
        out.append("battery record covers only some cells")
    if record.get("failures") != []:
        out.append(f"battery fails in gating cells {record.get('failures')}")
    if record.get("stepm_sha256") != stepm_sha256:
        out.append("battery ran on different StepM code")
    if record.get("studentize") != "draw":
        out.append(f"battery studentize {record.get('studentize')!r} is not the default 'draw'")
    for field, key in (("fwer", "fwer"), ("block_mean", "block_mean_sessions")):
        if record.get(field) != float(apr[f"alpha.selection.stepm.{key}"]):
            out.append(f"battery {field} {record.get(field)} is not the APR's")
    return out


def selection_refusals(
    missing: list[dict], other_vintages: list[str], battery: list[str]
) -> list[str]:
    """Every reason the selection set is not a result (empty: it is)."""
    out = [f"{len(missing)} charged runs have no series"] if missing else []
    if other_vintages:
        out.append(
            f"charged runs on other vintages {other_vintages}: re-evaluation onto the extended "
            "vintage (E18) is not built"
        )
    return out + battery


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
        return max(
            horizon_sessions(family_text_at(path), family_text_at) for path in model.families
        )
    return math.ceil(model.horizon / model.panel.analysis_bars_per_session)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


async def _load(dsn: str, vintage: str | None) -> tuple[list[dict], list[str], dict, str]:
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
        uncharged = list(UNCHARGED_STATUSES)
        rows = [dict(r) for r in await conn.fetch(_COUNTED_SQL, vintage, uncharged)]
        others = [r["vintage"] for r in await conn.fetch(_OTHER_VINTAGES_SQL, vintage, uncharged)]
    finally:
        await conn.close()
    return rows, others, apr, vintage


async def main(args: argparse.Namespace) -> int:
    dsn = args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    root = repo_root(Path.cwd())
    rows, others, apr, vintage = await _load(dsn, args.vintage)
    with_series = [r for r in rows if r["sessions"] is not None]
    missing = [r for r in rows if r["sessions"] is None]
    record = json.loads(Path(args.battery).read_text()) if args.battery else None
    refusals = selection_refusals(
        missing, others, battery_refusals(record, apr, stepm_source_sha256())
    )
    if refusals and not args.diagnostic:
        raise SystemExit("selection is not a result: " + "; ".join(refusals))
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
        "result": not refusals,
        "refusals": refusals,
        "vintage": vintage,
        "attempts": len(with_series),
        "sessions": [str(calendar[0]), str(calendar[-1]), len(calendar)],
        "fwer": out.fwer,
        "block_mean": out.block_mean,
        "reps": out.reps,
        "max_horizon_sessions": max(horizons),
        # Under a failed gate the set is not a selection: its key says so, so a reader that
        # skips "result" cannot take it for one.
        ("selection_set" if not refusals else "unattested_set"): [
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
    return 3 if refusals else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vintage", default=None, help="default: APR alpha.research.vintage_id")
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--battery", default=None, help="a complete StepM null-battery record")
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="print the set even when a gate fails, marked result false (exit 3)",
    )
    return parser


if __name__ == "__main__":
    sys.exit(asyncio.run(main(_parser().parse_args())))
