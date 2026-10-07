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

# An IBKR SMART TRADES 1d bar the d2-v2 rule admitted where the policy's primary source
# (Tradier) has none: a head before Tradier's first bar, or an interior hole within the basis
# tolerance (plan 185-36, migration 446). A source label of its own so
# market_data_ohlcv_tradeable NULLs its volume by source, as for ibkr_venue, with no join to
# bar_source_policy on every read.
SOURCE_IBKR_FALLBACK = "ibkr_fallback"

# The 1d market_data_ohlcv sources that are canonical bars: IBKR named (an IBKR-primary policy
# range), venue (stored history from the deleted d2-v1 rule), the admitted IBKR fallback (d2-v2)
# and Tradier, the 1d primary source (migration 438, bar_source_policy). The 1d content digest
# and the daily stage's value comparison read every one of them.
CANONICAL_1D_SOURCES: tuple[str, ...] = (
    "ibkr_named",
    "ibkr_venue",
    SOURCE_IBKR_FALLBACK,
    "tradier",
)
