---
**Created:** 2026-07-02
**Area:** intelligence / alpha-integrity
**Type:** enforcement
**Priority:** P2
**Effort:** 0.5 session (append-only log + one migration or file convention)
**Risk:** low
**Gate:** none — additive, non-blocking to the diagnostic scorer
---

# 044 — OOS Look-Log Audit Trail

From Phase 141.1 code review (CR-02, `.planning/phases/141.1-measurement-and-decision-integrity-foundation-make-everythin/141.1-REVIEW.md`).

`scripts/ops/corpus/ops_oos_holdout_eval.py` is an intentionally non-gating diagnostic
scorer over the OOS holdout window (`docs/plans/OOS-EVAL-PROTOCOL.md`). The protocol doc
states its output "must not be used to tune any in-sample parameter," but this is a
documented convention with zero code-level enforcement — exactly the failure pattern
(unenforced rule, "zero readers" gap) that this same phase's `TRAINING_WINDOW_END` clamp
was created to close one layer up.

## Problem

An operator can run the diagnostic scorer repeatedly, read its markdown report, and then
adjust an in-sample APR parameter (e.g. `alpha.ic.min_reliable_n`, a feature-selection
threshold) "to see if it helps" — silently renegotiating after seeing the OOS number, with
no trace connecting the parameter change to having seen the holdout result.

## Fix

Have `ops_oos_holdout_eval.py` write a persistent, append-only, timestamped "OOS look log"
each time it runs (git-visible file under `.planning/` or a DB table). Each entry records:
run timestamp, symbols/TFs scored, and the report path/hash. This does not need to block
runs — the scorer stays non-gating — but it turns an honor-system rule into an auditable
one: a reviewer can grep the look log against `config_history` timestamps to check whether
an APR parameter changed suspiciously close to an OOS look.

## References

- `docs/plans/OOS-EVAL-PROTOCOL.md` — the protocol this closes a gap in
- `scripts/ops/corpus/ops_oos_holdout_eval.py` — the scorer to instrument
- `.planning/phases/141.1-measurement-and-decision-integrity-foundation-make-everythin/141.1-REVIEW.md` — CR-02 for full reasoning
