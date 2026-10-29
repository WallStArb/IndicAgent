"""vendor_kind: the one label <-> (vendor, kind) map (phase 191 plan 01)."""

from __future__ import annotations

import pytest

from src.intelligence.bars import sources
from src.intelligence.bars.vendor_kind import (
    BAR_KINDS,
    BAR_VENDORS,
    LABEL_TO_VENDOR_KIND,
    VENDOR_KIND_TO_LABEL,
    VENDOR_SERVED_KINDS,
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
    "alpaca": ("alpaca", "sip_rth"),
    "derived_5m": ("derived", "5m_grid"),
}


def test_label_map_is_exactly_the_specified_nine():
    assert LABEL_TO_VENDOR_KIND == _EXPECTED


def test_every_label_constant_is_mapped_and_none_else():
    """Tripwire: the map is exactly the nine label constants, no more, no fewer (plan 13
    replaced the LABEL_VENDOR cross-check, which was deleted with the label column)."""
    from src.core import bar_normalizer

    constants = {
        bar_normalizer.SOURCE_IBKR_NAMED,
        bar_normalizer.SOURCE_IBKR_VENUE,
        bar_normalizer.SOURCE_IBKR_CONTINUOUS,
        bar_normalizer.SOURCE_IBKR_OFFICIAL,
        bar_normalizer.SOURCE_IBKR_GENERIC,
        sources.SOURCE_IBKR_FALLBACK,
        sources.SOURCE_ALPACA,
        sources.SOURCE_DERIVED_5M,
    }
    assert set(LABEL_TO_VENDOR_KIND) == constants
    assert not hasattr(sources, "LABEL_VENDOR"), "LABEL_VENDOR was deleted in plan 13"


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
        ("ibkr", "ARCA", "TRADES", "venue_arca"),
        ("ibkr", "ISLAND", "TRADES", "venue_island"),
        ("alpaca", "ALPACA", "TRADES", "sip_rth"),
        ("alpaca", "SIP", "TRADES", "sip_rth"),
        ("alpaca", "IEX", "TRADES", "iex_rth"),
        ("ibkr", "LEGACY_IMPORT", "TRADES", "smart_trades"),
    ],
)
def test_observation_kind(source, route, wts, kind):
    assert observation_kind(source, route, wts) == kind


def test_alpaca_kind_for_feed_names_the_answered_basis():
    from src.intelligence.bars.vendor_kind import ALPACA_FEED_KINDS, alpaca_kind_for_feed

    assert alpaca_kind_for_feed("sip", "split") == "sip_rth"
    assert alpaca_kind_for_feed("iex", "split") == "iex_rth"
    with pytest.raises(ValueError, match="unknown alpaca feed 'databento'"):
        alpaca_kind_for_feed("databento", "split")
    # D-191-A follow-up: the alpaca kinds are split-adjusted bases; an unadjusted answer has no
    # kind, so it can never land last-wins as sip_rth
    with pytest.raises(ValueError, match="split-adjusted"):
        alpaca_kind_for_feed("sip", "none")
    # The feed map is the vendor-served kinds for alpaca, and both kinds are described.
    assert set(ALPACA_FEED_KINDS.values()) == set(VENDOR_SERVED_KINDS["alpaca"])
    assert {"sip_rth", "iex_rth"} <= set(BAR_KINDS)


def test_vendor_served_kinds_gate_the_explicit_kind():
    """The nightly's kind override is legal exactly for the kinds the vendor serves: an iex
    answer must never be writable as sip_rth (the basis lie the split exists to prevent)."""
    from src.intelligence.bars.vendor_kind import VENDOR_SERVED_KINDS

    assert "iex_rth" in VENDOR_SERVED_KINDS["alpaca"]
    assert "tradier" not in VENDOR_SERVED_KINDS
    assert "alpaca" in VENDOR_SERVED_KINDS and "ibkr" not in VENDOR_SERVED_KINDS


@pytest.mark.parametrize(
    "args",
    [
        ("ibkr", "ARCA", "ADJUSTED_LAST"),
        ("ibkr", "LEGACY_IMPORT", "ADJUSTED_LAST"),
        ("ibkr", "TRADIER", "TRADES"),
        ("tradier", "SMART", "TRADES"),
        ("tradier", "TRADIER", "TRADES"),
        ("tradier", "LEGACY_IMPORT", "TRADES"),
        ("derived", "SMART", "TRADES"),
    ],
)
def test_observation_kind_unknown_combination_raises(args):
    with pytest.raises(ValueError, match="unmapped"):
        observation_kind(*args)


def test_canonical_kind_for_raw():
    assert canonical_kind_for_raw("ibkr", "smart_trades") == "named"
    assert canonical_kind_for_raw("ibkr", "venue") == "venue"
    assert canonical_kind_for_raw("ibkr", "venue_nyse") == "venue"
    with pytest.raises(ValueError):
        canonical_kind_for_raw("tradier", "consolidated")
    # D-191-Q: Alpaca SIP is a canonical 1d primary and keeps its raw kind, as canonical 5m does.
    assert canonical_kind_for_raw("alpaca", "sip_rth") == "sip_rth"
    for pair in (("ibkr", "smart_adjusted"), ("ibkr", "fallback"), ("alpaca", "iex_rth")):
        with pytest.raises(ValueError):
            canonical_kind_for_raw(*pair)


def test_vocabularies_cover_every_mapped_pair():
    assert BAR_VENDORS == ("ibkr", "alpaca", "tradier", "derived")
    for vendor, kind in LABEL_TO_VENDOR_KIND.values():
        assert vendor in BAR_VENDORS
        assert kind in BAR_KINDS
    assert {"smart_trades", "smart_adjusted"} <= set(BAR_KINDS)
    assert all(BAR_KINDS.values())


def test_each_listing_venue_route_is_its_own_raw_kind():
    from src.intelligence.bars.vendor_kind import VENUE_ROUTE_KINDS, VENUE_ROUTES

    kinds = {observation_kind("ibkr", route, "TRADES") for route in VENUE_ROUTES}
    assert kinds == set(VENUE_ROUTE_KINDS) and len(kinds) == len(VENUE_ROUTES)


def test_unlisted_venue_route_raises_naming_the_route():
    with pytest.raises(ValueError, match="unmapped ibkr listing-venue route 'EDGX'"):
        observation_kind("ibkr", "EDGX", "TRADES")


def test_unmapped_observation_is_a_distinct_error_type_and_still_a_value_error():
    from src.intelligence.bars.vendor_kind import UnmappedObservation

    assert issubclass(UnmappedObservation, ValueError)
    with pytest.raises(UnmappedObservation):
        observation_kind("ibkr", "EDGX", "TRADES")
    with pytest.raises(UnmappedObservation):
        observation_kind("ibkr", "SMART", "MIDPOINT")


def test_apr_venue_fallback_seed_is_a_subset_of_venue_routes():
    """Review finding 11: a venue added to the APR list without a kind mapping would fail every
    1d window for the names that route there."""
    import json
    import re
    from pathlib import Path

    from src.intelligence.bars.vendor_kind import VENUE_ROUTES

    text = Path("production/migrations/374_former_venue_history_recovery.sql").read_text()
    seed = re.search(r"\('infra\.ibkr\.venue_fallback\.exchanges', '(\[[^']*\])'", text)
    assert seed is not None
    assert set(json.loads(seed.group(1))) <= set(VENUE_ROUTES)
