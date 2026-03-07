---
phase: 14-feedback-loop
verified: 2026-03-06T20:00:00Z
status: gaps_found
score: 5/6 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 5/6
  gaps_closed: []
  gaps_remaining:
    - "Outperforming setups rank higher than underperforming setups in the aggregator"
  regressions: []
gaps:
  - truth: "The signal aggregator reads setup performance weights at startup and outperforming setups rank higher than underperforming setups in aggregation"
    status: failed
    reason: "Plan 04's multiplier formula inversion (0.5 + ((n-1-rank)/n)) is insufficient to close this gap. The structural problem is that SETUP_PRIORITY assigns the highest composite_rank (=worst starting position) to the lowest-priority setups. The perf multiplier cannot overcome this handicap in the general n>=3 case. A best-Sharpe setup with composite_rank=5 and multiplier=0.5 gets adjusted_rank=2.5. A worst-Sharpe setup with composite_rank=1 and multiplier=1.5 gets adjusted_rank=1.5. The worst Sharpe still ranks first. Only in the n=2 case where the test manually assigns extreme weights (0.5 / 1.5) does the inversion appear to work — and only by coincidence of the specific composite_ranks chosen. The test uses manually crafted weights, not actual _compute_perf_multipliers output, so it does not expose the structural problem."
    artifacts:
      - path: "src/intelligence/trading/aggregator.py"
        issue: "_build_all_ranked() multiplies composite_rank (1-based, lower=better) by perf_multiplier. Best-Sharpe setups (multiplier=0.5) that happen to have low SETUP_PRIORITY receive the highest composite_rank numbers, so even at 0.5x they produce adjusted_ranks larger than high-priority worst-Sharpe setups at 1.5x. Example with all 5 setups: LSR (worst Sharpe, multiplier=1.5, composite_rank=1) adjusted_rank=1.5 beats MeanReversion (best Sharpe, multiplier=0.5, composite_rank=5) adjusted_rank=2.5."
      - path: "src/intelligence/setup_performance_updater.py"
        issue: "Formula inversion (0.5 + ((n-1-rank)/n)) is correct in isolation — best Sharpe gets lowest multiplier. But multiplying a low multiplier by a high composite_rank still produces a large adjusted_rank that loses under ascending sort."
      - path: "tests/unit/intelligence/test_aggregator_perf.py"
        issue: "test_build_all_ranked_outperformer_promoted uses manually crafted weights (MeanReversion=0.5, LSR=1.5) in a 2-plugin scenario where composite_ranks happen to be 2 and 1 respectively, so 2*0.5=1.0 < 1*1.5=1.5. This passes but does not reflect what _compute_perf_multipliers actually produces for these setups, and does not cover the n>=3 case where the structural problem is apparent."
    missing:
      - "The adjusted_rank formula must be redesigned so that perf_multiplier actually determines rank, independent of SETUP_PRIORITY. Options: (A) Replace composite_rank with a fixed base rank (e.g. 1.0 for all setups, so adjusted_rank = perf_multiplier directly), then use SETUP_PRIORITY only as a tiebreaker. (B) Invert composite_rank role: assign composite_rank from SETUP_PRIORITY ascending (so lower-priority setups get lower composite_rank numbers), then best-Sharpe (multiplier=0.5) on a low-priority setup yields the smallest adjusted_rank. (C) Use perf_multiplier alone as the rank key when weights are present, falling back to SETUP_PRIORITY when absent. Any fix must be validated end-to-end via _compute_perf_multipliers output into _build_all_ranked, not manually crafted weights."
      - "Add an integration test: call _compute_perf_multipliers() with explicit sharpe stats, feed the result into _build_all_ranked(), and assert the best-Sharpe setup is result[0] regardless of its SETUP_PRIORITY position."
---

# Phase 14: Feedback Loop Verification Report

**Phase Goal:** Setup performance data flows from resolved signal outcomes into the aggregator's ranking weights automatically — no manual intervention required

**Verified:** 2026-03-06T20:00:00Z
**Status:** gaps_found (re-verification after Plan 04 gap closure attempt)
**Re-verification:** Yes — after Plan 04 gap closure attempt for FEED-03

## Goal Achievement

### Observable Truths (from Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `setup_performance` table exists with correct columns, populated daily by scheduled job with win_rate, avg_pnl_r, sample_size, Sharpe per setup from rolling 30-day window | ✓ VERIFIED | `production/migrations/021_setup_performance_table.sql` has all required columns. `weight_updater.py __main__` calls `run_setup_performance_update()` in same nightly pass as CIS weights. |
| 2 | Setup with fewer than 30 resolved signals has no performance weight applied — aggregator uses baseline weights | ✓ VERIFIED | `compute_setup_performance()` returns empty dict when `n < MIN_SAMPLE_SIZE (30)`. `run_setup_performance_update()` only upserts and writes Redis when `stats` is non-empty. Absent Redis key → `_load_perf_weights()` is a no-op leaving `_perf_weights = {}`. |
| 3 | Signal aggregator reads setup performance weights at startup and outperforming setups rank higher | ✗ FAILED | Plan 04's formula inversion is insufficient — structural design flaw remains. See Gaps section. |

