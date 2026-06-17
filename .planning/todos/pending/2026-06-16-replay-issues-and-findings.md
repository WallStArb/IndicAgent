# Phase 127 replay (2026-06-16): issues & findings — investigation backlog

**Status:** pending (post-rebuild investigation)
**Created:** 2026-06-16
**Context:** Full clean-slate rebuild launched 2026-06-16 (~20:00 UTC) at `--workers 8` after wiping all signal-derived tables + stale features. This file consolidates every issue/finding discovered during the rebuild session for investigation in a fresh context. Check `logs/REBUILD_STATUS` = COMPLETE before validating.

---

## 1. Plugin errors on rolled-month contracts (HIGHEST PRIORITY)
Per-plugin error summaries fire on several contracts during replay:
- `NQU6`: 103,360 errors across 8 plugins
- `YMM6`: 117,013 errors across 4 plugins
- `RTYM6`: 112,523 errors across 13 plugins

**Nature:** Non-fatal (each plugin wrapped in try/except → output skipped for affected bars, run continues). Signals still produced at healthy rate. But could indicate a plugin edge case on rolled-month variants (U6/M6) — possibly missing market-context fields, asset_class=None, or a schema mismatch.

**Investigate:**
- `grep -E "plugin.*error|_log_plugin_error" logs/rebuild_phase127_8w_*.log | sort | uniq -c | sort -rn | head` — which plugins + which exception types dominate.
- Check whether affected symbols have asset_class populated (warnings showed `asset_class=None` in framing logs).
- Determine if errors correlate with specific contract months (rolled vs front) or symbol classes (futures vs ETF vs FX).
- Quantify impact: are signals from erroring symbols missing whole plugin contributions (e.g. no OFI/CVD setups on NQU6)?

## 2. reset_pipeline_data.py FK bug (must fix)
`_execute_wipe()` TRUNCATEs tables one-at-a-time without CASCADE. Fails on `trade_frames` because `trade_executions` holds an FK to it (`FeatureNotSupported: cannot truncate a table referenced in a foreign key constraint`). Since the wipe commits only at the end, the error rolls back the ENTIRE transaction → partial-looking wipe that actually changed nothing.

**Fix:** Replace the per-table loop with a single `TRUNCATE TABLE <all 14 tables> CASCADE;` (PostgreSQL resolves intra-set FKs in one statement). Done manually via psql this session; the script itself is still broken for next operator.

## 3. `--warmup` flag is dead code (no-op)
Already captured in `2026-06-16-remove-dead-warmup-flag.md`. Summary: `plugin_states`/`intelligence_cache` are local to each `replay_symbol()` call, so Pass 1's caches die before Pass 2 — warmup double-pass provides zero cold-start benefit, just 2x compute + forces `--workers 1`. Cold-start within a single pass is already handled by chronological lower-TF-first merge + `min_bars_for_tf()` guard. Remove the flag.

