---
**Created:** 2026-06-29
**Area:** intelligence
**Type:** capability expansion
**Priority:** P2 near-term (derived); P3 medium (new compute); P4 long-term (production)
**Effort:** Near-term = 1 session each; MI = 2 sessions; PnL attribution = own phase
**Risk:** low (all additive; IC pipeline unchanged)
**Gate:** IC corpus must be stable (DONE as of 2026-06-29)
---

# 029 — Feature Scoring Beyond IC

**Plan:** `docs/plans/2026-06-29-feature-scoring-beyond-ic.md`

IC (Spearman rank correlation) is the discovery layer but answers only one question:
does rank order predict rank order? Five complementary methods fill the gaps.

## Summary

| Priority | Method | Gap IC Misses | Output | Effort |
|---|---|---|---|---|
| Near | IC decay curve | Temporal structure / predictive half-life | `feature_decay_profiles` | 1 session |
| Near | Cross-symbol IC consistency | Breadth (Fundamental Law) | derived query | 1 session |
| Medium | R²_OOS | Return magnitude (not just rank) | column on `feature_ic_scores` | 1 session |
| Medium | Mutual Information | Non-linear / non-monotone relationships | `feature_mi_scores` | 2 sessions |
| Long | PnL attribution loop | Realized alpha vs statistical proxy | via `trade_frames` | own phase |

## How they coexist

IC earns features into the corpus. The full stack reads:
`IC × breadth_consistency`, gated by PnL attribution, decayed by trailing IC recency
(todo 028 P1), with MI as safety net for non-linear edges IC rejects.

See plan doc for full design, implementation notes, and table schema.

## Dependencies

- Todo 028 (IC engine improvements) is a sibling -- fix the IC foundation first, then extend it
- PnL attribution (long-term) requires v3.0 alpha emission live and 90+ days of trade_frames
