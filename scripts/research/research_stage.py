"""Have we tried this? The research stage of every concept (design 10.2.4, plan 187-11).

A read of the concept_research_stage view with each concept's latest recipe, never a write. A
concept's stage (idea, specified, registered, tested, refused, frozen, confirmed) is derived from
the registry, its recipes and its attempts; nothing stores it.

    .venv/bin/python scripts/research/research_stage.py --name periodicity
    .venv/bin/python scripts/research/research_stage.py --domain member
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402

_SQL = """
SELECT s.domain, s.name, s.stage, s.recipe_versions, s.attempts, s.started, s.tested,
       s.refused, s.legacy_verdicts, r.recipe_hash
FROM concept_research_stage s
LEFT JOIN concept_recipe r ON r.concept_id = s.concept_id AND r.version = s.latest_version
WHERE s.domain <> 'feature'
  AND ($1::text IS NULL OR s.domain = $1)
  AND ($2::text IS NULL OR s.name ILIKE '%' || $2 || '%')
ORDER BY s.domain, s.name
"""
_HEADER = ("domain", "concept", "stage", "recipe", "hash", "attempts", "tested", "refused")


def format_rows(rows: list[dict]) -> str:
    """One line per concept: stage, the latest recipe version and hash, attempt counts by status
    (started attempts are included in the total)."""
    table = [_HEADER] + [
        (
            r["domain"],
            r["name"],
            r["stage"],
            f"v{r['recipe_versions']}" if r["recipe_versions"] else "-",
            (r["recipe_hash"] or "-")[:12],
            f"{r['attempts']}" + (f" ({r['started']} started)" if r["started"] else ""),
            str(r["tested"]),
            str(r["refused"] + r["legacy_verdicts"]),
        )
        for r in rows
    ]
    widths = [max(len(str(line[i])) for line in table) for i in range(len(_HEADER))]
    return "\n".join(
        "  ".join(str(cell).ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in table
    )


async def _main(args: argparse.Namespace) -> int:
    dsn = args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await connect_with_codecs(dsn)
    try:
        rows = [dict(r) for r in await conn.fetch(_SQL, args.domain, args.name)]
    finally:
        await conn.close()
    if not rows:
        print("no concept matches: not tried (or not registered)")
        return 1
    print(format_rows(rows))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default=None, help="substring of the concept name")
    parser.add_argument("--domain", default=None, help="family, member, combiner, ... or book")
    parser.add_argument("--dsn", default=None, help="default: Settings().database_url")
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
