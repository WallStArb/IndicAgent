# Phase 127 Issues Master List
**Created:** 2026-06-17
**Purpose:** Consolidated input for planning the next phase(s). All issues surfaced during Phase 127 clean replay + validation. Triaged by code layer to separate live-pipeline fixes from script-only fixes.

---

## Layer A — Live Code (`src/`, `services/`)
These affect the running pipeline AND every replay. Fix here = fix everywhere.

### A1. POCRejection + HVNRejection: float(None) crash → 0 signals [HIGH]
**File:** `src/intelligence/trading/trade_framer.py:343`
**Bug:** `_get_htf_vp()` returns `float(poc_htf)` without guarding for None. Crashes on early historical bars and higher TFs where HTF VP data is absent. Both plugins produce 0 signals in the corpus.
**Fix:** Guard before cast; return `(None, None, None)` when any field is None; verify callers handle it.
**Impact:** 2 valuable plugins contribute nothing to training data. Quick fix.

### A2. Stop-zone geometry: 25% stopped_at_entry [HIGH]
**Files:** `src/intelligence/trading/trade_framer.py`, `src/intelligence/trading/zone_engine.py`
**Bug (multi-part):**
- Zone generation produces sub-ATR zones on ETFs (QQQ: 2-6 cents, XLE: 1-2 cents). `MIN_ZONE_WIDTH_ATR = 0.25` exists but feature-layer fast paths bypass zone_engine's guard.
- Stop calculated from `zone_low - 1xATR` (zone edge), not from entry price. When zone is narrow + entry at edge, stop is immediately behind entry.
- Result: ~130K signals in current corpus have `stopped_at_entry` outcome.
**Fix:** (1) Enforce min zone width at all paths including fast paths. (2) Calculate stop distance from entry, not zone edge. (3) Add emission gate: `stop_distance >= min_stop_distance_atr * ATR`.
**Related APR keys:** `feature.zone_engine.min_zone_width_atr.*`, `feature.trade_framer.min_stop_atr`

### A3. Emission gate silently killing whole instrument/setup combinations [HIGH]
**File:** `src/intelligence/trading/trade_framer.py`
**Bug:** The 1-tick stop gate (`stop <= entry + 1 tick`) is correct logic, but ATR-based stop geometry on low-tick instruments (SI silver, NG natgas, HG copper, CL crude, FX pairs) produces `stop ≈ entry` on virtually every bar. Result: VWAPDeviation, TrendFollowing, SupplyDemandSetup emit 0 signals for these entire instrument/setup combinations — silent coverage gap.
**Investigate:** Confirm missing combos via `SELECT setup_plugin, symbol, count(*) FROM signal_events GROUP BY 1,2`. Root cause: ATR stop multiplier too tight for these instruments, or tick-floor logic incorrectly sized.
**Fix options:** Per-asset-class stop multiplier floors in APR, or widen geometry on small-tick instruments.

### A4. Plugin errors on rolled-month contracts [MEDIUM]
**Scope:** NQU6 (103K errors, 8 plugins), YMM6 (117K errors, 4 plugins), RTYM6 (112K errors, 13 plugins). Non-fatal — each plugin wrapped in try/except — but those bars skip entirely for the erroring plugins.
**Symptoms:** `asset_class=None` in framing logs, missing market-context fields.
**Investigate:**
- `grep -E "plugin.*error" logs/rhp_reemit.log | sort | uniq -c | sort -rn | head 30` — dominant plugins + exception types.
- Check whether rolled contracts have `asset_class` populated in `contract_metadata` or `instruments`.
- Cross-check signal counts per symbol vs asset-class peers — NQU6 should look like NQM6.
**Root cause options:** Missing `asset_class` lookup for rolled contracts; schema field absent on older bar data; plugin-specific guard missing for rolled-month edge case.

### A5. trade_framer.py: 16 hardcoded APR violations [MEDIUM]
**File:** `src/intelligence/trading/trade_framer.py`
**Bug:** Every ATR stop multiplier, zone width multiplier, RR ratio, and adaptive buffer coefficient is a module-level constant. ML discovery cannot tune them without a code deploy. Architecture violation per CLAUDE.md.
**Constants to migrate** (from todo `2026-06-14-trade-framer-apr-migration.md`):
`ATR_STOP_DEMAND_MULTIPLIER`, `ATR_STOP_SWEEP_MULTIPLIER`, `ATR_STOP_OB_MULTIPLIER`, `ATR_STOP_SWING_MULTIPLIER`, `ATR_STOP_SR_MULTIPLIER`, `ATR_STOP_FALLBACK_MULTIPLIER`, `MIN_STOP_ATR_MULTIPLIER`, `MIN_RR_T1`, `ADAPTIVE_BUFFER_HARD_CAP`, `STRUCTURE_SNAP_PROXIMITY_ATR`, `ATR_ZONE_*` (3 keys), `ATR_TARGET_MIN_MULTIPLIER`, `VP_PROXIMITY_THRESHOLD_ATR`, adaptive buffer piecewise coefficients.
**Sequencing:** Do after lifecycle_replay is clean and corpus is stable. ML can then tune per asset class + regime.

