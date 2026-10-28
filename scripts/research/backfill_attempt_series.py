"""Backfill the StepM selection universe with the series of runs recorded before migration 515.

Phase 187 plan 03 (design 7.2, 7.3.2). Each completed family evidence run is replayed from its
stored snapshot with the spec blob it ran, through the runner's synthetic path (the same S1-S5
code with no git gate and no ledger; valid for a spec with no transform, total_return or
members universe, which read nothing beyond the snapshot). A replay is accepted only when its
decision block equals the recorded one exactly; then its D_s series is written through S6
(`ledger.backfill_series`). Any difference, a missing snapshot or a spec the synthetic path
cannot replay faithfully is recorded as series_unavailable, never loosened. A replay is not a
new look: no research_run row is created.

    .venv/bin/python scripts/research/backfill_attempt_series.py            # dry run
    .venv/bin/python scripts/research/backfill_attempt_series.py --apply
    .venv/bin/python scripts/research/backfill_attempt_series.py --compare-all

--compare-all is the E17 parity gate (plan 07): it replays every completed evidence run, series
or not, and requires the decision block and any stored D_s series (sessions and values) to equal
the replay bit for bit. It never writes and exits non-zero on any difference.

A run whose decision block has no `memory_sessions` was scored by the E16 timing statistic,
before E17 was adopted (the four family 1 periodicity runs of 2026-09-25, annotated by
migration 377). The E17 code cannot reproduce it by construction, so it is logged as
`pre_e17` and never replayed or given a series; it is a record, not a parity failure. The
class is read from the record itself, never from a replay's outcome.

The run log lands in logs/research/series_backfill_<UTC>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import make_worker_pool  # noqa: E402
from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402
from src.core.service_utils import format_iso_ts  # noqa: E402
from src.intelligence.research import panel as panel_mod  # noqa: E402
from src.intelligence.research import store  # noqa: E402
from src.intelligence.research.ledger import PostgresLedger  # noqa: E402
from src.intelligence.research.provenance import repo_root  # noqa: E402
from src.intelligence.research.runner import BudgetConfig, RunContext, run_family  # noqa: E402
from src.intelligence.research.spec import load_spec_from_blob  # noqa: E402

# The decision fields a replay must reproduce exactly (the E17 record's decision block).
DECISION_FIELDS = ("t", "p", "se", "lag", "n_sessions", "mean_session_pnl", "memory_sessions")

_RUNS_SQL = """
SELECT r.run_id::text AS run_id, r.spec_path, r.spec_hash, r.spec_blob, r.snapshot_hash,
       c.name AS concept, r.evidence, s.sessions, s.d_s
FROM research_run r
JOIN concept_registry c USING (concept_id)
LEFT JOIN research_run_series s USING (run_id)
WHERE r.kind = 'evidence' AND r.status = 'completed' AND ($1 OR s.run_id IS NULL)
ORDER BY r.spec_path, c.name
"""


def compare(recorded: dict, replayed: dict) -> dict:
    """{field: [recorded, replayed]} for every decision field that differs (empty: equal)."""
    rec, rep = recorded.get("decision") or {}, replayed.get("decision") or {}
    return {f: [rec.get(f), rep.get(f)] for f in DECISION_FIELDS if rec.get(f) != rep.get(f)}


def series_differs(row: dict, series) -> bool:
    """True when a stored D_s series is not bit-identical to the replay's (False: none stored)."""
    if row["sessions"] is None:
        return False
    if series is None:
        return True
    return not (
        np.array_equal(np.asarray(row["sessions"], dtype="datetime64[D]"), series.sessions)
        and np.array_equal(np.asarray(row["d_s"], dtype=np.float64), series.values)
    )


def pre_e17(row: dict) -> bool:
    """True for a run scored by the E16 statistic: its decision block records no memory."""
    return "memory_sessions" not in ((row["evidence"] or {}).get("decision") or {})


def replay_refusal(spec) -> str | None:
    """Why the synthetic path cannot replay this spec faithfully, or None."""
    panel = spec.panel
    if panel.transform or panel.total_return is not None or panel.members_universe:
        return "spec reads beyond the snapshot (transform, total_return or members universe)"
    return None


async def _rows(dsn: str, compare_all: bool) -> list[dict]:
    conn = await connect_with_codecs(dsn)
    try:
        return [dict(r) for r in await conn.fetch(_RUNS_SQL, compare_all)]
    finally:
        await conn.close()


