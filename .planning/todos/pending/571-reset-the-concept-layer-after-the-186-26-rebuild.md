---
status: pending
priority: P1
filed: 2026-10-30
source: owner 2026-10-30 ("yes reset it after the rebuild")
---

# Reset the concept layer after the 186-26 rebuild

The 306 `active` features in `concept_registry` were admitted by 590 `concept_evaluation` rows from
2026-09-24, on the old feature corpus and incomplete data. The owner voided every earlier test result
(migration 544 reset the research ledger) and wants this layer reset too, after the rebuild, not during it:
`feature_factory` reads concept statuses, so changing them mid-rebuild could change which features are
computed.

## Trigger

186-26 complete on all timeframes (including the 229 D7-hold names and the recent listings) and todo 564's
kernel batch applied. The data lane gives the go; the reset itself is owner-approved here.

## Do

1. Back up first: `pg_dump -Fc` of `concept_registry`, `concept_evaluation`, `concept_gate`,
   `concept_transition_log`, `concept_recipe`, `concept_parent`, `concept_annotation` into
   `data/backups/reset-<date>/`.
2. Demote the 306 `active` features (and any `shadow_only`) to `candidate` through
   `ConceptRegistryService` only (it is the sole writer of a status; no direct UPDATE), with a reason naming
   this todo, so `concept_transition_log` records it. Clear `concept_gate` counters for them.
3. Decide with the data lane whether `feature_factory` must keep computing the full column set for the
   rebuilt `feature_vectors_v2` regardless of status (the rebuild is a fact table; statuses govern which
   features are measured and trusted, which is the point of resetting them). Verify by reading
   `feature_factory.py` and `services/feature_lifecycle.py` before the demotion; do not assume.
4. `concept_evaluation` rows from 2026-09-24: delete with the same append-only-guard care as migration 544
   (check the table's triggers first; one migration, backup, guard re-enabled in the same transaction).
5. Re-earn `active` on clean data only, through the normal evaluation, after the restart conditions in
   `.planning/STATE.md`.

## Done when

No concept is `active` on evidence from before the rebuild; `concept_transition_log` shows the demotion;
a fresh evaluation run on clean features is what promotes anything next.
