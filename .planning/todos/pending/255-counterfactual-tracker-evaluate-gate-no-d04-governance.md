---
status: open
priority: P2
filed: 2026-08-04
source: split out of todo 253 while wiring D-04 governance into cross_sectional_spread_tracker.py
  -- same gap, different phase, deliberately not fixed in that pass to avoid expanding its blast
  radius past the construction that was actually blocking todo 243
---

# `counterfactual_tracker.py --evaluate-gate` (Phase 142B) has no D-04 run-once governance --
# writes only to `logs/`, no `gate_evaluations` row, no `gate_look_log.jsonl` entry

## What

Same gap todo 253 found and fixed for `cross_sectional_spread_tracker.py`'s Gate 1/Gate 2:
`services/counterfactual_tracker.py`'s `_run_evaluate_gate()` (`services/counterfactual_tracker.py:848`)
evaluates Phase 142B's OOS gate and writes only a `write_verdict_artifact`-style JSON file under
`logs/`, with no re-run guard. Confirmed via `.planning/gate_look_log.jsonl` -- zero
Phase 142B entries exist there, same as Phase 167's gap before todo 253's fix.

Not urgent: Phase 142B's gate has not needed re-evaluation recently, and re-running it today
would not silently corrupt anything (it would just be an unguarded second look, same failure
mode `OOS-EVAL-PROTOCOL.md`'s cadence rule exists to prevent, but nobody is currently trying to
re-run it). Filed so the gap is tracked rather than rediscovered from scratch if/when Phase 142B's
gates are ever re-evaluated.

## Fix (design already proven, same session)

Reuse the exact pattern `cross_sectional_spread_tracker.py` now uses (todo 253,
`services/cross_sectional_spread_tracker.py`'s `_write_gate_result`/`_append_gate_look_log`,
themselves reused from `ops_oos_gate1_signal_eval.py`'s Phase 148 precedent): one
`gate_evaluations` row per real run (`gate_id` disambiguated by construction/phase, e.g.
`gate1_counterfactual_tracker` or whatever this construction's own name ends up being), one
`.planning/gate_look_log.jsonl` append, atomic re-assert-no-prior-row-then-INSERT, a `--dry-run`
escape hatch. No new mechanism to design -- copy the pattern.

## Cross-refs

- [todo 253](../completed/253-forward-returns-frozen-at-oos-boundary-corpus-rebuild-skipped-step3.md)
  -- where this gap was found and fixed for the sibling construction
- `docs/plans/OOS-EVAL-PROTOCOL.md` -- now documents `cross_sectional_spread_tracker.py` as a
  named scorer (2026-08-04); `counterfactual_tracker.py` should get the same treatment once fixed
