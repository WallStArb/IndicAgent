"""Every recorded spec's hash is pinned (phase 187 plan 07, the E17 parity gate's first half).

A spec hash names a counted attempt: a spec.py change that moves one (a new field not routed
through `_OPTIONAL_*_FIELDS`, a canonical-form change) silently detaches every recorded run from
its spec. The literals were computed at HEAD on 2026-10-27 and cross-checked against the ledger:

    SELECT spec_path, spec_hash, count(*) FROM research_run GROUP BY 1, 2;

which held one row group per file below (family2_overnight_intraday has no run yet).
"""

from pathlib import Path

import pytest

from src.intelligence.research.spec import load_spec_from_file

ROOT = Path(__file__).resolve().parents[3]

PINNED = {
    "book_v1.yaml": "4cf8d2e98e5e140c120062c560b53b9914cc866581e9a992e38202193f9e2604",
    "family1_h2.yaml": "52184708730f79343ed9d44b2167e2e15b630175f11803cffad0a1d06bc7532e",
    "family1_h26.yaml": "53d3b9b3bfe6dbcd16189c67f68ac7ec425cc5baa82e4a28b5c62a722ef2c30f",
    "family1_h4.yaml": "4bfea743fd45f0060c9f30ff899b9b35a7e859f99619312694f8cf974825401b",
    "family1_h8.yaml": "950b7100ef299ba610cfb29a7506f4984a87729abeb0889a5aa13eecd15a01d7",
    "family1_intraday_periodicity.yaml": (
        "b828c285a369b97f35790585327e7a8d8ae98af2db65ec059204603fae172466"
    ),
    "daily_residual_h5.yaml": "30ba50bf93a4215f54b691f516f1f24f0cfbe3d94b1ad104688d3f630a4fc04a",
    "family2_overnight_intraday.yaml": (
        "e898745795b34ddc4b00f8de306c9f461d38f6e8b0112a8888d0f5f768c3d845"
    ),
}


def test_every_spec_file_is_pinned():
    assert sorted(p.name for p in (ROOT / "research/specs").glob("*.yaml")) == sorted(PINNED)


@pytest.mark.parametrize("name", sorted(PINNED))
def test_spec_hash_does_not_move(name):
    loaded = load_spec_from_file(ROOT / "research/specs" / name, root=ROOT)
    assert loaded.spec_hash == PINNED[name]
