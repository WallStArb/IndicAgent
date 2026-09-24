# Edge proof program (v3.4)

**Author:** Claude (Opus 5.5), 2026-09-24; reviewed by AGY the same day (four findings adopted: harness instead of DB services, excess-over-null power, two-level decision, 179 off 178's path), at Brandon's request ("come up with concrete steps
and make our priorities/roadmap reflect what levers need to be pulled").
**Status:** active. This doc owns the ordering of milestone v3.4 (phases 177-181).
`.planning/ROADMAP.md` carries the phase entries, `.planning/STATE.md` the current position,
`.planning/todos/PRIORITIES.md` the todo tiers. When they disagree, fix them to match this doc
or revise this doc; don't let a fourth copy of the sequence grow anywhere else.

## Where the project actually stands

The measurement machinery is strong. The edge search has not produced a result that would
survive "would I trust this with real money."

- 14 constructions have been run to a definitive verdict, zero PASS
  (`docs/research/construction-verdict-ledger.md`), across three paradigms. Phase 176's two
  calendar primitives also failed the feature gate. Effective breadth of the feature corpus is
  about 8 independent bets out of about 290 columns.
- Single-name equity breadth failed its decorrelation gate (Phase 174, D-10): shared market beta
  dominates. Cross-asset ETFs passed it (13-symbol basket, avg pairwise corr 0.088, n_eff 6.3).
- The only positive result on record is the cross-asset portfolio diagnostic (todo 378):
  signed `vol_normalized` weighting at ann. Sharpe about 1.19 (naive t=3.08) against an
  `equal_weight` arm at 0.18.

That positive result is weaker than its headline, for three reasons found while writing this
plan:

1. **Mostly in-sample.** The diagnostic ran 2018-01-01 to 2026-09-17 on `alpha_events` from
   `weight_version='run_2025122405150000'`, whose IC selection and ensemble weights were fitted
   on data through 2025-12-24. About 90% of the window scores the signal on the data it was
   fitted to. The walk-forward inside the diagnostic only re-estimates the per-instrument
   scaling, not the signal.
2. **Wrong comparator.** `equal_weight` is long-only and ignores the signal. Beating it shows
   that a signed book differs from a long-only basket, not that the signal carries information.
   The comparator that answers that question is the same weighting fed a null signal
   (sign-shuffled or circular-shifted `alpha_score`).
3. **Underpowered out of sample.** The true holdout (from `alpha.validation.oos_start`,
   2025-12-24) is about 9 months. Even taking the standalone Sharpe of 1.2 at face value
   (the real test is excess over a null, which is weaker), that gives t of about 1.0; reaching t=2 takes
   about 2.8 years of holdout. Waiting is not a plan.

The structural reasons the search has stalled:

- **Feature-first search on a breadth-8 corpus.** Each new primitive gets measured against a
  corpus that already saturates its independent bets, so new features mostly get subsumed
  (176-08 is the latest example).
- **Ensemble weights are fitted once, over the whole in-sample window.** No construction has
  ever had multi-year, weight-level out-of-sample history, so every downstream test either
  spends the 9-month holdout or runs in-sample.
- **Infrastructure work crowds out verdict work.** Most of the last three weeks went to
  throughput, backfill and planning hygiene. Each piece was justified; together they left no
  alpha verdict in flight.
- **Sequencing is spread across four documents** (STATE's next-step chain, PRIORITIES'
  narrative blocks, ROADMAP's pointer section, the memory index), which is how a finished
  migration 351 stayed listed as a blocker.

## The levers, ranked

| # | Lever | Why it moves the edge question | Phase |
|---|---|---|---|
| 1 | Weight-level walk-forward on the cross-asset sleeve | Turns ~9 months of true OOS into ~7 years of pseudo-OOS, enough power for a real verdict on the only vehicle with measured diversification | 179 |
| 2 | Cross-asset breadth | IR grows with the square root of independent bets; n_eff 6 is the binding constraint on any sleeve verdict | 180 |
| 3 | Data floor | Survivorship and weekly silent data gaps bias every number the other levers produce | 177 |
| 4 | Recompute throughput | A 3-day full recompute is the rate limit on every experiment; the bundle cuts it to about 1 day | 178 |
| 5 | Construction track, parallel with 179 | Pre-registered designs already exist (H-A/H-B, cross-TF divergence); they are the fastest new alpha shots after 179, so they run now, each counted in the meta-FDR | 181 |

Lever 1 ranks first because it is the only one that can produce a PASS/FAIL on a real
candidate within weeks. It starts now, in parallel with lever 3. Lever 4 is not on its path:
179 runs in an in-memory harness at 1d and never waits on the full-corpus recompute.

## Phases

### Phase 177: Data integrity floor

Goal: every number produced after this phase comes from data that is fresh, complete, and not
survivorship-selected by construction, and a failure of any of that is heard.

- Todo 395: route `OneshotJobFailed` to a receiver that reaches Brandon, add a gateway-auth probe
  before the nightly fetch, retry after re-auth. The weekly 2FA gap costs ~3 days of bars every
  week and nothing has reported it.
- Todo 376: decide the survivorship sourcing method (delisted and closed ETFs/names with
  point-in-time membership) before phase 180 onboards anything. For the ETF sleeve the concrete
  question is closed/merged ETFs in each asset-class bucket.
- Confirm the 2026-09-24 backfill rerun and 2026-09-25 nightly: exit status, stale-symbol
  counts, `ohlcv_empty_history` growth.
- Backlog triage: every pending todo gets one of on-path (named in a v3.4 phase), keep
  (real, off-path, P2/P3), or close/park with a one-line reason. Target: under 60 pending.

Exit: 7 consecutive nightly runs green, or failed loudly into a working receiver; freshness
within 1 trading day for all `compute_eligible` symbols; survivorship method written into the
phase 180 selection rule.

### Phase 178: Recompute throughput bundle

Goal: one full recompute in about 1.1-1.2 days instead of 3.1-3.5, with fresh weights after it.
Work already in flight in the `indicagent-bundle` worktree (branch
`ic-engine-bundle-post-176`); this phase records it, not re-plans it.

- Todos 401 (row-block memmap fill), 389 (short-horizon cell deletion, pre-registered),
  386 (exact pre-flight count, cap back to 15M), 399 (main-process result memory), prange
  adoption with the worker x numba-thread layout decision (385 lever 2).
- One full recompute, then `ops_ic_shrinkage.py`, `ensemble_trainer`, `alpha_publisher`
  (closes todo 404: champion weights predate the 176-08 recompute).
- Todo 402 (lifecycle hook keyed on window only) if it can land in the same invalidation.

Exit: measured wall time of the bundled recompute; fresh `weight_version` published.

### Phase 179: Cross-asset sleeve walk-forward verdict

Goal: a pre-registered PASS/FAIL on whether the signed, IC-driven cross-asset sleeve carries
information beyond a null signal, with weight-level out-of-sample evidence.

1. **Pre-register before any new number is seen** (`docs/plans/`, same discipline as the
   personal-scale program). Pin the sleeve (the 13 Gate A symbols, fixed), the 1d horizon, the
   arms, the null, the statistic, the decision rule and the meta-FDR discount.
2. **Walk-forward at the weight level, in an in-memory harness.** Annual refits (2011-2025;
   2011-2012 fill the portfolio warmup, trading 2013-2025): IC selection, shrinkage and
   weights are fitted only on data before each refit, pooled over the equity regime group as
   production does, then scored on the next year. The harness reuses the production statistics
   code and never writes production tables. The design, fidelity gates and decision rules live
   only in the pre-registration, `docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md`.
3. **Every input causal at each refit.** Regime labels that stratify the pooled cells, IC
   shrinkage, and any normalization must use only pre-refit data. Note that production strata
   come from `regime_group='equity'` for every symbol (hardcoded in `ensemble_trainer`), so
   GLD, TLT and VIXY are scored with equity-regime-stratified weights. The harness reproduces
   that first; an asset-class-aware variant is a separate pre-registered arm and counts toward
   N_tested. The equity regime labels are causal by construction; features computed from the
   full-sample-fitted HMM (todo 248) are excluded rather than refitted. Full design: the phase
   179 pre-registration, `docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md`.
4. **Arms and null.** Keep `vol_normalized`, `ic_proportional`, `mean_variance`; replace
   `equal_weight` as the decision comparator with the same arm fed a circular-shifted
   `alpha_score` (the project's standing null-arm rule). Keep `equal_weight` as a reported
   reference only.
5. **Statistics and decision levels.** The statistic is the excess return of each arm over
   its own circular-shift null, so power is set by the excess information ratio, not the
   standalone Sharpe, and the day-clustered bootstrap widens it further; the pre-registration
   states the minimum detectable excess IR at 7 years. Two levels, both pinned in advance:
   PASS at a permutation p < 0.05 against the null distribution opens a forward shadow run and
   phase 180's re-test; ACT additionally requires p below 0.05 / N_tested (15 including this
   test, per the ledger's rule, a Bonferroni-style bound) and is the only level that opens
   v4.0 scoping. This keeps the ledger's multiplicity discipline without letting it kill a
   first read that a 7-year sample can't power to t near 3.
6. **Costs.** Fix the cost proxy (todo 393) with a real bps model and report net figures as
   diagnostics only; costs never flip the verdict (standing directive).
7. **Holdout read, once, last.** After the walk-forward verdict is written, score the
   2025-12-24 onward holdout once with the frozen method as a confirmation read. It cannot
   rescue a FAIL.

Exit: `SLEEVE_VERDICT=ACT|PASS|FAIL` recorded in the verdict ledger. PASS opens a forward
shadow run and 180's re-test; ACT also opens scoping of v4.0's portfolio-state phase (156). FAIL closes the sleeve as specified and
leaves lever 2 as the remaining path, re-planned against the failure mechanism.

### Phase 180: Cross-asset breadth expansion

Goal: raise sleeve n_eff from about 6 to 12 or more with a mechanical, survivorship-aware
selection rule, sized by the phase 178 recompute budget.

- Pre-registered selection rule plus a D-10-style decorrelation gate (Phase 174's pattern),
  sourcing per phase 177's survivorship decision.
- Todo 384 (security classification hierarchy) folded in, so point-in-time classification starts
  with the first new onboarding batch.
- Candidate buckets from the current gaps: vol term structure beyond spot VIX, international
  rates and credit, commodity sub-sectors not yet covered, differentiated factor exposures
  (MTUM/QUAL/USMV correlate 0.86-0.98 with SPY, so they don't count until shown otherwise).
- Onboarding and backfill are IBKR-bound, not CPU-bound, so data work starts while phase 179
  runs. The sleeve re-test on the expanded universe waits for 179's verdict and reuses its
  frozen method.

Exit: expanded universe passes its gate; sleeve re-run with the frozen 179 method.

### Phase 181: Construction track (active, parallel with 179)

Runs alongside 179 so idea generation never waits on one verdict; it yields CPU to the phase 178
recompute only while that is running. Each run adds a row to the ledger and raises N_tested.

- H-A/H-B extreme-volume divergence/confirmation (designs final since 2026-09-09; todo 372's
  null-shift fix still needs its independent review first).
- Cross-TF divergence pre-registration (momentum decorrelates across TFs; ensemble-level fusion
  does not exist yet).
- Todo 403 (null-controlled re-decision of earnings-season conditioning).

## What stops

- New feature primitives measured against the full corpus. The corpus is saturated at about 8
  independent bets; a new primitive needs a construction or a sleeve to be tested in, not
  another corpus-wide IC pass.
- Parked until a phase 179 or 180 PASS, or a milestone-boundary review: 145, 147, 149, 150,
  151 waves 6-7, 155, 168, 169, v4.1 (152/153), v2.8 AI Part 2. v4.0 (156-159) stays gated on
  a PASS.
- Off-path P2/P3 todos are started only when no on-path item in the same resource lane (DB
  writes, ic_engine, IBKR) is open.

## Working rules for this milestone

- One verdict phase in flight at all times. Infrastructure work enters only as a P0 or as a
  named step on a verdict phase's critical path.
- Pre-register before looking. The holdout is read once per method, last.
- Every verdict lands in the ledger with the current N_tested.
- The sequence lives here and in ROADMAP's v3.4 section. STATE records position, not plans.
