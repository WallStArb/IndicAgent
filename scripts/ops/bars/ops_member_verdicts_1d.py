"""ops_member_verdicts_1d.py - the 1d verdict report for every universe member (todo 649a).

The nightly bar reconciliation audit writes the 1d verdicts (session_coverage, canonical_recompute,
digest_fresh, freshness_1d, unexplained_seam, ...) only for the active names (the backfill
dimension). The corpus rerun's `d2_landed` gate reads them for every name the corpus computes, so
a name that is a member but not active (a dead or stage 2 name) has no verdict and fails as
missing. This one-shot judges exactly the same nine 1d checks, with the audit's own pure
judgement (`judge_name_1d`) and writer, over every symbol in `universe_membership`, so the proof
that canonical 1d equals the d2-v2 recompute of raw covers every name the compute reads.

Dry run by default: judges and prints the failing and passing counts by check, writes nothing.
`--apply` writes the verdict rows (monitor_type bar_integrity) and reads them back.

    .venv/bin/python -m scripts.ops.bars.ops_member_verdicts_1d [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import asyncpg

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from services.bar_hold import held as read_held  # noqa: E402
from services.bar_reconciliation_audit import (  # noqa: E402
    _APR_PATTERNS,
    BarReconciliationAudit,
    _IntegrityParams,
    _Params,
    _Window,
)
from services.batch_support.db import load_apr_dict_async  # noqa: E402
from src.config.settings import Settings  # noqa: E402

SEAM_CHUNK_NAMES = 1000  # the seam read is chunked: ANY(names) arrays go superlinear at full size


class MemberVerdictReport1d(BarReconciliationAudit):
    """The audit's 1d verdict report over every universe member (judge and write, nothing else)."""

    job_name = "member-verdicts-1d"
    apply = False
    sample_every = 1

    @staticmethod
    async def _membership_ends(conn: asyncpg.Connection) -> dict[str, date]:
        """Each inactive member to its last membership month-end. The compute reads no bar after
        that span end (the data gate's span), and an inactive name has no capture after the
        archive end, so its verdicts are judged up to there. An active member is judged to the
        last completed session, as the nightly audit does."""
        rows = await conn.fetch(
            "SELECT m.symbol, max(m.as_of) AS last FROM universe_membership m "
            "JOIN instruments i ON i.symbol = m.symbol WHERE NOT i.is_active GROUP BY m.symbol"
        )
        return {r["symbol"]: r["last"] for r in rows}

    async def execute(self, pool: asyncpg.Pool) -> None:
        now = datetime.now(UTC)
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(conn, _APR_PATTERNS)
            params = _Params.from_apr(apr)
            window = _Window.build(now, params)
            members = [
                r["symbol"]
                for r in await conn.fetch(
                    "SELECT DISTINCT symbol FROM universe_membership ORDER BY 1"
                )
            ]
            span_end = await self._membership_ends(conn)
            if self.sample_every > 1:  # a read-only measurement on every k-th member
                members = members[:: self.sample_every]
            seam_samples: list[str] = []
            for start in range(0, len(members), SEAM_CHUNK_NAMES):
                chunk = members[start : start + SEAM_CHUNK_NAMES]
                seams = await self._seams(conn, params, window, chunk)
                seam_samples.extend(seams.result.samples)
            verdicts = await self._verdict_report_1d(
                conn,
                _IntegrityParams.from_apr(apr),
                window,
                members,
                seam_samples,
                now,
                holds=await read_held(conn, "1d"),
                last_sessions=span_end,
            )
        print(f"members judged {len(members)}; rows {len(verdicts.facts)}")
        print(f"failing by check {dict(sorted(verdicts.failing_by_check.items()))}")
        print(f"seconds by check {({k: round(v) for k, v in sorted(verdicts.timings.items())})}")
        if not self.apply:
            print("dry run: nothing written (--apply writes the verdict rows)")
            return
        async with pool.acquire() as conn:
            await self._write_verdicts(conn, verdicts, now)
        self._log_verdicts(verdicts)
        print("verdict rows written and read back")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the verdict rows")
    parser.add_argument("--sample-every", type=int, default=1, help="dry run on every k-th member")
    args = parser.parse_args(argv)
    if args.apply and args.sample_every > 1:
        parser.error("--apply judges every member; drop --sample-every")
    MemberVerdictReport1d.apply = args.apply
    MemberVerdictReport1d.sample_every = args.sample_every
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(MemberVerdictReport1d(db_dsn=db_dsn).run())


if __name__ == "__main__":
    main()
