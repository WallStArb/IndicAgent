---
created: 2026-05-03T18:00:00.000Z
title: HMM Multi-TF + Training Pipeline
area: intelligence
priority: 8
tier: data-gated
files:
  - src/intelligence/context/hmm_regime.py
  - docs/ideas/hmm-multi-tf-and-training.md
  - docs/ideas/regime-transition-early-detection.md
---

# HMM Multi-TF + Training Pipeline

**Filed:** 2026-05-03
**Data gate:** ~May 10 (30+ days clean signal_ledger data)
**Priority:** High — highest-impact untracked item

## Problem

Two structural gaps in HMM regime detection:

1. **Single timeframe (1m only)** — all higher-TF signals consume wrong regime context. A 1h FVG setup filtered by 1m regime (3.3h lookback) is structurally wrong. Per-TF HMM instances needed: 5m (200 bars = 16h), 15m (200 bars = 50h), 1h (100 bars = 10 days).
2. **Untrained parameters** — emission means/variances are hand-tuned priors, never fitted to actual data. `hmm_parameters.json` doesn't exist. Baum-Welch training on `intelligence_features` was always planned (v2.3 candidate) but never executed.

## Solution

### Part A: Per-TF HMM Instances
- Multiple HMM plugin instances, one per timeframe, with TF-appropriate lookbacks
- Each higher-TF pipeline run consumes its own HMM regime context
- Requires `InputSpec` per-TF configuration in plugin registration

### Part B: Baum-Welch Training Pipeline
- Offline EM training on `intelligence_features` (returns, volume, volatility)
- Per-symbol, per-TF model fitting
- Output: `hmm_parameters.json` with fitted emission matrices
- Schedule: retrain monthly or on drift detection trigger

## Dependencies

- 30+ days clean `intelligence_features` data (gate lifts ~May 10)
- Phase 70 (ML Scoring) should run first to validate feature quality
- Related: Regime Transition Early Detection (todo 010)

## Context

Full design: `docs/ideas/hmm-multi-tf-and-training.md`
Related: `docs/ideas/regime-transition-early-detection.md`
