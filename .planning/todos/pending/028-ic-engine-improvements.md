---
**Created:** 2026-06-29
**Area:** intelligence
**Type:** correctness + quality
**Priority:** P0-P2 correctness fixes; P1 (trailing IC) is a major capability
**Effort:** P0/P2/P3/P4 = 1 session; P1 = own phase; P5/P6 = 1 session each
**Risk:** P0/P3/P4 low; P1 medium (schema change); P2 low; P5 medium; P6 low
**Gate:** P1 gated on corpus pipeline stable (DONE as of 2026-06-29)
---

# 028 — IC Engine Improvements

**Plan:** `docs/plans/2026-06-29-ic-engine-improvements.md`

Renaissance Council audit of `services/ic_engine.py` (2026-06-29).

## Summary

| Priority | Finding | File | Effort |
|---|---|---|---|
| P0 | Walk-forward is CV, not WF — methodology contamination | `ic_engine.py:882` | Small |
| P1 | No trailing IC series — ensemble weighter blind to recency | `ic_engine.py` + schema | Phase |
| P2 | BH-FDR applied per-cell, not corpus-wide — inflated FDR | `ic_engine.py` | Small |
| P3 | Embargo = max(lookaheads) for all scales — discards fast-scale observations | `ic_engine.py:791` | Trivial |
| P4 | Clustering uses transitive linkage — can silently merge uncorrelated features | `ic_engine.py:438` | Trivial |
| P5 | No IC vintage model — old scores silently win on re-run | schema + weighter | Medium |
| P6 | Cross-sectional CI assumes independence across symbols — overconfident | `ic_engine.py:1264` | Medium |

## Ship order

**Session 1 (P0 + P2 + P3 + P4):** All small/correctness fixes. Requires full corpus
re-run after because P0 changes walk-forward pass/fail outcomes and P2 changes FDR
verdicts corpus-wide.

**Session 2 (P5):** Schema + ensemble weighter vintage logic.

**Own phase (P1):** Trailing IC series (60-day rolling IC). The answer to "is this
feature still working *now*?" See plan doc for full design.

**Session 3 (P6):** Cross-sectional effective N correction. Lower priority; only affects
POOLED rows.

See plan doc for full implementation notes, fix sketches, and APR keys.

---

## Status (2026-06-30)

**P0/P2/P3/P4 — IN PROGRESS** — being implemented in Phase A Task 1, branch
`phase-a-ic-fixes`. Reference: `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md §A2`.
Move this todo to completed/ once that branch merges and corpus re-run confirms correct output.

**P1 (trailing IC series)** — deferred to its own phase after static corpus is stable
and validated. Do not start until Phase B gate is confirmed (>=5 features with
ic_ci_lower > 0 per TF in >= 3 regimes).

**P5 (IC vintage model)** — deferred. The ON CONFLICT DO UPDATE approach (newer
training_window_end wins) can be added in the same session as P5 schema change.

**P6 (cross-sectional effective N)** — deferred. Lower priority; only inflates CI for
POOLED rows. Evaluate after Phase B validates per-symbol IC coverage.
