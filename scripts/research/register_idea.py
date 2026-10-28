"""Log an idea the day it is had (187-12, design 10.2.5).

One `candidate` concept_registry row in a typed domain, no recipe and no gate. Recipes and
attempts are the S6 ledger's; this only gives the idea an identity.

    .venv/bin/python scripts/research/register_idea.py --domain family --name <id> \\
        --description "..." --source docs/ideas/<file>.md [--source ...] [--dry-run]
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
from src.intelligence.concept_registry_service import (  # noqa: E402
    IDEA_DOMAINS,
    ConceptExistsError,
    ConceptRegistryService,
)


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--domain", required=True, choices=sorted(IDEA_DOMAINS))
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--source", action="append", default=[], dest="sources")
    parser.add_argument("--author", default=getpass.getuser())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.name.strip() or not args.description.strip():
        parser.error("--name and --description must be non-empty")
    return args


async def _exists(conn, args: argparse.Namespace) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT 1 FROM concept_registry WHERE domain = $1 AND name = $2",
            args.domain,
            args.name,
        )
    )


async def _check(args: argparse.Namespace) -> bool:
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await connect_with_codecs(dsn)
    try:
        return await _exists(conn, args)
    finally:
        await conn.close()


async def _register(args: argparse.Namespace) -> str:
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await connect_with_codecs(dsn)
    try:
        return await ConceptRegistryService().register_idea(
            conn,
            domain=args.domain,
            name=args.name,
            description=args.description,
            sources=args.sources,
            author=args.author,
        )
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.dry_run:
        if asyncio.run(_check(args)):
            print(
                f"refused: concept_registry already has {args.domain}/{args.name}", file=sys.stderr
            )
            return 1
        print(
            f"candidate {args.domain}/{args.name} author={args.author} "
            f"sources={args.sources} description={args.description!r}"
        )
        return 0
    try:
        print(asyncio.run(_register(args)))
    except ConceptExistsError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
