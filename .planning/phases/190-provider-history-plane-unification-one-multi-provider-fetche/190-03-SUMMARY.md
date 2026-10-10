---
phase: 190-provider-history-plane-unification-one-multi-provider-fetche
plan: 03
subsystem: infra
tags: [fetcher-planner, provider-dimension, two-tier-ledger, provider-plan, per-tf-floors, bar-source-policy, live-drain-safe]

# Dependency graph
requires:
  - phase: 190-provider-history-plane-unification-one-multi-provider-fetche (190-02)
    provides: the two-tier ledger contract: ohlcv_coverage.provider and ohlcv_provider_head.timeframe applied live (464), the 465 key shapes contract-tested and un-applied, the provider-parameterized coverage writer
  - phase: 190-provider-history-plane-unification-one-multi-provider-fetche (190-01)
    provides: the HistoryProvider surface whose plans the queue's budget fields mirror (consumed by 190-04)
provides:
  - ProviderPlan + load_provider_plan: per-provider planner inputs from infra.<provider>.* APR keys with per-provider validation and the raise/fallback contract
  - Provider-threaded planner: per-provider coverage/heads/empty-history reads, per-(symbol, provider, timeframe) floor resolution with the pre-465 NULL-to-1d fallback, per-row provider failure state, provider in the rank tuple
  - (provider, symbol, timeframe) triple keys in the queue with legacy-pair acceptance everywhere (the compat contract the OLD fetcher relies on)
  - plan.confirmation_chunks as the no-data evidence threshold; answers_1d=False plans issue no daily-answer query and get no 1d items
  - record_head_per_tf / load_fresh_heads_per_tf in _empty_history (465 key shape, code + tested, wave-5 gated)
  - policy_authorizes: the read-only bar_source_policy gate on item creation with today's live row shape proven a pass-through
