---
status: pending
priority: P2
filed: 2026-07-23
source: Phase 166 (Frame/Execution Recalibration) D-06 -- consolidated Part 2 deferral,
  filed at phase completion per RESEARCH.md's Q3/Q4 recommendation and the project's
  "capture todos immediately" convention
gate: Phase 164 (SMC Institutional Footprint Primitives) executed + Phase 165 (Swing/Fib/Trend
  Structure Primitives) planned and executed + anchored-VWAP net-new scoping done
status_update_2026-07-29: 2 of 3 prerequisites now cleared -- Phase 164 and Phase 165 both
  COMPLETE per ROADMAP.md (2026-07-28). Anchored-VWAP scoping still not done (no registered
  phase). Historical feature_vectors backfill for both phases' columns is running now (todo 176)
  -- per this todo's own "Do NOT" section, verify columns are non-NULL live before building
  against them, don't assume schema-complete means data-complete.
---

# Extend Phase 166's structural confluence candidate with SMC/swing/fib/anchored-VWAP sources

## Context

Phase 166 built `src/intelligence/trading/structural_confluence.py`: a v3-native port of
`zone_engine.py`'s generic 3-tier confluence-resolution architecture (declarative candidate-spec
table -> dedup -> cluster -> diverse-cluster preference -> single-best -> ATR fallback), with its
candidate universe (Part 1) populated ONLY with what Phase 163 makes live: VP POC/VAH/VAL
ATR-distance fields and `sr_support_dist`/`sr_resist_dist` (+ D-19's companion
`resistance_strength`/`support_strength`/`*_age_bars`).

This is the user's original ask -- "look at what good ideas/logic could be reused/resurfaced/
reimagined from v2 trade lifecycle/tradeframer and applied to v3" -- evaluated empirically as a
competing candidate (D-04), not adopted by inspection. Part 1 (VP/S-R) was buildable now because
its data source (Phase 163) was already planned/execution-ready. The broader v2.x toolkit was
NOT buildable within Phase 166 because every other structural source's feature columns are
100% absent from v3's live `feature_vectors` schema (166-RESEARCH.md Finding 2/Q3, verified by
direct column-name grep against the live DB and the full `FeatureVector` field list -- zero
matches). Building the full toolkit would require executing/planning three separate phases
first, which is out of scope for one phase (166-RESEARCH.md Q3/Q4).

## What this todo asks

Once its three prerequisites land, extend `structural_confluence.py`'s spec table (the
`(feature_key, display_name, default_strength, source_tier, source_family)` tuples starting at
the `# EXTENSION POINT` comment, currently populated only with `_SR_SPECS`/VP fields) with three
additional source families:

1. **SMC (Phase 164, "SMC Institutional Footprint Primitives")** -- order blocks, liquidity
   pools/sweeps, BOS/CHoCH, premium/discount. Phase 164 is registered in ROADMAP.md but has zero
   planning artifacts (no CONTEXT.md/RESEARCH.md/PLAN.md) as of this todo's filing --
   `/gsd-discuss-phase 164` -> `/gsd-plan-phase 164` -> `/gsd-execute-phase 164` must run first.
2. **Swing/Fib/Trend (Phase 165, "Swing/Fib/Trend Structure Primitives")** -- swing highs/lows,
   trend structure (HH/HL/LH/LL), Fibonacci zones. Phase 165 has CONTEXT.md + RESEARCH.md already
   written (41 new columns across 5 files: `swing_detector`/`swing_momentum`/`trend_structure`/
   `fibonacci_zones`/`session_levels`) but is not yet planned (no PLAN.md) or executed --
   `/gsd-plan-phase 165` -> `/gsd-execute-phase 165` must run first.
3. **Anchored VWAP** -- `avwap_upper_band`/`avwap_lower_band` and related bands. No registered
   phase covers this at all as of this todo's filing (neither ROADMAP.md nor STATE.md mentions a
   phase for porting `src/intelligence/context/anchored_vwap.py` into v3's Feature Factory). This
   needs net-new scoping (a new phase, or folded into 164/165's scope) before it can be built.

## Why this is cheap once the data exists

The confluence-resolution ARCHITECTURE (this todo's whole point per 166-RESEARCH.md Pattern 2)
already supports this extension with zero redesign: `collect_candidates()`'s spec-table-driven
design means adding a new source is purely additive -- new `(feature_key, ...)` tuples feeding
the same generic `_find_clusters`/`_score_cluster`/`_pick_single_best` core, which is entirely
generic over `ZoneCandidate` and references no specific feature name. The hard part (porting the
clustering/scoring core, proving it works against a real Phase-163-gated candidate universe) is
already done. This todo is "widen the spec table," not "redesign the mechanism."

## Do NOT

- Do not silently build against `src/intelligence/features/smc_context/`'s orphaned duplicate
  copies (`register_plugins.py` imports exclusively from `src/intelligence/archive/smc_context/`
  for every SMC file with a dual copy -- the `features/` copies are byte-identical unimported
  dead code, not "the newer version"). See 166-RESEARCH.md Q2's naming-collision warning.
- Do not assume any of Phase 164/165/anchored-VWAP's future columns exist before verifying live
  (`SELECT count(*) FROM feature_vectors WHERE <column> IS NOT NULL`) -- the same
  NULL_PENDING_163 trap Phase 166 hit for VP/S-R applies to each of these three sources
  independently once their respective phase lands.
- Do not re-evaluate the empirical comparison from scratch -- re-run this exact extended
  candidate through a NEW gate_id (not `gate166_structural`, which is a one-shot D-04 result
  already consumed) once the extension is built.

## References

- `src/intelligence/trading/structural_confluence.py` -- the module this todo extends (its
  `# EXTENSION POINT` comment cites this todo's number)
- `.planning/phases/166-frame-execution-recalibration/166-RESEARCH.md` -- Q1-Q4 ("Broadened
  Structural Candidate: Full Investigation"), the full reasoning for the two-part split
- `.planning/phases/166-frame-execution-recalibration/166-CONTEXT.md` D-06 -- the phase-level
  decision this todo implements
- `docs/plans/archive/2026-07-23-phase166-frame-recalibration-verdict.md` -- Phase 166's verdict doc,
  which states the toolkit was evaluated and deliberately deferred here (not silently dropped)
- `src/intelligence/trading/zone_engine.py` -- the archived v2.x module this phase's Part 1
  ported from; its own 14-entry spec table names the exact v2.x feature keys (all currently
  absent from v3) that would map onto Phase 164/165/anchored-VWAP's eventual columns