### A6. bocpd_changepoint.py vol mean includes current bar [LOW]
**File:** `src/intelligence/features/smc_context/bocpd_changepoint.py:278`
**Bug:** `avg_vol = float(np.mean(vol[-20:]))` includes the current bar. Lower severity than plugin-level because this is an I4/I5 feature detector computing context, not a signal quality gate. But vol ratio is slightly inflated during high-volume bars.
**Fix:** Change to `np.mean(vol[-21:-1])` matching the corrected pattern in I7 plugins.

---

## Layer B — Scripts (`production/scripts/`)
These only affect replay/rebuild operations, not the live pipeline.

### B1. lifecycle_replay: TTL-expiry path incomplete [BLOCKING — Phase 127]
**File:** `production/scripts/lifecycle_replay.py`
**Bug:** Two related issues from the previous failed `_verify_replay`:
- 66K signals remain `status='pending'` despite being >2 days old (TTL-expiry path not firing for signals whose bar window exhausted without activation).
- 74K signals have `status='expired'` but no `trade_executions` row — expiry sets status but never writes the outcome record.
**Fix:** Find the TTL/non-activation branch (~lines 960-1070). Ensure expired signals always get a `trade_executions` INSERT (pnl_r=0 is acceptable for a TTL-expiry-without-entry). Ensure stale-pending signals are caught by the sweep.
**Test:** Re-run lifecycle_replay after fix; `_verify_replay` must pass with stale_unresolved=0, target_no_pnl=0, orphans=0.

### B2. lifecycle_replay: asyncpg transaction hygiene [LOW-MEDIUM]
**File:** `production/scripts/lifecycle_replay.py`
**Bug:** `ERROR Resetting connection with an active transaction` fires at every symbol/tf boundary. Connection is returned to pool with an open transaction. Data commits fine but it's dirty and risks subtle corruption under load.
**Fix:** Ensure every connection acquired in the per-(symbol, tf) worker is released only after explicit commit or rollback. Audit the worker coroutine's exception paths for missing finally/rollback.

### B3. feature_replay.py: stateless vs stateful coverage gap [MEDIUM]
**File:** `production/scripts/feature_replay.py`
**Bug:** `feature_replay.py` uses `compute_full()` (stateless, single-bar). The original corpus was built with `incremental_compute()` (stateful — plugins accumulate GARCH/Kalman/HMM/BOCPD state across bars). Dry-run produces 0 signals. The fast I7-only replay path is architecturally correct but currently broken for stateful plugins.
**Fix options:** (a) Make feature_replay use incremental_compute with per-symbol state accumulation; (b) Identify which plugins need stateful context and only skip them in feature_replay (stateless plugins still get the speed benefit).
**Impact:** Until fixed, `run_historical_pipeline.py --replay-only` is the only correct full-corpus rebuild path. feature_replay cannot be used as the fast I7-only path.

### B4. reset_pipeline_data.py: TRUNCATE without CASCADE [LOW]
**File:** `production/scripts/reset_pipeline_data.py`
**Bug:** `_execute_wipe()` TRUNCATEs tables one-at-a-time. Fails on `trade_frames` because `trade_executions` FK blocks it. Error rolls back entire transaction — partial-looking wipe that changed nothing.
**Fix:** Replace per-table loop with single `TRUNCATE TABLE <all 14 tables> CASCADE;`. PostgreSQL resolves intra-set FKs in one statement.

### B5. run_historical_pipeline.py: dead --warmup flag [LOW]
**File:** `production/scripts/run_historical_pipeline.py`
**Bug:** `--warmup` double-pass is a provable no-op. `plugin_states` and `intelligence_cache` are local to `replay_symbol()` — Pass 1 caches die before Pass 2 starts. Cold-start already handled by chronological lower-TF-first merge + `min_bars_for_tf()` guard. The flag just doubles compute and forces `--workers 1`.
**Fix:** Remove `--warmup` argparse arg, two-pass loop in workers==1 branch, and the parallel-mode NOTE. Sweep `grep -rn "warmup" tests/ docs/ production/`.

---

## Layer C — Schema

### C1. trade_frames → TimescaleDB hypertable [MEDIUM — Phase 130 prerequisite]
**Migration:** 142
**Why:** Currently 851MB uncompressed with no compression path. Will grow 5x once CounterfactualTracker adds 5 entry_types per signal. ML training full-scans this table repeatedly.
**Steps:** Drop FK from trade_executions; drop UUID-only PK; create hypertable on `signal_ts` (chunk 7 days); recreate composite PK `(frame_id, signal_ts)`; add `signal_ts` to trade_executions as FK anchor; enable compression `segmentby=symbol,tf`.
**Timing:** Before CounterfactualTracker goes live. Do not block Phase 130 planning on it — early Phase 130 task.