affects: [190-04 fetcher generalization (consumes ProviderPlan, triples, per-TF head functions), 190-06 cutover (activates the per-TF write), todo 521 alpaca lane (policy rows + plans)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-shape keys: pairs accepted, triples canonical, one _series_key normalizer at every boundary"
    - "Per-provider key classes: planner inputs raise when missing, leaf-native limits keep a logged fallback"
    - "Derived policy rows name no fetch vendor, so they fall back to the default plane instead of gating it"

key-files:
  created:
    - tests/integration/test_provider_head_per_tf.py
  modified:
    - scripts/infrastructure/backfill/_fetch_queue.py
    - scripts/infrastructure/backfill/_empty_history.py
    - tests/unit/scripts/test_fetch_queue.py
    - tests/unit/scripts/test_empty_history.py
    - tests/unit/scripts/test_ibkr_history_fetcher.py

key-decisions:
  - "Policy gate authorizes a vendor when the applicable bar_source_policy row names it primary OR fallback: the two open tradier-primary 1d rows (MOD, QRVO) carry the ibkr fallback and the drain must keep fetching them; derived rows name no fetch vendor and fall back to the default plane"
  - "The raise contract splits by key class: load_provider_plan raises on missing planner inputs (timeout, retries, confirmation chunks, inter-item pause) and keeps the logged 600.0 leaf-native fallback only for the rate-limit window; this deliberately retires the old blanket fallbacks for the ibkr planner keys"
  - "QueueConfig keeps history_request_timeout_s/retries as fetcher-compatible mirrors of the ibkr plan until 190-04 passes plans, because fetch_item_with_retries reads them from the config the OLD fetcher passes"
  - "_HEADS_SQL selects timeframe and filters provider+symbols in one query; the per-TF resolution with the NULL-to-1d fallback lives in the floor closure, which tolerates both the pre-465 and post-465 worlds unchanged"
  - "PriorityQueue takes an optional plan (and provider); without one it reads the ibkr APR keys exactly as before, so the old-shape call path is byte-for-byte behavior-identical"

patterns-established:
  - "Commit-boundary compat proof: back-to-back dry-run TSV diffs through the OLD fetcher at every task boundary (T1/T2/T3 identical except one last_fetched_at the drain itself updated between runs)"

requirements-completed: [P190-queue]

# Metrics
duration: 62min
completed: 2026-10-10
---

# Phase 190 Plan 03: Per-provider planner Summary

**The fetcher's planner now reads per-provider tiers only: ProviderPlan config from infra.<provider>.* keys, provider-filtered coverage/head/empty-history reads, per-TF floors with the pre-465 fallback, per-provider failure state, plan-gated 1d due rule, and a read-only bar_source_policy gate on item creation, all while the unmodified fetcher kept draining across every commit boundary.**

## Performance

- **Duration:** 62 min
- **Started:** 2026-10-10T05:34:45Z
- **Completed:** 2026-10-10T06:37Z
- **Tasks:** 3 (all tdd, RED/GREEN per task)
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments

- ProviderPlan + load_provider_plan: per-provider APR reads (infra.<provider>.*), per-provider timeout/window validation with the existing message shape, per-provider depth overrides, answers_1d/daily_answer_filter as provider-native planner data
- The planner's four ledger reads are provider-filtered; floors resolve per-(symbol, provider, timeframe) with the NULL-timeframe (1d) fallback, so behavior is identical pre-465 and the seeded per-TF rows win after the 190-06 cutover (todo 526's surviving item, done on the read side)
- Items, candidates, due reasons and visited keys are (provider, symbol, timeframe) triples internally; every legacy (symbol, timeframe) call shape still works and produces results identical to the explicit-ibkr calls (dedicated compat tests)
- The empty-history evidence threshold comes from plan.confirmation_chunks; answers_1d=False plans never issue the daily-answer query and never create 1d items (pitfall 4)
- bar_source_policy gates item creation read-only, batched over the candidate symbol set; today's live row shape (152 rows incl. derived defaults and the open tradier+ibkr-fallback rows) is proven a pass-through
- The per-TF head write/read exist in _empty_history against the 465 key shape, proven in an integration force-rollback case; the live old-shape write path is unchanged
- Compat proof at every boundary: the OLD unmodified fetcher's dry run succeeded after each task, with T1/T2/T3 TSVs identical (3024 candidates, same order/lanes/holds) except one last_fetched_at the live drain itself updated between runs; the drain kept answering (44 requests in the 30 minutes after the last commit)

## Task Commits

Each task was committed atomically (RED and GREEN separately per the tdd gates):

1. **Task 1 (RED): ProviderPlan failing tests** - `ce42ffe7e` (test)
2. **Task 1 (GREEN): ProviderPlan loader + per-provider validation** - `f9a2ef81d` (feat)
3. **Task 2 (RED): provider-threading + per-TF head failing tests** - `5e1d75329` (test)
4. **Task 2 (GREEN): provider through ledger reads, floors, rank, keys; per-TF heads** - `aca366675` (feat)
5. **Task 2: 465 rollback-fixture integration proof for record_head_per_tf** - `782b85d5a` (test)
6. **Task 3 (RED): policy-gate failing tests** - `740a51691` (test)
7. **Task 3 (GREEN): bar_source_policy read gate** - `5df2303e4` (feat)
8. **Fetcher test fixtures for the raise contract** - `fcf14f79f` (test; Rule 3 blocking fix)

## Files Created/Modified

