"""Record splits found in the nightly overlap, re-fetch their history, re-derive it (plan 185-22, D-21).

For each fetch run it is given, services/split_detection.detect_overlap_splits compares the run's
fresh 1d observations with the earlier ones for the same dates. A constant ratio is a split:

1. corporate_action gets one row (inferred_by nightly_overlap, evidence request ids), idempotent per
   (symbol, effective date, factor), in a transaction under bar_derivation_writer;
2. the symbol's full 1d history is re-fetched into D1 (ibkr_history_fetcher.py with the symbols
   named and a large --overlap-sessions re-asks sessions D1 already answers) so every
   observation is on the new scale;
3. the daily stage re-derives it, which clears pre_split_unrefetched because a fetch now exists
   after the action was recorded. The order matters: D2 counts only a fetch made after the
   recording as post-split.

A non-constant difference is never recorded as a split: it becomes an integrity fact
(bar_split_detection) for a human. A failed re-fetch or derivation exits non-zero; D2 keeps
flagging the symbol's older bars until it succeeds, and `--refetch-only SYM,SYM` repeats steps 2
and 3 by hand.

The re-fetch takes FetcherLock like every IBKR history fetch (plan 189-08). When this script
runs as the fetcher's own run-end stage, the fetcher still holds that lock, so the re-fetch is
refused: the refusal line maps to exit 3 (LOCK_HELD_EXIT), the derivation is skipped, the
fetcher run ends partial, and the split stays recorded and loudly quarantined
(pre_split_unrefetched) until `--refetch-only` runs after the fetcher exits. Plan 189-10 owns
moving the re-fetch in-process (its update lane's overlap escalation).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import asyncpg
import structlog

from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE
from services.split_detection import DetectedSplit, detect_overlap_splits

_logger = structlog.get_logger(__name__)

_INFERRED_BY = "nightly_overlap"
_FACT_MONITOR = "bar_split_detection"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FETCHER = _REPO_ROOT / "scripts" / "infrastructure" / "backfill" / "ibkr_history_fetcher.py"
# Exit code for a re-fetch the fetcher refused because its lock is held (the fetcher itself
# exits 0 and prints LOCK_HELD_MESSAGE). Non-zero, so the derivation is skipped.
LOCK_HELD_EXIT = 3
# Sessions per year used to turn APR split_refetch_years into --overlap-sessions: a calendar
# fact (the NYSE trades about 252 days a year), with slack so the window clears the listing.
_SESSIONS_PER_YEAR = 260

_APR_KEYS = (
    "threshold.seam.rel_tol",
    "threshold.seam.min_run",
    "threshold.seam.ratio_snap_tol",
    "infra.bar_derivation.split_refetch_years",
)

_EXISTING_SQL = """
SELECT action_id::text, factor FROM corporate_action_current
WHERE symbol = $1 AND effective_date = $2 AND inferred_by = 'nightly_overlap'
"""

_INSERT_SQL = """
INSERT INTO corporate_action
    (symbol, action_type, effective_date, factor, inferred_by, evidence_request_ids,
     detail, supersedes)
