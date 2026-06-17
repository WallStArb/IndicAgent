# Cleanup: obsolete replay/snapshot scripts after Phase 127 rebuild

**Status:** pending
**Created:** 2026-06-16
**Trigger:** After `logs/REBUILD_STATUS` = COMPLETE and services restarted

## Context
Phase 130 (script-rewriting) already did ~95% of the old-schema → 3-table migration across the replay scripts. The major rewriting (run_historical_pipeline, lifecycle_replay, feature_replay, signal repositories) is verified complete per `.planning/phases/130-script-rewriting/130-VERIFICATION.md`.

A scan for old-schema residue (`signal_outcomes`, `signal_ledger_full`, writable `signal_ledger`, uuid4 IDs) found the codebase is clean except for two one-shot Phase 127 helper scripts.

## Delete candidates (one-shot, purpose served)
- [ ] `production/scripts/phase_127_before_snapshot.py` — references dropped tables (`signal_outcomes`, `signal_ledger_full`). Pre-replay baseline capture; the 2026-06-16 clean wipe removed the "before" data it would anchor against. Obsolete.
- [ ] `production/scripts/phase_127_monitor_replay.py` — replay monitoring helper. Obsolete once the 2026-06-16 rebuild completes.

## Verified NOT obsolete (leave alone)
- `lifecycle_replay.py` `signal_outcomes` references — all docstring/comment migration notes (lines 10, 12, 13, 128, 1282), no live dependency. 3-table schema confirmed.
- `run_historical_pipeline.py` / `feature_replay.py` `i1/i5` keys — current Phase 122 tier-code schema (contested naming per MEMORY.md Open Decisions, but LIVE, not obsolete).
- `memory_recall_benchmark.py` `uuid4` — synthetic benchmark test IDs, not schema.

## Also consider (separate concern, not blocking)
- `migrate_signal_ledger.py` — one-shot Phase 128-129 migration (old signal_ledger → 3-table). Already executed. Candidate for an `archive/` move rather than delete (keep provenance).

## Execution notes
- Do NOT run during the 2026-06-16 rebuild (services down, scripts in active use by the chain).
- After deletion: `grep -r "phase_127_before_snapshot\|phase_127_monitor_replay" tests/ docs/` to catch dangling references (per CLAUDE.md file-rename sweep rule).
- Commit on a feature branch per done-coding SOP.
