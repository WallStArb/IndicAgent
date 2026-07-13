---
status: pending
priority: P3
filed: 2026-07-12
source: Phase 144 execution session — user follow-up after regime_group shipped
---

# Formalize the `StratificationDimension` provider contract (design-only, not a build)

## Why now

`docs/research/stratification-dimension-unification.md` ("StratificationDimension — A Unified Conditioning
Layer") proposes unifying the codebase's regime/stratification providers — today two live,
unrelated systems (per-symbol HMM in `regime_writer.py`, cross-sectional in
`equity_regime_model.py`/Phase 144's `cross_sectional_regime_model.py`) plus a backlog of ~12
more candidate dimensions sitting in archived idea docs (percentile-rank, microstructure,
multi-engine variants, todo 076's correlation/liquidity/posterior-weighted candidates) — behind
one provider contract. Its own stated build gate: **"nothing here should be built before v3.15
planning"** — v3.15 is Phases 144+145. Phase 144 shipped 2026-07-12 (code-complete; D-05's
empirical gate still blocked on the unrelated 143.1-07 corpus rebuild, see todo 102).

This todo is explicitly NOT "go build the `StratificationDimension` interface." It's the
design-formalization step: once Phase 144's D-05 verdict lands (proving or disproving the
regime_group mechanism empirically), revisit `stratification-dimension-unification.md` with that evidence
in hand and decide whether/how to formalize the contract — write the actual `Protocol`/ABC,
decide the `concept_registry` row-grain question (already flagged as open in
`platform-unified-concept-registry.md`'s Domain Vetting section and in Phase 144's own
CONTEXT.md Deferred section), and scope which of the ~12 backlog candidates (todo 076 et al.)
are worth planning next. Idea/design work, not code.

## Not yet done

- Phase 145 (Tag Calibrator) hasn't shipped yet either — worth checking at revival time whether
  145's evidence also bears on this (it doesn't directly touch regime stratification, but its
  measured betas could feed a future stratification dimension).
- The `concept_registry` row-grain decision (per-dimension vs per-(dimension, regime_group)
  status) is a prerequisite this todo should resolve or explicitly punt, not silently inherit.

## References

- `docs/research/stratification-dimension-unification.md` (the proposal itself — read in full at revival
  time, it has an 8-point 2026-07-06 re-verification pass worth re-checking for further drift)
- `.planning/phases/144-cross-sectional-regime-model-regime-group-planned/144-06-SUMMARY.md`
  (Phase 144's actual D-05 outcome, whenever it lands)
- `.planning/todos/deferred/076-new-stratification-dimensions-correlation-liquidity-posterior.md`
  (candidate dimensions already gated on Phase 144 shipping — now unblocked for revival too)
- `.planning/todos/pending/105-concept-registry-regime-model-domain-seed.md` (sibling todo —
  Concept Registry's `regime_model` domain seeding; likely sequenced together, not necessarily
  the same work)

**Blocked on:** Phase 144's D-05 empirical verdict (in flight, blocked on todo 102's corpus
rebuild as of filing). Revive once that verdict lands — the whole point of "empirical over
theoretical" is that this unification decision should be informed by whether regime_group
actually worked, not planned blind ahead of that evidence.
