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

## Summary (updated 2026-07-01 — plan doc v2 council pass)

| Priority | Method | Gap IC Misses | Output | Effort |
|---|---|---|---|---|
| Near 1st | **Shrinkage (0b)** | Selection bias in every raw estimate; weighter over-allocates to lucky cells | `ic_shrunk` + `shrinkage_weight` columns | 1 session |
| Near | IC decay curve | Temporal structure; shape classification first, tau fit only for decaying archetype (4-point fit is under-determined) | `feature_decay_profiles` | 1 session |
| Near | Effective-breadth consistency | Breadth (Fundamental Law) — must use N_eff from correlation matrix, NOT symbol count (58 ETFs ≈ 8-15 independent bets) | derived + corr matrix (reuse ANALOG-07 math) | 1 session |
| Medium | **Marginal contribution (0a)** | Standalone IC ≠ value added to existing ensemble; promotion should read partial IC | `partial_ic` column | 1 session |
| Medium | R²_OOS | Return magnitude (not just rank) | column on `feature_ic_scores` | 1 session |
| Medium | Mutual Information | Non-linear relationships — REQUIRES permutation null (MI is positively biased, non-negative) + corpus BH-FDR | `feature_mi_scores` | 2 sessions |
| 142A | **Calibration (0c)** | Whether persisted magnitudes are honest enough to size on; also fastest decay signal | ensemble-level first | with 142A |
| Long | PnL attribution loop | Realized alpha vs statistical proxy | via `trade_frames` | own phase |

## How they coexist

The full stack: `ic_shrunk × effective_breadth`, admitted by marginal contribution,
sized only if calibrated, net of cost (todo 030), demoted by PnL attribution and
trailing IC (todo 028 P1), with MI as discovery net routed back through the candidate
pipeline (never straight to a weight). Shrinkage ships first — it is the only item
correcting decisions already being made today.

See plan doc for full design, implementation notes, and table schema.

## Dependencies

- Todo 028 (IC engine improvements) is a sibling -- fix the IC foundation first, then extend it
- PnL attribution (long-term) requires v3.0 alpha emission live and 90+ days of trade_frames