- `scripts/infrastructure/backfill/_fetch_queue.py` - ProviderPlan, load_provider_plan, default_provider/_series_key, provider-filtered _COVERAGE_SQL, timeframe-selecting _HEADS_SQL, plan-aware empty threshold and daily-answer filter, triple-keyed PriorityQueue with dual-shape acceptance, provider in the rank tuple, policy_authorizes + the gate in load(), docstring header documenting the provider dimension and compat contract
- `scripts/infrastructure/backfill/_empty_history.py` - record_head_per_tf and load_fresh_heads_per_tf (465 shape, wave-5 activation notes naming 190-06 Task 2); the live record_head path documented and unchanged
- `tests/unit/scripts/test_fetch_queue.py` - 25 new cases: loader/validation/depth-override, provider-filtered reads, per-TF floors, NULL-head fallback, plan threshold, per-row exclusion, provider tiebreak, triple keys, pair-vs-triple compat, parity-hold pairs, no-1d plans, daily filter from plan, policy gate/resolution/batching
- `tests/unit/scripts/test_empty_history.py` - per-TF upsert shape, old-shape live path pin, per-TF read preference
- `tests/integration/test_provider_head_per_tf.py` - 465 provider_head re-key applied in a force-rolled-back transaction; distinct per-TF rows, dedupe, live PK untouched
- `tests/unit/scripts/test_ibkr_history_fetcher.py` - fixtures seed the four planner-input APR keys and the coverage provider column (Rule 3)

## Decisions Made

- **Policy authorization is primary-OR-fallback, not primary-only.** The plan's compat claim "today's DB has no policy rows" was wrong: 152 rows are live, including two OPEN tradier-primary 1d rows with the ibkr fallback (MOD, QRVO) that the drain fetches nightly via IBKR. A primary-only gate would have silently dropped them. The gate authorizes primary or fallback; derived rows (15m/1h defaults) name no fetch vendor and fall back to the default plane. Verified against the live row shape by a dedicated test and the dry-run parity diff.
- **Planner inputs raise; the leaf-native window keeps its fallback.** load_provider_plan raises on missing timeout/retries/confirmation/pause keys and logs a fallback only for rate_limit_window_sec (600.0, ibkr.py's own window). This retires the old blanket fallbacks for the ibkr planner keys inside load_queue_config, per the plan's contract; the two existing config tests were updated to the split contract rather than around it.
- **QueueConfig keeps its two ibkr budget fields as fetcher-compat mirrors.** fetch_item_with_retries (a live-drain file) reads config.history_request_timeout_s/retries; removing them would have crashed the OLD fetcher mid-drain. They are copied from the ibkr plan load_queue_config builds, documented for the 190-04 cut.
- **Heads read once per load, resolved in the floor closure.** _HEADS_SQL selects timeframe without filtering it; the floor closure does per-TF resolution with the NULL-to-1d fallback. One query per load (same as before), and the same code path is correct in both the pre-465 and post-465 worlds, which is the contract's requirement (6).
- **item_lane and parity-sample keys are NOT tripled here.** They live in ibkr_history_fetcher.py, which the plan explicitly forbids editing (190-04 owns it). The queue side is triple-canonical and pair-accepting; the fetcher-side keys move next plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fetcher test fixtures broke on the raise contract and the provider column**
- **Found during:** Task 3 verification (full scripts suite)
- **Issue:** test_ibkr_history_fetcher's _RecordingSyncConn seeded only neutral keys, so load_queue_config's new planner-input raise killed two parity-sample tests; its coverage fake rows lacked the provider column the planner now selects.
- **Fix:** fixtures seed the four infra.ibkr.* planner keys and the provider field.
- **Files modified:** tests/unit/scripts/test_ibkr_history_fetcher.py
- **Committed in:** fcf14f79f

### Plan-Reality Sync (no code deviation)

**2. "Today's DB has no policy rows" was stale**
- **Found during:** Task 3
- **Issue:** the plan's compat argument assumed an empty policy table; the live table holds 152 rows (185's d2 work), including shapes that a naive primary-only gate would have used to silently drop live fetch work (MOD/QRVO 1d) and to gate 15m/1h parity items off (derived defaults).
- **Resolution:** the primary-or-fallback plus derived-fallback semantics above; pinned by test_todays_live_policy_shape_keeps_every_ibkr_candidate and the T2/T3 dry-run identity.
- **Files modified:** scripts/infrastructure/backfill/_fetch_queue.py (policy_authorizes)

