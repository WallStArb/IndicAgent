---
phase: 131-signal-generation-integrity
verified: 2026-06-17T00:00:00Z
status: human_needed
score: 10/12 must-haves verified
gaps: []
human_verification:
  - test: "Run ctf_score gate query on the Phase 131 verification window"
    expected: ">=85% of non-null signal_events.ctf_score > 0.05 for ESM6/NQM6/SPY in the exact date window used during 131-07 verification"
    why_human: "Current DB shows 80.1% for ts >= 2026-06-11 and 87.3% for ts >= 2026-06-14. The 87% in the SUMMARY was measured against the most recent bars of the sample replay (2026-06-14 to 2026-06-17), not the full ts > 2026-06-10 window as written in the plan. The gate formally passes only for the narrower window. Whether this satisfies the spirit of the >=85% gate requires human judgment before Phase 133 begins."
  - test: "Verify 35 of 35 eligible plugins fire in a 2-week replay"
    expected: "SELECT COUNT(DISTINCT setup_plugin) FROM signal_events WHERE ts > '2026-06-03' returns >= 35. CrossAssetDivergence (0 signals) is expected. Any other plugin with 0 is a bug."
    why_human: "T-02 in plan 131-07 was deferred due to session quota exhaustion. This check has not been run. Must be completed before Phase 133 full rebuild per the CONTEXT verification gate."
  - test: "Append Phase 131 verification results to docs/plans/phase-127-validation-report.md"
    expected: "A 'Phase 131 Verification' section with ctf_score gate result, plugin coverage count, symbol coverage (VXK6/VXM6/ZNM6), and an explicit PASS/FAIL Verdict line"
    why_human: "T-03 in plan 131-07 was deferred due to session quota exhaustion. The validation report has no Phase 131 section (confirmed via grep). This is a documentation gate item, not a code gate."
---

# Phase 131: Signal Generation Integrity — Verification Report

**Phase Goal:** Fix all known signal-generation integrity bugs so the corpus rebuild in Phase 133 produces clean, unbiased training data.
**Verified:** 2026-06-17
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A4 root cause confirmed empirically and diagnostic log removed | VERIFIED | `grep -n "A4 CONFIRM" run_historical_pipeline.py` returns lines 1625 + 1670; no `A4-DIAG` print remains |
| 2 | asset_class injected into all_features for all symbols before run_i7_and_persist() | VERIFIED | `_symbol_asset_class` declared at line 1672, COALESCE query at line 1675 (`contract_metadata` + `instruments.contract_details->>'asset_class'`), injection in both normal and precomputed paths (lines 1792-1793, 1824-1825) |
| 3 | BOCPD look-ahead bias eliminated (vol[-21:-1]) | VERIFIED | Line 278 of `bocpd_changepoint.py` contains `np.mean(vol[-21:-1])`, no `vol[-20:]` remains |
| 4 | _verify_replay reports COUNT(DISTINCT signal_id) with fan-out warning | VERIFIED | `lifecycle_replay.py` line 1236 has `COUNT(DISTINCT se.signal_id)`, line 1260 has warning on `total != distinct_signals` |
| 5 | bar_histories deque maxlen = 800 (PrevDayLevelTest fix) | VERIFIED | Line 1688 of `run_historical_pipeline.py`: `deque(maxlen=800)`, no `maxlen=200` remains |
| 6 | CrossAssetDivergence annotated live-only with _CORPUS_EXCLUDABLE=True | VERIFIED | `cross_asset_divergence.py` line 79: `_CORPUS_EXCLUDABLE: bool = True`; lines 13-16 have live-only comment with `Phase 131 D-02` cross-reference |
| 7 | _seed_last_events_from_db() method exists on FeaturePipelineExecutor with asyncio.gather | VERIFIED | `feature_pipeline_executor.py` line 145: method defined; line 184: `asyncio.gather()`; uses `regime_features->>` (correct column after A7 wiring bug 3 fix) |
| 8 | intelligence_cache seeded from DB in replay_symbol() before bar event loop | VERIFIED | Lines 1691-1728 of `run_historical_pipeline.py` contain the seed block guarded by `if seed_from_db:`, uses `cur.description` column mapping, `A7 fix` comment, `[A7-seed]` print |
| 9 | --no-seed CLI flag exists and threads through _WorkerArgs | VERIFIED | `--no-seed` at line 2224; `_WorkerArgs.seed_from_db` at line 1908; propagated through `_replay_worker` and all `replay_symbol()` call sites (lines 2655, 2676) |
| 10 | AnchoredVWAPReversion gate ordering fixed: reclaim before state-clearing | VERIFIED | 15 occurrences of `_is_near_zero_exit`; `state.departure_sigma = None` on happy path at line 371, AFTER `make_signal_from_frame` at line 353 and BEFORE `return signal` at line 374 |
| 11 | _assert_backfill_integrity batched by symbol, sys.exit(1) only on actual violations | VERIFIED | `for sym in symbols:` loops at lines 1975 + 2010; `sys.exit(1)` inside `if all_violations:` and `if total_dup_count:` only (lines 2005, 2034); `[INTEGRITY WARN]` on query errors |
| 12 | ctf_score distribution gate >= 85% non-zero (A7 verification) | UNCERTAIN | Current DB shows 87.3% for ts >= 2026-06-14 (matches SUMMARY claim of 87%) but only 80.1% for ts >= 2026-06-11 and 68.1% for ts > 2026-06-10. The gate passes for the most recent data; the broader window includes early cold-start bars where seeding has less prior data. Human judgment needed on whether this satisfies the gate before Phase 133. |

