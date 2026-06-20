# Phase 127 RESEARCH.md

## Purpose

Resolve methodology, schema, and execution concerns for Clean Replay + Validation. This is the empirical validation that the v2.10 architecture changes (Phases 123-130) achieved their goals: correct signal universe, full APR externalization, clean 3-table schema, and ML-training-quality replay data.

## Context

**Phase 127 deferred from 121, then 126, then placed after 128-130** so that clean replay lands directly in the final 3-table schema with counterfactual_pnl_r populated from day one. This avoids a second replay and produces usable ML training data immediately.

**Architecture changes completed (v2.10):**
- Phase 123: ECL boundary restoration - removed emission suppressors
- Phase 124: Signal universe integrity - cold-start hardening
- Phase 125: APR full migration - all 51 constants externalized
- Phase 126: Signal universe hardening - confluence wiring + zone mechanics
- Phase 128: 3-table schema ADR - signal_events/trade_frames/trade_executions
- Phase 129: Database migration - schema applied
- Phase 130: Script rewriting - all write paths migrated

**Replay Goal:** Run full historical replay with --warmup on the corrected pipeline to produce clean ML training corpus.

## Research Issues

### Issue 1: Methodology Conflict - Welch's t-test

**ROADMAP SC-04:** "Validation report uses correct methodology — **no cross-population Welch's t-test**"

**121-02-PLAN Task 1:** Includes Welch's t-test for before/after pnl_r comparison

**Resolution:**
- ROADMAP is correct. Welch's t-test on before/after pnl_r is INVALID because the populations are NOT exchangeable (different sample composition = different statistical properties). The exact before/after counts are captured at runtime by the before-snapshot (do NOT quote stale 7.85M/4M estimates - they are wrong; current corpus is ~1.44M and the real number is whatever the snapshot records).
- **Remove Welch's t-test from validation report.**
- Replace with outcome-free measures (see also Issues 4, 7, 8):
  - Signal volume delta (before-snapshot vs post-replay count - objective)
  - CTF coverage as feature (context_features coverage > 99% per ROADMAP SC-02 - valid hard gate, it is data-completeness not quality)
  - Emission fire-rate DISTRIBUTION per setup (descriptive only - Issue 7; NOT a `< 3%` gate)
  - NOTE: bootstrap 95% CI on calibration_corr is NOT valid this phase - it requires a PnL outcome target, which the replay corpus lacks (Issue 4). It moves to v2.11.

**Evidence:** ROADMAP explicitly lists correct measures: "signal volume delta, CTF as feature, firing rates, null distribution" - Welch's t-test is not among them. "Firing rates" here means the descriptive emission distribution and the structural leak-closed check, not an arbitrary pass/fail threshold.

### Issue 2: Schema Migration - 3-Table Adaptation Required

**Problem:** 121-02-PLAN references old schema (signal_ledger + signal_outcomes), but Phase 130 dropped those tables.

**Resolution:**
- Adapt all queries to 3-table schema:
  - signal_events (detection layer): raw_confidence, context_features, ctf_*, status, etc.
  - trade_frames (hypothesis layer): entry_price, stop_price, target_price, counterfactual_pnl_r, frame_details JSONB
  - trade_executions (execution layer): actual_pnl_r, actual_fill_price, exit_reason
  - signal_ledger (JOIN view): legacy compatibility, queries this view

**Query adaptations:**
1. **Signal counts:** `SELECT COUNT(*) FROM signal_events` (no longer signal_ledger)
2. **Selection metrics:** `signal_ledger` JOIN still works (view exists)
3. **stopped_at_entry:** Query trade_executions where `exit_reason = 'stopped_at_entry'` (NOT signal_outcomes)
4. **orphan_ledger_rows:** LEFT JOIN signal_events LEFT JOIN trade_frames (NOT signal_outcomes)
5. **Calibration pairs:** 
   - Shadow: `(cis_score, (counterfactual_pnl_r > 0)::int)` from signal_events + trade_frames
   - Non-shadow: `(raw_confidence, was_selected)` from signal_ledger view

### Issue 3: Before-Snapshot Baseline Compatibility

**Problem:** `phase-121-before-snapshot.json` was captured on OLD schema (signal_ledger + signal_outcomes). Its structure doesn't match 3-table schema.

**Resolution:**
- **Option A:** Regenerate before-snapshot using 3-table schema queries on pre-replay data
- **Option B:** Adapt report script to map old baseline keys to new schema

