"""Bar-source and rule identifiers for the derived grid (phase 185 plan 11).

Identifiers, not tunables: every value here names a thing (a source label, a
rule version, the grid's timeframe set), so each is APR-exempt by the registry's
own exemption list (schema identifiers and statistical concept definitions).
The moment one of these becomes operator-adjustable it must move to
config_state under infra.bar_derivation.* instead of growing a second value
here.

GRID_TIMEFRAMES maps the derived timeframes to their bucket size in minutes;
the minutes are the statistic definition of each grid (D-15: 15m and 1h on
session-anchored edges), matching aggregate_session_grid's minutes argument.
The digest table's rule_version column records GRID_RULE_VERSION beside every
bar_content_digest row so a reader can tell which grid rule hashed the slice;
the digest itself deliberately excludes it (D-07).

Label constants stay the raw-side vocabulary: ohlcv_request, ohlcv_load,
ohlcv_raw's own history and vendor_kind's map speak labels. Canonical rows
(market_data_ohlcv) carry (vendor, kind) since plan 191-13; the label map
itself lives in vendor_kind.py.
"""

from __future__ import annotations

SOURCE_DERIVED_5M = "derived_5m"
GRID_RULE_VERSION = "grid-v1"
GRID_TIMEFRAMES: dict[str, int] = {"15m": 15, "1h": 60}
# The stored timeframe the grid timeframes are derived from (D2b, plan 185-12); a derived
# timeframe has no independent provider-side truth, so it inherits this one's.
GRID_SOURCE_TF = "5m"

# Timeframes whose market_data_ohlcv rows services/bar_derivation owns
# (D-06/D-15 single writer, plan 185-18 task 1b): the daily stage writes 1d,
# the grid stage writes 15m/1h. Streaming and fetch writers import this fence
# instead of restating the set; when 4h joins the derivation (futures rework)
# this is the only definition that changes.
DERIVATION_OWNED_TIMEFRAMES: frozenset[str] = frozenset(GRID_TIMEFRAMES) | {"1d"}

# Alpaca, the intraday depth source (SIP via Polygon/Massive) admitted by the 521 admission
# build: 5m fills from 2016-01-01 forward, RTH-window aggregates only. Evidence and measured
# conventions: docs/plans/2026-10-09-alpaca-5m-admission-build.md. Since D-191-Q (2026-10-27)
# its split-adjusted SIP daily answer, raw kind sip_rth, is also the canonical 1d primary from
# 2016-01-04 with IBKR fallback (daily rule d2-v4); the 1d volume basis is consolidated.
SOURCE_ALPACA = "alpaca"
ROUTE_ALPACA = "ALPACA"

# An IBKR SMART TRADES 1d bar the daily rule admitted where the policy's primary source has
# none: a head before the primary's first bar, or an interior hole within the basis tolerance
# (plan 185-36, migration 446).
SOURCE_IBKR_FALLBACK = "ibkr_fallback"

# The 1d market_data_ohlcv (vendor, kind) pairs that are canonical bars: IBKR named (an
# IBKR-primary policy range), venue (stored history from the deleted d2-v1 rule), the
# admitted IBKR fallback (d2-v2), and Alpaca SIP, the primary from
# 2016-01-04 under D-191-Q (bar_source_policy). The 1d content digest and the daily stage's value comparison read
# every one of them. Literal pairs, not vendor_kind imports: vendor_kind builds its map
# from the label constants here, so importing the map back would be circular.
CANONICAL_1D_SOURCES: tuple[tuple[str, str], ...] = (
    ("ibkr", "named"),
    ("ibkr", "venue"),
    ("ibkr", "fallback"),
    ("alpaca", "sip_rth"),
)

# The two ANY arrays every canonical 1d read filters on (plan 191-13): the vendors and kinds
# of CANONICAL_1D_SOURCES, zipped nowhere (a pair is admitted only when both sides match a
# stored row's own vendor and kind; the cross product holds no canonical rows). Derived here
# once so the daily stage, the audit and the equivalence check bind the same arrays.
CANONICAL_1D_VENDORS: tuple[str, ...] = tuple(
    sorted({vendor for vendor, _kind in CANONICAL_1D_SOURCES})
)
CANONICAL_1D_KINDS: tuple[str, ...] = tuple(
    sorted({kind for _vendor, kind in CANONICAL_1D_SOURCES})
)
