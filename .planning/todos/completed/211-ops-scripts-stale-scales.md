---
status: pending
priority: P2
filed: 2026-07-30
source: final whole-branch review of docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md
  found these two additional consumers, distinct from todos 209/210
---

**Part 1 of 2 DONE 2026-07-30** (commit `658378a6`) — `ops_ensemble_ablation.py` migrated:
`AblationConfig` now mirrors `ICEngineConfig`'s shape exactly (per-tf `lookahead_{scale}` dicts +
`active_scales`, loaded via the shared `services._batch_utils` helpers). **Fixing this surfaced a
second, independent bug in the same file, not part of the original filing below**: `AblationConfig`
was ALSO still reading the pre-todo-146 flat global `alpha.ic.lookahead.{scale}` keys (no `{tf}`
component) — the script's own code carried a self-aware runtime warning citing todo 202 as the
tracker, but todo 202 closed without ever picking this up. Fixed in the same commit. Full test
suite green.

**Part 2 (`ops_interaction_primitives_pilot.py`) NOT started** — still needs the `_SCALES`
migration described below, plus its own independent stale-global-key bug (same class as the one
just found and fixed in part 1 — check for it explicitly, don't assume the `_SCALES` fix alone
covers it).

# Two more standalone ops scripts still read hardcoded, uniform-across-tfs scale
# tuples/keys -- one has an independent pre-existing bug unrelated to this plan

## Problem

The final whole-branch review of the per-tf active-scale-set plan (2026-07-30) ran a
repo-wide sweep beyond what any single task's scoped review covered, and found two more
standalone, manually-invoked scripts with the same "hardcoded 4-scale assumption" defect
class as todos 209/210 -- neither was named in the design spec, the plan, or either prior
todo:

1. **`scripts/ops/alpha/ops_ensemble_ablation.py`** -- imports `_SCALES` and
   `_SCALE_RETURN_COLUMNS` from `ensemble_ic_engine` and hardcodes all four scales at
   lines 363-365, 442, 562, 1098. Same defect class as todo 210 (reads the flat
   module-level constant, not `active_scales_for(tf)`).

2. **`scripts/ops/alpha/ops_interaction_primitives_pilot.py`** -- defines its own local
   `_SCALES` (line 54), AND separately builds `alpha.ic.lookahead.{scale}` (line 56) --
   **the pre-todo-146 GLOBAL key name, which no longer exists in `config_state`** (todo 146
   replaced it with the per-tf `alpha.ic.lookahead.{tf}.{scale}` keys back on 2026-07-29).
   This second issue is a standalone, independently pre-existing bug -- not caused by the
   per-tf active-scale-set plan at all, just newly discovered by its review sweep. Whatever
   this script currently reads from that key is either a silent-fallback default or
   erroring; needs its own investigation independent of the active-scales question.

## Fix

For (1): same mechanical fix as todos 209/210 -- migrate to `config.active_scales_for(tf)`
(or `EnsembleICConfig`'s equivalent, once todo 210 lands).

For (2): two independent fixes needed -- migrate `_SCALES` the same way, AND separately
fix the stale `alpha.ic.lookahead.{scale}` global-key reference to the real per-tf
`alpha.ic.lookahead.{tf}.{scale}` keys (same fix class as todo 202's already-closed
`corpus_manifest_verifier.py`/6-other-scripts sweep -- this script was apparently missed
by that sweep too, or introduced/last-touched after it ran).

## Sizing

Both are standalone, manually-invoked diagnostic/ablation scripts -- not in the corpus
pipeline's critical path (same category as todo 209's `ops_vol_normalized_target_ab.py`).
Small, mechanical fixes once picked up; not urgent, but should be batched with 209/210
when someone next touches this cluster of scripts.

## References

- `.planning/todos/pending/209-ops-vol-normalized-target-ab-scales.md`,
  `.planning/todos/pending/210-ensemble-ic-worker-scales.md` -- sibling findings, same
  defect class
- `docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md` -- the plan whose final
  review surfaced this
- `scripts/ops/alpha/ops_ensemble_ablation.py:80,363-365,442,562,1098`
- `scripts/ops/alpha/ops_interaction_primitives_pilot.py:54,56,65,66,92`
