# D7 check split_horizon_fresh (todo 600, admission step 2 item; step 7 precondition)

Author: session for the lead (indicagent-32), 2026-11-11
Status: built in branch `massive-step7-prep` (commit in the report), for the lead's review. Not landed.
Informed by: `docs/plans/2026-11-10-massive-admission-db-design.md` section 5 (late splits) and section 8 step 2, `services/bar_selection.py`, `src/intelligence/bars/split_rescale.py`, `services/bar_reconciliation_audit.py`, `src/intelligence/bars/verdict_gate.py`.

## Problem

Selection rescales an unadjusted Massive 5m winner by the splits known at its pinned horizon. A split recorded after that horizon (or executed after it) leaves every earlier Massive bar of the name on a stale scale until the name is reselected. The design asks for a required D7 check, `split_horizon_fresh`, that holds the name while that is true.

## Decision: judge the content, not a horizon record

The design words the check as "the selection's pinned horizon covers every split row of the name". The horizon is persisted only on the ingress path (the `ohlcv_load` detail note); `ops_source_policy --reselect-only` and the step 7 rebuild call `select_and_write` directly and record it nowhere durable per name. Persisting it would need a new table and a writer.

The check judges the consequence instead, which needs no record: for every canonical 5m bar of kind `sip_flat_adj`, it recomputes `raw close / scale(session)` with selection's own arithmetic (`split_rescale.scales_for_sessions` over `splits_known_at(rows, run start)`, the same market-split filter) and counts bars whose stored close is not exactly that value. Equality is exact because both sides run the same float operations in the same order; a tolerance would hide a one-split error on a small factor.

It catches every case the horizon wording targets (a split recorded or executed after the selection) and two it does not: a split voided after selection (the bar still carries the removed factor) and a canonical Massive bar whose raw row is gone (counted, since the raw close is NaN).

## What changed

- `src/intelligence/bars/integrity_checks.py`: `split_horizon_stale` (pure, vectorized; New York session dates) and `CHECK_SPLIT_HORIZON_FRESH` in `CHECKS_INTRADAY`.
- `services/bar_reconciliation_audit.py`: the 5m read also takes `m.kind` and the joined raw row's close; `_FiveMinute` carries a Massive mask and the raw close; the loader reads the name's split rows (only for a name holding Massive 5m bars) and passes `splits_known_at(rows, run_start)`; `judge_name_intraday` emits the verdict (5m, metric = stale bars, threshold 0).
- `src/intelligence/bars/verdict_gate.py`: `split_horizon_fresh` joins `REQUIRED_CHECKS["5m"]`, so promotion and the compute-ready predicate hold a stale name.

1d needs no new check: D7's `canonical_recompute` re-derives d2-v6 with the current splits and already fails a stale Massive 1d bar. 15m and 1h follow 5m through `digest_fresh`.

## Not built (named, for the lead)

- The reselect trigger on a split write (design section 5: the split writer's commit reselects the name's Massive spans). Until it exists, the red verdict is the hold, and the remedy is `ops_source_policy --reselect-only` for the name, then a grid derivation.

## Tests

`tests/unit/bars/test_split_horizon_fresh.py` (fresh, stale, voided, New York session date, missing raw row, bit-exact replay of two splits) and three audit-level cases in `tests/unit/services/test_bar_reconciliation_audit.py` (a split recorded after selection fails, one recorded after the run start passes, a non-Massive name passes with metric 0).
