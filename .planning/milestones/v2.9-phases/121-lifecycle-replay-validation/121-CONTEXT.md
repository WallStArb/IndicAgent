# Phase 121: Lifecycle Replay & Validation - Context

**Gathered:** 2026-06-10
**Status:** Wave 1 complete. Wave 2 = pipeline hardening (ATR + macro wiring) — next to execute. Wave 3 (validation report) deferred to Phase 126 — runs after v2.10 clean replay. Phase 126 Wave 2 carries the 121-02-PLAN.md spec.

## Wave Summary

| Wave | Scope | Status |
|------|-------|--------|
| Wave 1 | Replay infrastructure redesign + noise signal clean replay | Complete |
| Wave 2 | Pipeline hardening: ATR validation (todo 020) + macro cross-asset P1 wiring (todo 018) | **Next** |
| Wave 3 | Before/after validation report (121-02-PLAN.md) | Deferred → Phase 126 |

**Why Wave 2 here:** These fixes must land before the Phase 126 clean replay so replayed data reflects correct ATR and macro context logic. Small enough (1-2 days) to ship as a wave rather than a separate phase.

<domain>
## Phase Boundary

Phase 121 delivers a clean signal ledger for the 22 refactored I7 setups, plus a validated before/after comparison report. Wave 1 redesigns the lifecycle replay infrastructure to handle the current schema, executes a clean delete+regenerate+replay for the 22 refactored setups, and computes lifecycle outcomes for all pending signals. Wave 2 generates a reproducible comparison report using a pre-delete snapshot as the "before" baseline.

**In scope:**
- Complete the 8-change backfill integrity plan (`docs/plans/2026-06-06-backfill-signal-integrity-plan.md`) as Wave 1 prerequisite
- Redesign `lifecycle_replay.py` to handle current schema (remove hardcoded date windows, handle all new `signal_outcomes` columns, process all pending signals regardless of timestamp)
- Before-snapshot script: capture per-setup metrics before any deletes → `docs/plans/phase-121-before-snapshot.json`
- Run `historical_backfill.py --replay-only --clean` scoped to the 22 shadow setups (delete old noise signals, regenerate with corrected plugin code)
- Run redesigned `lifecycle_replay.py` on all pending outcomes (1.54M non-shadow pending as of 2026-06-10)
- Hard integrity gate before Wave 2 (hard-fail on invariant violations)
- `production/scripts/phase_121_report.py` → `docs/plans/phase-121-validation-report.md`
- Update RCA doc Part VI success metrics with actual measured numbers + `MEASURED [date]` annotations

**Out of scope:**
- 3-table schema migration (signal_events + trade_framing + trade_execution) — v2.10 Phases 123-125
- Extrinsic composite confidence layer — Phase 4.1 per RCA doc
- Shadow promotion (handled by shadow_validator weekly timer from Phase 120)
- New plugin modifications

</domain>

<decisions>
## Implementation Decisions

### Wave 2: ATR Validation Hardening

### D-07: I6 Confluence Functions — Early Return, Not Raise

`confluence_smc.py` and `cross_tf_sr_confluence.py` use `get_atr(features) or 0.0` / `or 1.0` as the ATR value. This is silent data corruption — 0.0 ATR propagates into ratio calculations; 1.0 produces plausible-looking but wrong SR proximity scores.

**Fix:** At the top of each function, guard: `atr = get_atr(features); if not atr: return {}`. Returns zero contribution to the I6 confluence score. Semantically correct: "no ATR data → no ATR-dependent score." Matches the established `CrossAssetContextPlugin` pattern (returns `{}` when data not ready).

**Why NOT raise:** I6 confluence runs inside the pipeline executor. A raise would drop the entire bar's confluence computation on quiet/off-hours bars where ATR is legitimately unavailable. Early return is the correct contract for I6.

---

### D-08: Add `get_atr_valid(features)` to `atr_utils.py`

Add a strict accessor that raises `ValueError` when ATR is None. Use this ONLY in I7 plugin `compute_full()` where `no_signal()` is the contract and a loud failure is correct behavior.

**Not for I6** — I6 uses the early-return pattern from D-07. The distinction is: I7 should loudly fail (no signal emitted); I6 should gracefully degrade (zero contribution to score).

---

### D-09: zone_engine.py:232 — No Migration Needed

