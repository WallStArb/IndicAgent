"""The have-we-tried-this printer (plan 187-11 Task 3); the view itself is proven against the
database in tests/integration/test_research_ledger.py."""

from scripts.research.research_stage import format_rows


def _row(**over):
    base = dict(
        domain="member",
        name="member.f.a",
        stage="tested",
        recipe_versions=2,
        attempts=5,
        started=0,
        tested=5,
        refused=0,
        legacy_verdicts=0,
        recipe_hash="ab" * 32,
    )
    return {**base, **over}


def test_a_tested_member_prints_its_recipe_and_counts():
    out = format_rows([_row()]).splitlines()
    assert out[0].split() == [
        "domain",
        "concept",
        "stage",
        "recipe",
        "hash",
        "attempts",
        "tested",
        "refused",
    ]
    assert out[1].split() == ["member", "member.f.a", "tested", "v2", "abababababab", "5", "5", "0"]


def test_an_idea_without_a_recipe_and_a_started_attempt_are_marked():
    idea = _row(name="x", stage="idea", recipe_versions=0, attempts=0, tested=0, recipe_hash=None)
    running = _row(name="y", stage="registered", attempts=1, started=1, tested=0)
    lines = format_rows([idea, running]).splitlines()
    assert lines[1].split()[3:5] == ["-", "-"]
    assert "1 (1 started)" in lines[2]


def test_refused_counts_include_legacy_verdicts():
    assert format_rows([_row(refused=1, legacy_verdicts=2)]).splitlines()[1].split()[-1] == "3"
