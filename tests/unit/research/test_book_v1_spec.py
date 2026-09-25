"""Book version 1 conforms to the family 1 prereg section 5 and embeds the family spec."""

import shutil
from pathlib import Path

from src.intelligence.research.spec import BookSpec, FamilySpec, load_spec_from_file

ROOT = Path(__file__).resolve().parents[3]
BOOK = "research/specs/book_v1.yaml"
FAMILY = "research/specs/family1_intraday_periodicity.yaml"


def test_book_v1_values():
    loaded = load_spec_from_file(ROOT / BOOK, root=ROOT)
    book, (fam,) = loaded.model, [f.model for f in loaded.families]
    assert isinstance(book, BookSpec) and isinstance(fam, FamilySpec)
    assert book.families == [FAMILY]
    for field in ("construction", "scoring", "guards", "costs"):
        assert getattr(book, field) == getattr(fam, field), field
    assert book.power.planted_rank_ic == 0.002  # prereg section 5
    assert book.power.participation_ratio == 60.0  # D-20
    assert book.power.replicates == 100  # D-23
    assert len(fam.members) == 4  # all four members, none dropped


def test_book_hash_moves_with_the_family(tmp_path):
    for rel in (BOOK, FAMILY):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    before = load_spec_from_file(tmp_path / BOOK, root=tmp_path).spec_hash
    fam = tmp_path / FAMILY
    fam.write_text(fam.read_text().replace("seed: 183\n", "seed: 184\n", 1))
    assert load_spec_from_file(tmp_path / BOOK, root=tmp_path).spec_hash != before
