#!/usr/bin/env python3
"""R-1: a member's mean session P&L and t in each sub-period its recorded runs declared.

Ledger 2026-11-23b (docs/plans/2026-11-23-reversal-21-replication-predeclaration-draft.md): a
disclosure, never a test. It reads the stored D_s series of recorded real evidence runs
(research_run_series) and the sub-periods of each run's own recorded spec (`scoring.sub_periods`,
read from the spec blob the run recorded, never chosen here), and prints one row per run group and
sub-period. It writes nothing, creates no series, no spec and no ledger row, and charges no look.
The two panels of a family share every date and the core names are a subset of the primary names,
so the cells are NOT INDEPENDENT of each other or of the runs they come from; the output says so.

The t is descriptive: a HAC t of the stored D_s over the cell (the E17 daily flat-top kernel with
overlap = horizon - 1 and the Newey-West taper), not the run's decision statistic, which reads an
influence series over the whole scored span.

Non-finite sessions are dropped before the HAC, so the finite sessions of a cell with gaps are
treated as consecutive; the report prints the non-finite count and the stored first and last
session of each cell, so a cell cut short by the stored span (the first sub-period starts before
the first scored session by design) is visible.

A cell never skips silently: a run group without exactly one completed real run of the member, an
empty sub-period, or fewer than 2 finite sessions in a cell stops the job (exit 1). A non-finite
session is counted and excluded from the cell, never read as zero. Sessions are calendar dates
exactly as stored (no timezone arithmetic).

    .venv/bin/python scripts/research/replication_subperiods.py \
        --run-groups c249e9bb d5a95034 --member reversal_21
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402
from src.intelligence.research.provenance import repo_root  # noqa: E402
from src.intelligence.research.spec import load_spec_from_blob  # noqa: E402
from src.intelligence.statistics.hac import hac_total_test  # noqa: E402

MIN_FINITE = 2  # hac_total_test's own floor; a thinner cell is an error, not a skipped cell

_RUN_SQL = """
SELECT r.run_id::text AS run_id, r.run_group::text AS run_group, c.name AS concept,
       r.spec_hash, r.spec_path, r.spec_blob, s.sessions, s.d_s
FROM research_run r
JOIN concept_registry c USING (concept_id)
LEFT JOIN research_run_series s USING (run_id)
WHERE r.run_group::text LIKE $1 || '%'
  AND r.kind = 'evidence' AND r.mode = 'real' AND r.status = 'completed'
  AND c.name LIKE 'member.%' AND right(c.name, length($2) + 1) = '.' || $2