`get_atr_with_floor(features, symbol)` at line 232 is already correct:
- Symbol is read from `features.get("symbol", "")` — not a separate arg
- `if atr is None:` check already exists at line 233
- `frames` is not in scope at this callsite

**Fix:** Add a clarifying comment only: `# symbol-variant API: frames not in scope here; symbol read from features dict`. Mark done — this is not a defect.

---

### Wave 2: Macro Cross-Asset P1 Wiring

### D-10: One `MacroContextPlugin` (Not Three Thin Plugins)

One data source (`frames["cross_asset"]`) = one DAG node. All 5 macro fields (ftq_score, ftq_regime, yield_curve_slope, yield_curve_regime, corr_z) arrive from the same merged frames key. Three separate plugins reading from the same source is complexity without SoC benefit.

**File:** `src/intelligence/context/macro_context.py`
**Class:** `MacroContextPlugin`
**Tier:** I4 — register in `TIER_I4` in `register_plugins.py`

`CrossAssetContextPlugin` (EQ_INDEX equity sector spreads) remains separate — different domain, different scope, different symbol-group guard.

---

### D-11: I4Context Field Changes

`I4Context` already has `yield_curve_slope` and `yield_curve_regime` as orphaned fields (never populated). Required changes:

1. **Uncomment** `ftq_score: float | None = None` and `ftq_regime: str | None = None` (lines 1065-1066 in `schemas.py`)
2. **Add** `corr_z: float | None = None`
3. Update the docstring field count (currently "Total: 93 fields") and add `MacroContext (5 fields)` to the plugin list

Total new/activated fields: 5 (`yield_curve_slope`, `yield_curve_regime`, `ftq_score`, `ftq_regime`, `corr_z`).

---

### D-12: Storage via I4Context JSONB — No Migration

Macro fields flow through `I4Context → event.i4.model_dump() → intelligence_features.i4` (JSONB). This is the standard I4 pattern — consistent with all 93 existing I4 fields. No DB migration needed.

**Note on naming:** `i4` column name fails the whiteboard test (tier code, not functional). This is the open decision from MEMORY.md (phases 95-116 used functional names; Phase 122 reverted to tier codes). **Deferred to Phase 123 ADR scope** — column rename belongs in the v2.10 migration decision, not a mid-flight rename.

---

### D-01: Wave 1 Scope — Renaissance-Grade Clean Replay

Signal ledger must reflect corrected reality, not track historical noise. The 22 refactored setups (in shadow mode since Phases 118-119) fired 4.46M noise signals under broken plugin code. Those signals are deleted and regenerated with corrected code.

**Wave 1 execution sequence (strict order):**
1. Complete backfill integrity plan (8 changes to `historical_backfill.py`)
2. Redesign `lifecycle_replay.py` for current schema
3. Capture before-snapshot (`docs/plans/phase-121-before-snapshot.json`) — atomic, before any deletes
4. Run `historical_backfill.py --replay-only --clean` scoped to the 22 shadow setups
5. Run redesigned `lifecycle_replay.py` on all pending signals
6. Run integrity gate — hard-fail if invariants violated

**Why not lifecycle_replay.py only:** The 1.59M→~250K OFI signal target requires actual signal regeneration, not just outcome computation. Jim Simons demands stopping noise at the source, not tracking it.

---

### D-02: lifecycle_replay.py Redesign Requirements

Current v1.2 has schema drift that must be corrected before any replay:

**Hardcoded constraints to remove:**
- `cutoff = datetime(2026, 6, 2, 0, 0, 0, tzinfo=UTC)` in `_seed_orphan_outcomes`
- `sl.timestamp >= '2026-05-21'` window in orphan seeding query
- `--reset-before` default `2026-06-02T00:00:00Z`
- `--reset-after` default `2026-05-21T00:00:00Z`

**New `signal_outcomes` columns to handle in SELECT and UPDATE:**
`trailing_stop_price`, `staleness_score`, `staleness_trigger_reason`, `chandelier_vol_source`, `shadow_tracking_start_ts`, `shadow_mae`, `shadow_mfe`, `shadow_outcome`, `effective_ts`

**New `signal_ledger` columns to include in SELECT (migration 119):**
`stop_basis`, `stop_type_col`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `plugin_regime_type`

