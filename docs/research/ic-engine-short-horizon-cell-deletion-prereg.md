# Pre-registration: delete structurally uneconomical short-horizon IC cells

**Status: EXECUTED 2026-09-24 (migration 358), see "Execution record" at the end.**
Originally: Evidence base complete; the delete set is
pre-registered as a decision rule, with final membership fixed by a measurement at
execution time. Execution is gated on the post-Phase-176-08 landing window (see
"Sequencing" below).

**Author:** Claude (GLM, dispatched via Claude Code), 2026-09-23. Evidence cited below
was produced by the 2026-09-13 TF-stack economics diagnostic (independent of this
author) and by the 2026-09-23 recompute-cost re-derivation from the completed
2026-09-17/22 corpus run's logs.

Informed by: Claude Opus 5.5 (execution record, 2026-09-24).

## Proposal

Stop MEASURING (not computing, not storing) the `ic_engine` cells whose holding period
structurally cannot clear the personal-scale turnover cost hurdle, by editing only the
`alpha.ic.active_scales.{tf}` APR keys (behavioral-list config, zero code change).
Existing `feature_ic_scores` rows for deleted scales are retained untouched (data
retention principle: never drop measured data); future runs simply stop writing them.

## Evidence

`scripts/analysis/personal_cost_hurdle_by_tf.py` (2026-09-13, read-only, reusing 0b's
validated 1.4bp live spread anchor; turnover measured per-bar at each tf's own rank
series; compared against the real measured avg IC at each tf's own `lookahead_bars`):

| Cell | Hurdle outcome |
| --- | --- |
| 5m @ H=1 (fast) | fails by 25-63x the measured IC |
| 15m @ H=1 (fast) | fails by 5-13x |
| 1h @ H=1 (fast) | MIXED pass/fail, depends on breadth assumption |
| 5m @ H=6/H=12 (mid/slow) | fails (margin below the 1.2-3x-clearing H=39); exact margins to be recorded at execution |
| 5m @ H=39 (extended, ~half day) | clears, 1.2-3x margin |
| 15m @ H=10 (extended, ~2.5hr) | clears everywhere |
| 1h @ H=20-60 (slow/extended, ~3-10 days) | clears, 18-100x margin |
| 1d @ H=1 (fast) | weak per 0a/0c (same shape at 1d: H=1 weak, H=5-10 strong); exact margin to be measured (script currently covers 5m/15m/1h only) |

The shape is identical at every tier: ultra-short holds fail catastrophically, long
holds clear. Replicated across granularity, not a 5m-specific artifact. Re-confirming
this every recompute is pure waste: these cells already fail their own economics by
5-60x regardless of what the corpus contains.

## Pre-registered decision rule

Candidate cells: `fast` at all four TFs, plus `mid` and `slow` at 5m.

A candidate is DELETED iff, on re-running `personal_cost_hurdle_by_tf.py` at execution
time (extended to cover 1d), it fails the hurdle UNIFORMLY across the full sensitivity
grid (both universe breadths 4.5/8.4 x both library ranks 3/10) by at least 5x. Mixed
results keep the cell. The 5x floor excludes borderline cells from deletion, keeping
the change conservative.

Expected outcome (for planning only, not binding): 1h fast survives the rule (mixed
today); the rest of the candidates fail uniformly. That is 5 of 16 per-symbol
(tf x scale) cells removed = ~31% of per-symbol scale-cell compute, reducing the
re-derived ~2.7 worker-hr/symbol to roughly ~1.9. Assumption: per-scale bootstrap cost
is approximately uniform within a cell (same matrix, one extra forward-return column
per scale); verify against the post-change run's logs rather than citing the estimate.

## Consumer impact

The 2026-09-23 Phase 176-05 audit (`.planning/phases/176-.../176-SCOPE-CONSUMER-AUDIT.md`)
inventoried all 39 `feature_ic_scores` consumers with a DECISION-DRIVING verdict per
file. That audit's axis was `regime_scope`; this change's axis is scale/lookahead
removal. Execution step: re-walk that same table and classify each decision-driving
consumer's sensitivity to scale-row absence. Two known up front:

- `ensemble_trainer` (`alpha.ensemble.lookahead_selection=max_ic_sharpe`): per-feature
  lookahead selection will no longer see fast-scale rows. This is an INTENDED
  consequence, not collateral: a feature whose best IC Sharpe sits at a H=1 hold is
  selecting an untradeable signal at personal scale. The ensemble re-derives from the
  next recompute onward.
- `ops_lookahead_horizon_response.py`: a horizon-response diagnostic; the short end of
  its response curve truncates. Diagnostic only, no gate.

## Statistical consequences

BH-FDR families shrink when cells leave them: survivor thresholds move. Any comparison
of FDR verdicts across the deletion boundary must note the family redefinition; this is
a methodology change, recorded as such (same discipline as the methodology-change
ledger). Backward comparisons within retained scales should treat pre-change and
post-change FDR columns as different families.

## Invalidation economics and sequencing

`_compute_apr_snapshot_key` (`services/ic_engine.py`) hashes the whole `active_scales`
dict into the base fingerprint key for EVERY cell, so trimming any tf's scales moves
every survivor's fingerprint: the next run recomputes all retained cells from scratch.
The change therefore carries a one-time full-recompute cost of the retained fraction
(~69% of a full run if the expected set holds), then saves ~31% on that run and every
run after.

Sequencing constraint (binding): land this ONLY bundled with the other pending
computational changes (todo 386's exact pre-flight count and 15M cap restore; the
threading/nogil adoption if the todo 385 lever benchmark supports it) in one landing
immediately before the next recompute that is already required. Never land it standalone
mid-cycle: it would trigger the one-time invalidation with no recompute scheduled to
absorb it.

Optional hardening for the same landing (code change): scope `active_scales` hashing
per-tf so a future scale edit (or rollback) invalidates only that tf's cells instead of
the whole corpus. Not required for the win.

## Rollback

APR-only: re-add the scale to `alpha.ic.active_scales.{tf}`. Note this re-moves the
fingerprint again (another full invalidation of that scope) unless the per-tf hashing
hardening is in place.

## Execution checklist (gated on the post-176-08 window)

1. Re-run `personal_cost_hurdle_by_tf.py` extended to 1d; record every candidate cell's
   margin grid in this doc; apply the decision rule; write the final delete set here.
2. Re-walk the 176-05 consumer audit table for scale-removal sensitivity; patch any
   decision-driving consumer that assumes fast rows exist.
3. Verify no CI test asserts the 4-scale active set (grep `active_scales` in tests/).
4. Bundle: land with todo 386 (+ threading/nogil if adopted) as one commit set.
5. Flip the `alpha.ic.active_scales.*` APR keys with `changed_by`/`reason` recording
   this doc as the reason.
6. Measure the actual savings from the next run's logs (same leg-accounting method as
   the 2026-09-23 re-derivation) and record them here, replacing the estimate.

