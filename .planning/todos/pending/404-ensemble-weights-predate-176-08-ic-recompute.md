---
status: pending
priority: P1
filed: 2026-09-24
source: measured while designing todo 402 (docs/plans/2026-09-24-feature-lifecycle-evidence-ledger-design.md, finding 6)
---

# Champion ensemble weights predate the 176-08 IC recompute

## What

The champion `ensemble_weights` version `run_2025122405150000` (385 UNIVERSE rows, 86 features,
31 strata) was computed 2026-09-22 13:40 UTC. The 176-08 corpus IC recompute finished
2026-09-24. On the recomputed `feature_ic_scores`, 143 of the 385 weighted cells fail the
per-cell gate (`passes_fdr` or CI on own side). `ensemble_trainer` has not re-run against the
new IC, so `alpha_publisher` and any shadow evaluation read weights built on superseded
evidence.

## Fix direction

Re-run `ensemble_trainer` for the pinned window after the post-176 bundle's recompute (not
before: that recompute supersedes 176-08's IC again). Separately, decide whether the corpus
pipeline chain should run `ensemble_trainer` after every `ic_engine` recompute so this cannot
recur; with `feature_lifecycle` as its own node (todo 402 design) the chain would be
`ic_engine -> feature_lifecycle -> ensemble_trainer`.