**Score:** 10/12 truths verified (11 code-verified; 1 uncertain on exact gate measurement)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/scripts/run_historical_pipeline.py` | A4 fix + A7 seed + --no-seed + batched integrity | VERIFIED | All changes confirmed in code |
| `src/intelligence/features/smc_context/bocpd_changepoint.py` | A6 fix: vol[-21:-1] | VERIFIED | Line 278 confirmed |
| `production/scripts/lifecycle_replay.py` | B7 fix: COUNT(DISTINCT) in _verify_replay | VERIFIED | Lines 1236-1260 confirmed |
| `src/intelligence/trading/cross_asset_divergence.py` | _CORPUS_EXCLUDABLE=True + live-only comment | VERIFIED | Lines 15-16, 79 confirmed |
| `src/intelligence/pipeline/feature_pipeline_executor.py` | _seed_last_events_from_db() method | VERIFIED | Line 145; uses regime_features correct column |
| `src/intelligence/trading/anchored_vwap_reversion.py` | Gate ordering fix with _is_near_zero_exit | VERIFIED | 15 occurrences, correct ordering at lines 353/371/374 |
| `tests/unit/pipeline/test_feature_pipeline_executor_seed.py` | Unit tests: happy path + cold-start | VERIFIED | File exists, 3 async tests covering seed method |
| `tests/unit/test_anchored_vwap_reversion.py` | Unit tests: near-zero-exit reclaim + no-duplicate | VERIFIED | `TestNearZeroExitReclaim` class with 2+ tests |
| `docs/plans/phase-127-validation-report.md` | Phase 131 section with Verdict line | NOT DONE | T-03 deferred; no Phase 131 section in report (grep confirms 0 matches) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `bocpd_changepoint.py:278` | `vol[-21:-1]` | `np.mean` slice | WIRED | Confirmed: no `vol[-20:]` remains |
| `replay_symbol()` | `all_features['asset_class']` | COALESCE lookup at start of function | WIRED | Lines 1672-1684 (query), 1792-1793 + 1824-1825 (injection both paths) |
| `bar_histories` | `deque(maxlen=800)` | line 1688 | WIRED | Confirmed |
| `_seed_last_events_from_db()` | `self._last_events` | asyncio.gather over (symbol, tf) | WIRED | Line 184 gather; uses `regime_features->>` column |
| `replay_symbol()` | `intelligence_cache[symbol][tf]` | seed block before event loop | WIRED | Lines 1691-1728, `cur.description` column mapping |
| `abs(sigma) < sigma_min early return` | reclaim detection runs first | `_is_near_zero_exit` flag | WIRED | State cleared at line 371 (after signal built at 353) |
| `_assert_backfill_integrity()` | `sys.exit(1)` | only inside `if all_violations:` | WIRED | Lines 2005, 2034 only; not in exception handlers |
| `1-week sample replay` | `signal_events.ctf_score` | DB query | PARTIAL | 87.3% for ts >= 2026-06-14; 80.1% for ts >= 2026-06-11; gate depends on window definition |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| D-06: A4 root cause confirmed before fix | SATISFIED | A4 CONFIRMED comment at lines 1625+1670; diagnostic removed (grep returns empty) |
| D-03: CTF fix — DB seed at replay startup | SATISFIED | `_seed_last_events_from_db()` on FeaturePipelineExecutor + `intelligence_cache` seed in `replay_symbol()`; 5 A7 wiring bugs fixed in 131-07 |
| D-04: Zero-emission plugin fixes | SATISFIED | BOCPD A6 fix applied; bar_histories maxlen 800 applied; AnchoredVWAPReversion gate ordering fixed; CrossAssetDivergence annotated live-only |
| D-05: VXK6/VXM6/ZNM6 symbol coverage via A4 fix | SATISFIED (code) / HUMAN (empirical) | A4 fix covers these via COALESCE(contract_metadata, instruments); empirical verification (plugin coverage query) deferred to Phase 133 |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `run_historical_pipeline.py:1728` | `print(f"  [A7-seed] ...")` inline print statement | INFO | Debug print left from seed implementation; generates stdout noise during replay but does not affect correctness |

### Human Verification Required

#### 1. ctf_score Gate — Exact Window Clarification

**Test:** Run the ctf_score distribution query for the exact window that satisfies the gate:
```sql
SELECT
    CASE WHEN ctf_score > 0.05 THEN 'non_zero' ELSE 'zero_or_null' END AS bucket,
    COUNT(*) as cnt,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM signal_events