## 4. Obsolete scripts cleanup
Already captured in `2026-06-16-cleanup-obsolete-replay-scripts.md`. Summary: `phase_127_before_snapshot.py` (references dropped tables) + `phase_127_monitor_replay.py` (one-shot) are dead post-rebuild. Phase 130 already did ~95% of old-schema cleanup. `migrate_signal_ledger.py` is a completed one-shot (archive, don't delete).

## 5. Post-rebuild validation checklist
Once `REBUILD_STATUS=COMPLETE`:
- [ ] **Signal volume sanity:** total signals vs prior baseline (~484k pre-wipe). 36 setups firing across 116 symbols.
- [ ] **CTF validity:** `SELECT count(*) FROM signal_events WHERE ctf_score IS NULL` — should be ~0 except genuinely-pending. Confirms cold-start is handled (validates finding #3).
- [ ] **Feature completeness:** verify the previously-stale keys now populate: `volume_sma_20`, `rel_volume`, `hmm_probability`, `zone_friction_score` in intelligence_features (were 0/4.2M pre-rebuild).
- [ ] **Lifecycle outcomes:** `trade_executions` populated, `signal_events.status` transitions off `pending` (active/stopped/target/expired).
- [ ] **counterfactual_pnl_r still NULL:** expected — this is the CounterfactualEvaluator agent in live alpha_swarm (Phase 130/v2.11), NOT computed by the historical rebuild. Populates during normal live operation. Confirm ML training materialization doesn't break on NULL until alpha_swarm fills it.

## 6. intelligence_features column naming (pre-existing open decision)
From MEMORY.md Open Decisions: Phase 122 applied tier-code columns (`i1`/`i3`/`i4`/`i5`/`composite_events`) but phases 95-116 moved toward functional names. Resolve before any future phase touching these columns — the rebuild uses tier-code names (current live schema). Not introduced by this rebuild but still open.

## 7. Architecture observations (no action, just record)
- Replay emits all 36 `trad_*` setups (`TIER_I7`); the 16 `smc_*` plugins are SMC-tier feature detectors feeding into setups, not standalone signal generators. No "60 setups."
- `feature_replay.py` is the intentional I7-only fast path (Phase 130) for when only signal code changes and features are valid. Coexists with `run_historical_pipeline.py` by design — NOT redundant.
- `--clean` (default) only deletes the 22 `_SHADOW_VALIDATION_SETUPS`; replay emits all 36 → mismatch. For a full wipe, TRUNCATE directly (done this session). Consider whether `--clean` default should widen.

## 8. Emission-gate rejections: stop within 1 tick of entry (signal coverage gap)
Distinct from finding #1. Multiple I7 plugins reject signals where the stop rounds to within 1 tick of entry:
- `trad_VWAPDeviation`, `trad_TrendFollowing`, `trad_SupplyDemandSetup` (at least)
- Hits low-priced / small-tick instruments: SI (silver), NG (natgas), HG (copper), CL (crude), FX pairs (EURUSD, GBPUSD)
- Example: `Emission gate: stop (2.86) is within 1 tick (0.001) of entry (2.859)` — NGN6

**Nature:** The gate (`_log_plugin_error`, first-occurrence per plugin/symbol/tf) is a legitimate data-quality guard — a stop equal to entry is a zero-risk-distance, meaningless trade. BUT if ATR-based stop geometry consistently produces stop≈entry on these instruments, the plugin emits **zero signals** there → silent coverage gaps for whole instrument/setup combinations.

**Investigate:**
- Confirm coverage: `SELECT setup_plugin, symbol, count(*) FROM signal_events GROUP BY 1,2` — are SI/NG/HG/CL/FX missing VWAPDeviation/TrendFollowing/SupplyDemandSetup signals entirely?
- Root cause: is the ATR stop multiplier too tight for low-priced instruments, or is tick-size floor logic off? Check `get_atr_with_floor_from_frames` and the tick-floor logic in `atr_utils.py`.
- Decide: widen stop geometry on low-priced instruments, or accept the gap (zero-risk signals correctly rejected).

## 9. Verify the rolled-month "plugin errors" aren't contaminating signal counts
Related to #1 but a specific validation: NQU6/YMM6/RTYM6 showed 100k+ plugin errors. Confirm those symbols still produced a reasonable signal volume (not just the non-erroring plugins). If a symbol has anomalously low signal counts vs peers, the errored plugins may be systematically dropping most of its setups. Cross-check signal counts per symbol against the asset-class cohort.

---

## Session execution log (for reproducibility)
1. Stopped lifecycle services + neutralized auto-restart (service-auditor, self-healing-agent stopped; `Restart=no` drop-ins on writers — restart watcher removes these).
2. Wiped all 14 signal-derived tables + intelligence_features via single `TRUNCATE ... CASCADE` (reset_pipeline_data.py was broken, see #2).
3. Launched `--workers 1 --warmup`, proved warmup no-op (#3), killed at ~3%.
4. Relaunched `--workers 8` (no warmup) — correct + ~8x faster.
5. Chained lifecycle_replay → verify → restart-services watchers (logs/chain2.log, logs/restart2.log).

**Resume in fresh context** for items 1-5. Items 3 & 4 are independent code cleanups; item 1 is the real investigation; item 5 is the validation gate before trusting the new training data.
