---
slug: lifecycle-replay-fk-violation
status: resolved
trigger: >
  DATA_START
  lifecycle_replay trade_executions FK violation — during Phase 127 clean-slate
  rebuild, lifecycle_replay.py fails on every symbol/tf: "insert or update on
  table trade_executions violates foreign key constraint fk_trade_executions_frame".
  DATA_END
created: 2026-06-17
updated: 2026-06-17
goal: find_and_fix
tdd_mode: false
---

# Debug: lifecycle_replay FK violation on trade_executions

## Symptoms

- **Expected behavior:** `lifecycle_replay.py --workers 8` inserts `trade_executions` rows, each referencing a `trade_frames.frame_id` via FK `fk_trade_executions_frame`. Backfill already wrote 1,036,513 signal_events + 1,036,513 trade_frames (1:1, 0 orphans). Replay should resolve outcomes against those existing frames.
- **Actual behavior:** Every symbol/tf insert fails: `insert or update on table "trade_executions" violates foreign key constraint "fk_trade_executions_frame"`. The restart/abort safety gate fired correctly → services stayed down, `logs/REBUILD_STATUS=FAILED`.
- **Error messages:** FK violation on `trade_executions.frame_id` (full text in `.planning/phases/127-clean-replay-validation/.continue-here.md`).
- **Timeline:** Surfaced 2026-06-16 after the clean-slate wipe + overnight backfill (`--workers 8`, no warmup). Backfill succeeded; features/signals/frames are valid and intact. Never worked in this run.
- **Reproduction:** On the freshly backfilled DB: `python production/scripts/lifecycle_replay.py --workers 8` (any symbol/tf fails).

## Phase 127 Constraints (read first)