**`_verify_replay` update:** Currently filters `is_shadow = false` — must be reviewed to verify shadow signals are handled correctly post-regeneration.

**Behaviour change:** Process ALL pending signals by default (no date-bounded window). The window flags (`--reset-before`/`--reset-after`) become optional overrides, not defaults with hardcoded dates.

---

### D-03: Delete+Regenerate Scope — Exactly the 22 Shadow Setups

The delete+regenerate operation is scoped to `_SHADOW_VALIDATION_SETUPS` frozenset in `services/shadow_validator.py` (assert len == 22). This is the exact list of setups refactored in Phases 118-119 and currently in shadow mode.

The 8 GOOD setups (trad_TrendFollowing, trad_MeanReversion, trad_LiquiditySweepReclaim, trad_CHoCHReversal, trad_SqueezeExpansion, trad_SupplyDemandSetup, plus trad_AnchoredVWAPReversion and trad_VWAPDeviation) are NOT touched — they serve as control group in the comparison report.

---

### D-04: Before-Snapshot — Atomic Capture Before Any Destructive Operation

A before-snapshot script (or Wave 1 preflight step) runs these metrics per-setup BEFORE any `DELETE` executes, and writes `docs/plans/phase-121-before-snapshot.json` with ISO timestamp:

```sql
SELECT
    sl.setup_plugin,
    sl.is_shadow,
    COUNT(*) as total_signals,
    COUNT(CASE WHEN sl.was_selected THEN 1 END) as selected,
    COUNT(CASE WHEN sl.was_selected THEN 1 END)::float / NULLIF(COUNT(*), 0) as selection_rate,
    AVG(CASE WHEN so.pnl_r IS NOT NULL THEN so.pnl_r END) as avg_pnl_r,
    CORR(sl.cis_score, (so.pnl_r > 0)::int) FILTER (WHERE so.pnl_r IS NOT NULL) as calibration_corr
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
GROUP BY sl.setup_plugin, sl.is_shadow
ORDER BY total_signals DESC
```

The snapshot JSON is the authoritative "before" baseline. Wave 2 report script reads it for comparison. The RCA doc numbers (7.85M / 0.19% SNR) are supplementary context — do not use stale documentation numbers as the measurement baseline.

---

### D-05: Comparison Report — All 30 Setups, 5 Metrics

**Script:** `production/scripts/phase_121_report.py`
**Output:** `docs/plans/phase-121-validation-report.md`

Runs identical queries post-replay, diffs against `phase-121-before-snapshot.json`. Covers all 30 setups.

**Mandatory report metrics per setup:**
1. Signal count (before → after, % reduction)
2. Selection rate (before → after)
3. SNR (signal-to-noise ratio = selection_rate, presented as %)
4. Calibration correlation: `CORR(cis_score, pnl_r > 0)` for shadow setups; `CORR(confidence, was_selected)` for non-shadow
5. `stopped_at_entry` count — must be 0 for all regenerated signals (validates Phase 117 fix)

**Cluster-level rollup:** GOOD / MODERATE / NEEDS_REFACTOR SNR with before/after (shows structural shift, not just per-setup noise).

**Success criteria verdicts:** Per-setup pass/fail column against roadmap targets (1.59M→~250K OFI, 0.18%→15-25% SNR, calibration>0.3, etc.).

**RCA doc update:** After report generation, update `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md` Part VI "After" column with measured values + `MEASURED 2026-XX-XX` annotations.

---

### D-06: Integrity Gate Before Wave 2

Hard-fail (raise RuntimeError) if any of these are violated post-replay:
- Any signal older than 2 days with `outcome IS NULL` and `status NOT IN ('regime_suppressed', 'active')`
- Any `stopped_at_entry` outcome in regenerated signals (is_shadow=True for the 22 setups)
- Any `signal_id` in `signal_ledger` without a matching `signal_outcomes` row (Phase 104 invariant)

Same pattern as existing `_verify_replay()` — extend, don't replace.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Root Cause + Blueprint
- `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md` — Full RCA + Phase 5 implementation roadmap + Part VI success metrics. The 22 setup list, SNR targets, and calibration criteria all derive from here.