"""


class ReplicationError(RuntimeError):
    """A cell or a run that cannot be read as declared; the job stops, nothing is skipped."""


@dataclass(frozen=True)
class Cell:
    start: date
    end: date
    n_sessions: int  # stored sessions inside the sub-period
    n_finite: int
    n_nonfinite: int  # counted and excluded, never read as zero
    mean_session_pnl: float
    t: float
    p: float  # one-sided, descriptive
    first_session: date | None = None  # first and last stored session inside the cell: a cell
    last_session: date | None = None  # cut short by the stored span shows here


def cell_stats(
    sessions: Sequence[date], d_s: Sequence[float], start: date, end: date, overlap: int
) -> Cell:
    """The cell over start..end inclusive. Raises when it holds no stored session or fewer than
    MIN_FINITE finite ones."""
    if len(sessions) != len(d_s):
        raise ReplicationError(f"series lengths differ: {len(sessions)} sessions, {len(d_s)} d_s")
    inside = np.array([start <= s <= end for s in sessions], dtype=bool)
    stored = [s for s, keep in zip(sessions, inside) if keep]
    x = np.asarray(d_s, dtype=np.float64)[inside]
    finite = x[np.isfinite(x)]
    if not x.size:
        raise ReplicationError(f"sub-period {start}..{end} holds no stored session")
    if finite.size < MIN_FINITE:
        raise ReplicationError(
            f"sub-period {start}..{end} holds {finite.size} finite sessions, need {MIN_FINITE}"
        )
    res = hac_total_test(float(finite.sum()), finite, int(finite.size), overlap)
    return Cell(
        start,
        end,
        int(x.size),
        int(finite.size),
        int(x.size - finite.size),
        float(finite.mean()),
        float(res.t),
        float(res.p),
        min(stored),
        max(stored),
    )


def run_cells(row: dict, root: Path) -> list[Cell]:
    """The cells of one recorded run, with the sub-periods and horizon of its own recorded spec."""
    try:
        spec = load_spec_from_blob(root, row["spec_path"], row["spec_blob"]).model
    except (subprocess.CalledProcessError, OSError) as error:
        raise ReplicationError(f"run {row['run_id']}: spec blob unreadable: {error}") from error
    overlap = spec.horizon - 1
    return [
        cell_stats(
            row["sessions"], row["d_s"], date.fromisoformat(a), date.fromisoformat(b), overlap
        )
        for a, b in spec.scoring.sub_periods
    ]


async def load_rows(dsn: str, run_groups: Sequence[str], member: str) -> list[dict]:
    """One recorded run per run group, in the order given; exactly one or the job stops."""
    conn = await connect_with_codecs(dsn)
    try:
        out = []
        for group in run_groups:
            rows = await conn.fetch(_RUN_SQL, group, member)
            if len(rows) != 1:
                raise ReplicationError(
                    f"run group {group!r} holds {len(rows)} completed real evidence runs of "
                    f"member {member!r}, expected exactly 1"
                )
            row = dict(rows[0])
            if row["sessions"] is None or row["d_s"] is None:
                raise ReplicationError(f"run {row['run_id']} has no stored series")
            out.append(row)
        return out
    finally:
        await conn.close()


def format_report(member: str, results: list[tuple[dict, list[Cell]]]) -> str:
    """`results` pairs each run's identifying fields (run_group, spec_hash, concept) with its cells."""
    lines = [
        f"R-1 sub-period disclosure for {member} (ledger 2026-11-23b)",
        "NOT INDEPENDENT: the panels share every date, the core names are a subset of the primary "
        "names, and every cell reads series of runs already counted. Non-gating; promotes nothing; "
        "charges no look. t is a descriptive HAC t of the stored D_s over the cell, not the "
        "run's decision statistic.",
        "",
    ]
    for row, cells in results:
        lines.append(
            f"run group {row['run_group'][:8]}  spec {row['spec_hash'][:8]}  {row['concept']}"
        )
        for c in cells:
            sign = "positive" if c.mean_session_pnl > 0 else "NON-POSITIVE"
            lines.append(
                f"  {c.start} to {c.end}  stored {c.first_session} to {c.last_session}  "
                f"sessions {c.n_sessions} (finite {c.n_finite}, "
                f"non-finite {c.n_nonfinite})  mean session P&L {c.mean_session_pnl:+.3e}  "
                f"t {c.t:+.2f}  one-sided p {c.p:.4f}  {sign}"
            )
    n = sum(len(cells) for _, cells in results)
    nonpos = sum(c.mean_session_pnl <= 0 for _, cells in results for c in cells)
    lines += ["", f"cells {n}, non-positive {nonpos}"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-groups", nargs="+", required=True, help="run group id prefixes")
    parser.add_argument("--member", required=True, help="member name, for example reversal_21")
    parser.add_argument("--dsn", default=None, help="default: Settings().database_url")
    args = parser.parse_args()
    if len(set(args.run_groups)) != len(args.run_groups):
        print("error: a run group is listed twice", file=sys.stderr)
        return 1
    dsn = args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        rows = asyncio.run(load_rows(dsn, args.run_groups, args.member))
        root = repo_root(Path.cwd())
        results = [(row, run_cells(row, root)) for row in rows]
    except (ReplicationError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(format_report(args.member, results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