**Score:** 5/6 must-haves verified (infrastructure fully correct, goal semantic still wrong)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/021_setup_performance_table.sql` | DDL with win_rate, avg_pnl_r, sample_size, sharpe_ratio, nullable timeframe/regime | ✓ VERIFIED | Exact columns present. PRIMARY KEY (setup_plugin). |
| `src/intelligence/setup_performance_updater.py` | `compute_setup_performance()` with rolling 30-day window, n>=30 gate; inverted `_compute_perf_multipliers()` | ✓ VERIFIED | 196 lines. Gate at `MIN_SAMPLE_SIZE = 30`. Formula at line 118: `0.5 + ((n - 1 - rank) / n)` — best Sharpe gets multiplier=0.5. Docstring updated. |
| `src/core/stream_keys.py` | `setup_performance_weights_cache(env_prefix)` | ✓ VERIFIED | Returns `f"{env_prefix}setup_performance:weights"` at line 83. |
| `src/intelligence/weight_updater.py` | `__main__` calls `run_setup_performance_update()` | ✓ VERIFIED | Lines 237-252 call `run_setup_performance_update(db, redis_client, env_prefix)` in same asyncio loop. |
| `src/intelligence/trading/aggregator.py` | `_build_all_ranked()` with `perf_weights` param, correct sort semantics | ✗ SEMANTIC BUG | Ascending sort + composite_rank multiplication: best-Sharpe setups with low SETUP_PRIORITY get high composite_rank numbers, so even at 0.5x multiplier they produce adjusted_ranks larger than worst-Sharpe setups with high SETUP_PRIORITY at 1.5x. LSR (worst Sharpe, composite_rank=1, 1.5x) = 1.5; MeanReversion (best Sharpe, composite_rank=5, 0.5x) = 2.5 — underperformer wins. |
| `services/signal_generator_service.py` | `_perf_weights`, `_load_perf_weights()`, `_perf_weights_refresh_loop()`, startup load, passes to `aggregate()` | ✓ VERIFIED | All 4 elements present and wired. `self._perf_weights = {}` at line 372, startup load at line 900, refresh loop at 904, kwarg at 579. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `signal_generator._process_bar()` | `aggregator.aggregate()` | `perf_weights=self._perf_weights` | ✓ WIRED | Line 579: `perf_weights=self._perf_weights` |
| `signal_generator._load_perf_weights()` | Redis `setup_performance:weights` key | `redis_client.get(setup_performance_weights_cache(env_prefix))` | ✓ WIRED | Uses `setup_performance_weights_cache(self.env_prefix)` |
| `aggregator._build_all_ranked()` | `composite_rank * perf_multiplier` | `adjusted_rank` computation + ascending sort | ✗ BROKEN SEMANTICS | Formula is present and attached to every signal dict; ascending sort direction is correct in isolation; but the composite_rank values assigned by SETUP_PRIORITY invert the intended outcome — best-Sharpe setups with low SETUP_PRIORITY receive the highest composite_rank numbers and lose the sort despite lowest multiplier |
| `weight_updater.__main__` | `run_setup_performance_update()` | same asyncio loop | ✓ WIRED | Lines 237-252 |
| `run_setup_performance_update()` | Redis `setup_performance:weights` | `redis_client.set(key, json.dumps(perf_weights))` | ✓ WIRED | Line 188 in setup_performance_updater.py |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| FEED-01 | 14-01, 14-02 | Scheduled job computes win_rate/avg_pnl_r/sample_size/Sharpe per setup, writes to setup_performance table | ✓ SATISFIED | `run_setup_performance_update()` queries signal_ledger, upserts table, writes Redis. `weight_updater __main__` extended. |
| FEED-02 | 14-01, 14-02 | Promotion gate: n<30 → no weight applied | ✓ SATISFIED | `compute_setup_performance()` excludes setups with n<MIN_SAMPLE_SIZE. Tests pass, including boundary at n=30. |
| FEED-03 | 14-01, 14-03, 14-04 | Aggregator reads perf weights at startup; outperforming setups rank higher | ✗ BLOCKED | Plan 04 fixed the multiplier formula direction but did not close the structural gap. The design of adjusted_rank = composite_rank * perf_multiplier fails when SETUP_PRIORITY assigns high composite_rank numbers to low-priority setups that happen to be the best Sharpe performers. |

No orphaned requirements found. FEED-01, FEED-02, FEED-03 are all assigned to Phase 14 plans.

### Anti-Patterns Found

| File | Lines | Pattern | Severity | Impact |
|------|-------|---------|----------|--------|
| `src/intelligence/trading/aggregator.py` | 379-392 | `adjusted_rank = composite_rank * perf_multiplier` with ascending sort — best-Sharpe setups with low SETUP_PRIORITY still rank below worst-Sharpe setups with high SETUP_PRIORITY | 🛑 Blocker | Goal not achieved: outperforming setups do NOT rank higher in the general case. LSR (worst Sharpe, composite_rank=1, multiplier=1.5, adjusted_rank=1.5) beats MeanReversion (best Sharpe, composite_rank=5, multiplier=0.5, adjusted_rank=2.5). |
| `tests/unit/intelligence/test_aggregator_perf.py` | 100-121 | `test_build_all_ranked_outperformer_promoted` uses manually crafted weights in a 2-plugin scenario where the math accidentally works; does not call `_compute_perf_multipliers()` and does not test n>=3 case where the bug is exposed | ⚠️ Warning | Tests pass and appear to validate the goal but do not cover the failure scenario. |

### Detailed Analysis: Structural Design Flaw

Plan 04 correctly inverted the multiplier formula. The formula `0.5 + ((n-1-rank)/n)` now correctly assigns multiplier=0.5 to the best-Sharpe setup. This part is verified.

The unresolved problem is in the `adjusted_rank = composite_rank * perf_multiplier` formula in `_build_all_ranked()`.

SETUP_PRIORITY values are: MeanReversion=1, SqueezeExpansion=2, TrendFollowing=3, MTFAlignment=4, LiquiditySweepReclaim=5. The aggregator sorts by SETUP_PRIORITY descending to assign composite_rank, so composite_rank=1 goes to LiquiditySweepReclaim (highest priority) and composite_rank=5 goes to MeanReversion (lowest priority).

If MeanReversion has the best Sharpe and LiquiditySweepReclaim has the worst Sharpe (a realistic scenario — mean reversion performs best in ranging markets while trend-following setups like LSR may underperform):

| Setup | SETUP_PRIORITY | composite_rank | perf_multiplier (n=5) | adjusted_rank |
|-------|---------------|----------------|----------------------|---------------|
| LiquiditySweepReclaim (worst Sharpe) | 5 | 1 | 1.5 | 1.5 |
| MTFAlignment | 4 | 2 | 1.25 | 2.5 |
| MeanReversion (best Sharpe) | 1 | 5 | 0.5 | 2.5 |

LiquiditySweepReclaim ranks first despite worst Sharpe. The goal is not achieved.

**Why the test passes but the goal fails:** `test_build_all_ranked_outperformer_promoted` uses two plugins (MeanReversion and LiquiditySweepReclaim) with manually assigned weights (0.5 and 1.5). In this case, composite_ranks are 2 and 1 (only 2 plugins). The test assertions hold: 2×0.5=1.0 < 1×1.5=1.5. But this test does not call `_compute_perf_multipliers()` — it bypasses the actual data flow. And it does not reproduce the case where all 5 plugins are present and the worst-Sharpe plugin has composite_rank=1 (which is what happens in production when all setups fire).

**What fix is needed:** The `adjusted_rank` formula must be redesigned so that perf_multiplier is the primary ranking key, not a modifier of composite_rank. One approach: use a fixed base (e.g. all setups start at adjusted_rank = perf_multiplier), then break ties by composite_rank. Another approach: assign composite_rank from SETUP_PRIORITY ascending (so lower SETUP_PRIORITY = lower composite_rank) so the multiplication goes in the right direction. The selected fix must be tested with the actual `_compute_perf_multipliers()` output, not manually crafted weights.

### Human Verification Required

None — the structural bug is fully verifiable programmatically, and the analysis above confirms it.

### Gaps Summary

FEED-01 and FEED-02 remain fully satisfied. The feedback loop infrastructure (migration, compute function, promotion gate, nightly job, Redis write, service load, refresh loop, aggregate kwarg) is correct and complete.

FEED-03 remains open after Plan 04. The multiplier formula was correctly inverted — best Sharpe now gets multiplier=0.5, worst gets ~1.5. However, the `adjusted_rank = composite_rank * perf_multiplier` design fails because SETUP_PRIORITY assigns the largest composite_rank numbers to the lowest-priority setups. A setup that is both low-priority (high composite_rank) and a strong performer (low multiplier) still produces a large adjusted_rank that loses under ascending sort. The goal — "outperforming setups rank higher" — is not achieved in the general case.

The existing tests pass because they use manually crafted weights in restricted scenarios where the math accidentally works, not because the end-to-end pipeline is correct.

---

_Verified: 2026-03-06T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