### Prerequisite Plan (must be completed in Wave 1)
- `docs/plans/2026-06-06-backfill-signal-integrity-plan.md` — 8 changes to `historical_backfill.py`: `_load_calibration_curves`, `_load_perf_weights`, calibration kwargs threading, integrity gate. Must execute Task 1 through Task 8 before running `--replay-only --clean`.

### Scripts to Redesign / Use
- `production/scripts/lifecycle_replay.py` — v1.2 (current). D-02 specifies exactly what to change. Read before modifying.
- `production/scripts/historical_backfill.py` — v1.4. Stage 2 (`--replay-only --clean`) deletes old signals and regenerates from historical bars. Read the `--replay-only` and `--clean` code paths before modifying.

### Schema (READ before writing any queries)
- `production/migrations/095_signal_ledger_split.sql` — Phase 104 signal_ledger/signal_outcomes split. All queries must JOIN on signal_id.
- `production/migrations/096_signal_ledger_zone_fields.sql` — entry_zone_low/high columns
- `production/migrations/097_signal_ledger_expires_at.sql` — expires_at column
- `production/migrations/112_update_signal_ledger_full_view.sql` — signal_ledger_full view definition (authoritative column list)
- `production/migrations/115_signal_id_unique.sql` — UNIQUE constraint on signal_id
- `production/migrations/119_framing_audit_trail.sql` — 5 new signal_ledger columns (stop_basis, stop_type_col, structural_stop_distance_atr, adaptive_buffer_mult, plugin_regime_type)
- `production/migrations/121_signal_ledger_shadow_view.sql` — signal_ledger_shadow view (use for shadow-specific reporting)

### Shadow Setup List (scope of delete+regenerate)
- `services/shadow_validator.py` — `_SHADOW_VALIDATION_SETUPS` frozenset (22 setups, assert len == 22). This is the exact scope of the delete+regenerate operation in Wave 1.
- `src/intelligence/register_plugins.py` — `_PHASE_119_PLUGINS` (17 setups) + Phase 118 setups (5) — verify names match shadow_validator frozenset

### Prior Phase Context
- `.planning/phases/120-shadow-mode-validation/120-CONTEXT.md` — D-03: calibration metric is `CORR(cis_score, (pnl_r > 0)::int)` for shadow signals. D-02: shadow signal outcome metrics. D-06: `_SHADOW_VALIDATION_SETUPS` definition and count (22, not 21).

### Design Principles
- `docs/foundation/principles.md` — "Instrument everything", "Earn promotion through proof", "Data quality over model complexity"
- `CLAUDE.md` — `BaseWriter._parse_payload` return contract, asyncpg JSONB handling, UTC timestamp rules

### Wave 2: ATR Hardening
- `src/intelligence/trading/atr_utils.py` — add `get_atr_valid(features)` here (raises on None); existing `get_atr`, `get_atr_with_floor`, `get_atr_with_floor_from_frames` stay unchanged
- `src/intelligence/confluence/confluence_smc.py` — D-07 fix: replace `or 0.0` with early-return guard
- `src/intelligence/confluence/cross_tf_sr_confluence.py` — D-07 fix: replace `or 1.0` with early-return guard
- `src/intelligence/trading/zone_engine.py:232` — D-09: comment-only, no code change

