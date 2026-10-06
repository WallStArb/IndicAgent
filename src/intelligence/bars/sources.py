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

# The 1d market_data_ohlcv sources that are canonical bars (plan 185-27): D2's IBKR named and
# venue sources plus Tradier, the primary 1d source of the names it owns (migration 438). The
# 1d content digest reads every one of them; D2's own value comparison keeps its IBKR-only list
# because a Tradier-owned name never reaches it.
CANONICAL_1D_SOURCES: tuple[str, ...] = ("ibkr_named", "ibkr_venue", "tradier")
# The rule the Tradier daily loader stamps on canonical_bar_lineage and bar_content_digest: a
# stored bar is the latest non-test TRADIER observation of its date with equal values.
TRADIER_RULE_VERSION = "tradier-v1"
