"""Hand-ledger idea import (phase 187 plan 13 Task 2): the parse; the DB write is register_idea's."""

from pathlib import Path

from scripts.research.import_ledger_ideas import LEDGER, parse_ledger

_FIXTURE = """# Ledger

## 1. Active queue

| # | Family | Status | Blocked on |
|---|---|---|---|
| 1 | Intraday periodicity (Heston 2010) | recorded | none |
| 1b | Residual first half hour | design | pre-registration |
| 9 | `generated_family`: a grammar | design | grammar |

## 2. Reopened

| Idea | Frozen verdict | Why | Enters as |
|---|---|---|---|
| `range_pct_fast_xs_ls_h5` (both forms) | DEAD | beta tilt | a family |
| TSMOM on the sleeve | FAIL | underpowered | residual momentum |

## 3. Open, never tested

| Idea | Where | Note |
|---|---|---|
| Overnight futures path to ETF open | `docs/research/data-edge-source-thesis.md` | never run |

## 4. Verdict record

| Idea | not imported |
|---|---|
| `x` | y |
"""


def test_every_table_row_of_sections_1_to_3_is_one_idea():
    ideas = parse_ledger(_FIXTURE)
    assert [(i.section, i.row) for i in ideas] == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (3, 1)]


def test_names_aliases_and_confidence():
    by = {(i.section, i.row): i for i in parse_ledger(_FIXTURE)}
    assert by[(1, 1)].alias == "family.intraday_periodicity" and by[(1, 1)].confidence == "high"
    assert by[(1, 2)].name == "residual_first_half_hour" and by[(1, 2)].confidence == "low"
    assert by[(1, 3)].name == "generated_family" and by[(1, 3)].confidence == "high"
    assert by[(2, 1)].name == "range_pct_fast_xs_ls_h5"
    assert by[(2, 2)].alias == "tsmom_sleeve"


def test_description_is_the_raw_row_and_sources_carry_the_anchor_and_paths():
    idea = parse_ledger(_FIXTURE)[-1]
    assert idea.description == (
        "Overnight futures path to ETF open | `docs/research/data-edge-source-thesis.md` | never run"
    )
    assert idea.sources == (
        f"{LEDGER}#section-3-row-1",
        "docs/research/data-edge-source-thesis.md",
    )


def test_real_ledger_parses_without_dropping_a_row_or_repeating_a_name():
    text = (Path(__file__).resolve().parents[3] / LEDGER).read_text()
    ideas = parse_ledger(text)
    rows = sum(
        1
        for section in (1, 2, 3)
        for line in text.split(f"## {section}. ", 1)[1].split("\n## ", 1)[0].splitlines()
        if line.startswith("|")
        and not set(line) <= set("|- :")
        and line.split("|")[1].strip() not in ("#", "Idea")
    )
    assert len(ideas) == rows >= 50
    assert len({i.name for i in ideas}) == len(ideas)
    assert all(i.description and i.name for i in ideas)
