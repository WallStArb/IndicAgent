---
plan: 64-01
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
status: superseded
superseded_by: 64-01-GAPCLOSURE
completed: 2026-04-27
---

# Plan 64-01: CrossTFMomentumDivergence Plugin (Superseded)

## Summary

This plan was superseded by **64-01-GAPCLOSURE**, which delivers the same CrossTFMomentumDivergence plugin with stricter must-haves incorporating CodeRabbit HIGH-severity fixes (proper np.tanh() gradient computation, not static stub; all 5 D-06 regimes; full _shadow capture).

## What Was Built

See `64-01-GAPCLOSURE-SUMMARY.md` — all deliverables are identical and the GAPCLOSURE implementation fully satisfies this plan's must-haves.

## Self-Check: PASSED

All must-haves from this plan are verified by GAPCLOSURE:
- ✓ CrossTFMomentumDivergence plugin with continuous gradient scoring
- ✓ I6Confluence schema extended with ctf_momentum_divergence and ctf_momentum_regime
- ✓ Plugin registered in TIER_I6
- ✓ _shadow dict capture extended via capture_signal_features()
- ✓ 15 unit tests pass