**3. Task 2's "_HEADS_SQL ... WHERE provider = $1 AND timeframe = $2" sketch adjusted**
- **Found during:** Task 2
- **Issue:** a per-request-timeframe SQL filter cannot serve a load whose candidates span timeframes, and the NULL-timeframe world needs the fallback in the same read.
- **Resolution:** timeframe in the SELECT, provider+symbols in the WHERE, per-TF resolution in the floor closure (decision 4 above). The behavior tests assert the select/filter shape and the resolution semantics.

**4. Existing config tests updated to the new split contract**
- **Found during:** Task 1
- **Issue:** the plan's raise contract deliberately changes what load_queue_config does when the ibkr planner keys are missing (raise, not fall back); the old fallback test asserted the retired behavior.
- **Resolution:** tests rewritten to the split contract (neutral fallbacks warn once; planner inputs raise); the coupling-check test is unchanged and passes through the per-provider validation.

**Total deviations:** 1 auto-fix (Rule 3), 3 plan-reality syncs. No scope creep; no live-drain file edited beyond the plan's list; the timer was never stopped.

## Issues Encountered

- structlog output from unit tests lands in logs/ibkr_history_fetcher.log (BaseBatch re-points logging on every construction), which briefly made two test-fixture fallback warnings look like live-drain noise; confirmed they were pytest-side and pre-existing in kind.
- The rank tuple's provider tiebreak sorts alpaca before ibkr (plain string order); harmless with one configured provider, noted for the 190-04 lane ordering work.

## Known Stubs

- `scripts/infrastructure/backfill/_empty_history.py`: record_head_per_tf and load_fresh_heads_per_tf are written and tested but deliberately NOT on the live path until 190-06 Task 2 applies migration 465 and flips the write (the contract's wave-5 activation gate; calling the upsert before the flip fails with 42P10). The live old-shape write stays.
- `scripts/infrastructure/backfill/_fetch_queue.py`: PriorityQueue.plan/provider and policy-gated multi-provider candidate creation are seams; 190-04 passes the plans and triples, and until then the ibkr defaults reproduce today's behavior exactly. No data source is stubbed: every read hits the real ledger tables.

## User Setup Required

None. No migrations applied (465 stays un-applied by design), no APR seeds added (depth overrides need no seeds), no service or timer touched.

## Next Phase Readiness

- 190-04 constructs one ProviderPlan per configured provider (load_provider_plan is the reader), passes plans + provider into PriorityQueue, sets non-default provider labels at the item, triples item_lane/visited/parity keys, and renders the provider column in the dry-run TSV from RankedItem.row.provider (already carried)
- 190-06 applies 465 and flips _empty_history's live write to record_head_per_tf; the floor reads need no change (the per-TF rows win automatically)
- The Alpaca lane (todo 521) needs: load_provider_plan("alpaca", get, answers_1d=False, daily_answer_filter=None) plus its APR seeds, policy rows naming alpaca, and a _REBUILD_FILTERS entry; no further planner change
- The depth-override keys (infra.<provider>.depth_days.<tf>) are readable with no seeds required; Alpaca's 2016-forward 5m scope can land as data

## Self-Check: PASSED

All six created/modified files exist on disk; all eight task commits verified in git log (ce42ffe7e, f9a2ef81d, 5e1d75329, aca366675, 782b85d5a, 740a51691, 5df2303e4, fcf14f79f). Plan verification: full unit suite exit 0 (scripts suite green, pre-existing skips only), dry-run through the OLD fetcher green at every boundary with identical planned work, `grep "PROVIDER = "` on _fetch_queue.py returns nothing.

---
*Phase: 190-provider-history-plane-unification-one-multi-provider-fetche*
*Completed: 2026-10-10*
