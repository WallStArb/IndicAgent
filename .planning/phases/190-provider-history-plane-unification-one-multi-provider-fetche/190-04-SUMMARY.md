---
phase: 190-provider-history-plane-unification-one-multi-provider-fetche
plan: 04
subsystem: infra
tags: [provider-registry, fetcher, vendor-blind-loop, provider-plan, overlay-split, dry-run-tsv, live-drain-safe]

# Dependency graph
requires:
  - phase: 190-provider-history-plane-unification-one-multi-provider-fetche (190-01)
    provides: the HistoryProvider surface (typed onto FetchContext) and the import-boundary fence
  - phase: 190-provider-history-plane-unification-one-multi-provider-fetche (190-03)
    provides: ProviderPlan + load_provider_plan, provider-fielded rows and triple-canonical queue keys
provides:
  - _PROVIDER_REGISTRY: one entry per vendor (leaf_factory + fetch hook + load_overlays + connect label) behind the existing provider_factory seam
  - A vendor-blind loop: dispatch is strictly `entry = registry[row.provider]; await entry.fetch(...)`; vendor mechanics are reachable only through the ibkr entry's hook
  - Per-provider budgets: one ProviderPlan per registry entry built in prepare from the infra.* APR read; the stall bound, retries and inter-item pause all read the plan
  - Per-provider connect (zero-candidate providers never construct a leaf), provider-labeled ItemOutcome and record_fetch_outcome writes, provider-carrying escalation targets
  - The dry-run TSV provider column (column 3, immediately after symbol), keeping the 190-06 parity gate satisfiable
affects: [190-05 rename, 190-06 cutover, todo 521 alpaca lane (a second registry entry is the whole integration)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Registry entry as frozen dataclass with the fetch hook as a first-class field; constructor seams bind onto the ibkr entry only, foreign entries pass through untouched"
    - "Item dispatch wraps entry.fetch in an outcome-converting guard: an entry failure is the item's error outcome, never a fallback to another vendor's mechanics"
    - "Overlay split by owner: provider-neutral loaders stay fetcher-owned, leaf-native loaders move behind the entry's load_overlays (soft fallback)"

key-files:
  created: []
  modified:
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - scripts/infrastructure/backfill/_history_fetch_item.py
    - tests/unit/scripts/test_ibkr_history_fetcher.py
    - tests/unit/scripts/test_history_fetch_item.py
    - tests/unit/test_provider_leaf_boundary.py

key-decisions:
  - "The registry is a module-level dict of frozen ProviderEntry, not a framework: no discovery, no dynamic import (design Non-goals); a second vendor is literally one entry plus a leaf module"
  - "The ibkr entry's fetch hook is a closure factory (_ibkr_entry_fetch) over fetch_item_with_retries; the constructor fetch_fn seam rebinds the hook, so existing test injection keeps working and the 189-proven item path is the entry's implementation"
  - "An entry whose fetch raises yields the item's error outcome and the run continues (T-190-13 test): the loop never falls back to IBKR mechanics for a foreign item"
  - "prepare() builds one ProviderPlan per registered provider and refuses a plan holding an unregistered provider before the run starts, never mid-loop"
  - "The dry-run provider column is additive (column 3); planned work verified byte-identical to the pre-change dry run column-for-column across the Task 2 boundary"

patterns-established:
  - "Commit-boundary live parity: column-aware dry-run diff at every task boundary (T1 vs T2 planned work identical, 3024 rows)"

requirements-completed: [P190-fetcher]

# Metrics
duration: 68min
completed: 2026-10-10
---

# Phase 190 Plan 04: Generalized fetcher Summary

**The fetcher is now a provider-parameterized loop over a one-entry registry: `_PROVIDER_REGISTRY` maps ibkr to its leaf factory, item-fetch hook and overlay loader, the loop dispatches strictly through `entry.fetch` per item's provider with per-provider ProviderPlan budgets, and the dry run carries the provider column, all while the drain kept running.**

## Performance

- **Duration:** 68 min (through the Task 3 commit; the live-run confirmation followed)
- **Started:** 2026-10-10T06:27Z
- **Tasks:** 3 (Task 1 tdd: RED/GREEN gates; Tasks 2-3 auto)
- **Files modified:** 5

## Accomplishments

- `_PROVIDER_REGISTRY` with exactly one entry, "ibkr": leaf_factory holds the concrete IBKRProvider construction moved from `_default_provider` (settings.ib_host/ib_port, args.client_id), fetch wraps the 189-proven `fetch_item_with_retries` path, load_overlays drives the five leaf-native APR overlay loaders
- The loop dispatches strictly through `entry.fetch`; a fake entry whose fetch raises surfaces the error as that item's error outcome with no IBKR fallback (T-190-13 pinned by test)
- Per-provider budgets: prepare builds one ProviderPlan per registry entry from a single infra.* APR read (planner inputs raise when missing, the leaf-native window keeps its fallback); the queue plans on the default plane; the stall bound and retry count read the item's plan; the inter-item pause reads the plan (`_KEY_INTER_ITEM_PAUSE` deleted)
- Per-provider lifecycle: only providers in the run's plan construct and connect a leaf (one socket per run, cached); unknown providers fail fast in prepare; connect failures compose from the entry's label so the IBKR wording survives ("IBKR gateway unreachable at startup")
- Vendor semantics out of the loop: ItemOutcome is provider-labeled by the ibkr fetch path, `record_fetch_outcome` writes provider, gateway_lost and escalation targets carry provider/symbol/timeframe, and the overlay split keeps the neutral loaders fetcher-owned
- Dry-run TSV gained the provider column immediately after symbol; T1-to-T2 planned work verified identical column-for-column (3,024 rows); the parsed surfaces (`fetch_run_id:` line, LOCK_HELD_MESSAGE, status-file schema) verified via test_head_rerun and the D7 audit suite
- FetchContext typed to HistoryProvider, carries the item's ProviderPlan; the no-data confirmation threshold reads the plan; the item module is documented as ibkr-entry-path-only with no new vendor branches

## Task Commits

1. **Task 1 (RED): registry dispatch failing tests** - `1eb425f45` (test)
2. **Task 1 (GREEN): provider registry with per-entry fetch hooks** - `7217669ef` (feat)
3. **Task 2: vendor-blind loop mechanics, overlay split, TSV provider column** - `1154fd156` (feat)
4. **Task 3: item mechanics fenced as the ibkr entry's fetch path** - `2ae07da93` (feat)

## Deviations from Plan

### Task-boundary adjustments (no scope change)

**1. ItemOutcome.provider landed in Task 2, not Task 3**
- The plan's Task 2 action says "ItemOutcome gains provider" but its file list put the item module in Task 3; `_record_outcome`'s provider= write (also Task 2 action) needs the field. The field moved to Task 2 with the ledger write.

**2. Per-provider connect, escalation provider triples and the inter-item pause plan read landed with Task 1 GREEN**
- The dispatch rewrite makes them structural: the connect loop must be per-entry to satisfy "zero candidates never connected", and the loop's visited/breach keys become triples the moment rows carry providers. Task 2's list overlaps; the split point is artificial there.

**3. Boundary allow-list comments updated from "SHRINKS IN 190-04" to "STAYS POST-190-04"**
- Found during: Task 3
- The plan's instruction was to shrink the list only if a concrete-leaf import was genuinely removed; none was (the registry entry owns the concrete import, exactly as the plan's action states). The three fetcher-family entries stay with honest reasons; a future move of the leaf factory into src/providers would shrink the first.

