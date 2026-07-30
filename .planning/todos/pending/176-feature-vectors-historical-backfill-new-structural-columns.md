---
status: pending
priority: P1
filed: 2026-07-23
source: Phase 163 (VP/SR Structural Primitives) execution -- discovered mid-phase while
  executing Wave 3, confirmed against live persistence code before filing
gate: Phase 163 fully executed (all 3 waves) -- this todo is the operational follow-up,
  not part of the phase's own plans
decision: Delete + full recompute (option a), confirmed 2026-07-23. Full 58-symbol/multi-tf/
  multi-year corpus is in scope unless a narrower window is confirmed sufficient at run time.
---

## Status update (2026-07-30, todo-priorities audit)

**The combined `--refresh` recompute has run.** Live DB check: SMC (`ob_bull_dist_atr`)
36,854,098/36,854,099 populated (100%); swing (`swing_high_dist_atr`) 36,811,016/36,854,099
(~99.9%). This same `--refresh` run is what caused the todo 205 regime-wipe incident (root
cause fixed same day) — the two are the same event, not independent.

**VP/SR (`nearest_hvn_above_dist_atr`) is only partially populated**, and unevenly across tfs:

| tf | total rows | VP/SR populated |
|---|---|---|
| 5m | 25,443,790 | 18,007,814 (70.8%) |
| 15m | 8,824,030 | 5,485,726 (62.2%) |
| 1h | 2,254,176 | 1,107,427 (49.1%) |
| 1d | 332,103 | **0 (0%)** |

1d's 0% is worth checking before treating this todo as closed: either a legitimate design gap
(VP/SR is a session-level concept that may not apply to daily bars, which have no intraday
session structure to accumulate a volume profile from) or a real remaining backfill gap. Not
diagnosed in this pass — flagging rather than guessing.

# feature_vectors' 94 new structural columns (Phases 163-165) are NULL on every pre-existing row -- need a targeted historical backfill, not a naive re-run

## Scope widened 2026-07-28

