# 084 — Pre-committed ablation protocol for ensemble degradation

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §11 (G-2).
**Priority:** medium — cheap precursor of the already-planned 0a (marginal contribution) item in
`measurement-ic-engine.md`; buildable now against existing tables.
**Gate:** none — a script over `ensemble_weights`/`feature_vectors`/`forward_returns`, no new
tables (results go in the run manifest).

## Proposal

When ensemble OOS IC degrades between epochs, the current response is ad-hoc forensics
(EIC-05-style diagnosis, done by hand each time). Pre-commit the mechanical first pass:
leave-one-family-out re-scoring (zero one `group_name`'s weights, recompute alpha on the OOS
window, re-measure) across all ~10 families, producing a marginal-attribution table per stratum.
Answers "what died" in one batch run before any human hypothesis enters the room — the
SHADOW-REVIEW discipline applied to postmortems.

Building this first derisks 0a's eventual full implementation (same computation shape, coarser
grain).
