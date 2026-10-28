"""Summary cards as ledger input (phase 187 plan 13, design 10.2.3): a pure parse of
`docs/research/summary-cards/*.md` into the fields S6 writes as a `legacy_verdict` attempt.

Numbers are copied, never recomputed: `evidence` is the card's front matter verbatim (dates as
ISO strings) plus `card_path`. Only `kind: legacy_verdict` cards load; `dead_cache` cards record
dropped caches, not verdicts, and stay files. No I/O beyond reading the card files.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

LEGACY_VINTAGE = "legacy"


class CardLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false. YAML 1.1 also reads yes/no/on/off
    as booleans, which would let `reproducible: no` pass silently as False."""


CardLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
CardLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def parse_front_matter(text: str, name: str = "card") -> dict[str, Any]:
    """Front matter of a card via the strict loader. Raises on missing fences."""
    if not text.startswith("---\n"):
        raise ValueError(f"{name}: card must start with a '---' front matter fence")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{name}: card front matter has no closing '---' fence")
    front = yaml.load(text[4:end], Loader=CardLoader)
    if not isinstance(front, dict):
        raise ValueError(f"{name}: front matter must be a YAML mapping")
    return front


def _iso(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_iso(v) for v in value]
    return value


@dataclass(frozen=True)
class LegacyCard:
    card_id: str
    concept_name: str
    title: str
    spec_path: str
    spec_hash: str
    spec_blob: str
    code_commit: str
    evidence: dict[str, Any]


def concept_name(card_id: str) -> str:
    """`legacy-range-pct-fast` -> `range_pct_fast`: the name plan 11 gave the retyped rows."""
    return card_id.removeprefix("legacy-").replace("-", "_")


def load_cards(card_dir: Path) -> tuple[list[LegacyCard], int]:
    """(every legacy_verdict card sorted by card_id, count of other-kind cards skipped)."""
    cards: list[LegacyCard] = []
    skipped = 0
    for path in sorted(card_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        raw = path.read_bytes()
        text = raw.decode()
        front = parse_front_matter(text, path.name)
        if front.get("kind") != "legacy_verdict":
            skipped += 1
            continue
        recipe = front["recipe"]
        relative = f"docs/research/summary-cards/{path.name}"
        cards.append(
            LegacyCard(
                card_id=front["card_id"],
                concept_name=concept_name(front["card_id"]),
                title=front["title"],
                spec_path=recipe.get("spec") or recipe.get("script") or relative,
                spec_hash=hashlib.sha256(raw).hexdigest(),
                spec_blob=text,
                code_commit=recipe["recipe_commit"],
                evidence={**_iso(front), "card_path": relative},
            )
        )
    return cards, skipped
