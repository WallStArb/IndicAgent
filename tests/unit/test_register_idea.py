"""Unit tests: scripts/research/register_idea.py (187-12)."""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from scripts.research import register_idea
from src.intelligence.concept_registry_service import ConceptExistsError

_ARGV = ["--domain", "family", "--name", "gap_reversal", "--description", "d", "--source", "a.md"]


def test_dry_run_prints_the_row_and_writes_nothing(capsys, monkeypatch):
    async def absent(args):
        return False

    monkeypatch.setattr(register_idea, "_register", lambda args: pytest.fail("wrote"))
    monkeypatch.setattr(register_idea, "_check", absent)
    assert register_idea.main([*_ARGV, "--dry-run"]) == 0
    assert "candidate family/gap_reversal" in capsys.readouterr().out


def test_dry_run_refuses_an_existing_name(capsys, monkeypatch):
    async def present(args):
        return True

    monkeypatch.setattr(register_idea, "_check", present)
    assert register_idea.main([*_ARGV, "--dry-run"]) == 1
    assert "refused" in capsys.readouterr().err


def test_feature_domain_and_empty_text_are_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        register_idea.main(["--domain", "feature", "--name", "x", "--description", "d"])
    with pytest.raises(SystemExit):
        register_idea.main(["--domain", "family", "--name", " ", "--description", "d"])


def test_invalid_domain_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        register_idea.main(["--domain", "ensemble_strategy", "--name", "x", "--description", "d"])


def test_registered_idea_prints_its_concept_id(capsys, monkeypatch):
    async def fake(args):
        return "abc"

    monkeypatch.setattr(register_idea, "_register", fake)
    assert register_idea.main(_ARGV) == 0
    assert capsys.readouterr().out.strip() == "abc"


def test_existing_name_exits_nonzero(capsys, monkeypatch):
    async def fake(args):
        raise ConceptExistsError("already")

    monkeypatch.setattr(register_idea, "_register", fake)
    assert register_idea.main(_ARGV) == 1
    assert "refused" in capsys.readouterr().err