### Wave 2: Macro Cross-Asset P1
- `src/intelligence/schemas.py` — D-11: uncomment ftq_score/ftq_regime, add corr_z to I4Context
- `src/intelligence/context/macro_context.py` — D-10: new MacroContextPlugin (create this file)
- `src/intelligence/context/cross_asset_context.py` — reference: established pattern for `frames["cross_asset"]` reads and EQ_INDEX symbol guard
- `src/intelligence/register_plugins.py` — `TIER_I4`: register MacroContextPlugin
- `src/intelligence/pipeline/feature_pipeline_executor.py:207-210` — confirms macro_data is already merged into `frames["cross_asset"]`; no changes needed here
- `services/intelligence_pipeline.py:460-470` — confirms ftq_score/ftq_regime/yield_curve fields already extracted from macro_signals topic into cache

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lifecycle_replay.py` bar streaming + zone/market track evaluation logic — reusable as-is; only date constraints and column lists need updating
- `_flush_writes()` chunked batch pattern (ZONE_CHUNK=1500, MARKET_CHUNK=2000, ACTIVATION_CHUNK=4000) — PostgreSQL 32767 param limit; preserve these exact chunk sizes
- `pg_try_advisory_lock` + `_check_service_quiescence()` preflight pattern — must be preserved in redesigned script
- `evaluate_signal()` + `evaluate_market_entry()` from `src/intelligence/trading/lifecycle_tracker.py` — core evaluation functions, unchanged
- `flush_and_shutdown_metrics()` + `JOB_COMPLETED_TOTAL` — mandatory oneshot exit pattern per CLAUDE.md D-06

### Established Patterns
- Advisory lock ID is `_REPLAY_LOCK_ID = 20260602` — keep this value; changing it would allow concurrent replays with old lock ID
- `SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0` — must be set per connection before any DML (TimescaleDB compressed chunk requirement)
- `asyncpg` for lifecycle_replay.py, `psycopg2` for historical_backfill.py — don't mix drivers
- Before-snapshot and report scripts: use `asyncpg` pattern (consistent with lifecycle_replay.py)

### Integration Points
- `signal_ledger_shadow` view (migration 121) — use for shadow-specific reporting queries in Wave 2
- `signal_ledger_full` view (migration 112 + 119) — authoritative column list; use for all reporting queries
- `setup_performance` + `swarm_agent_weights` tables — will be truncated by `--reset` flow and repopulate on next scheduled runs (nightly ml-training 11pm, weekly ml-orchestrator Mon); document this in Wave 2 report
- `src/observability/metrics.py` `JOB_COMPLETED_TOTAL` — emit `job="lifecycle-replay"` and `job="phase-121-report"` at script exit

</code_context>

<specifics>
## Specific Ideas

- **Before-snapshot timing:** Run the snapshot query inside the same DB transaction that acquires the advisory lock — ensures atomicity with the delete operation. Release lock after snapshot is written to disk.
- **`historical_backfill.py --clean` scope:** The `--clean` flag must be scoped to the 22 shadow setups via `--plugins` or similar filter — not a blanket delete of all signal_ledger rows. Verify that the flag accepts a plugin filter before planning.
- **lifecycle_replay.py date arguments:** Replace hardcoded defaults with `None` (process all signals). Add `--after` / `--before` as optional override flags (preserve backward compatibility for targeted replays).
- **Report format:** Per-setup table with columns: `setup_plugin | cluster | signals_before | signals_after | delta_pct | snr_before | snr_after | calibration_corr | stopped_at_entry | verdict`. Verdict = PASS/FAIL/PARTIAL per roadmap target.
- **RCA doc update:** Use a `| Metric | Target | Before (measured) | After (measured) | Status |` table format in Part VI. Append `MEASURED YYYY-MM-DD` in status column.
- **Integrity gate placement:** Run `_verify_replay()` as a hard prerequisite before `phase_121_report.py` is allowed to run — script should abort with clear error if verify fails.

</specifics>

<deferred>
## Deferred Ideas

- **3-table schema migration** (signal_events + trade_framing + trade_execution) — RCA doc Phase 4.5, v2.10 Phases 123-125. The replay writes into existing schema; migration happens after.
- **Extrinsic composite confidence layer** — softmax-normalized composite of ctf_score + hmm_regime_weight + zone_friction + exhaustion_guard. RCA doc Phase 4.1. Requires shadow outcome data (accumulating now).
- **Per-symbol magnitude threshold tuning** — OFI/CVD thresholds derived from `signal_probe_results` data. Phase 117.5 in RCA doc. Data still accumulating.
- **`intelligence_features` column rename** (`i4` → functional name, and `i1`/`i3`/`i5`): `i4` fails the whiteboard test — tier codes don't communicate intent. MEMORY.md open decision (phases 95-116 moved toward functional names; Phase 122 reverted). Fix in Phase 123 ADR — lock the functional column names before Phase 124 migration executes. Do not rename mid-flight before v2.10.
- **Macro P2 (regime segmentation)** — `setup_performance` win rates segmented by `(yield_curve_regime, ftq_regime)` bucket; I7 signal gating by macro regime shadow-only, n≥100 gate. After P1 data accumulates.
- **Macro P3 (new enrichment services)** — `StockBondCorrelationAgent`, VX term structure. After P1+P2 prove signal.

</deferred>

---

*Phase: 121-Lifecycle-Replay-Validation*
*Context gathered: 2026-06-10*
