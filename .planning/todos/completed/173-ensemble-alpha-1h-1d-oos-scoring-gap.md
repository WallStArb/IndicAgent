---
status: pending
priority: P2
filed: 2026-07-22
source: Phase 148-05, discovered after Gate 1's real (irreversible) run recorded a PASS verdict
  covering only 5m/15m -- disclosed transparently in the promotion decision record rather than
  silently accepted as "the whole universe was tested."
---

# `ensemble_alpha` has zero OOS-side rows at 1h (any weight_version) and zero at 1d for the champion/default weight_version

## Problem

Gate 1 (SCORE-02, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py`) was invoked over the
default `5m`/`15m`/`1h`/`1d` timeframe set (no `--tf` filter) but produced cells for **only**
`5m` and `15m` -- 640 cells total, 320 per timeframe, zero for `1h`/`1d`. Traced directly (not
guessed): `ensemble_alpha` itself has zero rows with `bar_ts >= alpha.validation.oos_start`
(2025-12-24T05:15:00Z) for `tf='1h'` under **any** weight_version (`143.1-08-champion`,
`143.1-08-challenger`, and `run_2025122405150000`, the value `alpha.ensemble.weight_version`
currently resolves to -- which itself has identical 5m/15m row counts to `143.1-08-champion`,
suggesting it may be an alias/duplicate label for the same underlying scoring run). `tf='1d'`
has rows only under `143.1-08-challenger` (3,461); champion and the resolved default weight
version have zero 1d rows in the OOS window either.

This is a distinct root cause from the `forward_returns` OOS-coverage gap this same plan
resolved earlier in execution (that was `forward_return_writer`'s OOS-holdout clamp never being
overridden for a label table; this is `ensemble_alpha` -- the ensemble scoring output itself --
apparently never having been computed at 1h at all in the OOS window, for any weight version).

**Consequence for the already-recorded Gate 1 verdict:** because Gate 1 is a run-once,
irreversible gate (D-04), this cannot be re-run to include 1h/1d now that the gap is known.
The recorded `gate1_signal` PASS verdict is accurate for what it actually measured (640
5m/15m cells, 21.875% qualifying against a 2% floor), but is **not** a full 4-timeframe signal
proof -- disclosed explicitly in
`docs/plans/archive/2026-07-22-phase148-promotion-decision.md` rather than silently presented as
covering the whole configured universe.

## Fix

Not scoped in detail here (this is a capture, not a plan). Needs investigation, not a blind
backfill:

1. Confirm whether `ensemble_alpha` at 1h/1d was ever computed for the OOS-adjacent period at
   all (in-sample included) or whether this is 1h/1d-specific ensemble scoring coverage gap
   going back further -- check `ensemble_trainer.py`/`alpha_publisher.py` run history and
   whether a recurring cadence exists for 1h/1d specifically (may overlap with existing todo
   089's "no recurring `ensemble_ic_engine` schedule" finding, or todo 166's 1d small-sample
   observation -- check both before scoping a fix, this could be a symptom of the same
   underlying "no recurring ensemble scoring cadence" gap rather than a new independent one).
2. If genuinely never computed: understand why before backfilling -- unlike the
   `forward_returns` fix (a fixed, mechanical, deterministic transform with no parameter to
   tune, confirmed safe to backfill), `ensemble_alpha` is the actual ensemble SCORE output;
   computing it retroactively for the OOS window touches exactly the kind of decision
   `OOS-EVAL-PROTOCOL.md` treats carefully. Do not casually backfill without the same
   deliberate sign-off this plan's `forward_returns` fix required.
3. `run_2025122405150000`'s relationship to `143.1-08-champion` (identical row counts,
   different label) should be understood/documented -- if it is genuinely a duplicate/alias,
   that itself may be worth a naming or `alpha.ensemble.weight_version` config note.

## Sizing

Investigation-first; sizing depends entirely on whether 1h/1d ensemble_alpha needs a full
recurring cadence (large, a genuine unbuilt piece per todo 089) or whether this is narrower
(a specific run that was scoped to 5m/15m only and never repeated for 1h/1d, small to extend).

## References

- `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` -- Gate 1 section discloses this
  limitation on the recorded PASS verdict
- `.planning/gate_look_log.jsonl` -- Gate 1's pre-run snapshot (`apr_values_used.weight_version:
  "run_2025122405150000"`)
- [089](089-ensemble-ic-engine-recurring-cadence.md) -- possible root-cause overlap (no
  recurring `ensemble_ic_engine` schedule)
- [166](166-1d-ensemble-eligibility-small-sample-treatment.md) -- possible related 1d
  observation, different symptom (small sample vs. zero rows) -- check for shared cause

## CLOSED 2026-08-03

Verified live (`SELECT tf, count(*) FILTER (WHERE bar_ts >= '2025-12-24T05:15:00Z') FROM
ensemble_alpha WHERE tf IN ('1h','1d') AND weight_version='run_2025122405150000' GROUP BY 1`):
1h now has 71,972 OOS rows, 1d has 10,126 -- the specific "never computed" gap this todo
reported is resolved by the 2026-08-02 corpus run (`ensemble_trainer`/`alpha_publisher` steps
7/8). Fix step 1's question is answered: not a structural 1h/1d exclusion, just a run that
hadn't happened yet for this weight_version.

**Not closed by this:** whether to formally re-score Gate 1 (D-04, irreversible) across all 4
timeframes is a separate promotion-decision question this todo never owned, and todo 089's
"no recurring ensemble_ic_engine cadence" concern stands independently -- this run happening
doesn't establish it happens routinely. Both remain open under their own todos (089, 166) if
still relevant.
