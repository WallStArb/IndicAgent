"""ops_cutover_review.py - the per-name review gate before the first d2-v2 apply (plan 185-38).

Reads a daily-stage dry-run TSV (services/bar_derivation.py --stage daily --report) and fails
(exit 1, each name listed) on any name without an open 1d exception row in bar_source_policy
that would lose or alter stored data beyond threshold.bar_integrity.cutover_max_removed_share:
- removed / n_stored (stored bars deleted), or
- value-changed / n_stored, where value-changed = changed - changed_source_only (a relabel with
  equal values alters nothing), on a name whose stored series is Tradier or mixed. An IBKR-only
  name moving to Tradier is exempt from this measure: the admission sweep's evidence
  (ops_source_policy.py) is the review of that switch.
Refused-interior and refused-head shares above threshold.bar_integrity.cutover_max_refused_share
are reported as informational: a refusal that removes nothing stored loses no data (orchestrator
decision 2026-10-07, SIL and BNO; the thresholds were not changed). A refusal that does remove
stored bars is gated through the removed share. Exit 0 when no name fails. A failed review blocks the apply; the answer is evidence (an exception
row via ops_source_policy.py, or a fix), never a raised threshold.

The revision-ratio refusal is waived for every name at the first apply (no applied d2-v2 load
exists), so this review is the gate the waiver cannot bypass. One-off: 185-42 deletes it after the
cutover, and its two keys get retire: 185-43 entries then.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_apr_dict_async  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_KEY_REMOVED = "threshold.bar_integrity.cutover_max_removed_share"
_KEY_REFUSED = "threshold.bar_integrity.cutover_max_refused_share"
# Fallbacks equal to migration 454's seeds; the run reads APR.
_DEFAULT_REMOVED = 0.005
_DEFAULT_REFUSED = 0.005

_EXCEPTION_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM bar_source_policy
WHERE timeframe = '1d' AND symbol IS NOT NULL AND valid_to IS NULL
"""


@dataclass(frozen=True)
class Finding:
    symbol: str
    measure: str
    share: float
    limit: float

    def __str__(self) -> str:
        return f"{self.symbol}\t{self.measure}\t{self.share:.6f}\t> {self.limit:g}"


def _share(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _int(row: Mapping[str, str], key: str) -> int:
    return int(row.get(key) or 0)


def review(
    rows: Iterable[Mapping[str, str]],
    exceptions: frozenset[str],
    *,
    max_removed: float,
    max_refused: float,
) -> list[Finding]:
    """Every (name, measure) losing or altering stored data over its limit, for names without
    an exception row. max_refused is accepted for the informational report only."""
    findings: list[Finding] = []
    for row in rows:
        symbol = row["symbol"]
        if symbol in exceptions:
            continue
        stored = _int(row, "n_stored")
        measures = [("removed", _share(_int(row, "removed"), stored))]
        if row.get("group") != "ibkr_only":
            altered = _int(row, "changed") - _int(row, "changed_source_only")
            measures.append(("changed", _share(altered, stored)))
        for measure, share in measures:
            if share > max_removed:
                findings.append(Finding(symbol, measure, share, max_removed))
    return findings


def informational(rows: Iterable[Mapping[str, str]], *, max_refused: float) -> list[Finding]:
    """Refused-interior and refused-head shares over max_refused (reported, not gated)."""
    out: list[Finding] = []
    for row in rows:
        head, refused_head = _int(row, "head"), _int(row, "refused_head")
        for measure, share in (
            ("refused_interior", _share(_int(row, "refused_interior"), _int(row, "n_stored"))),
            ("refused_head", _share(refused_head, head + refused_head)),
        ):
            if share > max_refused:
                out.append(Finding(row["symbol"], measure, share, max_refused))
    return out


async def _context() -> tuple[frozenset[str], float, float]:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        apr = await load_apr_dict_async(conn, ["threshold.bar_integrity.%"])
        exceptions = frozenset(r[0] for r in await conn.fetch(_EXCEPTION_SYMBOLS_SQL))
    finally:
        await conn.close()
    return (
        exceptions,
        float(_cfg(apr, _KEY_REMOVED, _DEFAULT_REMOVED)),
        float(_cfg(apr, _KEY_REFUSED, _DEFAULT_REFUSED)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tsv", help="daily-stage dry-run report")
    args = parser.parse_args(argv)
    with Path(args.tsv).open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows or "refused_head" not in rows[0]:
        print(f"{args.tsv}: no rows or no refused_head column (a pre-185-38 report)")
        return 1
    exceptions, max_removed, max_refused = asyncio.run(_context())
    findings = review(rows, exceptions, max_removed=max_removed, max_refused=max_refused)
    print(
        f"names {len(rows)}; exception rows {len(exceptions)}; "
        f"max_removed_share {max_removed:g}; max_refused_share {max_refused:g}"
    )
    info = informational(rows, max_refused=max_refused)
    if info:
        print(f"INFO: {len(info)} refused share(s) over {max_refused:g} (reported, not gated)")
        print("symbol\tmeasure\tshare\tlimit")
        for finding in info:
            print(finding)
    if findings:
        print(f"FAIL: {len({f.symbol for f in findings})} name(s) over a limit")
        print("symbol\tmeasure\tshare\tlimit")
        for finding in findings:
            print(finding)
        return 1
    print("PASS: no name over a limit without an exception row")
    return 0


if __name__ == "__main__":
    sys.exit(main())
