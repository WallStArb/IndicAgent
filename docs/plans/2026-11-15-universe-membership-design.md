# Universe membership: table and writer design

Status: implementation note for todo 609 gate 5; the rule itself is frozen in `2026-11-13-stage2-universe-preregistration.md`.

## Table

`universe_membership(as_of, symbol, security_type, median_dollar_volume, close, sessions, entered)`, primary key (as_of, symbol), `symbol` references `instruments`. A row means the symbol is a member as of the NYSE month-end `as_of`, effective for the following month; a non-member has no row. `universe_membership_build(as_of, rule_id, n_members)` is the ledger: a month exists exactly when its ledger row does, so an unbuilt month is never read as an empty one. Both tables are insert-only (trigger refuses UPDATE, DELETE, TRUNCATE). A correction is a dated amendment of the preregistration and a new rule id, never an edit.

## Rule and inputs

The rule values are code constants in `src/intelligence/universe_membership.py` (not APR; preregistration). Per security at month-end t: type CS, ADRC or ETF from the Massive point-in-time ticker snapshot of t; a bar on t; close at or above $1; at least 60 own bars; trailing 60-session median of close x volume at or above $1M to enter, kept while at or above $0.5M. Type, price, bar-on-t and history are hard for members too; hysteresis relaxes only the liquidity floor. Bars after t are never read. Bars come from `market_data_ohlcv_tradeable` 1d, restricted to days a live `ticker_event` span places on the symbol (identity: a reused ticker is two securities, an unplaced span is not a member).

## Writer and readers

`UniverseMembershipWriter` (Ring 2, `BaseBatch`) is the only writer. One transaction per run under an advisory lock; rehearsal rolls back unless `--apply`. It builds every month-end up to `--through` not yet in the ledger, seeds hysteresis from the last built month, refuses a ledger built under another rule id, fails on a month-end with no snapshot, and fails on an empty month after the first member. Early month-ends with under 60 sessions are legitimately empty.

The corpus compute universe is every symbol ever in `universe_membership` (`services/corpus_universe.py`): features compute on every name with 1d data so an entering name arrives warmed, and membership at each month-end gates the IC panel. There is no fallback to `compute_1d`; an empty ledger raises.
