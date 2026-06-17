# Phase 127 — lifecycle_replay verify failure (2 issues) + structural fix

**Status:** open (blocks Phase 127 completion + service restart)
**Created:** 2026-06-17
**Root cause debug session:** `.planning/debug/resolved/lifecycle-replay-fk-violation.md`

## What happened

Clean-slate rebuild (tasks 1-3 done): full wipe → backfill (1,036,513 signals / 1,036,513 frames / 4.9M features / 0 orphans) → lifecycle_replay ran with the FK fix (`.hex`, commit `82a71a69`).

`lifecycle_replay.py --workers 8` **completed the per-symbol/tf sweep** but its `_verify_replay` integrity gate **FAILED with 2 issues** and raised `RuntimeError: VERIFY FAILED`. Replay exited non-zero. Services remain down (correct — restart gate held).

Verify totals: `total=1,133,165 with_outcome=1,064,075 stale_unresolved=66,078 target_no_pnl=74,296 orphan_signal_events=0`.

FK integrity is CLEAN (0 orphans) — the `.hex` fix held. The defects are in lifecycle *resolution completeness*, not joining.

## Issue 1 — stale_unresolved (66,078)

`status='pending' AND ts < NOW() - INTERVAL '2 days'`. Signals still pending despite being >2 days old. The lifecycle sweep should have expired them. Root cause TBD — candidate: TTL-expiry path not firing for signals whose post-fire bar window exhausted without activation but TTL never elapsed in-bar, OR a (symbol, tf) subset the sweep skipped. Final `pending` count is 431,442 (most are recent end-of-data, but 66k are genuinely stale).

## Issue 2 — target_no_pnl (74,296)

`status='expired' AND te.actual_pnl_r IS NULL`. Signals correctly marked `expired` but with **no trade_executions outcome row** (so no pnl_r). The expiry path sets status but doesn't always write an outcome. These need an execution row (pnl_r=0 for a TTL-expiry-without-entry is acceptable; the point is the row must exist).

Both issues point at the **TTL-expiry / non-activation resolution path** in lifecycle_replay not fully recording outcomes.

## Fix order (next session)

1. **Structural fix (pre-approved):** `lifecycle_replay.py` — fetch `signal_id` as hex from DB (`encode(se.signal_id::bytea, 'hex') AS signal_id`) instead of coercing through `uuid.UUID`; drop the `.hex` calls at lines 479 and 532; add comment that signal_id is a SHA-256 content hash, not a uuid. Source edit only — does not affect any running process. See memory + the discussion: the `.hex` fix works but still lets a content hash pass through a uuid object; fetch-as-hex makes the mangling structurally impossible.
2. **Diagnose Issue 1 + Issue 2.** Likely the same code path. Grep the expiry/TTL branch in lifecycle_replay (around the `zone_exits` / `markets` / never_activated / ttl_expired handling, ~lines 960-1070). Confirm whether expired-without-pnl signals ever get an execution INSERT.
3. **Fix** so every resolved signal gets a trade_executions row, and every stale pending signal gets expired.
4. **Re-run** `python production/scripts/lifecycle_replay.py --workers 8 --commit-every 500` (NO re-backfill — backfill is intact).
5. **Verify passes** (`_verify_replay` clean: stale_unresolved=0, target_no_pnl=0, orphans=0).
6. **Task 6:** restore services (remove `/etc/systemd/system/<svc>.service.d/no-restart.conf` drop-ins for intelligence-pipeline + feature-writer; `systemctl daemon-reload`; `systemctl reset-failed`; start writers + service-auditor + self-healing-agent). Then full validation checklist (CTF non-null, stale feature keys populate, status transitions, trade_executions populated).

## Notes

- `counterfactual_pnl_r` is correctly NULL — populated by live alpha_swarm CounterfactualEvaluator (Phase 130), NOT historical replay. Do not treat as a defect.
- DB: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`
- Sudo: `echo '!123Angelina' | /usr/bin/sudo -S <cmd>`
- Recurring asyncpg `ERROR Resetting connection with an active transaction` at every symbol/tf boundary — transaction-hygiene bug (connection released with tx open). Data commits fine; non-blocking but worth a cleanup pass. Lower priority than the 2 verify issues.
