---
status: pending
priority: P3
filed: 2026-08-30
source: User naming-taste call, 2026-08-29 session -- discussing the corpus recompute's
  remaining steps surfaced that "ensemble" is an ML borrowing, not native quant vocabulary,
  and doesn't fit this project's stated Renaissance/Simons framing as well as alternatives.
---

# Rename the "ensemble" combination layer to `alpha_combiner`

## What

User doesn't like "ensemble" as the name for the feature-combination stage
(`services/ensemble_trainer.py`, `EnsembleICEngine`, `ensemble_weights` table,
`alpha_ensemble_ic` table, `alpha.ensemble.*` APR namespace). "Ensemble" is an ML/bagging-boosting
borrowing; classic stat-arb shops more commonly say "alpha combination" or "signal blending" for
this stage (independently-measured signals -> one weighted composite feeding position sizing).
Given CLAUDE.md's explicit Renaissance/Simons north star, `alpha_combiner` reads as the better
fit and follows the naming system's concept-name-derives-all-layers rule cleanly:

`alpha_combiner` -> `AlphaCombiner` -> `indicagent-alpha-combiner.service` ->
`alpha_combiner_weights` table -> `alpha.combiner.*` APR namespace.

## Scope (real rename, not a quick find-replace)

- `services/ensemble_trainer.py`, `EnsembleICEngine` class + every call site
- DB objects: `ensemble_weights` table, `alpha_ensemble_ic` table/column -- needs a migration
  (rename in place, not drop/recreate; both carry live data and `alpha_ensemble_ic` is the
  ensemble-trainer eligibility source per STATE.md's Key Decisions)
- APR namespace `alpha.ensemble.*` keys in `config_schema`/`config_state`
- CLAUDE.md itself (glossary, pipeline diagram, Key Decisions section) plus every doc/memory
  citing "ensemble"
- Service registry (`_DAG_ORDER`/`_AGENT_ID_TO_UNIT` in `service_auditor.py`) if a systemd unit
  name changes

## Why not now

The in-flight post-Phase-173 corpus recompute (`ops_corpus_pipeline_run.sh --from-step 4`,
launched 2026-08-27) hasn't reached step 7 (`ensemble_trainer`) yet. Land this rename before that
step runs so it executes once, under the new name, against corrected data -- not both a rename
migration and a live-run collision. Purely a naming/hygiene change, no functional behavior
change, no urgency beyond "before ensemble_trainer's next run."
