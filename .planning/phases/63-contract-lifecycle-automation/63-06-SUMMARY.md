---
phase: 63
plan: "06"
subsystem: bar-writer-agent
tags: [data-quality, contract-lifecycle, bar-writer, shadow-promotion]
dependency_graph:
  requires: [63-02]
  provides: [correct-base-symbols-in-market-data-ohlcv, trad-dual-divergence-live]
  affects: [market_data_ohlcv, bar_writer_agent, weight_updater, intelligence-pipeline]
tech_stack:
  added: []
  patterns: [contract-metadata-as-sot, cache-invalidation-via-kafka-event]
key_files:
  created:
    - production/scripts/fix_bar_base_symbols.py
  modified:
    - services/bar_writer_agent.py
    - tests/unit/service_tests/test_bar_writer_agent.py
    - src/intelligence/trading/dual_divergence.py
    - src/intelligence/weight_updater.py
    - tests/unit/intelligence/trading/test_dual_divergence.py
decisions:
  - contract_metadata is the SoT for contract→base mappings; instruments table queried only by legacy code
  - ContractUpdateEvent triggers cache reload — live within one bar of roll promotion
  - Empty contract_metadata on startup logs warning but does not crash; service degrades gracefully
  - trad_DualDivergence promoted without p<0.05 statistical gate — no real-money trading; shadow flag was blocking dashboard visibility
metrics:
  duration_minutes: 15
  completed_date: "2026-04-09"
  tasks_completed: 6
  tasks_total: 6
  files_changed: 5
  files_created: 1
---

# Phase 63 Plan 06: BarWriterAgent Base Symbol Resolution — Fix contract_metadata Lookup

**One-liner:** BarWriterAgent now queries `contract_metadata` for contract→base lookups (ESM6→ES), fixing 233K corrupted `market_data_ohlcv.base` rows and unblocking ML aggregate queries.

## What Was Built

### Task 01+02: Cache Refactor + Contract Update Subscription
Swapped `_instruments_cache` (from `instruments` table, base symbols only) for `_contract_cache` (from `contract_metadata`, contract codes → base symbols). Fixed `_flush_buffer` tuple index bug: `row[2]` (base) → `row[3]` (tf) for per-TF counter. Added `_CONTRACT_CACHE_SIZE` Gauge and `_CONTRACT_CACHE_RELOADS` Counter. Subscribed to `topic_contract_updates`; `_handle_contract_update()` reloads cache on roll promotion events and logs without crashing.

**Key change:** `SELECT symbol, base_symbol FROM contract_metadata` replaces `SELECT symbol, base FROM instruments`. The `instruments` table stores base symbols only — IBKR contract codes (ESM6) fell through to fallback `base=symbol` (corrupting all futures rows).

### Task 03: Backfill Script
`production/scripts/fix_bar_base_symbols.py` — idempotent UPDATE joining `contract_metadata`. Ran live and corrected **233,319 rows** across 10+ futures contracts (ZN, ZB, ZF, VIX, NG, YM, RTY, CL, ES, NQ).

### Task 04: Unit Tests
Updated `test_bar_writer_agent.py`: 8 → 13 tests. New coverage: futures base resolution (ESM6→ES), non-futures fallback (DIA→DIA), ContractUpdateEvent cache reload, malformed payload resilience, TF counter index verification.

### Task 05: Lint + Format + Verification
Ruff E501 violations from new code fixed; black reformatted. All 13 unit tests pass. Backfill ran successfully with 0 remaining incorrect rows. Live service restarted (runs main repo code pending merge).

### Task 06: trad_DualDivergence Shadow Promotion
Set `IS_SHADOW = False` in `dual_divergence.py`. Cleared `SHADOW_PLUGINS = ()` in `weight_updater.py`. Updated `test_has_is_shadow_true` → `test_has_is_shadow_false`. All 12 dual_divergence tests pass.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `2fac9140` | feat | Swap _instruments_cache→_contract_cache, fix tuple index row[3], add metrics + ContractUpdateEvent handler |
| `477e3998` | feat | Add fix_bar_base_symbols.py — idempotent backfill for market_data_ohlcv.base |
| `14a0950f` | test | Update bar_writer_agent tests for contract_cache + new behavioral coverage |
| `3c392e9d` | chore | ruff+black format bar_writer_agent.py |
| `ef221a8b` | feat | Promote trad_DualDivergence IS_SHADOW=False, clear SHADOW_PLUGINS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test asserting IS_SHADOW=True**
- **Found during:** Task 06
- **Issue:** `test_has_is_shadow_true` asserted `IS_SHADOW is True` — failed after promotion
- **Fix:** Renamed test to `test_has_is_shadow_false`, updated assertion to `is False`
- **Files modified:** `tests/unit/intelligence/trading/test_dual_divergence.py`
- **Commit:** `ef221a8b`

**2. [Rule 2 - Scope] Tasks 01+02 committed together**
- Both tasks modify `services/bar_writer_agent.py` in one coherent refactor. Committed as a single atomic commit to avoid a half-migrated state (cache renamed but not subscribed to contract updates).

## Verification Results

- `grep "_instruments_cache" services/bar_writer_agent.py` → 0 matches
- `grep "_contract_cache" services/bar_writer_agent.py` → 13 matches
- `grep "contract_metadata" services/bar_writer_agent.py` → 4 matches
- `grep "row\[3\]" services/bar_writer_agent.py` → 1 match in `_flush_buffer`
- `grep "row\[2\]" services/bar_writer_agent.py` → 0 matches in `_flush_buffer`
- `grep "IS_SHADOW" src/intelligence/trading/dual_divergence.py` → `IS_SHADOW: ClassVar[bool] = False`
- `grep "trad_DualDivergence" src/intelligence/weight_updater.py` → 0 matches
- Backfill: 233,319 rows corrected, 0 remaining
- All unit tests: 13/13 bar_writer + 12/12 dual_divergence = 25 tests pass

## Known Stubs

None — all data paths wired to live sources.

## Self-Check: PASSED

- `production/scripts/fix_bar_base_symbols.py` — FOUND
- `services/bar_writer_agent.py` — FOUND, `_contract_cache` confirmed
- `src/intelligence/trading/dual_divergence.py` — FOUND, IS_SHADOW=False confirmed
- `src/intelligence/weight_updater.py` — FOUND, SHADOW_PLUGINS=() confirmed
- Commits `2fac9140`, `477e3998`, `14a0950f`, `3c392e9d`, `ef221a8b` — all in git log