async def _workers(dsn: str) -> tuple[int, int]:
    cfg = ConfigService(dsn)
    await cfg.initialize()
    try:
        workers = int(await cfg.get("infra.research_runner.workers"))
        blas = int(await cfg.get("infra.blas_threads_per_worker") or 1)
    finally:
        await cfg.close()
    return workers, blas


async def main(args: argparse.Namespace) -> int:
    if args.compare_all and args.apply:
        raise SystemExit("--compare-all never writes; drop --apply")
    dsn = args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    root = repo_root(Path.cwd())
    workers, blas = await _workers(dsn)
    ctx = RunContext(
        root=root,
        budget=BudgetConfig("replay", 0, 0.0),
        workers=workers,
        pool_factory=functools.partial(make_worker_pool, blas_threads_per_worker=blas),
    )
    ledger = PostgresLedger(dsn)
    by_spec: dict[tuple, list[dict]] = {}
    for row in await _rows(dsn, args.compare_all):
        if args.specs and row["spec_path"] not in args.specs:
            continue
        by_spec.setdefault((row["spec_path"], row["spec_blob"], row["snapshot_hash"]), []).append(
            row
        )
    log: list[dict] = []
    for (spec_path, blob, snapshot_hash), group in by_spec.items():
        for row in (r for r in group if pre_e17(r)):
            member = row["concept"].rsplit(".", 1)[-1]
            entry = {"run_id": row["run_id"], "spec_path": spec_path, "member": member}
            entry.update(outcome="pre_e17", reason="E16 statistic, no E17 replay (migration 377)")
            print(json.dumps(entry), flush=True)
            log.append(entry)
        rows = [r for r in group if not pre_e17(r)]
        if not rows:
            continue
        loaded = load_spec_from_blob(root, spec_path, blob)
        reason = replay_refusal(loaded.model)
        if loaded.spec_hash != rows[0]["spec_hash"]:
            reason = f"spec hash {loaded.spec_hash} is not the recorded {rows[0]['spec_hash']}"
        path = Path(args.snapshot_dir) / f"panel_{snapshot_hash[:16]}"
        if reason is None and not path.exists():
            reason = f"snapshot {path} not on disk"
        if reason is None and store.verify(path) != snapshot_hash:
            reason = f"snapshot {path} does not hash to {snapshot_hash}"
        results = {}
        if reason is None:
            panel = panel_mod.load(path)
            print(f"replaying {spec_path} ({len(rows)} runs)", flush=True)
            results = await run_family(loaded, ctx, mode="synthetic", panel=panel, replay=True)
        for row in rows:
            member = row["concept"].rsplit(".", 1)[-1]
            entry = {"run_id": row["run_id"], "spec_path": spec_path, "member": member}
            replayed = results.get(member)
            if reason is not None or replayed is None:
                entry.update(outcome="series_unavailable", reason=reason or "member not replayed")
            elif diff := compare(row["evidence"], replayed["evidence"]):
                entry.update(outcome="series_unavailable", reason="replay differs", diff=diff)
            elif series_differs(row, replayed["series"]):
                entry.update(outcome="series_unavailable", reason="stored series differs")
            elif replayed["series"] is None:
                entry.update(outcome="series_unavailable", reason="no tested session")
            else:
                entry.update(outcome="equal", n_sessions=len(replayed["series"].values))
                if args.apply and row["sessions"] is None:
                    await ledger.backfill_series(row["run_id"], replayed["series"])
                    entry["written"] = True
            print(json.dumps(entry), flush=True)
            log.append(entry)
    out = Path(args.log_dir) / f"series_backfill_{format_iso_ts(datetime.now(UTC))}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"apply": args.apply, "runs": log}, indent=2))
    print(f"log: {out}")
    return 0 if all(e["outcome"] in ("equal", "pre_e17") for e in log) else 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the series (default: dry)")
    parser.add_argument(
        "--compare-all",
        action="store_true",
        help="parity gate: replay every completed evidence run, stored series included; never writes",
    )
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--snapshot-dir", default="logs/research/snapshots")
    parser.add_argument("--log-dir", default="logs/research")
    parser.add_argument(
        "--specs",
        nargs="*",
        default=None,
        help="replay only these spec paths (resume a stopped run; each spec replays whole)",
    )
    return parser


if __name__ == "__main__":
    sys.exit(asyncio.run(main(_parser().parse_args())))
