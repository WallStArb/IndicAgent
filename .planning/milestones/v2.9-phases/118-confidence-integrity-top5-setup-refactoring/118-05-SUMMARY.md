---
phase: 118-confidence-integrity-top5-setup-refactoring
plan: "05"
subsystem: intelligence/trading
tags: [divergence-stack, confidence, extrinsic-strip, shadow-mode, i7]
dependency_graph:
  requires: [118-00b]
  provides: [REFACTOR-05]
  affects: [divergence_stack.py, test_divergence_stack.py]
tech_stack:
  added: []
  patterns: [4-factor-intrinsic-composite, freshness-persistence, always-log]
key_files:
  created:
    - tests/unit/intelligence/test_divergence_stack.py
  modified:
    - src/intelligence/trading/divergence_stack.py
decisions:
  - "Persistence scored on freshness (min active age inverted) not max-age — stale stacks are lower quality"
  - "4-factor weights: 0.40 base + 0.25 purity + 0.20 breadth + 0.15 persistence = 1.00 exactly"
  - "shadow_only = True enforced at class level"
metrics:
  duration_minutes: 15
  completed_date: "2026-06-09"
  tasks_completed: 3
  files_modified: 2
---

# Phase 118 Plan 05: DivergenceStack Extrinsic Strip and 4-Factor Confidence Summary

One-liner: DivergenceStack extrinsic modifiers stripped and confidence replaced with 4-factor intrinsic composite (base, purity, breadth, freshness-persistence) routed through compose_confidence().

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Strip extrinsic modifiers — exhaustion_guard, ctf_score, hmm_regime_weight | bae455d1 | src/intelligence/trading/divergence_stack.py |
| 2 | 4-factor intrinsic composite with freshness-based persistence | 48b07c83 | src/intelligence/trading/divergence_stack.py |
| 3 | Unit tests for extrinsic strip, freshness persistence, always-log | b1c187db | tests/unit/intelligence/test_divergence_stack.py |

## What Was Built

### Task 1: Extrinsic Strip

Removed all three extrinsic confidence modifiers from `divergence_stack.py`:

- `apply_exhaustion_guard(...)` and its import from `exhaustion_utils`
- `ctf_score` additive block (`raw_div_conf += 0.15 * ...`)
- `hmm_regime_weight(...)` additive block (`raw_div_conf += 0.10 * ...`) and its import from `gradient_utils`
- Set `shadow_only = True` as a class attribute

The always-log `base_output` dict and `signal.update(base_output)` merge pattern were preserved intact.

### Task 2: 4-Factor Intrinsic Composite

Replaced the single-formula `weighted_score / DIVERGENCE_CONFIDENCE_NORM` with a 4-factor composite:

- **Factor 1 (base, weight 0.40)**: `min(1.0, max(0.0, weighted_score / DIVERGENCE_CONFIDENCE_NORM))` — the existing intrinsic formula, now clamped
- **Factor 2 (purity, weight 0.25)**: `max(bull_weight, bear_weight) / total_active_weight` — direction unanimity; 1.0 = all inputs agree, 0.5 = perfectly split
- **Factor 3 (breadth, weight 0.20)**: `(n_agreeing - DIVERGENCE_MIN_AGREEING) / (5 - DIVERGENCE_MIN_AGREEING)` — how many inputs agree beyond the gate
- **Factor 4 (persistence, weight 0.15)**: freshness-based using minimum active age inverted — `1.0 - min_active_age / 10.0`. A stack with a recently-confirmed component (age=1) scores higher than a stale one (age=9). Documented in a comment: "freshness, not max-age — a stale stack is lower quality"

All factors are clamped to [0, 1] before weighting. Weights sum to exactly 1.00. Final `raw_div_conf` routes through `compose_confidence()`.

### Task 3: Unit Tests (9 tests)

All 9 tests pass:

1. `test_no_exhaustion_guard_in_confidence` — exhaustion fields don't change confidence
2. `test_no_ctf_in_confidence` — ctf_score=0.8 vs 0.0 produces same confidence
3. `test_base_score_from_weighted_inputs` — fires at minimum n_agreeing with confidence > 0
4. `test_purity_score_increases_with_unanimity` — unanimous > mixed direction confidence
5. `test_breadth_score_increases_with_n_agreeing` — 5 inputs > 3 inputs confidence
6. `test_freshness_persistence_recent_higher_than_stale` — fresh (age=1) > stale (age=9)
7. `test_base_output_populated_on_no_signal` — always-log fields present on no-signal path
8. `test_shadow_only_flag` — shadow_only is True
9. `test_extrinsic_perturbation_delta_zero` — ctf/hmm/exhaustion fields cannot move confidence (delta < 1e-9)

## Verification Results

```
grep -n "apply_exhaustion_guard|hmm_regime_weight|ctf_score" divergence_stack.py
# -> zero hits (all stripped)

grep -n "shadow_only|base_score|purity_score|breadth_score|persistence_score|compose_confidence" divergence_stack.py
# -> shadow_only=True, all 4 factors present, compose_confidence wraps output

pytest tests/unit/intelligence/test_divergence_stack.py -v
# -> 9 passed

pytest tests/unit/ (excluding correctness/) -q
# -> 36 failed (all pre-existing), 4427 passed, 34 skipped
```

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

Files created/modified:
- [x] `src/intelligence/trading/divergence_stack.py` — FOUND
- [x] `tests/unit/intelligence/test_divergence_stack.py` — FOUND

Commits:
- [x] bae455d1 — refactor(118-05): strip exhaustion_guard, ctf_score, hmm_regime_weight
- [x] 48b07c83 — feat(118-05): DivergenceStack 4-factor intrinsic confidence
- [x] b1c187db — test(118-05): DivergenceStack extrinsic strip, freshness persistence

## Self-Check: PASSED
