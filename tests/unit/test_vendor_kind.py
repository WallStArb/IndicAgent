"""vendor_kind: the one label <-> (vendor, kind) map (phase 191 plan 01)."""

from __future__ import annotations

import pytest

from src.intelligence.bars import sources
from src.intelligence.bars.vendor_kind import (
    BAR_KINDS,
    BAR_VENDORS,
    LABEL_TO_VENDOR_KIND,
    VENDOR_SERVED_KINDS,
    canonical_kind_for_raw,
    label_to_vendor_kind,
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
    "massive": ("massive", "sip_flat_agg"),
    "massive_day": ("massive", "sip_flat"),
}


def test_label_map_is_exactly_the_specified_eleven():
    assert LABEL_TO_VENDOR_KIND == _EXPECTED


def test_every_label_constant_is_mapped_and_none_else():
    """Tripwire: the map is exactly the eleven label constants, no more, no fewer (plan 13
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
        sources.SOURCE_MASSIVE,
        sources.SOURCE_MASSIVE_DAY,
    }
    assert set(LABEL_TO_VENDOR_KIND) == constants
    assert not hasattr(sources, "LABEL_VENDOR"), "LABEL_VENDOR was deleted in plan 13"


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
    assert BAR_VENDORS == ("ibkr", "alpaca", "tradier", "derived", "massive")
    for vendor, kind in LABEL_TO_VENDOR_KIND.values():
        assert vendor in BAR_VENDORS
        assert kind in BAR_KINDS
    assert {"smart_trades", "smart_adjusted"} <= set(BAR_KINDS)
    assert all(BAR_KINDS.values())


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


def test_massive_vendor_kind_maps_are_complete():
    from src.intelligence.bars.selection import SESSION_BOUND_KINDS
    from src.intelligence.bars.vendor_kind import (
        VENDOR_SERVED_KINDS,
        VOLUME_BASIS_CONSOLIDATED,
        canonical_kind_for_raw,
        raw_kind_for_canonical,
        volume_basis,
    )

    assert label_to_vendor_kind("massive") == ("massive", "sip_flat_agg")
    assert label_to_vendor_kind("massive_day") == ("massive", "sip_flat")
    assert VENDOR_SERVED_KINDS["massive"] == {"sip_flat_agg", "sip_flat"}
    assert "massive" in BAR_VENDORS and {"sip_flat_agg", "sip_flat", "sip_flat_adj"} <= set(
        BAR_KINDS
    )
    assert "sip_flat_agg" in SESSION_BOUND_KINDS and "sip_flat" not in SESSION_BOUND_KINDS
    # canonical never reuses a raw name that says unadjusted, and the raw join maps back by timeframe
    assert canonical_kind_for_raw("massive", "sip_flat_agg") == "sip_flat_adj"
    assert canonical_kind_for_raw("massive", "sip_flat") == "sip_flat_adj"
    assert raw_kind_for_canonical("massive", "sip_flat_adj", "5m") == "sip_flat_agg"
    assert raw_kind_for_canonical("massive", "sip_flat_adj", "1d") == "sip_flat"
    assert raw_kind_for_canonical("alpaca", "sip_rth", "5m") == "sip_rth"
    with pytest.raises(ValueError, match="no raw kind"):
        raw_kind_for_canonical("massive", "sip_flat_adj", "15m")
    assert volume_basis("massive", "sip_flat_adj") == VOLUME_BASIS_CONSOLIDATED


def test_massive_ingress_row():
    from src.intelligence.bars.vendor_ingress import vendor_ingress

    row = vendor_ingress("massive", "5m")
    assert row.kind == "sip_flat_agg" and row.artifact_dir.name == "minute_aggs_v1"


def test_reconciliation_5m_join_maps_canonical_kind_back_to_raw():
    from services.bar_reconciliation_audit import _SELECT_5M_SQL

    assert "THEN 'sip_flat_agg' ELSE m.kind END" in _SELECT_5M_SQL
    assert "r.kind = m.kind" not in _SELECT_5M_SQL
