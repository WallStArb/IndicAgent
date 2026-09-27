---
card_id: legacy-ctf-momentum-decile-ls
kind: legacy_verdict
title: ctf_momentum decile long-short cross-sectional construction (phase 167)
idea: Rank the 80-symbol ETF universe each bar by the ctf_momentum feature and hold a decile long-short dollar-neutral spread, gated by bootstrap CI, a shuffled-ranking null and a static-tilt attribution bound.
verdict: FAIL
verdict_date: 2026-08-07
recipe:
  spec: null
  script: services/cross_sectional_spread_tracker.py
  recipe_commit: 7bd23df2e9266cde4d841c30577ba829239159fd
results:
  - name: gate1_ctf_momentum_decile_ls
    value: "pass, 2026-08-04T23:13:01Z, binding cost 10 bps: fast ci_lower 0.000187, slow ci_lower 0.000164; null_p 0.0 at 40 shuffles, observed mean gross spread fast 0.000321, slow 0.000543"
    source: gate_look_log:gate1_ctf_momentum_decile_ls
  - name: gate1_ctf_momentum_decile_ls_ctf_join_v2
    value: "fail, 2026-08-07T11:59:56Z after the todo 243 corrected-join recompute: fast ci_lower -0.000141, slow ci_lower -0.000486 at 10 bps; null_p 0.649 (fast) and 0.986 (slow) at 1000 shuffles"
    source: gate_look_log:gate1_ctf_momentum_decile_ls_ctf_join_v2
  - name: gate2_ctf_momentum_decile_ls_ctf_join_v2
    value: "fail, 2026-08-07T12:00:31Z: static-tilt residual ci_lower fast -0.000071, slow -0.000354; static_r2 0.0011 (fast) and 0.0088 (slow), nothing survives after the static component is removed"
    source: gate_look_log:gate2_ctf_momentum_decile_ls_ctf_join_v2
known_defects:
  - The 2026-08-04 Gate 1 PASS ran after the todo 243 batch-join lookahead fix shipped but before the corpus was recomputed, so it measured known-corrupted data and was voided by the ctf_join_v2 re-verification.
  - The todo 243 defect was a batch-join lookahead in ctf_momentum/ctf_vwap_align/ctf_regime_align (fix _rekey_ctf_series_to_actual_close, shipped 2026-08-03), not a defect in the ranking machinery itself.
spans_looked_at:
  - {start: 2025-12-24, end: 2026-08-07, role: forward_span}
forward_span_looks: 3
tables: [construction_spreads]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - gate_look_log:gate1_ctf_momentum_decile_ls
  - gate_look_log:gate1_ctf_momentum_decile_ls_ctf_join_v2
  - gate_look_log:gate2_ctf_momentum_decile_ls_ctf_join_v2
  - docs/plans/archive/2026-08-05-ctf-join-fix-scoped-recompute-and-gate1-reverify.md
  - .planning/todos/completed/243-ctf-momentum-batch-join-lookahead-bias.md
  - .planning/milestones/v3.1-phases/167-cross-sectional-trade-construction/
  - db:construction_spreads
  - db:gate_evaluations
related_cards: []
---

# ctf_momentum decile long-short cross-sectional construction (phase 167)

## What was tried

The spread tracker implemented and gated a cross-sectional decile long-short construction over
the 80-name ETF universe, with the spec below, gated by Gate 1 (bootstrap CI + shuffled-ranking
null at each cost hurdle) and Gate 2 (static-tilt attribution with a residual CI bound). The
full decile spec the tracker implemented, preserved here so the tracker can be deleted:

- Ranked feature: `ctf_momentum` directly, a single continuous z-scored feature, never a
  composite and never `ensemble_alpha`.
- `decile_fraction = 0.1`; per bar, `n_leg = max(1, round(n * decile_fraction))`; when
  `n < 2 * n_leg` no spread is formed (too few symbols for two disjoint legs).
- Ranking is deterministic and order-independent (the cross_sectional_relative_value script's
  ascending-sort mechanic reproduced exactly): short leg = lowest n_leg, long leg = highest
  n_leg.
- Legs are flat equal-weight and dollar-neutral: spread = mean(long returns) - mean(short
  returns), never vol-scaled.
- Cost hurdles tested per round trip: 1, 3, 5 and 10 bps (`cost_hurdle_bps_round_trip`), read
  from APR, not from `cost_hurdle.<tf>`.
- Null control: shuffled-ranking null, 40 shuffles in the first look, hardened to 1000 in the
  re-verification, `null_p_threshold = 0.05`.
- Attribution: static-tilt regression with `attribution_max_static_r2 = 0.5` and a
  retrospective time-averaged membership benchmark; a surviving residual falsifies the
  static-tilt explanation without establishing what does explain the return.

## What was found

Gate 1 passed on 2026-08-04 (null_p 0.0, positive CI lower bounds at all four cost hurdles),
but that look measured the pre-recompute corpus: the todo 243 batch-join lookahead fix had
shipped 2026-08-03 while the corpus recompute completed 2026-08-06 and `construction_spreads`
was rebuilt 2026-08-07. The ctf_join_v2 re-verification on the corrected construction failed
both gates on 2026-08-07: no bootstrap CI clears zero at any cost hurdle, the shuffled null
gives p 0.649/0.986, and the Gate 2 residual CI lower is negative at both scales. The first
pass came from the lookahead bias fixed in todo 243; on clean data the edge does not survive.

## Known defects

As listed in the front matter: the voided first look, and the underlying todo 243 join
lookahead (fixed before the re-verification).

## Why closed

Both re-verification gates failed; the construction and its tracker are retired with the old
chain (phase 186 plan 19 deletes the tracker with this spec preserved here). Verdict FAIL.

## Where the numbers came from

All gate numbers are quoted verbatim from the three `gate_evaluations.evidence` rows (read
2026-09-27), mirrored in `.planning/gate_look_log.jsonl`. Row count read 2026-09-27:

```sql
SELECT count(*) FROM construction_spreads;  -- 130625
```

The decile spec parameters are quoted from `apr_values_used` in the gate snapshots and from
the tracker source (`_FEATURE = "ctf_momentum"`, `_CONSTRUCTION_NAME =
"ctf_momentum_decile_ls"`, leg mechanics in `_decile_spread_per_bar`/`_legs_per_bar`).
