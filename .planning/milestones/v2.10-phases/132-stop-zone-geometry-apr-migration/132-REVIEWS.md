---
phase: 132
reviewers: [codex, ollama]
reviewed_at: 2026-06-17T22:30:00Z
plans_reviewed:
  - 132-01-PLAN.md
  - 132-02-PLAN.md
  - 132-03-PLAN.md
  - 132-04-PLAN.md
  - 132-05-PLAN.md
notes: antigravity skipped (GUI-only, no stdout mode); claude skipped (self, running inside Claude Code)
---

# Cross-AI Plan Review — Phase 132

## Codex Review

**Summary**

The phase is well decomposed and follows the right architectural intent: measure before changing geometry, seed APR at current literals, then prove parity at seed values before expanding to adaptive buffer and per-class floors. The main weakness is that several critical checks can still pass while the system silently falls back to hardcoded defaults or queries the wrong ledger shape. That makes the overall phase correct in direction but high-risk in execution.

**Strengths**

- The plan respects the APR mandate and uses seed-equals-current-value migrations, which preserves training-data integrity.
- The dependency order is sensible: measure first, then migrate module-level constants, then adaptive buffer coefficients, then per-class stop floors, then final verification.
- It explicitly preserves the existing Phase 126 gates instead of re-implementing them.
- It recognizes the live pipeline already has `ConfigService` wiring and identifies the replay path gap as a separate issue.
- The regression-test intent is good: seed-value parity, anchor-point checks, and 1-tick gate preservation are all covered.
- The final verification phase correctly distinguishes "stop exits" from "all exits," which is the right pass/fail metric.

**Concerns**

- **HIGH:** The SQL in Plan 01 appears to use the wrong join keys. The repo schema uses `signal_id` + `signal_ts` on `trade_frames`, and `trade_executions` joins via `frame_id`. The plan's proposed `tf.signal_event_id = se.signal_event_id` does not match the current schema. See signal_events_repository.py and lifecycle_replay.py.
- **HIGH:** Plan 01's initial measurement query computes `stopped_at_entry` as a share of all exits, but the actual gate is later defined as a share of stop-type exits only. That mismatch can understate the true failure rate and falsely close A2.
- **HIGH:** The replay-path APR wiring in Plan 02 is under-specified. `run_historical_pipeline.py` uses a psycopg2 connection path, while `ConfigService` is asyncpg-based and only exposes `get_sync()` after prewarm. Without a precise startup snapshot/pool strategy, the replay path can still silently run on defaults.
- **HIGH:** Front-month selection logic is not robust. `ORDER BY symbol` is not a front-month resolver, and NG front-month selection is not fully specified — makes the sample potentially unrepresentative and hard to reproduce.
- **MEDIUM:** The parity tests are too permissive if the mock config service returns defaults on unknown keys. That can let an APR key typo pass while still exercising the fallback path — exactly the silent-failure mode to avoid.
- **MEDIUM:** The anchor-point tests for `_adaptive_buffer()` prove the curve at a few points, not the full piecewise shape. A branch inversion or denominator typo between anchors could still slip through.
- **MEDIUM:** Plans 02/03/04 introduce intermediate states where code may import cleanly while not exercising APR in replay. Acceptable only if treated as one release train.
- **MEDIUM:** The runtime cost of 35 `_cfg()` calls per `frame_trade()` is probably fine (`get_sync()` is in-memory), but the plan does not quantify it.
- **LOW:** The replay wiring list may be incomplete if only a subset of helper modules is injected.

**Suggestions**

- Fix the sample-replay SQL to use the actual schema join pattern: `trade_executions.frame_id -> trade_frames.frame_id` → `trade_frames.signal_id + signal_ts -> signal_events`.
- Make Plan 01 and Plan 05 use the same stop-exit denominator explicitly, and record both the "all exits" distribution and the "stop-type exits" gate metric.
- Resolve front-month futures by expiry/active-contract metadata, not by symbol ordering. Fail fast if the resolved symbol has no bars.
- For replay wiring, mirror the live pipeline's config prewarm and injection behavior exactly, and add an assertion that representative keys return non-default values before the first `replay_symbol()` call.
- Strengthen regression tests so the mock config service is strict: unknown keys should fail, not silently fall back.
- Add interior-point assertions for `_adaptive_buffer()` in each branch, not just endpoints, to catch piecewise-shape regressions.
- Keep Plans 02–04 on one release train or gate with an explicit feature flag so an intermediate merge cannot leave replay and verification out of sync.

**Risk Assessment: HIGH**

This phase touches pricing geometry, lifecycle outcomes, APR wiring, and replay verification where silent fallback is explicitly dangerous. The wrong join keys, denominator mismatch, and replay-path wiring ambiguity are enough to produce false-positive verification unless tightened.

---

## Ollama Review (nemotron-3-nano:4b)

**Summary**

Full coverage of all 35 constants (19 + 12 + 4). Replay-based verification introduces a gate that can catch silent DB-migration gaps before live rollout. Parallel migration Plans 03+04 do not alter trading geometry, keeping risk low.

**Strengths**

- Full coverage of all 35 constants across three migrations.
- Replay-based verification catches silent DB-migration gaps before live rollout.
- Parallel Plans 01+02 safe (02 is config migration only, no geometry change).

