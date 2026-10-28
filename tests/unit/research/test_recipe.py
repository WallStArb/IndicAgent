"""Recipe content and hashing (plan 187-11 Task 2): deterministic, and a change moves exactly
the concepts it touches."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from src.intelligence.research.recipe import (
    RecipeContent,
    book_recipes,
    family_recipes,
    pod_recipes,
    pointer,
)
from src.intelligence.research.spec import load_spec_from_file

ROOT = Path(__file__).resolve().parents[3]
BOOK = "research/specs/book_v1.yaml"
FAMILY = "research/specs/family1_intraday_periodicity.yaml"
APR = {"alpha.research.budget_m": 30, "alpha.research.screen_alpha": 0.05}


@pytest.fixture
def specs(tmp_path):
    shutil.copytree(ROOT / "research/specs", tmp_path / "research/specs")
    return tmp_path


def _hashes(root, apr=APR):
    loaded = load_spec_from_file(root / BOOK, root=root)
    return {name: r.recipe_hash for name, r in book_recipes(loaded, apr).items()}


def _edit(root, rel, old, new):
    path = root / rel
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def _moved(before, after):
    assert before.keys() == after.keys()
    return {k for k in before if before[k] != after[k]}


BOOK_CONCEPT = "book.book_v1"
RIDGE = "combiner.ridge"
RULE = "construction_rule.rank_vol_neutral"
MEMBER5 = "member.intraday_periodicity.same_slot_mean5"
OTHER_MEMBERS = {
    "member.intraday_periodicity.same_slot_lag1",
    "member.intraday_periodicity.same_slot_mean20",
    "member.intraday_periodicity.same_slot_mean40",
}


def test_every_concept_of_a_book_has_a_recipe(specs):
    loaded = load_spec_from_file(specs / BOOK, root=specs)
    names = set(book_recipes(loaded, APR))
    assert names == {BOOK_CONCEPT, RIDGE, RULE, "family.intraday_periodicity", MEMBER5} | (
        OTHER_MEMBERS
    )


def test_the_same_spec_hashes_the_same_in_this_and_another_process(specs):
    here = _hashes(specs)
    assert _hashes(specs) == here
    code = (
        "import sys, json; from pathlib import Path; "
        "from src.intelligence.research.recipe import book_recipes; "
        "from src.intelligence.research.spec import load_spec_from_file; "
        "root = Path(sys.argv[1]); l = load_spec_from_file(root / 'research/specs/book_v1.yaml', "
        "root=root); print(json.dumps({n: r.recipe_hash for n, r in "
        f"book_recipes(l, {APR!r}).items()}}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(specs)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout
    assert json.loads(out) == here


def test_a_member_param_moves_that_member_and_the_book_only(specs):
    before = _hashes(specs)
    _edit(specs, FAMILY, "params: {window_sessions: 5}", "params: {window_sessions: 6}")
    assert _moved(before, _hashes(specs)) == {MEMBER5, BOOK_CONCEPT}


def test_a_combiner_field_moves_the_combiner_and_the_book_only(specs):
    before = _hashes(specs)
    _edit(specs, BOOK, "penalty: 1.0", "penalty: 2.0")
    assert _moved(before, _hashes(specs)) == {RIDGE, BOOK_CONCEPT}


def test_a_construction_field_moves_the_rule_and_the_book_only(specs):
    before = _hashes(specs)
    _edit(specs, BOOK, "direction: 1  # continuation", "direction: -1  # continuation")
    assert _moved(before, _hashes(specs)) == {RULE, BOOK_CONCEPT}


def test_a_horizon_rule_moves_the_combiner_and_the_book_only(specs):
    before = _hashes(specs)
    _edit(specs, BOOK, "construction:  # prereg 4, R1", "horizon_rule: {kappa: 0.5}\nconstruction:")
    assert _moved(before, _hashes(specs)) == {RIDGE, BOOK_CONCEPT}


def test_an_apr_value_the_book_depends_on_moves_the_book_only(specs):
    before = _hashes(specs)
    assert _moved(before, _hashes(specs, {**APR, "alpha.research.budget_m": 31})) == {BOOK_CONCEPT}


def test_the_family_recipe_alone_covers_the_family_and_its_members(specs):
    loaded = load_spec_from_file(specs / FAMILY, root=specs)
    recipes = family_recipes(loaded)
    assert len(recipes) == 5
    book = book_recipes(load_spec_from_file(specs / BOOK, root=specs), APR)
    assert {n: r.recipe_hash for n, r in recipes.items()} == {
        n: book[n].recipe_hash for n in recipes
    }


def test_a_recipe_carries_valid_pointers_and_codes(specs):
    loaded = load_spec_from_file(specs / BOOK, root=specs)
    for recipe in book_recipes(loaded, APR).values():
        module, _, name = recipe.code_pointer.partition(":")
        assert module and name and all(p.isidentifier() for p in module.split("."))
        assert name.isidentifier()
        assert recipe.sources and recipe.mechanism
    recipes = book_recipes(loaded, APR)
    assert recipes[RULE].cvr_codes == {"research_construction_rule": "rank_vol_neutral"}
    assert recipes[BOOK_CONCEPT].cvr_codes == {
        "research_combiner": "ridge",
        "research_construction_rule": "rank_vol_neutral",
        "research_timeframe": "15m",
    }


def test_the_concept_name_is_part_of_the_hash():
    a = RecipeContent("member.x.a", "m:f", {}, {}, (), None, {}, None, ())
    b = RecipeContent("member.x.b", "m:f", {}, {}, (), None, {}, None, ())
    assert a.recipe_hash != b.recipe_hash


def test_pointer_splits_the_last_segment():
    assert pointer("a.b.c") == "a.b:c"
    with pytest.raises(ValueError):
        pointer("nodots")


def test_a_pod_recipe_pins_its_members():
    from src.intelligence.research.pod import series_sha256
    from tests.unit.research.test_pod_book import RUNS, A, B, _pod_repo

    with tempfile.TemporaryDirectory() as tmp:
        pins = [("a", RUNS[0], series_sha256(A)), ("b", RUNS[1], series_sha256(B))]
        loaded = _pod_repo(Path(tmp), pins)
        (recipe,) = pod_recipes(loaded).values()
        assert recipe.concept == "pod.pod_one"
        assert [i["run_id"] for i in recipe.inputs] == list(RUNS)
        assert recipe.cvr_codes == {"research_combiner": "pod"}
