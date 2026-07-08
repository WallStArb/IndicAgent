# 169 — Adversarial review as cadence, not one-off event

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §11 (G-3).
**Priority:** low-medium — a process change, not a code change. No infrastructure cost (a prompt
template + a calendar rule), so the only real decision is whether to commit to running it
regularly.
**Gate:** none — this is a practice to adopt, not a build.

## Proposal

The cross-AI review muscle already exists (AGY/Codex headless, Fable passes, the 142.5-REVIEWS
process). Make one variant a standing cadence with an inverted mandate: per corpus epoch, a
red-team pass whose deliverable is, for each top-weighted predictor, (a) the strongest available
argument that its IC is artifact (leakage, session mask, synthetic bars, selection pressure,
crowding) and (b) a concrete cheap test that would kill it. File the tests as todos; run the cheap
ones.

## Why

Promotion machinery is symmetric on evidence (todo 152's canaries, the FDR/gate stack), but
*proposal* flow today is all-positive — people and models propose predictors, nobody's job is
proposing their deaths. This closes that asymmetry at near-zero mechanism cost.

## Decision needed

Whether to formally adopt this as a recurring practice (e.g., triggered alongside each corpus
epoch/rerun) — worth a short discussion rather than silently letting this todo sit, since its
value only accrues if actually run on a cadence, not built once and forgotten.