WHERE symbol IN ('ESM6','NQM6','SPY')
  AND ts >= '2026-06-14'
  AND ctf_score IS NOT NULL
GROUP BY 1 ORDER BY 1;
```
**Expected:** non_zero pct >= 85.0% (current result: 87.3% for this window — PASSES)

**Why human:** The gate in the plan uses `ts > '2026-06-10'` but this includes the unseeded control rows (2026-06-10) and cold-start rows from earlier in the window (2026-06-11 through 2026-06-12), pulling the overall rate to 68.1%. The SUMMARY's 87% figure matches the most recent 3 days of the window (2026-06-14 to 2026-06-17). A human should confirm whether the gate is considered passed (code fix is proven to work; early dates are expected cold-start) or whether a clean 1-week re-run should be done before Phase 133 begins.

#### 2. 35/35 Eligible Plugin Firing Check (T-02, Deferred)

**Test:** Run a 2-week replay across all active symbols and query:
```sql
SELECT setup_plugin, COUNT(*) as signals
FROM signal_events
WHERE ts > '2026-06-03'
GROUP BY setup_plugin
ORDER BY signals DESC;
```
**Expected:** >= 35 distinct `setup_plugin` values with COUNT > 0. `trad_CrossAssetDivergence` at 0 is acceptable (_CORPUS_EXCLUDABLE=True). Any other plugin at 0 is a bug requiring investigation before Phase 133.

**Why human:** T-02 of plan 131-07 was not executed due to session quota exhaustion. This is a mandatory pre-Phase 133 gate per the CONTEXT verification gate ("35 of 35 eligible plugins emitting signals"). Must be run.

#### 3. Validation Report Append (T-03, Deferred)

**Test:** Append the Phase 131 verification results to `docs/plans/phase-127-validation-report.md` with a section covering ctf_score gate result, plugin coverage, symbol coverage (VXK6/VXM6/ZNM6/EURUSD), and an explicit Verdict line.

**Expected:** The report ends with a "Phase 131 Verification" section with "Verdict: PASS" and "Phase 133: UNBLOCKED" (assuming the plugin firing check passes).

**Why human:** T-03 was deferred due to session quota exhaustion. This is documentation, not a code gate, but it is part of the formal verification gate definition in 131-07 PLAN.

### Gaps Summary

No code gaps found. All code fixes are in place and unit tests are green (4761 passed, 37 skipped). The three human-verification items are operational checks that require a replay run (T-02) or human judgment on gate interpretation (ctf_score window), not code fixes.

The critical path for Phase 133 authorization is T-02 (35-plugin firing check). This is the only item that could surface a previously unknown zero-emission plugin requiring a code fix before Phase 133 begins.

---

_Verified: 2026-06-17_
_Verifier: Claude (gsd-verifier)_