Filed against Phase 163 alone (17 VP/SR columns). Phase 164 (36 SMC columns, migration 266) and
Phase 165 (41 swing/fib/trend/session columns, migration 267) have since landed with the
identical NULL-on-historical-rows problem -- same root cause (`ON CONFLICT DO NOTHING`), same
fix mechanism (the `--refresh` UPSERT path below, which is column-list-generic and already
covers all three phases' columns without further code changes). PRIORITIES.md's explicit user
override (2026-07-27: "build Phase 164 + Phase 165 regardless of the evidence-gate reasoning
above... then one combined `--refresh` recompute") already commits to backfilling all 94 columns
in one pass, not three separate ones -- this todo's scope now reflects that. The deprioritization
reasoning below (todo 179's `mid_bull` finding) predates that override and no longer blocks this;
kept for historical context only.

## Context (original, Phase 163)

Phase 163 (migration 255) added 17 new `feature_vectors` columns (12 ATR-normalized VP fields
per D-16/D-17/D-18, 5 S/R strength/age/count fields per D-19) and wired `FeatureFactory.compute()`
(live) / `compute_batch()` (backfill) to populate them going forward. This makes new bars correct
from the moment 163 ships. It does **not** touch the existing historical corpus -- every
`feature_vectors` row written before migration 255 has NULL in all 17 new columns and will stay
NULL forever unless something explicitly backfills them.

**Confirmed blocker (not theoretical):** `FEATURE_VECTOR_INSERT_SQL`
(`src/intelligence/features/feature_vector_persistence.py:157`) uses
`ON CONFLICT (...) DO NOTHING` -- the module's own comment says "idempotent replay; duplicate
bars are skipped silently." A naive re-run of
`scripts/... backfill_feature_factory.py --compute-only` over the historical date range will
silently no-op on every `(symbol, tf, bar_ts)` that already has a row -- which is the entire
existing corpus. The new columns will NOT get backfilled by just re-running the existing script
as-is.

**Why this matters now, not eventually:** Phase 166's structural candidate was correctly halted
specifically because `sr_support_dist`/`sr_resist_dist` were 100% NULL in the historical corpus
(the reason Phase 163 was promoted to a Wave-0 prerequisite in the first place). Phase 163 wiring
the live compute path is necessary but not sufficient -- Phase 166 Part 2 (rescoring the
structural candidate through gate166, tracked in todo 175) needs real historical VP/SR values
across the IN-SAMPLE and OOS corpus, not just new bars accumulating from today forward. Without
this backfill, todo 175 / Phase 166 Part 2 will hit the exact same 100%-NULL wall Phase 166 Part 1
already hit.

## What needs to happen

**Superseded 2026-07-27: mechanism now exists, decision below is stale.** The original
2026-07-23 decision (delete + full recompute) is no longer the plan -- while investigating why
`feature_vectors` was found 20 days stale (separate session finding), the actual root cause of
*this* todo's blocker was traced precisely: `FEATURE_VECTOR_INSERT_SQL`'s
`ON CONFLICT (symbol, tf, bar_ts) DO NOTHING` is keyed on the table's real PRIMARY KEY
(`(symbol, tf, bar_ts)`, not `feature_vector_id`), so it can never overwrite an existing row no
matter what changed. Fixed at the source: `feature_vector_persistence.py` now also exports
`FEATURE_VECTOR_UPSERT_SQL`/`FEATURE_VECTOR_UPSERT_SQL_PSYCOPG2` (`DO UPDATE SET` every non-PK
column, generated from the same single column-list as the INSERT variant so they can't drift
apart), and `backfill_feature_factory.py` gained a `--refresh` flag that selects it and also
bypasses the `backfill_status.status='complete'` checkpoint skip. **This avoids the DELETE step
entirely** -- no "briefly leaves feature_vectors short rows mid-run" risk window, since rows are
updated in place rather than deleted-then-reinserted. The live write path (`feature_vector_writer.py`)
is untouched -- still `DO NOTHING`, so a replayed live bar stays a no-op. Verified bit-identical
equivalence on a separate refactor in the same session (see `compute_batch()`'s window-slicing
fix); the upsert SQL itself is structurally tested
(`tests/unit/test_feature_vector_persistence_completeness.py`,
`tests/unit/services/test_backfill_feature_factory.py`).

**Revised steps (updated 2026-07-29 -- Step 0 added, Step 1's command corrected):**

0. **Market data gap first.** `market_data_ohlcv_tradeable` confirmed live 2026-07-29: latest
   bar is 2026-07-24 across all timeframes (~4.5-5.5 days stale, `1d` worst at 5d11h) --
   expected given live ingestion is intentionally paused
   (`[[project_ingestion_intentionally_paused]]`). Run
   `PYTHONPATH=. .venv/bin/python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --days 7`
   (all active symbols/timeframes by default; 7 days gives margin over the measured gap). **Do
   NOT use `backfill_feature_factory.py`'s own `--fetch-only`/combined mode for this** --
   traced its Stage 1 (`run_fetch_stage`, `services/backfill_feature_factory.py:721`): it skips
   any `(symbol, tf)` pair with `backfill_status.fetch_complete=true`, which is already true for
   the entire corpus from its original historical backfill. Running it again would silently
   no-op on the fetch and never touch the recent-days gap -- confirmed by reading the source,
   not assumed. `infrastructure_run_historical_pipeline.py` has no such checkpoint.
1. THEN run `backfill_feature_factory.py --compute-only --refresh` (full corpus unless scope is
   narrowed at run time) -- `--compute-only` explicitly skips its own Stage 1 (redundant with
   step 0 and subject to the checkpoint above). `--refresh` bypasses
   `backfill_status.status='complete'` so it reprocesses every row, including the newly-fetched
   recent bars from step 0. No DELETE step needed (UPSERT in place).
2. Verify via a spot-check that `sr_support_dist`/`poc_dist_atr`/etc. are non-NULL and
   non-constant across a sample of recomputed rows (mirror the "non-constant" regression guard
   Phase 163 Plan 02 added for the live path).
3. Confirm `ic_engine`'s corpus fingerprinting (Phase 162) correctly detects the recomputed rows
   as a fingerprint change and doesn't silently skip recompute for affected cells -- todo 198's
   fix (2026-07-29) makes this safer: a `feature_registry` status change alone won't force a
   false full recompute, but a genuine `feature_vectors` content change (this backfill) still
   correctly invalidates.
4. Document which date range / symbol set was actually backfilled, for todo 175's future
   reference.
5. **THEN run one full-corpus `ic_engine.py` pass** (all 80 symbols, equity + rates) --
   supersedes the narrower equity-only relaunch queued for todo 167; that todo's own file
   already commits to this exact sequencing ("not a second narrow equity-only one"). Do NOT
   relaunch the equity-scoped `ic_engine` run concurrently with steps 0-1 -- reading
   `feature_vectors` while `--refresh` is mid-UPDATE on those same rows risks torn reads, and
   any work done now gets fingerprint-invalidated the moment `--refresh` lands anyway.

**Not yet run** -- this todo tracks the mechanism now existing, not the actual recompute having
happened. **Queued to run next, after a pending server reboot for safety patches** (nothing
currently running needs graceful shutdown -- `ic_engine` already stopped; every Docker
container, including `ib-gateway`, has `restart: always`/`unless-stopped` and `docker.service`
is enabled at boot, so no manual restart steps needed post-reboot). `feature_vectors` was also
found 20 days stale overall (unrelated root cause -- live ingestion is intentionally paused),
so this run doubles as closing that gap too, in one pass.

## Acceptance criteria

- [x] Backfill mechanism chosen (delete + full recompute, 2026-07-23; superseded by --refresh
      UPSERT, 2026-07-27 -- see above)
- [ ] Historical `feature_vectors` rows (scope per above) have non-NULL, non-constant values in
      all 94 new structural columns (17 VP/SR + 36 SMC + 41 swing/fib/trend/session)
- [ ] `ic_engine` corpus fingerprint correctly triggers recompute for cells whose feature values
      changed as a result of this backfill
- [ ] Documented which date range / symbol set was actually backfilled, for todo 175's future
      reference
