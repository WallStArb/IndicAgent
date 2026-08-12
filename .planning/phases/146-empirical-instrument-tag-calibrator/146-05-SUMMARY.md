---
phase: 146-empirical-instrument-tag-calibrator
plan: 05
subsystem: docs
tags: [design-doc, regime-conditioning, tag-calibrator, TAG-02, dual-regime-system]

# Dependency graph
requires:
  - phase: 146-02
    provides: measurement-contract schema (migration 238) this design extends
provides:
  - Phase 2 regime-conditioning design document (docs/research/tag-calibrator-phase2-regime-conditioning.md)
  - Settled PK extension (symbol, tag) -> (symbol, tag, regime)
  - Settled regime-axis resolution (market_regimes default, feature_vectors.regime for idiosyncratic cases)
  - Settled trigger gate (non-overlapping-CI divergence test)
  - Settled per-stratum sample-size guard tied to alpha.tag_calibrator.min_sample_n
affects: [future Phase 2 regime-conditioning execution, TAG-02]

# Tech tracking
tech-stack:
  added: []
  patterns: ["design-only doc with settled PK/axis/gate/guard decisions ahead of code"]

key-files:
  created: [docs/research/tag-calibrator-phase2-regime-conditioning.md]
  modified: []

key-decisions:
  - "Regime axis default is market_regimes.regime_group (systematic/cross-sectional) for the canonical TLT/XLU flight-to-quality example, not feature_vectors.regime (idiosyncratic/per-symbol HMM) — either axis is supported by the schema sketch, resolved as an explicit (dimension, label) pair, never a bare label"
  - "Per-stratum sample-size guard reuses the existing alpha.tag_calibrator.min_sample_n APR key (no new, lower threshold for regime strata) applied once per (symbol, tag, regime) cell instead of once per (symbol, tag) pair"
  - "Trigger gate operationalized as non-overlapping confidence intervals across regime-stratified loadings, not a bare point-estimate difference"
  - "Phase 2 explicitly supersedes D-06's kept cycle_position definitional tags once it ships — flagged as a Phase 2 execution-plan item, not resolved now"

requirements-completed: [TAG-02]

# Metrics
duration: 12min
completed: 2026-07-17
---

# Phase 146 Plan 05: Tag Calibrator Phase 2 Regime-Conditioning Design Summary

**Design-only document settling TAG-02's regime-conditioning extension (PK, regime axis, trigger gate, per-stratum sample guard, deferral) so Phase 146's Wave 1 schema ships with the Phase 2 extension path already documented — no code, no migration.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-17T08:07:00Z (approx, first file read)
- **Completed:** 2026-07-17T08:20:17Z
- **Tasks:** 1/1 completed
- **Files modified:** 1 created

## Accomplishments
- Documented the PK extension `(symbol, tag)` -> `(symbol, tag, regime)`, including how the new
  `regime` dimension relates to migration 238's measurement-contract columns and how
  `valid_from`/`valid_to` behave per-regime (independent lifecycle per stratum).
- Resolved the regime-axis question against this project's dual regime system: the design states
  `market_regimes.regime_group` (systematic/cross-sectional) as the correct default axis for the
  design doc's canonical TLT/XLU flight-to-quality example, while explicitly leaving
  `feature_vectors.regime` (idiosyncratic/per-symbol HMM) available for future tags whose
  regime-dependence is instrument-specific rather than market-wide — resolved always as an explicit
  `(dimension, label)` pair, never a bare label.
- Operationalized the ROADMAP's "ships when IC stratification by tag shows regime-dependent
  divergence" ship condition into a concrete test: non-overlapping confidence intervals across
  regime-stratified loadings, evidenced across a tag's holder population, not a single anecdote or
  bare point-estimate gap.
- Documented the F6.3 per-stratum sample-size guard and tied it directly to the live
  `alpha.tag_calibrator.min_sample_n` APR key (already seeded by migration 238) — same key, same
  threshold, applied per `(symbol, tag, regime)` cell instead of once per `(symbol, tag)` pair — and
  noted the consequent hypothesis-count multiplication that makes Phase 1's run-level BH-FDR
  correction a hard prerequisite for Phase 2.
- Stated the explicit deferral: Phase 2 does not ship in Phase 146; listed four concrete
  preconditions (accumulated multi-regime history, an actually-evaluated trigger gate, a
  re-verified sample-size guard at live universe/regime-count scale, and explicit supersession of
  D-06's `cycle_position` definitional tags).

## Task Commits

1. **Task 1: Write the Phase 2 regime-conditioning design document** - `417897cb` (docs)

**Plan metadata:** (this commit, docs(146-05): complete plan)

## Files Created/Modified
- `docs/research/tag-calibrator-phase2-regime-conditioning.md` - Design-only doc: problem statement
  (why unconditional betas under-represent regime-dependent factor exposure), schema extension
  sketch, regime-axis resolution against the dual regime system, operationalized trigger gate,
  per-stratum sample-size guard tied to `alpha.tag_calibrator.min_sample_n`, and explicit
  non-goals/deferral section. Carries an `Informed by` provenance line per the project's
  doc-provenance convention (this is a Claude-authored synthesis of already-settled design-doc and
  CONTEXT.md/RESEARCH.md content, not a wholesale model-dispatched analytical doc, so `Informed by`
  rather than `Author` applies).

## Deviations from Plan

None - plan executed exactly as written. All six required sections (problem, schema extension,
regime-axis choice, trigger gate, per-stratum sample-size guard, non-goals/deferral) are present,
the PK extension and ship condition are stated explicitly, F6.3's gate is tied to
`alpha.tag_calibrator.min_sample_n`, and the doc contains no executable code or migration SQL.

## Known Stubs

None - this is a documentation-only deliverable with no code, no data flow, and no rendering
surface to stub.

## Threat Flags

None - per the plan's own threat model (T-146-11, disposition `mitigate`), the only risk was an
under-specified sample gate; the doc explicitly documents and ties F6.3's gate to
`alpha.tag_calibrator.min_sample_n`, satisfying the mitigation. No new network endpoints, auth
paths, file access patterns, or schema changes were introduced (design-only, zero code).

## Self-Check: PASSED

- FOUND: docs/research/tag-calibrator-phase2-regime-conditioning.md
- FOUND: 417897cb (git log --oneline --all confirms commit exists)
