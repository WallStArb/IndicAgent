# Ensemble Combiner Adaptivity & Allocation — Idea (Edge Source Thesis adaptive_combiner_weights, plus 3 related E-candidates)

**Status:** All four candidates below checked against live state 2026-08-07. One
(`adaptive_combiner_weights` / L5-4) reconciled to a data-driven trigger. Two (L5-2, L5-3) are
correctly, unavoidably gated — verified live, not just asserted. One (L5-1) has a real,
currently-idle blocker worth raising — see "Recommendation" below.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-07 — not a Fable dispatch. Consolidates
and supersedes `.planning/todos/pending/080-ensemble-combination-e-candidates-queue.md` (filed
2026-07-08, sourced from `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §8),
which had accumulated substantial research-backlog content in a `pending/` todo file — a
mismatch with that folder's own stated scope ("small, single-session, run-it-now items",
`PRIORITIES.md`'s header). Moved here wholesale, same precedent as todo 009 absorbing todos
012/032. Todo 080's own file is now a redirect stub.
**Origin:** All four originate from the same source doc's §8 (L5-1 through L5-4, executive
summary item 5) — a queue of E4+ ensemble-combination candidates, all expressible as
`weight_version` variants judged by the existing `ops_ensemble_weight_compare.py` A/B machinery,
all inside the one-model-one-book invariant. E1 (shrunk-IC) and E2 (mean-variance Σ⁻¹·IC) are
already built (Phase 142B.1) and out of scope here.
**Companion to:** `docs/research/data-edge-source-thesis.md` (only L5-4 is a named
Signal-Extraction thesis there, `adaptive_combiner_weights`; L5-1/L5-2/L5-3 are ensemble-layer
candidates with no thesis entry of their own — this doc is their only home).

---

## L5-4 — `adaptive_combiner_weights` (Trailing-IC adaptive weighting)

The one candidate with a Signal-Extraction thesis entry (`data-edge-source-thesis.md`).
`ensemble_trainer.py`'s shrunk-IC weights are re-estimated in discrete batch runs, not
continuously. Proposal: let weights drift smoothly (EWMA, or a Kalman filter — the discrete-time
analog of a continuous-time linear stochastic system, weights as latent slowly-varying state)
instead of updating only on periodic batch recomputes. Orthogonal to `regime_conditional_persistence` (continuous
drift vs. discrete regime switch) and `nonlinear_interaction_combiner` (adaptive linear weights vs. static non-linear
combination) — no new grouping or model family, just a different update dynamic on the existing
linear combiner.

**Falsification bar:** build a walk-forward EWMA (or Kalman-filtered) weight update over the same
per-feature IC series `ensemble_trainer.py` already computes, with a pre-specified halflife grid
(three halflives spanning an order of magnitude, motivated by the recompute cadence, not tuned to
the result — report every cell, BH-FDR across the grid). Compare OOS IC/Sharpe against the
current periodic-batch weights over the identical held-out window. If no real uplift, dead.

**Blocker, verified live 2026-08-07:** `feature_ic_scores`/`feature_ic_scores_history` both have
exactly **one** `training_window_end` snapshot — mathematically degenerate for fitting a halflife.
This is *not* the same gap as this doc's own `measurement-ic-engine.md` P1 proposal (a dedicated
60-day rolling-window `ic_trailing_series` table, ~60x static-run compute, doesn't exist and
isn't what this idea needs) — the coarse per-recompute series this candidate actually wants
accumulates for free via `ic_engine.py`'s own archive-before-overwrite step
(`_ARCHIVE_BEFORE_DELETE_SQL`), it's just thin on data because recomputes here are
event-triggered, not scheduled. Not worth accelerating artificially (no baseline evidence yet
that real time-varying decay exists to chase). Trigger tracked at
[`.planning/seeds/adaptive-combiner-weights-trailing-ic-trigger.md`](../../.planning/seeds/adaptive-combiner-weights-trailing-ic-trigger.md)
(`feature_ic_scores_history` ≥ 3 distinct snapshots).

**Consumer caveat, weaker than originally stated:** the live construction that made this "no
consumer" (`cross_sectional_spread_tracker.py` ranking by the single raw feature `ctf_momentum`)
is now confirmed dead (Phase 167, both Validation Gates FAIL, 2026-08-07). Whatever construction
eventually replaces it may consume ensemble weights directly. More features landing (Phase 151
waves 6-7, still pending) also increases the surface area for real feature-level decay between
periodic re-fits — this gets more valuable over time, not less.

---

## L5-1 — Regime-posterior soft blending (highest-conviction, per-symbol-HMM axis)

Today: `alpha_score(bar) = w[regime_label(bar)] · features(bar)` with hard argmax labels. The
per-symbol HMM's own posteriors are often 55/45 and the system already stores them
(`hmm_prob_trending_up/ranging/trending_down`, `hmm_entropy`, `hmm_churn`). Proposal:
`alpha_score = Σ_r P(r|bar) · (w_r · features)`. Removes the alpha discontinuity at every
boundary crossing (today manufactures emission churn from label noise) and degrades gracefully
exactly where the Phase 144 conditioning decision worries labels are weakest.

**Scope correction, 2026-08-02:** the cross-sectional-strata claim in the original write-up
doesn't hold — `market_regimes.regime_prob_vector` is the *raw signals* that fed hard-threshold
bucketing, not a probability distribution over labels (`cross_sectional_regime_model.py`'s
`_assign_labels` traced directly). There is no `P(regime|bar)` to consume for cross-sectional
strata without inventing one — a real design task. **The per-symbol HMM side (`hmm_prob_*`) is
unaffected by this correction** — those genuinely are posteriors, and this candidate can proceed
on that axis alone.

**Blocker: todo 005 must run first**
(`.planning/todos/pending/005-ic-regime-transition-purge.md`). Same underlying mechanics
(`_bucket()`/`_assign_labels()` hard-threshold behavior) from a different angle — IC measurement
contamination, not scoring churn. If todo 005's diagnostic finds combined-label smoothing worth
implementing at the source, that independently reduces the label flicker feeding this
candidate's boundary-churn question too. Running L5-1's own Phase 0 diagnostic
(`scripts/analysis/regime_boundary_churn_check.py`, built and tested, never executed) against
today's unsmoothed labels risks a materiality reading inflated by flicker todo 005 might
independently eliminate.

**Verified live 2026-08-07: todo 005 is itself unblocked, not another dead end.** Its own gate
("Phase 141 complete") cleared 2026-08-02; it's been sitting idle in `pending/` at **P2** for 5
days since, not started — attention went to the CTF investigation instead. Todo 005's own
re-scoped finding (2026-07-19, verified against live code) is sharper than a P2 label suggests:
`cross_sectional_regime_model.py`'s live label source (`market_regimes`, what `ic_engine.py`
actually stratifies on by default) does **pure per-bar VIX-percentile × breadth-fraction
threshold bucketing with zero transition guard of any kind** — not even the hysteresis the
per-symbol HMM path already has via `_smooth_states()`. A bar sitting right at a threshold
crossing can flip its regime label on the next tick with nothing smoothing it. That's not just
L5-1's blocker — it's a live measurement-integrity gap sitting underneath every
regime-stratified IC test this project runs, including the regime-conditional test
`jump_diffusion_decomposition`'s own pre-registration specifies
(`measurement-jump-diffusion-decomposition.md`).

**Recommendation:** raise todo 005 to P1 (currently mis-tiered given what it actually is — a live
integrity gap, not an optimization) and run its diagnostic as a third parallel track alongside
`jump_diffusion_decomposition`/`cointegrated_pairs_residual` — disjoint, read-only, same resource
shape as those two. Once todo 005 resolves, L5-1's own Phase 0 diagnostic becomes trustworthy to
run.

Scope once unblocked: one new `weight_version`, judged per-stratum by the existing D-10 win rule;
zero new parameters; a scoring-path change in `ensemble_trainer`/`alpha_publisher` behind a
variant flag, no new tables.

---

## L5-2 — Hierarchical family-then-feature allocation (HRP-lite)

`cluster_deflate_weights` only caps pairwise-correlated clusters, so a large feature family
(`structure`: 72 fields, `session`: 62 — 134 of 292 total, 46% — confirmed live 2026-08-05,
supersedes stale "31 vol vs 3 macro" framing from the original write-up) can still absorb
outsized total weight through sheer population regardless of pairwise correlation. Proposal:
allocate across families first (by family-level aggregate IC Sharpe), then within family —
weak-signal diversification at the family grain, structurally preventing "the ensemble is
secretly one [structure/session] bet." A pure function in `src/intelligence/ensemble/weights.py`
+ a variant flag; compare realized `effective_n` and family weight-share concentration between
variants. E1/E2 mechanism claims re-verified 2026-08-05: `mean_variance_weights` (E2) exists in
`src/intelligence/ensemble/weights.py`, `ops_ensemble_weight_compare.py` exists as the A/B judge.

**Blocker: `feature_registry.group_name` is not a safe anchor to build the family tree on.**
`concept_registry` (domain='feature') already has its own `group_name` column, and todo 118
("migrate feature_registry into concept_registry ASAP") is being executed by Phase 170 in a
separate concurrent session. Building on `feature_registry.group_name` today risks building on a
table mid-retirement.

**Verified live 2026-08-07: Phase 170 has not merged, and is not close.**
`feature_registry` still has 292 live rows; `concept_registry` (domain='feature') has 294 rows in
shadow-write only — the actual cutover (Plan 08, the DROP) is blocked behind zero
`registry_dual_write_verified` facts existing, which itself is blocked behind the corpus
pipeline's separate FATAL halt at `ops_canary_integrity_assert.py` (todo 230, unresolved).
Per `.planning/ROADMAP.md`'s own Phase 170 status: "6/8 plans genuinely complete, 2/8 correctly
BLOCKED — not 'phase done.'" This is a real, multi-step blocker chain Phase 170 didn't create and
can't resolve alone. **Correctly gated — no action available; re-check once Phase 170's Plan 08
actually lands**, then re-derive the `group_name` distribution above against `concept_registry`
before starting design.

---

## L5-3 — Bayesian averaging over variants instead of champion selection

Champion selection per stratum is strong-signal concentration at the meta level, with the
winner's-curse bias todo 069 documents. Once 3+ variants exist, blend variants with weights
proportional to accumulated evidence (todo 079's e-values slot in naturally as unnormalized
evidence weights). No single variant needs to be right; regime-varying variant quality handled
automatically. Just another `weight_version` in the A/B framework — if the blend can't beat its
own best constituent OOS, averaging loses and champion selection stands.

**Blocker: gated on 3+ variants existing.** **Verified live 2026-08-07:** exactly **one**
`weight_version` currently exists in `ensemble_weights` (`run_2025122405150000`). Structurally
cannot start — there's nothing to average over yet. Correctly gated. Will naturally clear if
L5-1 or L5-2 (or any other E-candidate) ever ships as a second variant; needs at least 2 more
beyond today's 1.

---

## References

- `docs/research/data-edge-source-thesis.md` — `adaptive_combiner_weights` thesis summary, points here
- `.planning/seeds/adaptive-combiner-weights-trailing-ic-trigger.md` — L5-4's trigger-condition tracker
- `.planning/todos/pending/005-ic-regime-transition-purge.md` — L5-1's blocker, recommend raising to P1
- `.planning/todos/pending/118-migrate-feature-domain-into-concept-registry.md` — L5-2's blocker's real content
- `.planning/ROADMAP.md` §Phase 170 — current, accurate Phase 170 status
- `services/ic_engine.py` — `_ARCHIVE_BEFORE_DELETE_SQL`, L5-4's free-accumulation mechanism
- `src/intelligence/ensemble/weights.py`, `scripts/ops/alpha/ops_ensemble_weight_compare.py` — the A/B machinery all four candidates would use
