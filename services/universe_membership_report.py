"""The membership build's counts-by-year view for the owner (todo 609, preregistration gate 5).

Read-only: it reads `universe_membership`, `universe_membership_build` and `instruments` (for the
seen-name holdout) and writes nothing; no bar table is read. It shows, per calendar year, the members
at the year's last built month-end by Massive type and the 5m tier, the cold-start share (member-days
whose residual history is shorter than a family's memory because of entry, `membership.
cold_start_share_by_year`), and the unplaced share of liquid rows when the pit capture's CSV is
given (`scripts/ops/bars/ops_pit_unplaced_share`); then the primary and core panel sizes over the
registered span.

It refuses, loudly, a ledger that is not the preregistered one: another rule id, a month-end that
is missing or extra against the NYSE calendar, or a month whose ledger count differs from its rows.

    .venv/bin/python -m services.universe_membership_report [--unplaced CSV] [--out FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import asyncpg
import numpy as np
import psycopg

from services.universe_membership_writer import candidates_at_l, month_ends_through
from src.config.settings import Settings
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.research import membership, snapshot
from src.intelligence.research.spec import load_spec_from_file
from src.intelligence.universe_membership import (
    ARCHIVE_START,
    CLOSED_LIST_CANDIDATES_SHA256,
    CLOSED_LIST_RULE_ID,
    candidates_digest,
    ledger_rule_label,
    ledger_rule_problem,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
# The registered daily specs the cold-start memory (declared_memory_rows) and the span are read from.
_PRIMARY_SPEC = "research/specs/daily_residual_h5.yaml"
_MEMORY_SPECS = (_PRIMARY_SPEC, "research/specs/seasonality_h5.yaml")


class MembershipReportRefused(RuntimeError):
    """The membership ledger is not the preregistered one; no view is produced."""


@dataclass(frozen=True)
class YearRow:
    year: int
    members: int  # at the year's last built month-end
    by_type: dict[str, int]
    tier_5m: int
    cold_start: dict[int, float]  # memory sessions -> share of member-days not yet warm
    unplaced_share: float | None


@dataclass(frozen=True)
class Report:
    rule_id: str
    months: int
    first_as_of: date
    last_as_of: date
    years: list[YearRow]
    ever_members: int
    ever_members_after_holdout: int
    core_members: int
    memories: tuple[int, ...]
    closed_list_months: int = 0
    candidates_live: str | None = None  # digest of the typed candidate set as the writer reads it


def check_ledger(
    ledger: Sequence[tuple[date, str, int]],
    row_counts: Mapping[date, int],
    *,
    month_ends: Sequence[date] | None = None,
) -> None:
    """Raise MembershipReportRefused unless the ledger is the preregistered build: every row under
    the rule id scheduled for its month-end, one month-end per NYSE month from the archive start through the last built
    one with none missing or extra, and each ledger count equal to its rows."""
    if not ledger:
        raise MembershipReportRefused("universe_membership_build is empty: the writer has not run")
    if problem := ledger_rule_problem((as_of, rule) for as_of, rule, _ in ledger):
        raise MembershipReportRefused(f"ledger differs from the preregistered rules: {problem}")
    built = [as_of for as_of, _, _ in ledger]
    expected = list(month_ends if month_ends is not None else month_ends_through(max(built)))
    missing, extra = sorted(set(expected) - set(built)), sorted(set(built) - set(expected))
    if missing or extra:
        raise MembershipReportRefused(
            f"ledger months differ from the NYSE month-ends since {ARCHIVE_START}: "
            f"missing {[str(d) for d in missing[:5]]}, extra {[str(d) for d in extra[:5]]}"
        )
    wrong = [str(a) for a, _, n in ledger if row_counts.get(a, 0) != n]
    if wrong:
        raise MembershipReportRefused(
            f"ledger n_members differs from the member rows at {wrong[:5]}"
        )


def unplaced_by_year(rows: Iterable[Mapping[str, str]]) -> dict[int, float]:
    """Year -> unplaced share of rows meeting the floor, from the unplaced-share CSV (all types)."""
    total: Counter[int] = Counter()
    unplaced: Counter[int] = Counter()
    for r in rows:
        year = int(r["year"])
        total[year] += int(r["rows_meeting_floor"])
        unplaced[year] += int(r["unplaced"])
    return {y: unplaced[y] / total[y] for y in total if total[y]}


def build_report(
    ledger: Sequence[tuple[date, str, int]],
    rows: Sequence[tuple[date, str, str, bool]],
    members_by_as_of: Mapping[date, frozenset[str]],
    sessions: np.ndarray,
    *,
    memories: Sequence[int],
    unplaced: Mapping[int, float] | None,
    ever_after_holdout: int,
    core_members: int,
    candidates_live: str | None = None,
) -> Report:
    """Counts by year for a checked ledger. `rows` are (as_of, symbol, security_type, tier_5m) of
    the whole table; `members_by_as_of` is the family-facing membership (holdout removed) the
    cold-start share is measured on; `sessions` the NYSE session dates the member mask spans."""
    last_by_year: dict[int, date] = {}
    for as_of, _, _ in ledger:
        last_by_year[as_of.year] = max(as_of, last_by_year.get(as_of.year, as_of))
    by_type: dict[date, Counter[str]] = defaultdict(Counter)
    tier: Counter[date] = Counter()
    counts: Counter[date] = Counter()
    for as_of, _, security_type, in_tier in rows:
        counts[as_of] += 1
        by_type[as_of][security_type] += 1
        tier[as_of] += bool(in_tier)
    symbols = sorted(set().union(*members_by_as_of.values()))
    mask = membership.member_mask(sessions, symbols, members_by_as_of)
    years = sessions.astype("datetime64[Y]").astype(int) + 1970
    cold = {m: membership.cold_start_share_by_year(mask, years, m) for m in memories}
    table = [
        YearRow(
            year=year,
            members=counts[last],
            by_type=dict(sorted(by_type[last].items())),
            tier_5m=tier[last],
            cold_start={m: cold[m].get(year, float("nan")) for m in memories},
            unplaced_share=None if unplaced is None else unplaced.get(year),
        )
        for year, last in sorted(last_by_year.items())
    ]
    built = [as_of for as_of, _, _ in ledger]
    return Report(
        rule_id=ledger_rule_label((as_of, rule) for as_of, rule, _ in ledger),
        months=len(ledger),
        first_as_of=min(built),
        last_as_of=max(built),
        years=table,
        ever_members=len({s for _, s, _, _ in rows}),
        ever_members_after_holdout=ever_after_holdout,
        core_members=core_members,
        memories=tuple(memories),
        closed_list_months=sum(rule == CLOSED_LIST_RULE_ID for _, rule, _ in ledger),
        candidates_live=candidates_live,
    )


def candidates_status(live: str | None) -> str:
    """MATCH when the live digest is the pinned one, MISMATCH when not, NOT READ without one."""
    if live is None:
        return "NOT READ"
    return "MATCH" if live == CLOSED_LIST_CANDIDATES_SHA256 else "MISMATCH"


async def _live_candidates_digest(dsn: str) -> str | None:
    """The live digest, or None (printed NOT READ) when the security_type table cannot be read."""
    conn = await asyncpg.connect(dsn)
    try:
        return candidates_digest(await candidates_at_l(conn))
    except (RuntimeError, asyncpg.UndefinedTableError) as error:
        print(f"candidate set not read: {error}", file=sys.stderr)
        return None
    finally:
        await conn.close()


def render(report: Report) -> str:
    types = sorted({t for y in report.years for t in y.by_type})
    head = ["year", "members", *types, "tier_5m"]
    head += [f"cold_{m}" for m in report.memories] + ["unplaced"]
    lines = [
        "cold_<n>: share of member-days with fewer than n sessions since first membership; n is a "
        "registered member's declared memory rows. The mask starts at the archive start, so 2003 "
        "and 2004 entrants count as cold here although the panel starts 2005-01-03.",
        f"rule {report.rule_id}; {report.months} month-ends {report.first_as_of} to {report.last_as_of}",
        f"ever members {report.ever_members}; after the seen-name holdout "
        f"{report.ever_members_after_holdout}; core panel {report.core_members}",
        f"closed list: {report.closed_list_months} month-end(s) after L; candidate set at L sha256 "
        f"live {report.candidates_live or 'not read'}, pinned {CLOSED_LIST_CANDIDATES_SHA256}: "
        f"{candidates_status(report.candidates_live)}",
        " ".join(f"{h:>9}" for h in head),
    ]
    for y in report.years:
        cells = [str(y.year), str(y.members), *(str(y.by_type.get(t, 0)) for t in types)]
        cells.append(str(y.tier_5m))
        cells += [f"{y.cold_start[m]:.3f}" for m in report.memories]
        cells.append("n/a" if y.unplaced_share is None else f"{y.unplaced_share:.4f}")
        lines.append(" ".join(f"{c:>9}" for c in cells))
    return "\n".join(lines)


def _read(dsn: str):
    """(ledger, per-month row counts, rows) from the tables; read-only."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT as_of, rule_id, n_members FROM universe_membership_build ORDER BY as_of"
        )
        ledger = [(a, r, int(n)) for a, r, n in cur.fetchall()]
        cur.execute("SELECT as_of, symbol, security_type, tier_5m FROM universe_membership")
        rows = cur.fetchall()
    return ledger, Counter(r[0] for r in rows), rows


