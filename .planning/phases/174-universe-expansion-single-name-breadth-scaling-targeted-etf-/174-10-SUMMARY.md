---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 10
subsystem: database
tags: [ibkr, instrument-onboarding, backfill, asyncpg, jsonb, etf-gap-fill]

# Dependency graph
requires:
  - phase: 174-07
    provides: "EMLC/VIXY ticker decisions with full contract_details/instrument_metadata/tag field values"
provides:
  - "EMLC (fx_em) and VIXY (vol_proxy) fully onboarded, backfilled, and compute_eligible"
  - "First live-exercised run of the full onboard_instrument() -> backfill -> promote pathway (Plan 03's helper), surfacing and fixing a real double-JSON-encoding bug before Plan 12 runs it at scale"
  - "--dimension flag on infrastructure_run_historical_pipeline.py so backfill-eligible-but-not-yet-compute-eligible symbols are fetchable"
affects: [174-12]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "onboard_instrument() commit-mode script convention: --dry-run default, --commit opt-in, aggregate OnboardResult logging, JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics at exit"
    - "backfill_status.fetch_complete checkpoint set from verified market_data_ohlcv_tradeable evidence (CLAUDE.md's Corpus Pipeline Gotcha pattern) when the fetch script used doesn't own that table itself"

key-files:
  created:
    - scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py
  modified:
    - src/config/instrument_onboarding.py
    - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py

key-decisions:
  - "onboard_instrument()'s contract_details/evidence JSONB writes were double-JSON-encoding (json.dumps() called on values passed to a connection whose pool codec already serializes dict->text) -- fixed by passing dicts directly. This was the first --commit-mode exercise of the helper since Plan 03 shipped it; the bug had never been triggered before."
  - "infrastructure_run_historical_pipeline.py never wrote to backfill_status at all -- that bookkeeping belongs to a different script (backfill_feature_factory.py). Since the plan mandated using the historical pipeline without duplicating fetch logic, fetch_complete was set via CLAUDE.md's already-documented Corpus Pipeline Gotcha UPSERT pattern, scoped to EMLC/VIXY only, gated on independently verified non-zero market_data_ohlcv_tradeable counts per (symbol, tf) -- not blindly trusted from the fetch script's exit status."
  - "Added --dimension flag to infrastructure_run_historical_pipeline.py (default unchanged at 'compute') rather than duplicating fetch logic or prematurely setting compute_eligible=true, so a --dimension backfill invocation can target is_active=true/compute_eligible=false symbols."

requirements-completed: [D-05, D-06, V5]

# Metrics
duration: ~5h40m (dominated by waiting on the ~85min live IBKR historical fetch across 8 symbol/timeframe pairs)
completed: 2026-09-16
---

# Phase 174 Plan 10: EMLC/VIXY Onboarding, Backfill, and Promotion Summary

**EMLC (EM-FX) and VIXY (vol-proxy) are now fully onboarded, backfilled across all four timeframes (4,756,602 real bars, 0 fetch errors), and compute_eligible -- the first live end-to-end exercise of Plan 03's onboarding pathway, which surfaced and fixed a real double-JSON-encoding bug in the shared onboard_instrument() helper.**

## Performance

