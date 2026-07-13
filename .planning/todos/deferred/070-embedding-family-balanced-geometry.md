# 070 — Family-balanced embedding geometry (decide before Phase 149 locks `embedding_version=1`)

**Status (moved to deferred/, 2026-07-10):** Gate: Phase 149 (AnalogEngine embedding substrate) hasn't started. This is a pre-registration decision, not standalone code work -- revive as part of Phase 149's ANALOG-01 calibration study, before embedding_version=1 locks.


**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §4 (L1a-1),
executive summary item 7.
**Priority:** high — free if decided now, expensive (full re-embed) if caught after the fact.
**Gate:** Phase 149 (AnalogEngine embedding substrate) hasn't started — this is a pre-registration,
not urgent code work today. Must be resolved as part of ANALOG-01's calibration study, before
`embedding_version=1` locks.

## Problem

`intel-analog-engine.md`'s serialization law (per-feature z-score + L2-normalize) makes every
*feature* contribute equal expected weight to cosine distance — which means feature *families*
contribute in proportion to their column count. With today's registry (31 volatility, 30 volume,
29 structure vs 3 macro, 3 cross_tf), "the most similar historical bar" is dominated by
vol/volume/structure resemblance roughly 10:1 over macro context, purely as an accident of how
many columns each family happened to get. The ratio also changes every time the feature set
grows, silently redefining "similar" between embedding versions.

## Fix

Scale each feature by `1/sqrt(n_family)` (group_name from `feature_registry`) before L2
normalization, so each family contributes equal total variance. Zero estimation risk, zero
look-ahead surface, one line in the serialization law. (The alternative — point-in-time PCA
whitening — is strictly more principled and strictly more fragile; pre-register it as the
challenger, not the default.)

## Verdict path

ANALOG-01's calibration study (recall@10, MRR on known-outcome bars) already measures retrieval
quality across candidates — run it with and without family balancing as part of that study, not
as a separate build.

## Action item for whoever plans Phase 149

Add this as an explicit input to ANALOG-01/ANALOG-02 planning, not something decided ad hoc mid-build.
