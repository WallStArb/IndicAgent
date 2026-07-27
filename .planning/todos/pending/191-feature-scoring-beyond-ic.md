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

**Plan (archived 2026-07-02):** `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` —
marginal contribution (0a), shrinkage (0b), and calibration (0c) carried forward into
`docs/research/intel-15-measurement-engine.md`'s "Measurement Gaps" section, but this todo is
still the live build reference (intel-15 note: "todo 029 is still pending" as of 2026-07-02).
Kept in archive/ for the full method detail (residualization, empirical-Bayes shrinkage
formula, Brier/reliability calibration) not reproduced in intel-15.

IC (Spearman rank correlation) is the discovery layer but answers only one question:
does rank order predict rank order? Five complementary methods fill the gaps.

## Summary (updated 2026-07-01 — plan doc v2 council pass; shrinkage row corrected 2026-07-19)

| Priority | Method | Gap IC Misses | Output | Effort |
|---|---|---|---|---|
| ~~Near 1st~~ **DONE** | ~~Shrinkage (0b)~~ | Selection bias in every raw estimate; weighter over-allocates to lucky cells | `ic_shrunk` + `shrinkage_weight` columns | shipped Phase 142B.1 — `src/intelligence/ensemble/shrinkage.py`, migration 191, live in `ensemble_trainer.py` (E1 champion vs E2, E1 won 2026-07-09) |
| Near | IC decay curve | Temporal structure; shape classification first, tau fit only for decaying archetype (4-point fit is under-determined) | `feature_decay_profiles` | 1 session |
| Near | Effective-breadth consistency | Breadth (Fundamental Law) — must use N_eff from correlation matrix, NOT symbol count (58 ETFs ≈ 8-15 independent bets) | derived + corr matrix (reuse ANALOG-07 math) | 1 session |
| Medium | **Marginal contribution (0a)** | Standalone IC ≠ value added to existing ensemble; promotion should read partial IC | `partial_ic` column | 1 session |
| Medium | R²_OOS | Return magnitude (not just rank) | column on `feature_ic_scores` | 1 session |
| Medium | Mutual Information | Non-linear relationships — REQUIRES permutation null (MI is positively biased, non-negative) + corpus BH-FDR | `feature_mi_scores` | 2 sessions |
| 142A | **Calibration (0c)** | Whether persisted magnitudes are honest enough to size on; also fastest decay signal | ensemble-level first | with 142A |
| Long | PnL attribution loop | Realized alpha vs statistical proxy | via `trade_frames` | own phase |

**Correction 2026-07-19:** the shrinkage row above was still listed as pending as of this todo's
last edit, but `alpha_ensemble_ic`'s E1-vs-E2 champion/challenger judgment (Phase 142B.1,
completed 2026-07-04, E1 confirmed champion 2026-07-09) already shipped exactly this. Don't
re-plan it.

**Scope note:** this todo spans effort levels from "1 session" to "own phase" across 7 remaining
methods — that's phase-level breadth, not the single-session scope `pending/` is defined for
(see `PRIORITIES.md`'s header). Recommend splitting: promote the "Near" tier (decay curve,
effective-breadth, marginal contribution — all cite todo 038/039's related effective-breadth
work) into a scoped ROADMAP phase or `deferred/` entry, and leave only whichever single item the
project owner wants tackled next as a standalone pending todo. Not resolving the split myself —
that's a scope call, not a code-vs-code judgment.

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
