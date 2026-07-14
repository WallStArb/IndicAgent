---
status: pending
priority: P2
filed: 2026-07-14
source: found while answering a promotion/demotion architecture question — checked
  src/intelligence/feature_registry_service.py directly rather than assuming
---

# 117 — `feature_registry` has no operator-override actuator

## Problem

`FeatureRegistryService.record_transition_sync` (`src/intelligence/feature_registry_service.py`)
correctly guards that automated transitions (`_AUTOMATED_REASONS = {ic_promotion, ic_demotion}`)
may never target `deprecated` — the code comment states "'operator_override' targeting
'deprecated' is the only legitimate path to that status." The guard is real and load-bearing
(line 390: raises if an automated reason targets `deprecated`).

But nothing calls `record_transition_sync` with `reason='operator_override'` anywhere in the
codebase. `grep -rl "record_transition_sync\|FeatureRegistryService(" --include="*.py" .`
returns exactly three files: `feature_registry_service.py` itself, `services/ic_engine.py`, and
`services/ensemble_trainer.py` — both automated callers only. There is no CLI script, ops
command, or dashboard endpoint that lets an operator actually deprecate a feature, or manually
force any other transition. The schema and guard rail exist; the actuator does not.

Practically: today, a feature can only ever reach `active`/`shadow_only` via the automated IC
gate, and can *never* reach `deprecated` at all — the state is reachable in the CHECK
constraint and reasoned about in code comments, but structurally unreachable in practice. If an
operator identifies a feature that should be permanently killed (bad formula, redundant with
another feature, whatever the reason), there is currently no way to do that except a manual SQL
UPDATE against `feature_registry` directly — bypassing `feature_transition_log` entirely, which
defeats the audit-trail purpose the whole registry exists for.

## Solution / Fix / What / Why

A small ops script (`scripts/ops/alpha/ops_feature_registry_override.py` or similar), following
the existing ops-script conventions (`ops_ensemble_weight_compare.py` et al.): takes
`--feature-name`, `--to-status`, `--reason` (free text, stored wherever `feature_transition_log`
ends up carrying operator notes — see todo 011's closing note on the missing `note` column,
same gap), calls `FeatureRegistryService.record_transition_sync(..., reason='operator_override')`
directly, so every manual intervention still goes through the same optimistic-locked,
transaction-safe write path and lands in `feature_transition_log` like every automated
transition does.

Low urgency today (no operator has hit this need yet — feature count is small, automated gates
have been sufficient), but worth building before Concept Registry (Phase 160, completed 2026-07-13)
migrates `domain='feature'` in, so the actuator pattern is proven on the simpler existing system
first rather than designed cold against the new one.