- Services are DOWN by design: `indicagent-intelligence-pipeline` + `indicagent-feature-writer` have `Restart=no` drop-ins at `/etc/systemd/system/<svc>.service.d/no-restart.conf`; `indicagent-service-auditor` + `indicagent-self-healing-agent` are STOPPED. Restore only after replay succeeds.
- Do NOT re-run the backfill — it is correct and intact (1.036M signals / 1.036M frames / 4.9M features / 0 orphans). Only `lifecycle_replay.py` needs fixing + re-running.
- DB access: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`
- Sudo: `echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo -S <cmd>`

## Pre-verified evidence (orchestrator checked before delegating)

The Phase 127 handoff's stated hypothesis is **DISPROVEN** — do not re-investigate this branch:

- ❌ NOT entry_type divergence. `trade_frames` contains **only `at_close`** (1,036,513 rows; `SELECT entry_type, count(*) FROM trade_frames GROUP BY 1`):
  ```
   entry_type |  count
  ------------+---------
   at_close   | 1036513
  ```
- ❌ NOT a `_make_frame_id` divergence. The helper is **byte-identical** across all three producers — same `uuid.uuid5(uuid.NAMESPACE_DNS, f"{signal_id}:{entry_type}")`:
  - `production/scripts/lifecycle_replay.py:91` (`_make_frame_id`)
  - `production/scripts/run_historical_pipeline.py:764` (`_make_frame_id`)
  - `src/persistence/repository/signal_events_repository.py:50` (`_make_frame_id`)
  - execution_id namespace also matches (`signal_events_repository.py:563` vs `lifecycle_replay.py:1012,1040`).

So the frame_id derivation formula is identical. The FK miss must come from a **different input** to that formula — e.g. lifecycle_replay passing a different `signal_id` than the one backfill wrote the frame under, or replaying signals whose frames were never written, or an entry_type that replay reads from a source the frames table doesn't have.

## Current Focus

- **hypothesis:** lifecycle_replay uses `str(s["signal_id"])` which produces dashed UUID format ("with-hyphens"), but backfill used hex format ("no-hyphens") from `make_signal_id()`. This causes `_make_frame_id()` to compute different frame_ids for the same signal.
- **test:** Fix lifecycle_replay.py to use UUID hex format instead of str() format.
- **expecting:** After fix, lifecycle_replay will compute frame_ids that match the backfill's frame_ids in trade_frames.
- **next_action:** Fix lifecycle_replay.py line 532 to use `s["signal_id"].hex` instead of `str(s["signal_id"])`.

## Evidence

- timestamp: 2026-06-17 (investigation resumed)
  checked: lifecycle_replay.py signal acquisition query (lines 437-468)
  found: `signals` query selects `se.signal_id` from signal_events, joins trade_frames on `signal_id + signal_ts`, and includes `tf.frame_id` in SELECT. Signal map built as `sig_map: dict[str, dict] = {str(s["signal_id"]): dict(s) for s in signals}`.
  implication: The `sid` used throughout replay (lines 597, 623, 969, 1004, 1037) is `se.signal_id` from signal_events, NOT `tf.signal_id` from trade_frames.

- timestamp: 2026-06-17 (investigation resumed)
  checked: lifecycle_replay.py _flush_writes function (lines 1014, 1041)
  found: Both zone exits (line 1014) and market track resolutions (line 1041) compute `frame_id = _make_frame_id(sid, "at_close")` where `sid` is the signal_id from the iteration (originally `se.signal_id`).
  implication: lifecycle_replay computes frame_id from signal_events.signal_id, but the FK expects a frame_id that exists in trade_frames.

- timestamp: 2026-06-17 (investigation resumed)
  checked: Query join condition (line 462)
  found: `LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts`
  implication: If a signal_event has no matching trade_frame (signal_id + signal_ts mismatch, or frame never written), the LEFT JOIN returns `tf.frame_id = NULL`. The query would still return the signal, but `frame_id` would be null in the result set.

- timestamp: 2026-06-17 (ROOT CAUSE)
  checked: UUID string format mismatch between backfill and replay
  found: 
    - Backfill (run_historical_pipeline.py line 975): `signal_id` is hex string from `make_signal_id()` (32 chars, no dashes like "6c4fa4db5c51322a8f32441dd0366cd3"). Passed to `_make_frame_id()` as-is.
    - Replay (lifecycle_replay.py line 532): `s["signal_id"]` is UUID object from asyncpg. Converted via `str()` to dashed format (like "6c4fa4db-5c51-322a-8f32-441dd0366cd3"). Passed to `_make_frame_id()`.
  tested: Manual verification with actual signal_id `6c4fa4db-5c51-322a-8f32-441dd0366cd3`:
    - Dashed format → `8d53b758-aefb-5bb1-864c-745aa1ff2845` (NOT in DB)
    - Undashed format → `b674c990-73b5-58a4-9fc0-3d5aa2ca8833` (MATCHES DB)
  implication: `_make_frame_id()` produces deterministic UUIDv5 from string input. Different string representations of the same UUID produce different frame_ids because the string format is part of the input hash.

## Eliminated

- hypothesis: entry_type divergence (at_close vs at_pullback/at_limit/at_reclaim/zone_proximal) → trade_frames has only at_close.
- hypothesis: `_make_frame_id` formula divergence across writers → byte-identical at all three sites.

## Resolution

root_cause: lifecycle_replay.py lines 479 and 532 convert UUID to string using `str(s["signal_id"])` which produces dashed format ("6c4fa4db-5c51-322a-8f32-441dd0366cd3"), but backfill uses hex format from `make_signal_id()` ("6c4fa4db5c51322a8f32441dd0366cd3"). Since `_make_frame_id()` hashes the string input, different formats produce different frame_ids.
fix: Changed lifecycle_replay.py lines 479 and 532 from `str(s["signal_id"])` to `s["signal_id"].hex` to match backfill's hex format.
verification:
  - Manual test: `_make_frame_id("6c4fa4db5c51322a8f32441dd0366cd3", "at_close")` produces `b674c990-73b5-58a4-9fc0-3d5aa2ca8833` which matches DB.
  - Dry-run test: Passed without errors.
  - Live test on AGG 15m: Successfully processed 973 signals and wrote 1789 trade_executions rows. Zero FK violations.
files_changed: ["production/scripts/lifecycle_replay.py"]
