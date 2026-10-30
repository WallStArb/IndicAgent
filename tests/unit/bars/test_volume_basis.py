"""The volume basis mapping (todo 555): one table, unknown pairs raise, grid bars inherit."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.bars.sources import CANONICAL_1D_SOURCES
from src.intelligence.bars.vendor_kind import (
    VOLUME_BASIS_BY_VENDOR_KIND,
    VOLUME_BASIS_CONSOLIDATED,
    VOLUME_BASIS_MIXED,
    VOLUME_BASIS_NONE,
    VOLUME_BASIS_SMART,
    grid_volume_basis,
    volume_basis,
)

# Every (vendor, kind) canonical market_data_ohlcv holds on 2026-10-28, plus the kinds the
# 1d daily rule and the IBKR smart_trades re-derive will write.
CANONICAL_PAIRS = {
    ("alpaca", "sip_rth"): VOLUME_BASIS_CONSOLIDATED,
    ("ibkr", "named"): VOLUME_BASIS_SMART,
    ("ibkr", "smart_trades"): VOLUME_BASIS_SMART,
    ("ibkr", "fallback"): VOLUME_BASIS_SMART,
    ("ibkr", "venue"): VOLUME_BASIS_NONE,
}


def test_every_canonical_pair_is_mapped():
    assert VOLUME_BASIS_BY_VENDOR_KIND == CANONICAL_PAIRS
    for pair, name in CANONICAL_PAIRS.items():
        assert volume_basis(*pair) == name


@pytest.mark.parametrize("pair", [("alpaca", "iex_rth"), ("ibkr", "smart_adjusted"), ("x", "y")])
def test_an_unmapped_pair_raises(pair):
    with pytest.raises(ValueError, match="no volume basis"):
        volume_basis(*pair)


def test_a_derived_pair_has_no_basis_of_its_own():
    with pytest.raises(ValueError, match="constituents"):
        volume_basis("derived", "5m_grid")


def test_grid_bar_is_mixed_only_when_constituents_differ():
    stamps = np.arange(0, 6 * 300, 300)
    bases = [VOLUME_BASIS_CONSOLIDATED] * 4 + [VOLUME_BASIS_SMART] * 2
    assert grid_volume_basis([0, 900], 15, stamps, bases).tolist() == [
        VOLUME_BASIS_CONSOLIDATED,
        VOLUME_BASIS_MIXED,
    ]


def test_a_grid_bar_never_reads_constituents_past_the_next_grid_stamp():
    stamps = np.arange(0, 4 * 300, 300)
    bases = [VOLUME_BASIS_SMART] * 2 + [VOLUME_BASIS_CONSOLIDATED] * 2
    assert grid_volume_basis([0, 600], 60, stamps, bases).tolist() == [
        VOLUME_BASIS_SMART,
        VOLUME_BASIS_CONSOLIDATED,
    ]


def test_a_grid_bar_without_a_constituent_raises():
    with pytest.raises(ValueError, match="no 5m constituent"):
        grid_volume_basis([10_000], 15, np.array([0, 300]), [VOLUME_BASIS_SMART] * 2)


def test_stamp_and_basis_lengths_must_match():
    with pytest.raises(ValueError, match="constituent stamps"):
        grid_volume_basis([0], 15, np.array([0, 300]), [VOLUME_BASIS_SMART])


def test_every_canonical_1d_source_has_a_basis():
    for pair in CANONICAL_1D_SOURCES:
        assert volume_basis(*pair) in {
            VOLUME_BASIS_CONSOLIDATED,
            VOLUME_BASIS_SMART,
            VOLUME_BASIS_NONE,
        }


def test_a_new_source_label_forces_a_basis_decision():
    # continuous, official and generic are labels no canonical row carries (checked against
    # market_data_ohlcv 2026-10-28: only the six mapped pairs and the derived grid exist). A new
    # label that is not mapped and not listed here fails this test instead of a rebuild.
    from src.intelligence.bars.vendor_kind import DERIVED_PAIR, LABEL_TO_VENDOR_KIND

    unmapped = {
        pair
        for pair in LABEL_TO_VENDOR_KIND.values()
        if pair not in VOLUME_BASIS_BY_VENDOR_KIND and pair != DERIVED_PAIR
    }
    assert unmapped == {("ibkr", "continuous"), ("ibkr", "official"), ("ibkr", "generic")}
