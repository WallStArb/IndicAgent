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
  docs/plans/2026-10-09-alpaca-5m-admission-build.md). An answer on feed=iex carries `iex_rth`
  (raw only, never selected); the feed->kind split lives in ALPACA_FEED_KINDS.
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

# The derived grid's canonical identity (derived, 5m_grid): the one pair services derive from
# the map instead of retyping (the daily stage's grid stage and the reconciliation audit).
DERIVED_PAIR = LABEL_TO_VENDOR_KIND[SOURCE_DERIVED_5M]

# Alpaca's feed is part of what was served: the same bars endpoint answers sip (consolidated,
# the 521 admission build's volume basis) or iex (IEX prints only). The nightly asks sip with its
# window end held back from the recent-SIP horizon (migration 513); whichever feed answers, the
# kind records it: rows written from iex carry iex_rth, never sip_rth, so raw never lies about
# the volume basis (and selection never picks iex_rth). The label map stays sip-only: the historical labeling.
ALPACA_FEED_KINDS: dict[str, str] = {"sip": "sip_rth", "iex": "iex_rth"}


# Every alpaca kind is a split-adjusted basis (the 521 admission build's stored convention);
# the leaf's adjustment default is "none", so the kind is only vouched for when the request
# asked for this adjustment (D-191-A follow-up).
ALPACA_RAW_ADJUSTMENT = "split"


def alpaca_kind_for_feed(feed: str, adjustment: str) -> str:
    """The raw kind of an Alpaca bars answer on `feed` asked with `adjustment`; ValueError when
    the feed is unknown or the answer is not split-adjusted (an unadjusted answer has no kind, so
    it can never land last-wins as sip_rth)."""
    if adjustment != ALPACA_RAW_ADJUSTMENT:
        raise ValueError(
            f"alpaca raw kinds are split-adjusted; an answer asked with adjustment="
            f"{adjustment!r} has no kind"
        )
    try:
        return ALPACA_FEED_KINDS[feed]
    except KeyError:
        raise ValueError(
            f"unknown alpaca feed {feed!r}; valid: {sorted(ALPACA_FEED_KINDS)}"
        ) from None


# The raw kinds each vendor can serve, the check a loader that names an explicit kind (the
# nightly's feed-derived one) is validated against: an iex answer must never be written under
# sip_rth. `fallback` is canonical-assigned, never served, and IBKR's kinds carry route evidence
# the label map already owns, so neither is listed.
VENDOR_SERVED_KINDS: dict[str, frozenset[str]] = {
    VENDOR_ALPACA: frozenset(ALPACA_FEED_KINDS.values()),
    VENDOR_TRADIER: frozenset({"consolidated"}),
}


def pair_token(vendor: str, kind: str) -> str:
    """The composite `vendor/kind` token for legacy single-column contexts: ohlcv_revision's
    old_value column and the archive-side UNION in ops_selection_gate's locate_groups. The
    format is owned here; the SQL literal in locate_groups follows it (a vendor or kind
    containing `/` would break the token, and none does)."""
    return f"{vendor}/{kind}"


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
    "iex_rth": "Alpaca IEX aggregate over the regular trading hours window",
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
    # D-191-Q: Alpaca SIP is the 1d primary from 2016-01-04 and keeps its raw kind, as canonical
    # 5m carries it; iex_rth is never canonical.
    (VENDOR_ALPACA, "sip_rth"): "sip_rth",
}

_ROUTE_SMART = "SMART"
_ROUTE_LEGACY_IMPORT = "LEGACY_IMPORT"
# The route evidence an alpaca request row carries: the feed the leaf asked, upper case
# ("SIP" is the historical spelling the leaf reported before the feed became configurable).
_ROUTE_ALPACA_SIP = "SIP"
_ROUTE_ALPACA_IEX = "IEX"
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
    """The raw kind for a fetched bar's route evidence (source, route, what_to_show), as the
    fetcher item pipeline maps it before the raw write (ohlcv_observation, the 1d store that
    carried these columns, was dropped by plan 191-16).

    ibkr SMART TRADES is smart_trades and SMART ADJUSTED_LAST is smart_adjusted; an ibkr
    listing-venue route with TRADES is `venue_<route>` (one kind per route). An alpaca route is
    the feed the leaf asked: SIP (or the label-level ALPACA) is sip_rth, IEX is iex_rth. Route
    LEGACY_IMPORT carries no route evidence and
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
    elif source == VENDOR_ALPACA and route in (
        ROUTE_ALPACA,
        _ROUTE_ALPACA_SIP,
        _ROUTE_LEGACY_IMPORT,
    ):
        if what_to_show == _TRADES:
            return "sip_rth"
    elif source == VENDOR_ALPACA and route == _ROUTE_ALPACA_IEX:
        if what_to_show == _TRADES:
            return "iex_rth"
    raise UnmappedObservation(
        f"unmapped observation (source={source!r}, route={route!r}, what_to_show={what_to_show!r})"
    )


def canonical_kind_for_raw(vendor: str, kind: str) -> str:
    """The canonical 1d kind a raw (vendor, kind) row becomes.

    (ibkr, smart_trades) -> named; (ibkr, venue) -> venue; (tradier, consolidated) ->
    consolidated; (alpaca, sip_rth) -> sip_rth. Adjusted bars and iex_rth are never canonical, and `fallback` is assigned by the daily
    rule, never derived from a raw kind; both raise.
    """
    if vendor == VENDOR_IBKR and kind in VENUE_ROUTE_KINDS:
        return "venue"
    try:
        return _CANONICAL_KIND_FOR_RAW[(vendor, kind)]
    except KeyError:
        raise ValueError(f"({vendor!r}, {kind!r}) has no canonical 1d kind") from None