### C2. intelligence_features column naming: tier codes vs functional names [LOW — open decision]
**Tables:** `intelligence_features` columns `i1`/`i3`/`i4`/`i5`/`composite_events`
**Issue:** Phase 122 applied tier-code column names but phases 95-116 decided toward functional names. Unresolved before any phase touching these columns.
**Action:** Search phases 95-116 CONTEXT/SUMMARY docs for the original decision. If functional names win, plan rename migration.

---

## Layer D — Naming / Code Hygiene (non-blocking)

| Item | File | Fix |
|------|------|-----|
| `_cfg()` → `_read_config()` | `src/intelligence/trading/zone_engine.py` | Rename function + call sites (internal only) |
| `confidence_utils.py` → `confidence.py` | `src/intelligence/trading/confidence_utils.py` | `git mv` + grep 39 import sites |
| Delete one-shot scripts | `production/scripts/phase_127_before_snapshot.py`, `phase_127_monitor_replay.py` | Delete + test sweep |
| Archive migration script | `production/scripts/migrate_signal_ledger.py` | Move to `archive/` |

---

## Already Resolved (stale todos — close these)

| Item | Status |
|------|--------|
| Vol SMA self-inflation (squeeze_expansion, vwap_deviation, candlestick_pattern_setup) | Already using `[-21:-1]` — correctly excludes current bar |
| shadow_validator read-path | Already reads `counterfactual_pnl_r` from `signal_ledger` (V2.11_ACTIVATED gate) |
| shadow_auditor read-path | Already reads `counterfactual_pnl_r AS pnl_r FROM signal_ledger` |

Close todos: `2026-06-15-vol-sma-self-inflation-multi-plugin.md`, `2026-06-16-phase127-00-readpath-execution.md` (Tasks 1+2 done; Tasks 3-4 still pending — see A5 + Layer D).

### B6. run_historical_pipeline: partial re-emit → incomplete corpus [HIGH]
**Discovered:** 2026-06-17 post-phase-127 audit
**Bug:** The phase 127 corpus rebuild (`--replay-only --include-rolled --client-id 40 --workers 8`) died mid-run with `psycopg2.OperationalError: server closed the connection unexpectedly` after inserting ~116K signals in Stage 2. Current corpus is ~537K signals vs the original 1,036,513. Root cause of the server-side connection drop is unknown — likely a long-running query hitting a PG timeout or OOM at the `_assert_backfill_integrity` step.
**Audit first:** `SELECT symbol, tf, COUNT(*) FROM signal_events GROUP BY symbol, tf ORDER BY symbol, tf` — check for symbols with 0 or near-0 counts that should have thousands. If counts look proportional across all symbols (each ~50% of expected), training is still viable. If certain symbols are completely absent, the corpus has structural bias.
**Fix:** (1) Diagnose the psycopg2 crash in `_assert_backfill_integrity` — check `run_historical_pipeline.py` around line 1837 for the long-running query. (2) After fixing crash, re-run with `--replay-only --include-rolled`. (3) Re-run `lifecycle_replay` after. Do NOT truncate before auditing coverage.
**Impact:** ML training on a biased corpus produces models that don't generalize. Block ML training until coverage is confirmed acceptable or corpus is completed.

### B7. _verify_replay SQL fan-out overcounting [LOW]
**Discovered:** 2026-06-17
**Bug:** The verify query does `LEFT JOIN trade_frames ... LEFT JOIN trade_executions`. When a frame has multiple execution rows (zone + market track both resolved), each signal_events row appears multiple times in the result. The `total` and `with_outcome` counts are inflated — the passing run showed `total=596,068` but `SELECT COUNT(*) FROM signal_events` returns 537,171. The zero-checks (`stale_unresolved=0`, `target_no_pnl=0`, `orphan_signal_events=0`) are CASE expressions and are trustworthy. Only the absolute counts in the log are misleading.
**Fix:** Add `DISTINCT se.signal_id` or restructure verify query to aggregate at the signal_events level before joining. Or add a separate COUNT(*) log line for the true signal count.
**Impact:** Low — verify gate logic is correct. The misleading log numbers could cause confusion when auditing corpus size post-replay.

---

## Sequencing for planning

**Must fix before corpus is usable for ML:**
- B1 (lifecycle_replay TTL expiry) — DONE (phase 127 complete)
- B6 (partial corpus) — audit coverage first; fix psycopg2 crash if re-run needed
- A1 (POCRejection/HVNRejection) — 2 plugins with 0 signals
- A3 (emission gate killing FX/commodity combos) — silent coverage gaps

**Fix together (same file, same ATR geometry problem):**
- A2 + A3 + A5 (trade_framer stop/zone geometry + APR migration)

**Independent, do anytime:**
- A4 (rolled contract plugin errors) — needs investigation first
- B2 (asyncpg hygiene), B3 (feature_replay), B4 (reset_pipeline), B5 (warmup), B7 (verify SQL)
- Layer D cleanups

**Schema — time-sensitive:**
- C1 (trade_frames hypertable) — must precede CounterfactualTracker going live
