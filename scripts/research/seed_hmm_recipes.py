"""Write version 1 recipes for the HMM feature columns migration 533 registered (187-12).

The recipe book's one writer is the S6 ledger; this one-shot command hands it the recipes of
the eleven regime-writer columns that had no concept_registry row. The expected set, the code
pointer and the code commit are literals checked by tests; the command asserts the exact set
of unrecipe'd HMM columns before and after, so a renamed column or a partial seed fails loudly.

    .venv/bin/python scripts/research/seed_hmm_recipes.py            # dry run
    .venv/bin/python scripts/research/seed_hmm_recipes.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402
from src.intelligence.research.ledger import PostgresLedger  # noqa: E402
from src.intelligence.research.recipe import RecipeContent  # noqa: E402

EXPECTED_COLUMNS = frozenset(
    {
        "hmm_prob_trending_up",
        "hmm_prob_trending_down",
        "hmm_prob_ranging",
        "hmm_churn",
        "hmm_vol_regime_prob",
        "hmm_vol_prob_calm",
        "hmm_vol_prob_elevated",
        "hmm_vol_prob_turbulent",
        "hmm_vol_entropy",
        "hmm_vol_duration",
        "hmm_vol_churn",
    }
)
# The function that writes every regime-writer-owned column; the commit is the last one to
# touch services/regime_writer.py when this plan was authored (git log -1 -- that file).
CODE_POINTER = "services.regime_writer:_write_family_results"
CODE_COMMIT = "8002643492dad1e37a212b47c53c690043912185"
SOURCE = "src/intelligence/features/kernels/_hmm.py"

_MISSING_SQL = """
SELECT r.name FROM concept_registry r
WHERE r.domain = 'feature' AND r.name = ANY($1::text[])
  AND NOT EXISTS (SELECT 1 FROM concept_recipe c WHERE c.concept_id = r.concept_id)
"""
_REGISTERED_SQL = (
    "SELECT name FROM concept_registry WHERE domain = 'feature' AND name = ANY($1::text[])"
)


def recipes() -> dict[str, RecipeContent]:
    return {
        name: RecipeContent(
            concept=name,
            code_pointer=CODE_POINTER,
            params={},
            apr_values={},
            inputs=(),
            universe_selector=None,
            cvr_codes={"composition": "base"},
            mechanism="HMM posterior or run-length statistic over the symbol's own bars",
            sources=(SOURCE,),
        )
        for name in sorted(EXPECTED_COLUMNS)
    }


async def _names(dsn: str, sql: str) -> set[str]:
    conn = await connect_with_codecs(dsn)
    try:
        return {r["name"] for r in await conn.fetch(sql, sorted(EXPECTED_COLUMNS))}
    finally:
        await conn.close()


async def _seed(dsn: str, apply: bool) -> int:
    registered = await _names(dsn, _REGISTERED_SQL)
    if registered != EXPECTED_COLUMNS:
        print(f"refused: registered HMM columns differ: {sorted(EXPECTED_COLUMNS - registered)}")
        return 1
    before = await _names(dsn, _MISSING_SQL)
    if before != EXPECTED_COLUMNS:
        print(f"refused: expected all 11 columns without a recipe, found {len(before)} (run once)")
        return 1
    if not apply:
        print(
            f"dry run: would write {len(EXPECTED_COLUMNS)} version 1 recipes at {CODE_COMMIT[:9]}"
        )
        return 0
    await PostgresLedger(dsn).seed_recipes(
        "feature", recipes(), code_commit=CODE_COMMIT, author=getpass.getuser()
    )
    after = await _names(dsn, _MISSING_SQL)
    if after:
        raise RuntimeError(f"columns still without a recipe after the seed: {sorted(after)}")
    print(f"wrote {len(EXPECTED_COLUMNS)} recipes")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    return asyncio.run(_seed(dsn, args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
