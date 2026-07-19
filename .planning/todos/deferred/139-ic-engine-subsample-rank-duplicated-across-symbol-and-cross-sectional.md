---
status: deferred
priority: P3
filed: 2026-07-19
moved_to_deferred: 2026-07-19
source: /simplify reuse review of commit be74f4a1 (ic_engine cross-sectional OOM fix)
---

**Moved to deferred/ 2026-07-19:** folded into ROADMAP **Phase 162 "ic_engine Corpus Pipeline
Throughput"** alongside 140 (same functions, same pass) and 133/134/122 -- not an
independently-actionable pending/ item. Revive at `/gsd-plan-phase 162`.

# `_compute_symbol_tf` and `_compute_cross_sectional_tf` now share byte-identical subsample+rank logic

## Finding

Commit `be74f4a1` fixed the same OOM-causing pattern (rankdata() defeating a
float32 optimization by promoting to float64; `arr[np.arange(...)]` fancy-index
copying instead of `arr[0:n:stride]` view-slicing) in two sibling functions,
`services/ic_engine.py`'s `_compute_symbol_tf` and `_compute_cross_sectional_tf`.
The per-scale subsample + rank block is now identical in shape in both places
(only variable names differ: `X_regime`/`X_sub_scale` vs `X_raw`/`X_sub`), linked
only by a "see the identical fix + rationale in ..." comment. The walk-forward
fold-loop rankdata calls in both functions got the identical treatment in the
same-day follow-up fix. No shared helper exists today for any of this — grepped
`src/` and `services/` and confirmed nothing reusable is being reimplemented, but
the same fix has now been hand-pasted into two places twice (subsample+rank, then
fold-loop rank), which is a strong signal a shared helper is warranted so a third
occurrence of this bug class doesn't get missed in one sibling again.

## Fix

Extract a shared helper (something like `_subsample_and_rank(X, X_nd, returns,
complete, n, stride) -> (X_sub, X_sub_nd, returns_sub, complete_sub,
ranks_X_scale, ranks_Y)`) covering the per-scale subsample + float32-cast-rank
step, and a second small helper for the fold-loop float32-cast-rank pair. Call
both from `_compute_symbol_tf` and `_compute_cross_sectional_tf`. Not urgent —
no known bug today, purely a maintainability gap — but low-risk to do since both
call sites are already verified numerically identical (bit-identical outputs,
confirmed in the be74f4a1 commit message and its regression tests).