## Execution record (2026-09-24)

Step 1: `scripts/analysis/personal_cost_hurdle_by_tf.py`, extended to 1d, run on the post-176-08
corpus. Minimum IC_min / measured IC over the 2x2 grid per candidate:

| Cell | Min margin | Rule outcome |
| --- | --- | --- |
| 5m fast (H=1) | 25.12 | DELETE |
| 5m mid (H=6) | 2.03 (5.06 at the thinnest grid point) | keep, mixed |
| 5m slow (H=12) | 0.99 (clears at breadth 8.4 x rank 10) | keep |
| 15m fast (H=1) | 5.50 | DELETE |
| 1h fast (H=1) | 0.60 | keep |
| 1d fast (H=1) | 0.05 (clears everywhere) | keep |

Final delete set: 5m fast and 15m fast, 2 of 16 (tf, scale) cells, not the 5 the planning
estimate expected. 5m mid/slow moved from "fails" in the 2026-09-13 table to mixed on this
corpus, and 1d fast clears by a wide margin. The ~31% savings estimate therefore does not hold;
measure the real saving from the next run's logs (step 6).

Step 2: consumers re-walked for scale-removal sensitivity. `ensemble_ic_engine` reads the same
`alpha.ic.active_scales.*` keys; `ensemble_trainer` loses the H=1 option at 5m/15m (intended);
`cross_sectional_spread_tracker` and `ops_ic_shrinkage` read `forward_returns.return_fast`,
which is unchanged; `corpus_manifest_verifier` only uses its fallback when APR is missing.
Step 3: no CI test pins the live 4-scale set (tests construct their own configs).
Step 4/5: landed in the post-176 bundle with todos 399, 401, 402, 403; APR flipped by
migration 358 with a `config_history` reason citing this document.
