"""Pod book spec kind (plan 187-10 Task 1)."""

import json
import textwrap

import pytest

from src.intelligence.research.spec import PodBookSpec, load_spec_from_file, parse_spec_text
from tests.unit.research.test_spec import BOOK, FAMILY

RUN_A = "0b8e3c1a-1111-4a2b-9c3d-000000000001"
RUN_B = "0b8e3c1a-2222-4a2b-9c3d-000000000002"
SHA = "ab" * 32


def _pod(books=("research/specs/book_a.yaml", "research/specs/book_b.yaml")):
    members = "".join(
        f"\n      - {{book: {b}, run_id: {r}, series_sha256: {SHA}}}"
        for b, r in zip(books, (RUN_A, RUN_B, RUN_A), strict=False)
    )
    return textwrap.dedent("""
        kind: pod_book
        pod: pod_one
        prior_source: docs/plans/prereg.md
        books:""") + members + "\n"


def _repo(tmp_path, pod_text=None):
    specs = tmp_path / "research/specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / "fam.yaml").write_text(FAMILY)
    (specs / "book_a.yaml").write_text(BOOK)
    (specs / "book_b.yaml").write_text(BOOK.replace("book: book_one", "book: book_two"))
    (specs / "pod.yaml").write_text(pod_text or _pod())
    return specs / "pod.yaml"


def test_a_pod_parses_and_embeds_each_member_book(tmp_path):
    loaded = load_spec_from_file(_repo(tmp_path), root=tmp_path)
    assert isinstance(loaded.model, PodBookSpec)
    assert [b.model.book for b in loaded.books] == ["book_one", "book_two"]
    canonical = json.loads(loaded.canonical)
    assert canonical["pod"]["books"][0]["run_id"] == RUN_A
    assert [b["book"]["book"] for b in canonical["books"]] == ["book_one", "book_two"]
    assert canonical["books"][0]["families"][0]["family"] == "fam_one"


def test_editing_a_member_book_or_its_family_moves_the_pod_hash(tmp_path):
    path = _repo(tmp_path)
    base = load_spec_from_file(path, root=tmp_path).spec_hash
    book_b = tmp_path / "research/specs/book_b.yaml"
    book_b.write_text(book_b.read_text().replace("prereg.md", "prereg2.md"))
    edited_book = load_spec_from_file(path, root=tmp_path).spec_hash
    assert edited_book != base
    fam = tmp_path / "research/specs/fam.yaml"
    fam.write_text(fam.read_text().replace("prereg.md", "prereg2.md"))
    assert load_spec_from_file(path, root=tmp_path).spec_hash not in (base, edited_book)


def test_repinning_a_member_attempt_moves_the_pod_hash(tmp_path):
    base = load_spec_from_file(_repo(tmp_path), root=tmp_path).spec_hash
    repinned = _pod().replace(RUN_B, RUN_B[:-1] + "9")
    assert load_spec_from_file(_repo(tmp_path, repinned), root=tmp_path).spec_hash != base


@pytest.mark.parametrize(
    "text",
    [
        _pod(books=("research/specs/book_a.yaml",)),  # one member
        _pod(books=("research/specs/book_a.yaml", "research/specs/book_a.yaml")),  # duplicate
        _pod(books=("research/specs/book_a.yaml", "elsewhere/book_b.yaml")),  # outside specs
        _pod().replace(RUN_A, "not-a-run-id"),
        _pod().replace(SHA, "AB" * 32),  # not lowercase hex
        _pod() + "extra: 1\n",
    ],
)
def test_malformed_pods_are_refused(text):
    with pytest.raises(ValueError):
        parse_spec_text(text)


def test_a_pod_may_only_name_book_specs(tmp_path):
    text = _pod(books=("research/specs/book_a.yaml", "research/specs/fam.yaml"))
    with pytest.raises(ValueError, match="book specs"):
        load_spec_from_file(_repo(tmp_path, text), root=tmp_path)
