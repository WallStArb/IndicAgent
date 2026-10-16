"""The one map between bar source labels and (vendor, kind), phase 191 plan 01.

A bar source label (`ibkr_named`, `tradier`, `derived_5m`) mixes vendor, kind and sometimes a
computation. The unified raw table (`ohlcv_raw`, design doc
docs/plans/2026-10-12-unified-raw-bar-table-design.md) splits it: `vendor` names who served the
bar, `kind` names what was served. This module is the single definition of that split. The
migration seeds, the backfill and the writers all derive from it; none retypes a pair.

Planner decisions (D-191-A, resolving design doc ambiguity):
- Raw `kind` is what the vendor served. `fallback` is therefore a canonical-only kind: it is a
  selection outcome the daily rule assigns, never something a vendor serves.
- Tradier's kind is `consolidated`; Alpaca's is `sip_rth` (RTH-window SIP aggregates,
  docs/plans/2026-10-09-alpaca-5m-admission-build.md).
- Canonical 1d rows keep the winning raw row's (vendor, kind), so the tradeable view can null
  volume by kind. `derived` is the vendor only of the 15m/1h grid (kind `5m_grid`). The rule
  version stays in bar_derivation_batch, not on the row.
- Databento is not seeded; it joins as a CVR row after its admission study.

Pure Ring 1: no database access. Canonical rows have carried (vendor, kind) since plan 191-13;
the label map stays the raw-side vocabulary's one definition.
"""

from __future__ import annotations

from src.core.bar_normalizer import (
    SOURCE_IBKR_CONTINUOUS,
    SOURCE_IBKR_GENERIC,
    SOURCE_IBKR_NAMED,
    SOURCE_IBKR_OFFICIAL,
    SOURCE_IBKR_VENUE,
)
from src.intelligence.bars.sources import (
    ROUTE_ALPACA,
    ROUTE_TRADIER,
    SOURCE_ALPACA,
    SOURCE_DERIVED_5M,
    SOURCE_IBKR_FALLBACK,
    SOURCE_TRADIER,
)

VENDOR_IBKR = "ibkr"
VENDOR_TRADIER = "tradier"
VENDOR_ALPACA = "alpaca"
VENDOR_DERIVED = "derived"

LABEL_TO_VENDOR_KIND: dict[str, tuple[str, str]] = {
    SOURCE_IBKR_NAMED: (VENDOR_IBKR, "named"),
    SOURCE_IBKR_VENUE: (VENDOR_IBKR, "venue"),
    SOURCE_IBKR_CONTINUOUS: (VENDOR_IBKR, "continuous"),
    SOURCE_IBKR_OFFICIAL: (VENDOR_IBKR, "official"),
    SOURCE_IBKR_GENERIC: (VENDOR_IBKR, "generic"),
    SOURCE_IBKR_FALLBACK: (VENDOR_IBKR, "fallback"),
    SOURCE_TRADIER: (VENDOR_TRADIER, "consolidated"),
    SOURCE_ALPACA: (VENDOR_ALPACA, "sip_rth"),
    SOURCE_DERIVED_5M: (VENDOR_DERIVED, "5m_grid"),
}

VENDOR_KIND_TO_LABEL: dict[tuple[str, str], str] = {
    pair: label for label, pair in LABEL_TO_VENDOR_KIND.items()
}

BAR_VENDORS: tuple[str, ...] = (VENDOR_IBKR, VENDOR_ALPACA, VENDOR_TRADIER, VENDOR_DERIVED)

# kind -> one-line description, in within-vendor selection precedence order (the migration seeds
# sort_order from this order: named lowest, then venue, continuous, official, generic).
BAR_KINDS: dict[str, str] = {
    "named": "IBKR named-contract direct fetch",
    "venue": "IBKR listing-venue route fetch (volume is not consolidated)",
    "continuous": "IBKR continuous back-adjusted fetch",
    "official": "IBKR official bars from TWS reconciliation",
    "generic": "IBKR generic fetch (real-time bars or fallback path)",
    "smart_trades": "IBKR SMART-routed TRADES daily answer",
    "smart_adjusted": "IBKR SMART-routed ADJUSTED_LAST daily answer (never canonical)",
    "fallback": "IBKR 1d bar admitted by the daily rule where the primary has none (canonical only)",
    "consolidated": "Tradier consolidated-volume bar",
    "sip_rth": "Alpaca SIP aggregate over the regular trading hours window",
    "5m_grid": "15m or 1h bar derived from 5m on the session-anchored grid",
}