def _memories() -> tuple[int, ...]:
    """The declared memory rows of the registered specs' members (slot history plus S1's loading
    reach): the residual history a family needs after a name's first membership, because S1 gives an
    entrant no loadings until it has finite rows in its window and the next refit."""
    found = set()
    for rel in _MEMORY_SPECS:
        spec = load_spec_from_file(REPO_ROOT / rel, root=REPO_ROOT).model
        found |= {m.declared_memory_rows for m in spec.members}
    return tuple(sorted(found))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unplaced", type=Path, help="CSV from ops_pit_unplaced_share")
    parser.add_argument("--out", type=Path, help="also write the table here (never overwritten)")
    args = parser.parse_args(argv)
    if args.out and args.out.exists():
        print(f"REFUSING: {args.out} exists; evidence is never overwritten", file=sys.stderr)
        return 2
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    ledger, row_counts, rows = _read(dsn)
    try:
        check_ledger(ledger, row_counts)
    except MembershipReportRefused as error:
        print(f"REFUSING: {error}", file=sys.stderr)
        return 2
    primary_spec = load_spec_from_file(REPO_ROOT / _PRIMARY_SPEC, root=REPO_ROOT).model
    panel = primary_spec.panel
    held = asyncio.run(
        snapshot.membership_inputs(
            dsn,
            "universe_membership",
            start=panel.start,
            end_exclusive=panel.end_exclusive,
            exclusion=panel.universe_exclusion,
        )
    )
    core = asyncio.run(
        snapshot.membership_inputs(
            dsn,
            "universe_membership_core",
            start=panel.start,
            end_exclusive=panel.end_exclusive,
            exclusion=panel.universe_exclusion,
        )
    )
    last = max(a for a, _, _ in ledger)
    covered_to = membership.covered_through(last)
    sessions = np.array(sorted(nyse_sessions(ARCHIVE_START, covered_to)), dtype="datetime64[D]")
    unplaced = None
    if args.unplaced:
        with args.unplaced.open(newline="") as handle:
            unplaced = unplaced_by_year(csv.DictReader(handle))
    report = build_report(
        ledger,
        rows,
        held.members_by_as_of,
        sessions,
        memories=_memories(),
        unplaced=unplaced,
        ever_after_holdout=len(held.symbols),
        core_members=len(core.symbols),
        candidates_live=asyncio.run(_live_candidates_digest(dsn)),
    )
    text = render(report)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    if candidates_status(report.candidates_live) == "MISMATCH":
        print("REFUSING: the candidate set at L moved since it was pinned", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
