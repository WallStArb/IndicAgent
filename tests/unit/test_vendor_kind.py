"""vendor_kind: the one label <-> (vendor, kind) map (phase 191 plan 01)."""

from __future__ import annotations

import pytest

from src.intelligence.bars import sources
from src.intelligence.bars.vendor_kind import (
    BAR_KINDS,
    BAR_VENDORS,
    LABEL_TO_VENDOR_KIND,
    VENDOR_KIND_TO_LABEL,
    canonical_kind_for_raw,
    label_to_vendor_kind,
    observation_kind,
    vendor_kind_to_label,
)

_EXPECTED = {
    "ibkr_named": ("ibkr", "named"),
    "ibkr_venue": ("ibkr", "venue"),
    "ibkr_continuous_adj": ("ibkr", "continuous"),
    "ibkr_official": ("ibkr", "official"),
    "ibkr": ("ibkr", "generic"),
    "ibkr_fallback": ("ibkr", "fallback"),
    "tradier": ("tradier", "consolidated"),
    "alpaca": ("alpaca", "sip_rth"),
    "derived_5m": ("derived", "5m_grid"),
}


def test_label_map_is_exactly_the_specified_nine():
    assert LABEL_TO_VENDOR_KIND == _EXPECTED


def test_every_label_vendor_key_is_mapped_and_vendor_agrees():
    for label, vendor in sources.LABEL_VENDOR.items():
        assert label in LABEL_TO_VENDOR_KIND, f"new label {label!r} needs a (vendor, kind)"
        assert LABEL_TO_VENDOR_KIND[label][0] == vendor


def test_inverse_round_trips_every_entry():
    assert len(VENDOR_KIND_TO_LABEL) == len(LABEL_TO_VENDOR_KIND)
    for label, (vendor, kind) in LABEL_TO_VENDOR_KIND.items():
        assert vendor_kind_to_label(vendor, kind) == label
        assert label_to_vendor_kind(label) == (vendor, kind)


def test_unknown_pair_raises_keyerror_naming_it():
    with pytest.raises(KeyError, match="databento.*named"):
        vendor_kind_to_label("databento", "named")
    with pytest.raises(KeyError, match="nope"):
        label_to_vendor_kind("nope")


@pytest.mark.parametrize(
    ("source", "route", "wts", "kind"),
    [
        ("ibkr", "SMART", "TRADES", "smart_trades"),
        ("ibkr", "SMART", "ADJUSTED_LAST", "smart_adjusted"),
        ("ibkr", "ARCA", "TRADES", "venue"),
        ("ibkr", "ISLAND", "TRADES", "venue"),
        ("tradier", "TRADIER", "TRADES", "consolidated"),
        ("alpaca", "ALPACA", "TRADES", "sip_rth"),
        ("ibkr", "LEGACY_IMPORT", "TRADES", "smart_trades"),
        ("tradier", "LEGACY_IMPORT", "TRADES", "consolidated"),
    ],
)
def test_observation_kind(source, route, wts, kind):
    assert observation_kind(source, route, wts) == kind


@pytest.mark.parametrize(
    "args",
    [
        ("ibkr", "ARCA", "ADJUSTED_LAST"),
        ("ibkr", "LEGACY_IMPORT", "ADJUSTED_LAST"),
        ("ibkr", "TRADIER", "TRADES"),
        ("tradier", "SMART", "TRADES"),
        ("derived", "SMART", "TRADES"),
    ],
)
def test_observation_kind_unknown_combination_raises(args):
    with pytest.raises(ValueError, match="unmapped observation"):
        observation_kind(*args)


def test_canonical_kind_for_raw():
    assert canonical_kind_for_raw("ibkr", "smart_trades") == "named"
    assert canonical_kind_for_raw("ibkr", "venue") == "venue"
    assert canonical_kind_for_raw("tradier", "consolidated") == "consolidated"
    for pair in (("ibkr", "smart_adjusted"), ("ibkr", "fallback"), ("alpaca", "sip_rth")):
        with pytest.raises(ValueError):
            canonical_kind_for_raw(*pair)


def test_vocabularies_cover_every_mapped_pair():
    assert BAR_VENDORS == ("ibkr", "alpaca", "tradier", "derived")
    for vendor, kind in LABEL_TO_VENDOR_KIND.values():
        assert vendor in BAR_VENDORS
        assert kind in BAR_KINDS
    assert {"smart_trades", "smart_adjusted"} <= set(BAR_KINDS)
    assert all(BAR_KINDS.values())
