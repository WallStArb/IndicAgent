---
created: 2026-05-03T18:00:00.000Z
title: Regime Transition Early Detection
area: intelligence
priority: 10
tier: data-gated
files:
  - src/intelligence/context/hmm_regime.py
  - src/intelligence/trading/regime_transition.py
  - docs/ideas/regime-transition-early-detection.md
---

# Regime Transition Early Detection

**Filed:** 2026-05-03
**Priority:** Medium-High
**Dependency:** HMM Multi-TF training (todo 009) or standalone

## Problem

All I7 plugins are regime-gated. Binary gating is correct for mature regimes but creates a blind spot during transition windows — often where the highest-alpha entries live.

- `hmm_regime_prob` drops below 0.30 floor during transitions → signals suppressed
- `trad_RegimeTransition` requires BOTH BOCPD changepoint AND CHoCH → late confirmation, not early detection
- Result: during consolidation→trend transition, every directional plugin fires zero signals until regime is mature and best entries are gone

The HMM's uncertainty IS the signal — we're discarding it.

## Solution

### 1. Add `regime_entropy` to I4 HMM output
Shannon entropy across three HMM state probabilities. High entropy = transition window.

### 2. Add `hmm_regime_velocity` to I4 HMM output
Rate of change of regime probabilities. High velocity = active transition.

### 3. Soft confidence multiplier for 0.30–0.55 prob band
Instead of binary gate (suppressed if < 0.30), apply continuous confidence:
- prob < 0.30: suppress (current behavior)
- 0.30–0.55: apply entropy-based confidence multiplier (not binary gate)
- > 0.55: full confidence (current behavior)

### 4. Early-path for `trad_RegimeTransition`
Use entropy/velocity as early trigger instead of waiting for BOCPD+CHoCH confirmation.

## Context

Full design: `docs/ideas/regime-transition-early-detection.md`
Related: HMM Multi-TF training (todo 009)