**Recommendation:** Option A - regenerate baseline. Reasons:
- Renaissance would demand fresh measurement over backward compatibility hacks
- Phase 130 changes are structural - old baseline columns don't map cleanly
- Ensures apples-to-apples comparison on same schema foundation

**Execution:** Run before-snapshot query against signal_ledger view (which exists in both schemas) before triggering clean replay.

### Issue 4: No PnL Outcome Target Exists In The Replay Corpus (load-bearing)

**Problem:** Calibration correlation, calibration retrain, and edge measurement all require a PnL outcome variable. NEITHER candidate exists in the Phase 127 replay corpus:

- `counterfactual_pnl_r` (trade_frames): NULL by design. `feature_replay.py:467` and `run_historical_pipeline.py:993` both carry the comment `counterfactual_pnl_r = NULL (CounterfactualTracker v2.11)`. Verified against the current 1,443,584-row corpus: 0 non-null.
- `actual_pnl_r` (trade_executions): table is EMPTY. There is no `INSERT INTO trade_executions` anywhere in `run_historical_pipeline.py`, `feature_replay.py`, or services - the replay emits signals and frames but never executes trades. Verified: trade_executions currently has 0 rows vs 1.44M signal_events.

**Why the earlier "use actual_pnl_r" resolution (carried over from a prior draft) is WRONG:** `actual_pnl_r` lives on `trade_executions`, which the replay does not populate. It is not a fallback; it is absent. Substituting it for `counterfactual_pnl_r` produces a calibration query that joins against an empty table and yields n<30 for every setup - empty columns dressed up as evidence. That is precisely the silent-wrong-answer failure mode the principles forbid.

**Resolution:**
- Calibration correlation and bootstrap CI are REMOVED from the Plan 02 report entirely (not "demoted to observational" - removed). Emitting empty/NULL calibration cells implies a measurement was made; it was not.
- Calibration retrain (Plan 03) is DEFERRED to v2.11. Plan 03 records the blocker via a pre-flight check and does NOT retrain on NULL/empty targets.
- Signal EDGE (the actual success criterion) is explicitly deferred to v2.11 in the report and in RCA Part VI. Phase 127 verifies plumbing and structure only.
- The ML training corpus produced here is structurally clean (correct schema, full CTF coverage, deterministic) and becomes ML-ready the moment v2.11 populates `counterfactual_pnl_r` - no second replay needed.

### Issue 7: Firing-Rate Metric Definition (emission frequency, not selection rate)

**Problem:** "Firing rate" is ambiguous. The plans (and the 121-02 spec) loosely equated it with `selected/total_signals` (a selection ratio). That is wrong.

**Resolution (verified against Phase 124-07 D6 report):** Firing rate = EMISSION FREQUENCY:
```
fire_rate_pct = 100.0 * COUNT(signal_events WHERE setup_plugin=X) / COUNT(intelligence_features bar-instances over the replay window)
```
- Phase 124-07 measured the 5 over-firing plugins at 0.12-3.08% (down from the pre-fix onset_guard leak of 15-30% of bars).
- Denominator is `intelligence_features` (the bar universe), which the replay's warmup pass also rebuilds - so post-clean-replay the ratio is well-defined.
- This is NOT `selected/total_signals`. Selection ratio measures the activation policy among emitted signals; emission fire rate measures how often the plugin fires at all. They answer different questions.

**Important (per operator direction): fire rate is MEASURED AND REPORTED, NOT GATED.** A hard "< 3%" pass/fail verdict is a proxy-as-target error. A valid signal firing at 10% with edge is good; a 0.5% signal without edge is not. The single structural claim fire rate supports in Phase 127: the onset_guard leak (15-30%/bar) is closed - and that is verified by comparison to the real buggy baseline, not to an arbitrary threshold. Edge itself is deferred (Issue 4).

### Issue 8: `stopped_at_entry` Is Not Measurable In Replay

**Problem:** `stopped_at_entry` is an execution-layer outcome (`trade_executions.exit_reason`). Replay does not populate `trade_executions` (Issue 4), so this count is structurally 0 and carries no information about whether Phase 126's zone mechanics suppress stopped-at-entry leaks.

**Resolution:** Do NOT report "0 stopped_at_entry" as evidence of success - that is a false positive (the metric is unmeasurable, not zero-because-fixed). Plan 02 records it explicitly as "not measurable in replay; requires executions (live trading or an execution-simulating replay path)."

