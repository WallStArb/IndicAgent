"""Load the hand ledger's ideas (sections 1 to 3) into UCR as idea rows (187-13, design 10.2.5).

Every table row of `docs/research/construction-verdict-ledger.md` sections 1 (active queue), 2
(reopened) and 3 (open, never tested) is one idea. A row whose backticked first token, a slug of
its text or an explicit alias names an existing concept is listed as a match and not duplicated;
every other row is written through ConceptRegistryService.register_idea as a `family` candidate
whose description is the row's raw text. Nothing is dropped: a row that does not parse into a
table cell, or whose name is a guess, is imported with `import_confidence: low`.

    .venv/bin/python scripts/research/import_ledger_ideas.py            # dry run
    .venv/bin/python scripts/research/import_ledger_ideas.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402
from src.intelligence.concept_registry_service import ConceptRegistryService  # noqa: E402

LEDGER = "docs/research/construction-verdict-ledger.md"
_SECTION_RE = re.compile(r"^## (\d+)\. ")
_NAME_TOKEN_RE = re.compile(r"^`([a-z0-9_]+)`")
_PATH_RE = re.compile(r"((?:docs|\.planning)/[\w./-]+\.md)")
_IDEA_SECTIONS = (1, 2, 3)

# Rows whose idea already has a concept under a different name than the row's text suggests
# (section 1 row 1 is the registered family 1; sections 2's two sleeve verdicts are cards).
ALIASES = {
    (1, "1"): "family.intraday_periodicity",
    (2, "Corpus features through the ensemble (phase 179)"): "phase179_sleeve_walk_forward",
    (2, "TSMOM on the sleeve"): "tsmom_sleeve",
}


@dataclass(frozen=True)
class LedgerIdea:
    section: int
    row: int
    name: str
    description: str
    sources: tuple[str, ...]
    confidence: str  # "high" when the row named its own concept, else "low"
    alias: str | None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _slug(text: str, words: int = 8) -> str:
    plain = re.sub(r"`", "", text.lower())
    tokens = re.findall(r"[a-z0-9]+", plain)[:words]
    return "_".join(tokens)[:60].strip("_")


def parse_ledger(text: str) -> list[LedgerIdea]:
    """One idea per table row of sections 1-3, in file order."""
    ideas: list[LedgerIdea] = []
    section = 0
    row = 0
    seen: set[str] = set()
    for line in text.splitlines():
        heading = _SECTION_RE.match(line)
        if heading:
            section, row = int(heading.group(1)), 0
            continue
        if section not in _IDEA_SECTIONS or not line.startswith("|"):
            continue
        cells = _cells(line)
        if cells[0] in ("#", "Idea") or set(line) <= set("|- :"):
            continue
        row += 1
        first = cells[1] if section == 1 and len(cells) > 1 else cells[0]
        key = cells[0] if section == 1 else first
        named = _NAME_TOKEN_RE.match(first)
        alias = ALIASES.get((section, key))
        name = named.group(1) if named else _slug(first)
        if name in seen:
            name = f"{name}_{section}_{row}"
        seen.add(name)
        raw = " | ".join(cells)
        ideas.append(
            LedgerIdea(
                section=section,
                row=row,
                name=name,
                description=raw,
                sources=(
                    f"{LEDGER}#section-{section}-row-{row}",
                    *dict.fromkeys(_PATH_RE.findall(raw)),
                ),
                confidence="high" if named or alias else "low",
                alias=alias,
            )
        )
    return ideas


def _author() -> str:
    out = subprocess.run(
        ["git", "config", "user.name"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip() or "unknown"


async def run(dsn: str, ideas: list[LedgerIdea], apply: bool) -> dict[str, int]:
    conn = await connect_with_codecs(dsn)
    counts = {"matched": 0, "new": 0}
    try:
        # Features are columns, not ideas: a backticked feature name in a row is not a match.
        known = {
            r["name"]
            for r in await conn.fetch("SELECT name FROM concept_registry WHERE domain <> 'feature'")
        }
        author = _author()
        for idea in ideas:
            target = idea.alias or idea.name
            if target in known or idea.alias in known or f"family.{target}" in known:
                print(f"match  s{idea.section}r{idea.row} {idea.name} -> {target}")
                counts["matched"] += 1
                continue
            print(f"new    s{idea.section}r{idea.row} {idea.name} ({idea.confidence})")
            counts["new"] += 1
            if apply:
                await ConceptRegistryService().register_idea(
                    conn,
                    domain="family",
                    name=idea.name,
                    description=idea.description,
                    sources=list(idea.sources),
                    author=author,
                    extra={"import_confidence": idea.confidence, "ledger_section": idea.section},
                )
                known.add(idea.name)
    finally:
        await conn.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    ledger = Path(__file__).resolve().parents[2] / LEDGER
    ideas = parse_ledger(ledger.read_text())
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    counts = asyncio.run(run(dsn, ideas, args.apply))
    verb = "wrote" if args.apply else "would write"
    print(f"{len(ideas)} ideas: {verb} {counts['new']}, matched {counts['matched']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