- **Duration:** ~5h40m wall clock (Task 1/2 active work ~15 min; Task 3's live IBKR fetch ran ~85 min; remainder was polling/monitoring wait time for the detached backfill)
- **Completed:** 2026-09-16
- **Tasks:** 3/3 completed
- **Files modified:** 1 created, 2 modified

## Accomplishments

- Re-verified `ib-gateway` live rather than trusting the plan's `Exited (1)` starting-state assumption: the container was already `Up` at session start (it had recovered on its own via the IBC nightly auto-restart's cached token, per the orchestrator's own note) -- ran a real bounded historical-bar request (SPY, 1d, 2026-09-08 to 2026-09-15, last close 757.39, 6 bars) through the project's own `IBKRProvider` path to prove it serves data, not just that the container status is `Up`.
- Built `scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py`, onboarding EMLC (`fx_em`) and VIXY (`vol_proxy`) through `onboard_instrument()`, qualified live against IBKR, using every `contract_details`/`instrument_metadata`/tag-evidence value verbatim from Plan 07's research doc. `session_id` is looked up live from an existing equity instrument row rather than hardcoded.
- Found and fixed a real, previously-undiscovered bug in `src/config/instrument_onboarding.py`: `contract_details` and `instrument_tags.evidence` were being pre-serialized with `json.dumps()` before being passed to a pooled asyncpg connection whose jsonb codec already serializes dict->text on the way out -- double-encoding both columns into a quoted JSON string instead of native JSONB. This had never been triggered before because no caller had run `onboard_instrument()` in `--commit` mode until this plan (Plan 08's stratified-sourcing script explicitly deferred its own `--commit` run to Plan 12). Fixed by passing the dicts directly; verified via a full onboard-delete-reonboard cycle showing correct native JSONB, plus the existing `tests/unit/config/test_instrument_onboarding.py` suite (10/10 passing, uses a FakeConnection so it didn't already cover this).
- Found and fixed a second real gap: `infrastructure_run_historical_pipeline.py` (the script this plan's Task 3 mandates using) defaults `get_active_contracts()` to `dimension="compute"`, which would have silently matched zero contracts for EMLC/VIXY (`compute_eligible=false` at the time of the fetch) and printed "No matching contracts" instead of fetching anything. Added an explicit `--dimension` flag (default unchanged, so every other caller's behavior is preserved) rather than duplicating fetch logic or prematurely flipping `compute_eligible`.
- Backfilled EMLC and VIXY across `5m,15m,1h,1d` via the historical pipeline, launched detached (`setsid nohup ... & disown`, PID 3176015) per this project's own recorded `disown`-alone failure history. The fetch completed cleanly in ~85 minutes: 4,756,602 total bars stored, 0 fetch errors (some retried pacing timeouts recovered automatically; pre-listing-date "no data" responses were expected, not truncation).
- Discovered a third real gap while verifying: `infrastructure_run_historical_pipeline.py` never writes to `backfill_status` at all (that bookkeeping belongs to a separate script, `backfill_feature_factory.py`, never invoked here). Rather than trusting the fetch script's clean exit as a stand-in for the checkpoint, independently verified real non-zero `market_data_ohlcv_tradeable` rows with listing-date-consistent earliest timestamps for all 8 (symbol, tf) pairs first, then set `backfill_status.fetch_complete=true` for exactly those 8 rows using CLAUDE.md's own already-documented Corpus Pipeline Gotcha UPSERT pattern (scoped to EMLC/VIXY only). Promotion to `compute_eligible=true` was then gated on that checkpoint, per the plan's T-174-28 mitigation.
- Confirmed `live_tradeable=true` still returns 0 corpus-wide after promotion (T-174-01).
- Full `tests/unit/` suite green (0 failures, 2 pre-existing unrelated skips) after all three tasks.

## Task Commits

Each task was committed atomically:

1. **Task 1: Bring ib-gateway back up and confirm it serves historical data** - no code changes (operational verification only; see Verification Results below for the evidence recorded in place of a commit)
2. **Task 2: Onboard the two gap-fill ETFs through the qualification-gated helper** - `eb32c339b` (feat) -- includes the double-JSON-encoding fix to `src/config/instrument_onboarding.py`, found and fixed in the same task
3. **Task 3 (prep fix): add `--dimension` flag to the historical backfill script** - `cefd12e14` (fix) -- committed ahead of the actual backfill launch since it blocked Task 3 from being runnable at all
4. **Task 3 (backfill + promotion)**: no code changes -- database-only actions (backfill launch, `backfill_status` checkpoint UPSERT, `compute_eligible` promotion UPDATE), all literal commands recorded below

**Plan metadata:** this SUMMARY's own commit (docs: complete plan) -- committed separately per worktree convention.

## Files Created/Modified

- `scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py` - onboards EMLC/VIXY via `onboard_instrument()`, `--dry-run` default / `--commit` opt-in, idempotent (verified via a second `--commit` run with unchanged counts).
- `src/config/instrument_onboarding.py` - fixed double-JSON-encoding of `contract_details`/`evidence` by passing dicts directly instead of pre-serializing with `json.dumps()`.
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` - added `--dimension` flag (default `compute`, unchanged behavior for every existing caller) so a `backfill`-dimension invocation can target `is_active=true`/`compute_eligible=false` symbols.

## Verification Results

**Task 1 (gateway):**
- Pre-existing state (per Plan 07's own research, recorded 2026-09-15 evening): `Exited (1)`, stopped 2026-09-07 as part of the todo-371 OOM workaround.
- Actual observed state at this plan's execution start (2026-09-16 ~07:40 UTC): already `Up 15 hours`, `StartedAt=2026-09-15T21:02:36Z` -- the orchestrator's own independent re-check (moments before this plan started) had already confirmed the container recovered via the IBC nightly auto-restart's cached "autorestart" token at 23:59:03 UTC on 2026-09-15, without requiring a fresh 2FA push (`docker logs ib-gateway` shows `"IBC: Login has completed"` at `2026-09-15 23:59:06`, after the earlier same-day 2FA-timeout window the orchestrator described).
- `docker ps --filter name=ib-gateway --format '{{.Status}}'` -> `Up 15 hours` (re-confirmed again at the end of this plan: `Up 16 hours`)
- `ss -ltn | grep 7497` -> `LISTEN 0 4096 127.0.0.1:7497`
- `docker inspect ib-gateway --format '{{json .HostConfig.LogConfig}}'` -> `{"Type":"json-file","Config":{"max-file":"3","max-size":"100m"}}` -- log-rotation caps intact.
- Real historical-bar request via `IBKRProvider` (client_id=42, one-off, not committed): connected=True, qualified=True (SPY), `bar_count=6`, `first=2026-09-08 00:00:00+00:00`, `last=2026-09-15 00:00:00+00:00`, `last_close=757.39`.

**Task 2 (onboarding):**
- `SELECT symbol, is_active, compute_eligible, live_tradeable FROM instruments WHERE symbol IN ('EMLC','VIXY')` -> both `is_active=t, compute_eligible=f, live_tradeable=f` (pre-promotion state)
- `SELECT symbol, tag, source FROM instrument_tags WHERE tag IN ('fx_em','vol_proxy')` -> `EMLC|fx_em|human`, `VIXY|vol_proxy|human`
- `SELECT count(*) FROM instrument_metadata WHERE symbol IN ('EMLC','VIXY') AND description IS NOT NULL` -> 2
- `SELECT symbol, count(*) FROM backfill_status WHERE symbol IN ('EMLC','VIXY') GROUP BY symbol` -> 4 each
- `contract_details->>'asset_class'` -> `equity` for both, verified native JSONB (not double-encoded) after the fix
- `grep -c "INSERT INTO instruments"` on the new script -> 0; `grep -c "except .* as exc"` -> 0
- `.venv/bin/ruff check` -> clean on both modified/created files
- Re-ran `--commit` a second time: identical result counts (`n_onboarded=2, tags_inserted=2, metadata_written=2, backfill_rows_seeded=8`), confirmed zero net DB changes via row counts before/after -- `ON CONFLICT DO NOTHING`/`DO UPDATE` idempotency holds.

**Task 3 (backfill + promotion):**
- Launch command (literal): `setsid nohup .venv/bin/python -u scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --symbols EMLC,VIXY --timeframes 5m,15m,1h,1d --dimension backfill --client-id 41 >> logs/phase174_gap_fill_backfill.log 2>&1 < /dev/null & disown`
- PID: 3176015 (confirmed `PPID=1`, own session -- genuinely detached, survived multiple conversation-turn boundaries)
- `backfill_status` polling query (run every 5 min): `SELECT symbol, tf, status, fetch_complete, rows_written FROM backfill_status WHERE symbol = ANY($1) ORDER BY 1,2`
- Orphan-reap/relaunch commands (documented, not needed): `ps aux | grep infrastructure_run_historical_pipeline | awk '{print $2}' | xargs kill`, then relaunch with the identical command above (resumes via gap detection against existing `market_data_ohlcv` rows, not from scratch).
- The launched process completed normally (not a crash) after ~85 minutes: log shows `"Stage 1 complete: 4,756,602 total bars stored, 0 fetch error(s)"` followed by `"Backfill complete."`. The polling script's simplistic `ps -p $PID` liveness check reported this as "FETCH PROCESS DIED" -- a false positive from normal process exit, not an actual crash; confirmed by reading the full fetch log, which shows all 8 `stored N bars` lines with 0 errors.
- Row counts / date ranges from `market_data_ohlcv_tradeable` (verified before any promotion):

  | Symbol | TF | Rows | Earliest | Latest | Listing date | Consistent? |
  |---|---|---|---|---|---|---|
  | EMLC | 5m | 296,430 | 2010-07-26 13:30 UTC | 2026-09-15 19:55 UTC | 2010-07-22 | Yes (4 trading days after IPO, tradeable-view volume filter) |
  | EMLC | 15m | 104,245 | 2010-07-26 13:30 UTC | 2026-09-15 19:45 UTC | 2010-07-22 | Yes |
  | EMLC | 1h | 28,329 | 2010-07-26 13:00 UTC | 2026-09-15 19:00 UTC | 2010-07-22 | Yes |
  | EMLC | 1d | 4,060 | 2010-07-26 | 2026-09-15 | 2010-07-22 | Yes |
  | VIXY | 5m | 264,883 | 2011-01-06 14:40 UTC | 2026-09-15 19:55 UTC | 2011-01-03 | Yes |
  | VIXY | 15m | 96,295 | 2011-01-05 15:00 UTC | 2026-09-15 19:45 UTC | 2011-01-03 | Yes |
  | VIXY | 1h | 27,107 | 2011-01-05 15:00 UTC | 2026-09-15 19:00 UTC | 2011-01-03 | Yes |
  | VIXY | 1d | 3,947 | 2011-01-04 | 2026-09-15 | 2011-01-03 | Yes |

- `backfill_status.fetch_complete` gap found: `infrastructure_run_historical_pipeline.py` does not write to `backfill_status` at all (confirmed via `grep -n "backfill_status" <file>` returning nothing) -- that bookkeeping belongs to a separate script, `backfill_feature_factory.py`, not invoked by this plan's Task 3. Fixed by setting the checkpoint from verified evidence using CLAUDE.md's own documented pattern, scoped to just these two symbols:
  ```sql
  INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
  SELECT DISTINCT symbol, timeframe, true, 'pending'
  FROM market_data_ohlcv_tradeable
  WHERE symbol IN ('EMLC','VIXY') AND timeframe IN ('5m','15m','1h','1d')
  ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true;
  ```
  Result: `INSERT 0 8`. Re-verified: `SELECT count(*) FROM backfill_status WHERE symbol IN ('EMLC','VIXY') AND fetch_complete = true` -> 8, reached before the promotion UPDATE below.
- Promotion (gated, parameterized-equivalent via a scoped correlated subquery, not a bare unconditional UPDATE):
  ```sql
  UPDATE instruments
  SET compute_eligible = true
  WHERE symbol IN ('EMLC','VIXY')
    AND (SELECT count(*) FROM backfill_status b WHERE b.symbol = instruments.symbol
         AND b.tf IN ('5m','15m','1h','1d') AND b.fetch_complete = true) = 4;
  ```
  Result: `UPDATE 2`, both rows returned `compute_eligible=t, live_tradeable=f`.
- `SELECT count(*) FROM instruments WHERE live_tradeable = true` -> 0 (corpus-wide, T-174-01 held).
- `SELECT count(*) FROM (SELECT symbol, timeframe FROM market_data_ohlcv_tradeable WHERE symbol IN (SELECT symbol FROM instrument_tags WHERE tag IN ('fx_em','vol_proxy')) GROUP BY symbol, timeframe HAVING count(*) > 0) s` -> 8 (plan's automated verify query)
- `.venv/bin/pytest tests/unit/ -q` -> full suite green (0 failures, 2 pre-existing unrelated skips)

**Observed throughput (for Plan 12's extrapolation):**
- Measured: 4,756,602 total bars in ~82.7 minutes (1.378h) wall clock (launch 2026-09-16T11:52:26Z, fetch-log-file last write 2026-09-16T13:15:02Z) -> **~3,455,000 bars/hour aggregate** across all 8 (symbol, tf) pairs combined. Per-timeframe bar totals (both symbols): 5m=3,349,389; 15m=1,116,464; 1h=279,117; 1d=11,632. Per-timeframe wall-clock split is not separately measurable from available logs (the script does not timestamp per-(symbol,tf) completion), so only the aggregate rate is reported as measured.
- Estimated (not measured -- the script logs no literal per-chunk counter): request count derived from `src/providers/CLAUDE.md`'s documented chunk-day config (5m=150d, 15m=730d, 1h=1095d, 1d=7300d single-shot) against each symbol's actual history span (~5,900 days for EMLC, ~5,735 for VIXY): approximately 79 requests for 5m, 17 for 15m, 12 for 1h, 2 for 1d -> ~110 requests total over 1.378h -> **~80 requests/hour aggregate**, well under the 58-requests-per-10-minute (348/hour) documented ceiling, consistent with the run completing without a sustained pacing violation (several individual chunk timeouts occurred and retried successfully; see the full fetch log for `ibkr.hist_chunk_retry`/`ibkr.hist_pacing_error` events, none of which caused a chunk to permanently fail).
- **This run did not span the 23:59 UTC IBC nightly gateway restart** (ran entirely between 2026-09-16 11:52 UTC and 13:15 UTC, same day) -- so this plan cannot observe whether the pipeline reconnects unattended across that restart. Plan 12, whose much larger run will very likely span it, will need its own observation for that specific question.

## Decisions Made

- **Fixed the double-JSON-encoding bug in `instrument_onboarding.py` rather than routing around it in the new onboarding script.** The bug is in the single sanctioned "add an instrument" path every future onboarding caller (including Plan 12's full-scale run) depends on; patching it once here, at the point of first real exercise, is exactly the phase's own stated purpose ("any defect in that pathway surfaces here, cheaply, before Plan 12 runs it at scale").
- **Added a `--dimension` flag rather than pre-flipping `compute_eligible=true` or duplicating fetch logic.** The plan explicitly said not to write a new fetch path; a flag with an unchanged default preserves every other caller's behavior while unblocking this one.
- **Set `backfill_status.fetch_complete` from independently verified `market_data_ohlcv_tradeable` evidence, not from the fetch script's exit code**, since the fetch script never touches that table. This keeps promotion gated on real data (T-174-28), using the project's own pre-existing documented pattern rather than inventing a new one.
- **Treated the poller's "FETCH PROCESS DIED" false positive as a signal to investigate, not to relaunch blindly.** Reading the actual fetch log first confirmed the process had exited normally with 0 fetch errors, avoiding an unnecessary and wasteful relaunch of an already-successful multi-hour fetch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed double-JSON-encoding of `contract_details`/`evidence` JSONB in `onboard_instrument()`**
- **Found during:** Task 2, first `--commit` run
- **Issue:** `_json.dumps(contract_details)` / `_json.dumps(evidence)` were passed as query parameters to a pooled asyncpg connection whose jsonb codec already serializes Python values on the way out, producing a quoted JSON string inside the jsonb column instead of a native JSONB object.
- **Fix:** Pass the dicts directly; removed the now-unused `import json as _json`.
- **Files modified:** `src/config/instrument_onboarding.py`
- **Verification:** Deleted the bad rows, re-ran `--commit`, confirmed `psql` shows native JSONB (`{"base": "EMLC", ...}` not `"{\"base\": ...}"`); `tests/unit/config/test_instrument_onboarding.py` (10/10) and full `tests/unit/` suite still green.
- **Committed in:** `eb32c339b` (Task 2 commit)

**2. [Rule 3 - Blocking] Added `--dimension` flag to `infrastructure_run_historical_pipeline.py`**
- **Found during:** Task 3, pre-flight check (flagged by the orchestrator from the discarded prior attempt, confirmed live)
- **Issue:** `get_active_contracts()` defaults to `dimension="compute"` (compute_eligible=true only); EMLC/VIXY were `compute_eligible=false` at fetch time, so `--symbols EMLC,VIXY` would have matched zero contracts and printed "No matching contracts" without fetching anything.
- **Fix:** Added an explicit `--dimension` CLI flag, default unchanged at `"compute"`.
- **Files modified:** `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`
- **Verification:** Confirmed live via a direct `get_active_contracts(dimension=...)` call that `dimension="backfill"` matches both symbols while the default `"compute"` matches neither; `tests/unit/scripts/test_run_historical_pipeline.py`, `test_infrastructure_nightly_backfill.py`, `test_market_data_ohlcv_boundary.py` all still pass.
- **Committed in:** `cefd12e14`

**3. [Rule 3 - Blocking] Set `backfill_status.fetch_complete` via a verified-evidence UPSERT since the fetch script never writes that table**
- **Found during:** Task 3, post-fetch verification
- **Issue:** `infrastructure_run_historical_pipeline.py` has no `backfill_status` write path at all; the checkpoint table this plan's acceptance criteria and the promotion gate both depend on would otherwise stay `fetch_complete=false` forever regardless of a successful fetch.
- **Fix:** After independently confirming non-zero, listing-date-consistent rows in `market_data_ohlcv_tradeable` for all 8 (symbol, tf) pairs, ran CLAUDE.md's own already-documented Corpus Pipeline Gotcha UPSERT, scoped to `symbol IN ('EMLC','VIXY')` only (not corpus-wide).
- **Files modified:** none (database-only action, no code change needed -- the pattern already exists as documented practice)
- **Verification:** `SELECT count(*) FROM backfill_status WHERE symbol IN ('EMLC','VIXY') AND fetch_complete = true` -> 8, confirmed before the promotion UPDATE ran.
- **Committed in:** n/a (data-only; no file to commit for this step)

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking)
**Impact on plan:** All three were necessary to complete Task 2/3 correctly and are exactly the class of defect this plan's objective predicted it would surface cheaply before Plan 12 runs the same pathway at scale. No scope creep beyond what was needed to make the mandated pathway actually work.

## Issues Encountered

- The background poller script's liveness check (`ps -p $PID`) reported the fetch process as "died" when it had actually completed normally and exited. Resolved by reading the full fetch log before assuming a crash, which showed a clean `"Backfill complete."` with 0 fetch errors. No relaunch was needed.
- A background `run_in_background` monitoring wrapper (launched via the Bash tool's own background tracking rather than a fully `setsid`-detached script) was silently reaped at a conversation-turn boundary without notifying, before the fetch completed. Root-caused and fixed by re-launching all monitoring as `setsid nohup ... & disown` from script files (matching the exact pattern already used successfully for the backfill launch itself and the 5-minute poller), which survived multiple turn boundaries as expected.
- This worktree spawned without its own `.venv` and `.env` (both gitignored) -- symlinked both from the main checkout (`ln -s /home/bg/dev/indicagent/.venv .venv`, `ln -s /home/bg/dev/indicagent/.env .env`), matching the pattern documented in 174-02/03/07's summaries. Without the `.env` symlink, `Settings().ib_host` fell back to its code default (`172.18.176.1`, a WSL-style address unrelated to this Docker-based deployment) instead of the `.env`-configured `localhost`, causing an early connection failure in `--commit` mode -- not a deviation from the plan itself, but worth flagging since it is a real (if inherited) worktree-environment gap: the code default for `ib_host` is misleading outside a `.env`-present environment.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- EMLC and VIXY are fully onboarded, backfilled, and `compute_eligible=true`, closing both genuinely-empty exposure gaps (EM currency, volatility) this phase set out to fill.
- The full onboarding pathway (governance columns, `onboard_instrument()`, tag registry, backfill seeding, gated promotion) has now been exercised end to end on two real symbols, with three real defects found and fixed along the way -- `src/config/instrument_onboarding.py` is now safe for Plan 12 to call at scale without re-triggering the double-JSON-encoding bug, and `infrastructure_run_historical_pipeline.py`'s new `--dimension` flag is available if Plan 12 needs to fetch backfill-eligible-but-not-yet-compute-eligible symbols.
- Plan 12's own throughput extrapolation should use the measured ~3.46M bars/hour aggregate rate and the ~80 requests/hour estimate from this two-symbol run, but should independently observe whether the pipeline reconnects unattended across the 23:59 UTC IBC nightly restart -- this run did not span that window, so that specific risk remains unverified.
- No blockers.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-16*

## Self-Check: PASSED

- FOUND: scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py
- FOUND: commit eb32c339b
- FOUND: commit cefd12e14