### Issue 9: `trade_executions` Join Key Is `frame_id`, Not `signal_id`

**Problem:** `trade_executions` has columns `(execution_id, frame_id, actual_pnl_r, exit_reason, ...)` - NO `signal_id`. Several draft queries joined `signal_events` directly to `trade_executions` on `signal_id`; those raise `column does not exist` at runtime.

**Resolution:** The correct join chain for any execution-layer data:
```sql
signal_events se
  JOIN trade_frames tf ON tf.signal_id = se.signal_id
  JOIN trade_executions te ON te.frame_id = tf.frame_id
```
Moot for Phase 127 outcome queries (table is empty - Issue 4), but must be correct if/when execution-layer metrics are reintroduced.

### Issue 5: Replay Determinism

**Renaissance Requirement:** Replay must be reproducible. Same inputs → same outputs.

**Verification:**
- uuid5 frame_id ensures deterministic frame IDs
- G0 grouping ensures 1 signal_events → N trade_frames relationship
- No random sampling in replay pipeline
- All sources deterministic: market_data_ohlcv, intelligence_features, plugin logic

**Test:** Re-run replay on same data → verify row counts identical, signal_ids identical.

### Issue 6: Cold-Start Handling

**Problem:** Phase 124 cold-start hardening means NULL context_features on first signals. ROADMAP SC-02 requires > 99% coverage for non-cold-start.

**Resolution:**
- Distinguish cold-start signals (context_features IS NULL or '{}'::jsonb)
- Compute coverage on non-cold-start subset only
- Report cold-start count separately (not penalized)

## Adapted Success Criteria

Per ROADMAP Phase 127, corrected for methodology conflicts and the no-outcome-data finding:

**Plumbing + structure (verifiable this phase):**
1. Clean replay completes without errors, deterministically, zero orphans
2. `context_features` coverage > 99% for non-cold-start signals (data-completeness gate)
3. Emission fire rate DISTRIBUTION measured and reported per setup_plugin (descriptive, NOT gated); onset_guard leak confirmed closed vs the real 15-30%/bar buggy baseline
4. Validation report uses correct methodology: signal volume delta, CTF coverage, fire-rate distribution. NO Welch's t-test. NO calibration correlation. NO arbitrary fire-rate pass/fail gate.

**Deferred to v2.11 (explicitly named, not substituted):**
5. Signal EDGE / predictive value - the actual success criterion; needs `counterfactual_pnl_r`
6. Calibration retrain - needs the same outcome target
7. `stopped_at_entry` measurement - needs executions

8. RCA Part VI updated with MEASURED plumbing/structural values and an explicit "edge unmeasured this phase" acknowledgement

## Proposed Tasks

1. **Regenerate before-snapshot baseline** (3-table schema compatible)
2. **Execute clean replay** with --warmup on full historical corpus
3. **Create phase_127_report.py** on 3-table schema: volume delta, CTF coverage, emission fire-rate distribution, integrity gates. NO Welch's, NO calibration.
4. **Generate validation report** with corrected methodology (outcome-free measures only)
5. **Verify data integrity:** no orphans, >99% context_features coverage
6. **Update RCA Part VI** with measured values + edge-deferred acknowledgement
7. **Record calibration deferral** (Plan 03 pre-flight blocks on NULL/empty target; surface as v2.11 dependency - do NOT retrain)

## Resolved Questions

1. **Historical replay scope:** Full corpus. DECIDED: `--include-rolled --timeframes 1m,5m,15m,1h,4h,1d` (all symbols, all TFs, full roll-chain). See Plan 01 Task 2.

2. **--warmup behavior:** VERIFIED in code (not guessed). `--warmup` is a real flag (`run_historical_pipeline.py:1991`); it triggers a two-pass replay (Pass 1 I1-I6 builds the per-symbol I6 cache, Pass 2 I1-I7 emits signals against warm CTF). It REQUIRES `--replay-only` (exits 1 otherwise) and is ONLY honored at `--workers 1` (silently skipped in parallel mode). The earlier "typically 50-100 bars" guess was wrong - warmup is a full I1-I6 pass over the corpus, not a fixed bar count. See Plan 01 critical_corrections #5.

3. **Replay output:** Fresh slate via `--clean`. DECIDED: yes, `--clean` deletes trade_executions -> trade_frames -> signal_events in FK order before replay. See Plan 01 Task 2.
