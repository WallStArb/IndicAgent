"""Legacy card import (phase 187 plan 13 Task 1): the pure parse and the script's idempotence.
The database writes are covered in tests/integration/test_research_ledger.py."""

import asyncio
import hashlib
from pathlib import Path

import pytest

from scripts.research import import_legacy_cards as script
from src.intelligence.research import legacy_cards
from src.intelligence.research.legacy_cards import concept_name, load_cards, parse_front_matter

_CARD = """---
card_id: legacy-some-idea
kind: legacy_verdict
title: Some idea
verdict: DEAD
verdict_date: 2026-09-03
recipe:
  spec: null
  script: scripts/analysis/x.py
  recipe_commit: 0123456789abcdef0123456789abcdef01234567
results: []
reproducible: false
---

# Some idea
"""


def _write(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text)


def test_concept_name_follows_the_retyped_rows():
    assert concept_name("legacy-range-pct-fast-xs-ls-h5") == "range_pct_fast_xs_ls_h5"
    assert concept_name("legacy-phase148-alpha-score-directional") == (
        "phase148_alpha_score_directional"
    )


def test_only_legacy_verdict_cards_load_and_the_rest_are_counted(tmp_path):
    _write(tmp_path, "legacy-some-idea.md", _CARD)
    _write(tmp_path, "cache-x.md", _CARD.replace("legacy_verdict", "dead_cache"))
    _write(tmp_path, "README.md", "# readme")
    cards, skipped = load_cards(tmp_path)
    assert [c.card_id for c in cards] == ["legacy-some-idea"] and skipped == 1


def test_card_fields_are_copied_from_the_file(tmp_path):
    _write(tmp_path, "legacy-some-idea.md", _CARD)
    (card,), _ = load_cards(tmp_path)
    assert card.spec_hash == hashlib.sha256(_CARD.encode()).hexdigest()
    assert card.spec_path == "scripts/analysis/x.py"  # no spec: the script
    assert card.code_commit == "0123456789abcdef0123456789abcdef01234567"
    assert card.evidence["verdict_date"] == "2026-09-03"  # a date becomes its ISO string
    assert card.evidence["card_path"].endswith("legacy-some-idea.md")
    assert card.evidence["reproducible"] is False


def test_strict_loader_rejects_yaml_11_booleans():
    assert parse_front_matter("---\nreproducible: no\n---\n")["reproducible"] == "no"


def test_every_real_card_loads():
    cards, skipped = load_cards(script.CARD_DIR)
    assert len(cards) >= 26 and skipped >= 6
    assert len({c.card_id for c in cards}) == len(cards)
    assert len({c.spec_hash for c in cards}) == len(cards)


def test_second_run_imports_nothing(tmp_path, monkeypatch):
    _write(tmp_path, "legacy-some-idea.md", _CARD)
    cards, _ = load_cards(tmp_path)
    store: set[str] = set()

    async def existing(dsn):
        return set(store), set()

    class Ledger:
        def __init__(self, dsn):
            pass

        async def import_legacy_card(self, card):
            if card.card_id in store:
                return None
            store.add(card.card_id)
            return "run"

    monkeypatch.setattr(script, "_existing", existing)
    monkeypatch.setattr(script, "PostgresLedger", Ledger)
    first = asyncio.run(script.run("dsn", cards, apply=True))
    second = asyncio.run(script.run("dsn", cards, apply=True))
    assert first["imported"] == 1 and second["imported"] == 0 and second["already"] == 1


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    _write(tmp_path, "legacy-some-idea.md", _CARD)
    cards, _ = load_cards(tmp_path)

    async def existing(dsn):
        return set(), set()

    class Ledger:
        def __init__(self, dsn):
            pass

        async def import_legacy_card(self, card):
            pytest.fail("a dry run wrote")

    monkeypatch.setattr(script, "_existing", existing)
    monkeypatch.setattr(script, "PostgresLedger", Ledger)
    assert asyncio.run(script.run("dsn", cards, apply=False))["imported"] == 1


def test_selection_universe_excludes_legacy_rows():
    sql = Path(script.__file__).with_name("select_books.py").read_text()
    assert "r.kind IN ('evidence', 'book_test', 'pod_book')" in sql
    assert legacy_cards.LEGACY_VINTAGE == "legacy"
