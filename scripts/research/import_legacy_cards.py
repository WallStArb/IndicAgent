"""Load every legacy_verdict summary card as a research_run attempt (187-13, design 10.2.3).

The S6 ledger writes the rows; this script reads the cards and prints the mapping. Idempotent by
card_id: a second run imports nothing. dead_cache cards are counted and skipped.

    .venv/bin/python scripts/research/import_legacy_cards.py            # dry run
    .venv/bin/python scripts/research/import_legacy_cards.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402
from src.intelligence.research.ledger import PostgresLedger  # noqa: E402
from src.intelligence.research.legacy_cards import LegacyCard, load_cards  # noqa: E402

CARD_DIR = Path(__file__).resolve().parents[2] / "docs" / "research" / "summary-cards"


async def _existing(dsn: str) -> tuple[set[str], set[str]]:
    """(card_ids already imported, family names already registered)."""
    conn = await connect_with_codecs(dsn)
    try:
        done = {
            r["card_id"]
            for r in await conn.fetch(
                "SELECT evidence->>'card_id' AS card_id FROM research_run "
                "WHERE kind = 'legacy_verdict'"
            )
        }
        names = {
            r["name"]
            for r in await conn.fetch("SELECT name FROM concept_registry WHERE domain = 'family'")
        }
        return done, names
    finally:
        await conn.close()


async def run(dsn: str, cards: list[LegacyCard], apply: bool) -> dict[str, int]:
    done, names = await _existing(dsn)
    counts = {"imported": 0, "already": 0, "new_family": 0}
    ledger = PostgresLedger(dsn)
    for card in cards:
        status = "already" if card.card_id in done else "import"
        target = "matches" if card.concept_name in names else "new family"
        print(f"{status:8s} {card.card_id} -> {card.concept_name} ({target})")
        if card.card_id in done:
            counts["already"] += 1
            continue
        if apply:
            if await ledger.import_legacy_card(card) is None:
                counts["already"] += 1
                continue
        counts["imported"] += 1
        counts["new_family"] += card.concept_name not in names
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    cards, skipped = load_cards(CARD_DIR)
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    counts = asyncio.run(run(dsn, cards, args.apply))
    verb = "wrote" if args.apply else "would write"
    print(
        f"{verb} {counts['imported']} (new families {counts['new_family']}); "
        f"{counts['already']} already imported; {skipped} dead_cache cards skipped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
