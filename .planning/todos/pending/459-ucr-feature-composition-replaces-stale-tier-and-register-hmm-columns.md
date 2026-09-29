---
status: pending
priority: P3
filed: 2026-09-29
source: owner question 2026-09-29 while describing the feature corpus; scoped into phase 187 (ROADMAP goal) by owner decision 2026-09-29
---

# UCR feature rows: replace the stale tier taxonomy with composition, register the 11 HMM columns

## What

`concept_registry.metadata->>'tier'` still carries `0_atomic` / `1_interaction` / `2_theory`
(164 + 5 candidate / 25 / 106 feature rows), and `controlled_vocabulary` namespace `tier` holds
the same three codes. The glossary already calls this taxonomy stale (`Stage 0` entry: proposed
against the dropped `feature_registry` table, never re-targeted at `concept_registry`).

The `2_theory` split is not a real distinction: those 106 features (`poc_dist_atr`,
`prior_session_close_dist_atr`, `sr_support_dist`, `sweep_detected`, `supply_freshness`, ...) are
direct measurements from a name's own bars, as atomic ones are; only the idea behind them comes
from market-structure theory. The one distinction that matters is composition: a base measurement
computed from bars or the timestamp, versus an interaction built from other features.

Separately, 11 numeric `feature_vectors` columns have no `concept_registry` row at all:
`hmm_prob_trending_up`, `hmm_prob_trending_down`, `hmm_prob_ranging`, `hmm_churn`,
`hmm_vol_regime_prob`, `hmm_vol_prob_calm`, `hmm_vol_prob_elevated`, `hmm_vol_prob_turbulent`,
`hmm_vol_entropy`, `hmm_vol_duration`, `hmm_vol_churn`. That breaks `lineage` for 11 of 311
feature columns.

## Steps

1. Decide the replacement key with phase 187's typed domains (a `composition` of `base` /
   `interaction`, or whatever the recipe book's recipe type already expresses; do not add a key
   187 would drop).
2. Migration: rewrite the metadata key on the 300 feature rows, replace the `tier` CVR namespace,
   update `src/config/vocabulary_drift.py`'s `tier` query in the same commit.
3. Register the 11 HMM columns (seeded `active`, as a migration adding a `FeatureVector` field
   may), with their recipe pointing at `regime_writer`. Check todo 248's HMM rebuild first: if it
   renames or replaces these columns, register the new names.
4. Update the glossary (`Stage 0` status note, the calendar atomic entry's code surface) and
   `docs/foundation/naming-system.md`.

## Counts at filing (live DB, 2026-09-29)

`feature_vectors`: 322 columns, 311 numeric features. `concept_registry` domain `feature`: 295
active (164 / 25 / 106), 5 candidate `0_atomic`, 2 deprecated.
