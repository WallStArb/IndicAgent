# Universe membership: table and writer design

Status: implementation note for todo 609 gate 5; the rule itself is frozen in `2026-11-13-stage2-universe-preregistration.md`.

## Table

`universe_membership(as_of, symbol, security_type, median_dollar_volume, close, sessions, entered)`, primary key (as_of, symbol), `symbol` references `instruments`. A row means the symbol is a member as of the NYSE month-end `as_of`, effective for the following month; a non-member has no row. `universe_membership_build(as_of, rule_id, n_members)` is the ledger: a month exists exactly when its ledger row does, so an unbuilt month is never read as an empty one. Both tables are insert-only (trigger refuses UPDATE, DELETE, TRUNCATE). A correction is a dated amendment of the preregistration and a new rule id, never an edit.

## Rule and inputs

The rule values are code constants in `src/intelligence/universe_membership.py` (not APR; preregistration). Per security at month-end t: type CS, ADRC or ETF from the Massive point-in-time ticker snapshot of t; a bar on t; close at or above $1; at least 60 own bars; trailing 60-session median of close x volume at or above $1M to enter, kept while at or above $0.5M. Type, price, bar-on-t and history are hard for members too; hysteresis relaxes only the liquidity floor. Bars after t are never read. Bars come from `market_data_ohlcv_tradeable` 1d, restricted to days a live `ticker_event` span places on the symbol (identity: a reused ticker is two securities, an unplaced span is not a member).

## Writer and readers

`UniverseMembershipWriter` (Ring 2, `BaseBatch`) is the only writer. One transaction per run under an advisory lock; rehearsal rolls back unless `--apply`. It builds every month-end up to `--through` not yet in the ledger, seeds hysteresis from the last built month, refuses a ledger built under another rule id, fails on a month-end with no snapshot, and fails on an empty month after the first member. Early month-ends with under 60 sessions are legitimately empty.

The corpus compute universe is every symbol ever in `universe_membership` (`services/corpus_universe.py`): features compute on every name with 1d data so an entering name arrives warmed, and membership at each month-end gates the IC panel. There is no fallback to `compute_1d`; an empty ledger raises.

## Price test, readings and checks added after review

- Price floor on the as-traded close. Canonical closes are split-adjusted by every split on record, including splits after t, so the stored close would leak the future (a $0.40 name that reverse-splits 1:20 stores $8). The rule multiplies the canonical close by the factors of market splits with effective_date on or after t (the inverse of `daily_rule.split_scale`) and stores that as-traded close. Dollar volume is invariant under the adjustment. The split set is exactly the one canonical 1d was divided by: every current `corporate_action_current` row accepted by `is_market_split`, no `recorded_at` horizon (`daily_rule.split_scale`, `bar_derivation._SELECT_DAILY_SPLITS_SQL`, the migration 588 lineage view). The build refuses when canonical is not current with the splits: a `corporate_action` row (superseding and void rows included) recorded after the symbol's latest 1d `bar_content_digest.computed_at`, or actions with no 1d digest, lists the symbols and writes nothing.
- 59 versus 60. "At least 60 sessions of the security's own bars before t" is read as 60 bars through t inclusive (the t bar is required anyway). The strict reading needs 61. The difference is one session of history per name; recorded so a later amendment can choose.
- Type mix measurement. Before the real build, count the Massive types in the month-end snapshots (including `OS` ordinary shares, `ETV` exchange-traded vehicles, and any unlisted code) against `ELIGIBLE_TYPES`. A type that is economically a common stock or ETF but absent from the set is a preregistration amendment decision for the owner, taken before any return-based look.
- Snapshot completeness. A month-end needs both `<date>@active` and `<date>@inactive`, pages contiguous from 1, status OK, the last page without `next_url`; anything else fails the run.
- Survivor-only builds are refused: with no inactive placed symbol the build raises (stage 2 gates 3 and 4 are not done).
- A NULL close or volume is NaN, so the name is not a member that month (no fill).
- `data/universe_membership/<through>/vanished_without_final_bar.csv` lists members whose bars stop more than 7 calendar days before their placed span ends (or before `--through` for an open span).
- Ledger months may be empty only before the first member ever built; once any built month has members, every later month must have members.
- Window convention. Bars come from the tradeable view (volume > 0), so the 60-bar window and the session count run over a name's traded days, the same convention as the day-file measurement that sized the floor. A name that trades one session in three has a window that spans about 180 calendar sessions; the preregistration does not bound the span, so none is applied. A later amendment may add one.