VALUES ($1, $2, $3, $4, 'nightly_overlap', $5::uuid[], $6::jsonb, $7::uuid)
"""


async def record_split(conn: Any, split: DetectedSplit) -> bool:
    """Insert the split unless the same factor is already recorded; True if a row was added.

    A different factor on the same date supersedes the earlier row rather than editing it
    (corporate_action is append-only). Refuses to record a split without evidence.
    """
    if not split.request_ids:
        raise ValueError(f"{split.symbol}: refusing to record a split without evidence request ids")
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE bar_derivation_writer")
        existing = await conn.fetch(_EXISTING_SQL, split.symbol, split.effective_date)
        if any(abs(float(factor) - split.factor) < 1e-9 for _id, factor in existing):
            return False
        await conn.execute(
            _INSERT_SQL,
            split.symbol,
            "split" if split.factor > 1.0 else "reverse_split",
            split.effective_date,
            split.factor,
            list(split.request_ids),
            json.dumps({"detected_by": "overlap", "n_evidence_requests": len(split.request_ids)}),
            existing[0][0] if existing else None,
        )
    return True


async def process(
    conn: Any,
    run_ids: Sequence[str],
    *,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
    refetch: Callable[[list[str]], int],
    derive: Callable[[list[str]], int],
    report_unexplained: Callable[[DetectedSplit], None],
) -> dict[str, Any]:
    """Detect over `run_ids`, record splits, then re-fetch and re-derive the recorded symbols."""
    detected: list[DetectedSplit] = []
    for run_id in run_ids:
        detected.extend(
            await detect_overlap_splits(
                conn,
                fetch_run_id=run_id,
                rel_tol=rel_tol,
                min_run=min_run,
                ratio_snap_tol=ratio_snap_tol,
            )
        )
    recorded: list[str] = []
    unexplained: list[str] = []
    for split in detected:
        if split.unexplained:
            report_unexplained(split)
            unexplained.append(split.symbol)
        elif await record_split(conn, split):
            recorded.append(split.symbol)
    symbols = sorted(set(recorded))
    returncode = 0
    if symbols:
        returncode = refetch(symbols) or derive(symbols)
    return {
        "recorded": symbols,
        "unexplained": sorted(set(unexplained)),
        "returncode": returncode,
    }


def refetch_command(symbols: Sequence[str], *, years: int, client_id: int) -> list[str]:
    """The fetcher invocation that re-asks `years` of 1d history for `symbols`.

    Named symbols are asked even when their series is current; --full-scan plans the full
    depth window as the pipeline did, and the overlap re-asks sessions D1 already answers.
    """
    return [
        sys.executable,
        str(_FETCHER),
        "--symbols",
        ",".join(symbols),
        "--timeframes",
        "1d",
        "--dimension",
        "backfill",
        "--client-id",
        str(client_id),
        "--full-scan",
        "--overlap-sessions",
        str(years * _SESSIONS_PER_YEAR),
    ]


def _run(command: list[str]) -> int:
    return subprocess.run(
        command, cwd=str(_REPO_ROOT), env={**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    ).returncode


def run_refetch(command: list[str], popen: Callable[..., Any] = subprocess.Popen) -> int:
    """Run the fetcher, echoing its output; LOCK_HELD_EXIT when it reports its lock held.
    The fetcher bootstraps its own import path, so no environment is passed."""
    proc = popen(
        command,
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lock_held = False
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="")
        lock_held = lock_held or line.strip() == LOCK_HELD_MESSAGE
    rc = proc.wait()
    if lock_held:
        _logger.error("split_detection.refetch_refused_lock_held", command=command)
        return LOCK_HELD_EXIT
    return int(rc)


def _derive_command(symbols: Sequence[str]) -> list[str]:
    return [
        sys.executable,
        str(_REPO_ROOT / "services" / "bar_derivation.py"),
        "--stage",
        "daily",
        "--symbols",
        ",".join(symbols),
        "--apply",
    ]


async def _load_apr(conn: Any) -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])",
        list(_APR_KEYS),
    )
    missing = set(_APR_KEYS) - {r["config_key"] for r in rows}
    if missing:
        raise RuntimeError(f"APR keys not set: {sorted(missing)}")
    return {r["config_key"]: r["config_value"] for r in rows}


def _unexplained_reporter(settings: Any) -> Callable[[DetectedSplit], None]:
    def report(split: DetectedSplit) -> None:
        import psycopg

        from src.core.integrity_monitor import emit_integrity_fact_sync

        with psycopg.connect(settings.database_url, autocommit=True) as fact_conn:
            emit_integrity_fact_sync(
                fact_conn,
                _FACT_MONITOR,
                split.symbol,
                "unexplained_overlap_difference",
                float(split.factor),
                1.0,
                False,
                None,
            )
        _logger.warning(
            "split_detection.unexplained",
            symbol=split.symbol,
            effective_date=str(split.effective_date),
            median_ratio=split.factor,
        )

    return report


async def _main(args: argparse.Namespace) -> int:
    from src.config.settings import Settings

    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        apr = await _load_apr(conn)
        years = int(apr["infra.bar_derivation.split_refetch_years"])

        def refetch(symbols: list[str]) -> int:
            return run_refetch(refetch_command(symbols, years=years, client_id=args.client_id))

        def derive(symbols: list[str]) -> int:
            return _run(_derive_command(symbols))

        if args.refetch_only:
            symbols = sorted({s.strip().upper() for s in args.refetch_only.split(",") if s.strip()})
            rc = refetch(symbols) or derive(symbols)
            print(json.dumps({"refetched": symbols, "returncode": rc}))
            return rc
        report = await process(
            conn,
            args.fetch_run_id,
            rel_tol=float(apr["threshold.seam.rel_tol"]),
            min_run=int(apr["threshold.seam.min_run"]),
            ratio_snap_tol=float(apr["threshold.seam.ratio_snap_tol"]),
            refetch=refetch,
            derive=derive,
            report_unexplained=_unexplained_reporter(settings),
        )
        print(json.dumps(report))
        return int(report["returncode"])
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fetch-run-id", action="append", default=[], help="a fetch run to judge (repeatable)"
    )
    parser.add_argument(
        "--refetch-only",
        default=None,
        help="comma-separated symbols: skip detection, re-fetch and re-derive them",
    )
    parser.add_argument("--client-id", type=int, default=45, help="IBKR client id (nightly lane)")
    args = parser.parse_args()
    if not args.fetch_run_id and not args.refetch_only:
        parser.error("give at least one --fetch-run-id, or --refetch-only")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