# One raw kind per IBKR listing-venue route (migration 476). A route is part of the source's
# identity: two routes answering one day are two raw rows, never one row revised. The label-level
# `venue` kind stays for the archive and canonical rows, which carry no route.
VENUE_ROUTES: tuple[str, ...] = ("AMEX", "ARCA", "BATS", "ISLAND", "NYSE")
VENUE_ROUTE_KINDS: dict[str, str] = {
    f"venue_{route.lower()}": f"IBKR {route} listing-venue route daily answer (volume is not consolidated)"
    for route in VENUE_ROUTES
}

_CANONICAL_KIND_FOR_RAW: dict[tuple[str, str], str] = {
    (VENDOR_IBKR, "smart_trades"): "named",
    (VENDOR_IBKR, "venue"): "venue",
    (VENDOR_TRADIER, "consolidated"): "consolidated",
}

_ROUTE_SMART = "SMART"
_ROUTE_LEGACY_IMPORT = "LEGACY_IMPORT"
_TRADES = "TRADES"
_ADJUSTED_LAST = "ADJUSTED_LAST"


def label_to_vendor_kind(label: str) -> tuple[str, str]:
    """(vendor, kind) of a bar source label; KeyError naming the label when unknown."""
    try:
        return LABEL_TO_VENDOR_KIND[label]
    except KeyError:
        raise KeyError(f"bar source label {label!r} has no (vendor, kind)") from None


def vendor_kind_to_label(vendor: str, kind: str) -> str:
    """The source label of a (vendor, kind); KeyError naming the pair when it has none."""
    try:
        return VENDOR_KIND_TO_LABEL[(vendor, kind)]
    except KeyError:
        raise KeyError(f"(vendor, kind) = ({vendor!r}, {kind!r}) has no source label") from None


class UnmappedObservation(ValueError):
    """A (source, route, what_to_show) with no raw kind: a route or request type nobody mapped.
    The fetcher reports it per item as `unmapped_kind` instead of failing the whole window."""


def observation_kind(source: str, route: str, what_to_show: str) -> str:
    """The raw kind of an ohlcv_observation row, from its source (vendor), route, what_to_show.

    ibkr SMART TRADES is smart_trades and SMART ADJUSTED_LAST is smart_adjusted; an ibkr
    listing-venue route with TRADES is `venue_<route>` (one kind per route). Route LEGACY_IMPORT carries no route evidence and
    resolves by its source column, as SMART. Anything else raises ValueError.
    """
    if source == VENDOR_IBKR:
        if route in (_ROUTE_SMART, _ROUTE_LEGACY_IMPORT):
            if what_to_show == _TRADES:
                return "smart_trades"
            if what_to_show == _ADJUSTED_LAST and route == _ROUTE_SMART:
                return "smart_adjusted"
        elif what_to_show == _TRADES and route not in (ROUTE_TRADIER, ROUTE_ALPACA):
            if route not in VENUE_ROUTES:
                raise UnmappedObservation(
                    f"unmapped ibkr listing-venue route {route!r}; add it to VENUE_ROUTES "
                    "and seed its bar_kind code"
                )
            return f"venue_{route.lower()}"
    elif source == VENDOR_TRADIER and route in (ROUTE_TRADIER, _ROUTE_LEGACY_IMPORT):
        if what_to_show == _TRADES:
            return "consolidated"
    elif source == VENDOR_ALPACA and route in (ROUTE_ALPACA, _ROUTE_LEGACY_IMPORT):
        if what_to_show == _TRADES:
            return "sip_rth"
    raise UnmappedObservation(
        f"unmapped observation (source={source!r}, route={route!r}, what_to_show={what_to_show!r})"
    )


def canonical_kind_for_raw(vendor: str, kind: str) -> str:
    """The canonical 1d kind a raw (vendor, kind) row becomes.

    (ibkr, smart_trades) -> named; (ibkr, venue) -> venue; (tradier, consolidated) ->
    consolidated. Adjusted bars are never canonical, and `fallback` is assigned by the daily
    rule, never derived from a raw kind; both raise.
    """
    if vendor == VENDOR_IBKR and kind in VENUE_ROUTE_KINDS:
        return "venue"
    try:
        return _CANONICAL_KIND_FOR_RAW[(vendor, kind)]
    except KeyError:
        raise ValueError(f"({vendor!r}, {kind!r}) has no canonical 1d kind") from None
