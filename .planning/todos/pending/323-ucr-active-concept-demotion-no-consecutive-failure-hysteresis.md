# 323 - UCR's active->shadow_only demotion has no consecutive-failure hysteresis -- one noisy corpus run can demote an already-proven concept

**Filed:** 2026-08-15
**Source:** User correction to a claim I made comparing UCR against the legacy `shadow_registry`
system. I'd claimed UCR's `consecutive_shadow_passes`/`observations_since_demotion` counters were
"an equivalent, richer version" of `shadow_registry`'s pre-demotion consecutive-failure count
(`shadow_auditor.py`'s `demotion_consecutive_count`, requiring N consecutive failing evaluations
before demoting). The user checked this against the actual `ConceptRegistryService` code and it's
wrong -- verified directly:

- `ConceptRegistryService.advance_shadow_counters_sync` (`src/intelligence/concept_registry_service.py:794-808`),
  its own docstring: *"there is no fail-counter for active concepts; demotion is decided by the
  caller's per-run materiality check, not by any registry counter (mirrors
  `FeatureRegistryService.advance_shadow_counters_sync` exactly)."*
- `consecutive_shadow_passes`/`observations_since_demotion` only mutate for concepts already in
  `shadow_only` status, and only feed `is_promotion_eligible()` -- the `shadow_only -> active`
  **recovery** gate. Neither is read anywhere in the `active -> shadow_only`/`deprecated` demotion
  path.
- This is a deliberate, explicit design decision dating to Phase 143 Plan 02
  (`.planning/phases/143-.../143-02-PLAN.md:233`, done-criteria: "no invented demotion counter"),
  carried forward verbatim into Phase 170's UCR migration.

## What the actual demotion mechanism is (checked: `services/ic_engine.py:4333-4378`)

Per corpus run, for each `active` feature: aggregate all of that feature's cells (stratum
combinations) evaluated as `active` this run, compute `demote_fraction` = fraction with a
`_material_fail`, and demote immediately (`record_transition_sync(..., to_status="shadow_only",
reason="demotion_performance")`) if `demote_fraction >= demotion_fraction_floor`
(`1.0 - config.meta_fdr_min_fraction`).

This is a **cross-sectional** materiality check (across strata within one run), not a **temporal**
one (across multiple independent runs over time). `shadow_registry`'s `demotion_consecutive_count`
provided the latter -- requiring the same failure to repeat across N separate evaluation cycles
before acting on it. UCR's live demotion path provides no equivalent: a single corpus run where a
feature's cells materially fail across most strata (data-quality blip, one-off regime noise,
transient upstream issue) demotes an already-`active`, previously-proven concept immediately, with
no requirement that the failure be observed more than once.

## Why this matters

This is an asymmetry the project's own design principles argue against: Invariant 7 (UCR's own
doc) requires promotion to clear an effective-N floor specifically because "a concept clearing
p<0.05 on 50 bars is a fluke, not proof" -- the same logic applies to demotion evidence, but
nothing currently enforces it there. `ensemble_strategy`'s promotion path additionally requires a
win-streak (`promotion_consecutive`) before promoting; the `feature` domain's demotion path has no
analogous streak requirement before demoting. `feature_ic_scores` cells are themselves subject to
run-to-run noise (regime reclassification, HMM refit drift, corpus-window edge effects) -- exactly
the kind of single-draw noise a consecutive-failure requirement exists to filter out.

## Fix (not scoped here -- needs a real design pass, not a drive-by patch)

Add a genuine pre-demotion hysteresis mechanism to `ConceptRegistryService`/`ic_engine.py`'s
demotion path -- e.g. a `consecutive_active_fails` counter (mirroring the existing
`consecutive_shadow_passes` shape but on the demotion side) that must clear an APR-sourced floor
(`alpha.concept_registry.demotion_min_consecutive_fails` or similar) before
`record_transition_sync(..., to_status="shadow_only")` actually fires, resetting to 0 on any
passing run. Needs its own plan: what floor value is defensible, whether it should be uniform
across `feature`/`ensemble_strategy` domains or domain-specific.

**Checked, not a pre-existing partial solution:** `concept_gate.decay_ratio`/`decay_floor` looked
like they might already serve this role (the column names suggest exactly this kind of smoothed
demotion signal). Grepped `concept_registry_service.py`, `ic_engine.py`, `ensemble_trainer.py` --
the only hit is `concept_registry_service.py:285`, which just resets `decay_ratio = 1.0` on
promotion (a neutral-baseline write, not a read). Nothing computes or reads either column to gate
a demotion decision today. Schema-level scaffolding exists; the read-side wiring that would make
it do something does not -- worth building the fix around these existing columns rather than
adding a fully separate counter, if their original intent (check migration 225/283's own
comments) was in fact this.
