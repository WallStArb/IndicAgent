---
status: done
priority: P1
filed: 2026-10-03
source: interactive session (186 session), review of 186-26 before launch
---

# Rebuild preconditions gate on D2b only; 186-26 can launch before 185-18's historical 1d D2 apply

## What

`services/rebuild_preconditions.py` checks `check_derived_grid_landed` (the STATE.md "D2b landed"
marker: derived 15m/1h grid). Nothing checks D2, the 185-18 sole 1d writer and its historical
apply. 1d is one of the rebuild's timeframes. On 2026-10-03 `canonical_bar_lineage` has 0 rows
(`SELECT rule_version, count(*) ... GROUP BY rule_version`), so the historical D2 run has not
applied to the live DB.

The rebuild's unit identity already folds each symbol's month content digest into `batch_key`
(`_unit_input_digest`, `services/backfill_feature_factory.py`), so a bar revised after a unit
completed gives that unit a new key and `_completed_provenance_batch` no longer skips it. That
makes stale units detectable, but only when something re-invokes `run_rebuild_stage` after D2
lands. 186-27 has no such step (no reference to `canonical_bar_lineage`, `d2-v1` or 185-18), so a
rebuild launched before D2 would keep pre-D2 1d bars until someone remembers to re-run it, after
a multi-day, 105-338 GB run.

## Fix

1. Add `check_d2_landed` to `rebuild_preconditions.py`: every 1d `compute_eligible_1d` name with
   volume > 0 bars has `canonical_bar_lineage` rows with `rule_version = 'd2-v1'`, and
   `bar_content_digest_current` has a 1d row for every derived month. Wire it through
   `fetch_landed_markers`/`run_all` like the D2b check, with a unit test.
2. 186-26 task 1 runs it; failure stops the plan with nothing launched (no pilot: a pilot on
   pre-D2 1d bars is discarded anyway).
3. 186-27 close-out re-plans every unit against current digests and expects zero pending units.

## Gate

Do not edit `services/rebuild_preconditions.py` while a rebuild run is live or resumable (none is
today). 185-18 is held by another session; this todo does not touch its files.

## Resolution (2026-10-03)

`check_d2_landed` and `fetch_d2_inputs` are in `services/rebuild_preconditions.py` (eight checks now),
with unit tests. Run against the live DB the same day: 931 of 931 `compute_eligible_1d` names have
`d2-v1` lineage (3.88M rows) and a digest row for every tradeable month, so the gate passes today.
186-26 task 1 calls it before any pilot; 186-27 step 1(e) re-plans against current digests and expects
zero pending units. Promoting new names (wave 2, 597 rows) makes the gate fail until their 1d bars are
derived, which is the intended behavior.