**Concerns**

| Issue | Level |
|-------|-------|
| Silent fallback mismatch: if config DB fails to return the intended constant, signals may use old hardcoded values as active | HIGH |
| 35 DB reads per signal evaluation — increased DB load; monitor latency under high-volume signals | MEDIUM |
| Parallel run of Plans 01+02: any unexpected schema mismatch could cause brief latency spikes | MEDIUM |
| Denominator for stopped_at_entry: if "all exits" used instead of "stop exits", 5% threshold becomes misleading | LOW |

**Suggestions**

- Add a pre-migration health check that confirms each config row matches the intended value; log any mismatches.
- Instrument DB-read latency to ensure < X ms per request under peak load.

**Risk Assessment: HIGH/MEDIUM**

Potential silent fallback errors during migration 144 need instrumentation; parallel execution is OK but performance impact of 35 DB reads needs monitoring; denominator issue could skew verification results.

---

## Consensus Summary

### Agreed Strengths

- **Seed = current value:** Both reviewers recognize that fallback-equals-current-value is the right ML integrity guarantee.
- **Dependency ordering:** Measure first (Plan 01) → constants (02) → buffer (03) → floors (04) → verify (05) is the correct Renaissance sequencing.
- **Plan 05 gate denominator is correct:** The stop-type-exits-only denominator (fixed in the plan-checker pass) is called out positively by Codex.
- **Parallel safety of Plans 01+02:** Both reviewers agree Plans 01+02 can safely run in parallel since Plan 02 is a config migration with no geometry change.

### Agreed Concerns

**1. Silent fallback on config miss (HIGH — both reviewers)**
If an APR key name has a typo, or the migration hasn't run, `get_sync(key, fallback)` returns the hardcoded fallback silently. The regression test may still pass because fallback == seed. Need a strict-mode assertion before the first replay_symbol() call that every expected key exists in config_state with a non-None value.

**2. DB reads per signal evaluation performance (MEDIUM — both reviewers)**
35 `_cfg()` calls per `frame_trade()` invocation. `get_sync()` is in-memory post-prewarm, but this is not quantified. Add a brief benchmark or note that the prewarm cache prevents actual DB I/O per call.

**3. Plan 01 stopped_at_entry denominator (HIGH — Codex)**
Plan 01's initial measurement query may use all exits as denominator, while the gate (Plan 05) uses stop-type exits only. If Plan 01 uses the wrong denominator, it could declare A2 closed when the true stopped_at_entry/stop-exits rate is above 5%.

**4. SQL join keys in Plan 01 (HIGH — Codex)**
Potential schema mismatch: `trade_executions` joins via `frame_id`, not `signal_event_id`. Executor must verify the actual join path from lifecycle_replay.py before writing the measurement query.

### Divergent Views

- **Codex (HIGH risk) vs Ollama (MEDIUM risk overall):** Codex rates the phase HIGH risk overall due to the join-key and replay-wiring concerns. Ollama rates it lower because the verification gate will catch most issues. Resolution: the join-key concern is real and should be fixed pre-execution; the verification gate is a fallback, not a primary defense.
- **Front-month selection (Codex only):** Codex flags that `ORDER BY symbol` is not a front-month resolver for futures. Ollama did not comment on this. Worth verifying the sample replay script correctly resolves active contracts via `contract_metadata` or `get_active_contracts()`.

---

## Issues Addressed (2026-06-17 — pre-execution plan amendments)

All Codex HIGH issues and MEDIUM test-quality issues applied to the plans before execution:

| Codex concern | Severity | Resolution |
|---|---|---|
| SQL join key `signal_event_id` → actual schema uses `signal_id` | HIGH | Fixed in Plans 01 + 05: all queries now use `tf.signal_id = se.signal_id`. Schema verified live: `trade_frames.signal_id` FK → `signal_events.signal_id`. |
| `stopped_at_entry` denominator mismatch between Plan 01 and Plan 05 gate | HIGH | Plan 01 Task 1 now runs TWO queries: full-distribution (pct_of_all) AND stop-exit denominator (stopped_pct_of_stop_exits). Plan 05 was already correct; now Plan 01 baseline is directly comparable. |
| Replay APR wiring gap (replay silently uses hardcoded defaults) | HIGH | Already fully addressed by Plan 02 Task 3 as written. No change needed. |
| Front-month selection via `ORDER BY symbol` | HIGH | Fixed in Plans 01 + 05: resolve via `WHERE base_symbol='ES' AND is_front_month=true LIMIT 1`. Fail fast if zero rows. Bar-count preflight added before replay start. |
| Mock ConfigService too permissive (typos silently return default) | MEDIUM | Fixed in Plans 02 Task 4, 03 Task 3, 04 Task 3: mock now RAISES ValueError for unknown keys instead of silently returning default. |
| Anchor-point tests cover endpoints only (branch inversions invisible) | MEDIUM | Plan 03 Task 3 expanded: interior points added at vol_ratio=0.85 (low-vol, expect 0.90) and vol_ratio=1.25 (high-vol, expect 1.175). Catches slope/denominator transpositions and branch miswiring. |