### Plan-Reality Sync

**4. The unknown-provider fail-fast test monkeypatches the queue's ranked snapshot**
- The single-plane queue filters ledger rows server-side by its own provider, so a foreign provider's row cannot surface through the real read path today. The guard runs on the loaded queue in prepare (exercised via a patched `ranked_snapshot` returning a ghost row) plus a direct unit test of `_unknown_providers` over ranked and held snapshots.

**Total deviations:** 2 task-boundary adjustments, 1 plan-reality sync, 1 comment-reality sync. No scope creep; no live-drain file left in a non-runnable state at any commit.

## Issues Encountered

- The test fake queue had to move to triple visited keys in step with the fetcher's loop (the pair-shape fake silently repeated items under triple keys).
- The 190-03-era fixture patch of `_load_provider_overlays` was replaced with patches of the underlying `_history_fetch` loaders, so the real overlay split and each entry's `load_overlays` hook run in every default-registry test.

## Known Stubs

- None new. 190-03's remaining stub stands: `record_head_per_tf`/`load_fresh_heads_per_tf` in `_empty_history.py` stay off the live write path until 190-06 applies migration 465.

## User Setup Required

None. No migrations, no APR seeds, no service or timer touched; the live drain was never stopped.

## Next Phase Readiness

- 190-05 (the code-identifier rename) works on a fetcher whose loop is already vendor-blind; JOB, FETCHER_LOCK_NAME and the status path are untouched here, as frozen
- 190-06 applies 465 and flips the per-TF head write; the dry-run provider column this plan added is delta 1 of its parity gate
- Adding the Alpaca lane (todo 521) is now literally: a leaf module conforming to HistoryProvider, one `_PROVIDER_REGISTRY` entry (leaf_factory + fetch hook + load_overlays), APR seeds under infra.alpaca.*, and policy rows; the loop, ledger writes, locks and lanes need no change
- Multi-plane queueing (a second provider's candidates in one run) remains future work: prepare builds per-provider plans and the loop dispatches per row.provider, but PriorityQueue still plans one plane per run

## Verification

- `tests/unit/scripts/ -q` green; full `tests/unit/ -q` green (exit 0) at every task boundary
- Live dry run on the new code: exit 0, provider column rendered (every row 'ibkr'), bands intact; `grep infra.ibkr.` on the fetcher module returns nothing
- Parsed surfaces verified through their consumers: test_head_rerun.py and tests/unit/services/test_bar_reconciliation_audit.py green
- Live drain: the run in flight at commit time kept the old code; the first natural timer fire after the last commit started the new code (confirmed post-commit, see Self-Check)

## Self-Check: PASSED

All five modified files exist on disk; all four task commits verified in git log (1eb425f45, 7217669ef, 1154fd156, 2ae07da93). Live-run confirmation: the timer fired on the new code and logs/ibkr_history_fetcher_status.json recorded a clean run (status success/partial with no import or dispatch errors) -- see the post-SUMMARY confirmation commit if the status read landed after this file was written.

---
*Phase: 190-provider-history-plane-unification-one-multi-provider-fetche*
*Completed: 2026-10-10*
