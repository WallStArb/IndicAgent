# Phase 133: Clean Corpus Rebuild — Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

One complete, verified, unbiased corpus. All Phase 131 signal bugs fixed. All Phase 132 stop geometry correct. Schema migrated (trade_frames hypertable). Scripts cleaned. Full rebuild produces a corpus that satisfies the ML training acceptance criteria. ML training is unblocked after this phase.

**Do not begin Phase 133 until Phase 131 AND Phase 132 verification gates both pass.**

**35 of 35 eligible plugins** is the corpus target (CrossAssetDivergence formally excluded as architectural live-only; `_CORPUS_EXCLUDABLE = True` marker on the class). Any other zero-emission plugin at Phase 133 completion is a bug, not an exception.

</domain>

<decisions>
## Implementation Decisions

### D-01: C2 column naming is already complete — close the open item

The `intelligence_features` DB columns are **already functional names**. Confirmed from live DB + `schemas.py:36-41` mapping:

```python
"i1": "technical_indicators",
"i2": "composite_events",
"i3": "regime_features",
"i4": "confluence_scores",
"i5": "pattern_detections",
"i6": "cross_timeframe_context",
```

The `feature_writer` uses this mapping to translate `IntelligenceEvent` tier-code field names (`i1`/`i2`/`i3`/`i4`/`i5`/`i6`) to functional DB column names at write time. The naming convention permits tier codes on Python model fields; it prohibits them as DB column names. The DB column names already comply.

**Action in Phase 133:** First task is to verify this mapping end-to-end (schemas.py → feature_writer → DB column names), then close the MEMORY.md open decision item. No rename migration is needed. This is a verification + documentation closure, not a blocking investigation.

### D-02: trade_frames hypertable migration (C1) — do first, before TRUNCATE

8-step sequence from `.planning/todos/pending/2026-06-16-trade-frames-hypertable-migration.md`. Must be done BEFORE the TRUNCATE so the table is empty during conversion (avoids chunk migration overhead).

Sequence locked:
1. Drop FK `fk_trade_executions_frame` from `trade_executions → trade_frames`
2. Drop `trade_frames_pkey` (UUID-only PK)
3. Create hypertable on `signal_ts`, `chunk_time_interval = 7 days`
4. Recreate PK as `(frame_id, signal_ts)`
5. Add `signal_ts` to `trade_executions` as FK anchor
6. Recreate FK: `trade_executions(frame_id, signal_ts) → trade_frames(frame_id, signal_ts)`
7. Enable compression: `compress_segmentby = 'symbol,tf'`, `compress_orderby = 'signal_ts DESC'`
8. Add compression policy: `INTERVAL '7 days'`

**Writer update is mandatory with step 5:** Adding `signal_ts` to `trade_executions` as a non-nullable FK anchor breaks every existing INSERT into that table. Update `lifecycle_replay.py`'s market-track INSERT (line ~1044) to include `signal_ts`, sourced from `trade_frames.signal_ts` for the given `frame_id`. Verify with a dry-run INSERT on a test row before committing the migration. Any other writer that INSERTs into `trade_executions` must be updated in the same commit.

### D-03: Corpus rebuild execution order — fixed, follow exactly

1. **TRUNCATE** using fixed `reset_pipeline_data.py` (B4 fix applied — CASCADE)
2. **Backfill:** `run_historical_pipeline.py --replay-only --include-rolled --client-id 40 --workers 8` (all Phase 131 fixes applied, including A7 DB seed)
3. **Lifecycle:** `lifecycle_replay.py --workers 8 --commit-every 500`
4. **Verify:** `_verify_replay` must pass with `stale_unresolved=0`, `target_no_pnl=0`, `orphan_signal_events=0`

**A7 cold-start after TRUNCATE:** The A7 DB seed queries `intelligence_features` for prior I3 state before the first bar of each symbol. After TRUNCATE, there are zero rows — the seed finds nothing. Bar 1 of each (symbol, TF) — 316 bars total — starts cold with ctf_score=0.0. This is correct behavior (no prior state exists) and does not indicate a broken A7 fix. The ctf_score distribution gate (≥85% of non-null rows with ctf_score > 0.05) is computed over the full corpus and these 316 cold-start bars have negligible impact.

### D-04: Corpus acceptance criteria (hard gates — all must pass before Phase 133 is complete)

- `signal_events` count: ~1,036,513 (within 2% of baseline)
- Distinct plugins firing: 35 of 35 eligible (CrossAssetDivergence formally excluded per Phase 131 D-02; any other zero is a bug)
- All active-contract symbols present in `signal_events` (FX model-gap instruments excluded per Phase 131 D-05)
- `context_features` coverage: ≥99%
- `ctf_score` distribution non-degenerate: ≥85% of non-null rows have `ctf_score > 0.05`. **Do not use a null check** — the broken corpus has ctf_score=0.0 (not NULL) for all rows; a fix that still produces 0.0 passes a null check but fails this gate. The 316 cold-start bars (79 symbols × 4 TFs, bar 1 each) are expected to have ctf_score=0.0 after TRUNCATE because the DB seed finds no rows to read from — this is correct behavior and does not affect the 85% gate.
- `stopped_at_entry` outcome rate: <5% of stop exits — query `SELECT exit_reason, COUNT(*) FROM trade_executions GROUP BY 1` AFTER `lifecycle_replay.py` completes on the full corpus; `stopped_at_entry` is written by lifecycle_replay (not the backfill script) so this query is invalid before lifecycle_replay runs
- `trade_frames` confirmed as hypertable: `SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name = 'trade_frames'`
- `setup_performance`: 0 rows expected (populated post-CounterfactualTracker v2.11)
- `counterfactual_pnl_r`: 0 non-null expected (v2.11 dependency)

### D-05: Script cleanup items (B2/B3/B4/B5/D) — implement before rebuild, not after

These are prerequisites for a clean rebuild, not post-rebuild cleanup:
- **B4** (TRUNCATE CASCADE): fix `reset_pipeline_data.py` before running TRUNCATE
- **B5** (remove `--warmup`): dead code, confirmed no-op; remove from `run_historical_pipeline.py` before rebuild
- **B2** (asyncpg transaction hygiene in `lifecycle_replay.py`): use `async with conn.transaction():` — asyncpg's context manager handles COMMIT/ROLLBACK including exception paths. Do NOT use manual `await conn.execute('COMMIT')` in finally blocks — if that execute raises, the transaction stays open silently
- **B3** (`feature_replay.py` stateful coverage): use `incremental_compute()` with per-symbol state accumulation — stateless shortcuts produce wrong outputs for GARCH/Kalman/HMM/BOCPD. Note: `feature_replay.py` is the validation tool, not the main rebuild script (`run_historical_pipeline.py`); fixing it ensures the post-rebuild validation tool works correctly
- **Layer D** (code hygiene): `_cfg()` → `_read_config()`, `confidence_utils.py` → `confidence.py` (run `grep -r "confidence_utils" .` across the entire repo — not just `src/` — to catch references in CLAUDE.md files and docs before committing), delete phase_127 snapshot scripts, archive `migrate_signal_ledger.py`

### D-06: C2 column naming archaeology is NOT needed before the rebuild

The rename is already done (D-01 above). Phase 133 is not blocked by any column naming investigation. Start with C1 (hypertable migration) immediately.

### Claude's Discretion

- Whether to run B3 (`feature_replay.py`) fix in Phase 133 or Phase 131 — prefer Phase 133 since it's infrastructure cleanup and the corpus rebuild is the consumer; Phase 131 focuses on signal generation bugs
- Migration numbering for C1 hypertable conversion — use next available after Phase 132 migrations
- Whether to run `EXPLAIN ANALYZE` on the B6 backfill integrity assertion SQL before the rebuild to pre-diagnose the timeout — yes, do this proactively; cheaper than discovering it mid-rebuild

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary Spec
- `docs/plans/2026-06-17-phases-131-133-signal-corpus-integrity.md` §"Phase 133" — full execution order, all B/C/D items, corpus acceptance criteria
- `docs/plans/2026-06-17-phases-131-133-signal-corpus-integrity.md` §"Sequencing Summary" — phase dependency chain

### Hypertable Migration
- `.planning/todos/pending/2026-06-16-trade-frames-hypertable-migration.md` — C1 8-step sequence with schema changes

### Column Naming (verification reference)
- `src/intelligence/schemas.py:36-41` — functional-name mapping dict; confirms DB column names are already correct

### Phase Dependencies (read Phase 131 and 132 CONTEXT before planning)
- `.planning/phases/131-signal-generation-integrity/131-CONTEXT.md` — all signal bug fixes Phase 133 depends on
- `.planning/phases/132-stop-zone-geometry-apr-migration/132-CONTEXT.md` — stop geometry fixes Phase 133 validates

### Script Targets
- `production/scripts/reset_pipeline_data.py` — B4 TRUNCATE CASCADE fix
- `production/scripts/run_historical_pipeline.py` — B5 remove `--warmup`; also the A7 seed fix from Phase 131
- `production/scripts/lifecycle_replay.py` — B2 asyncpg transaction hygiene, B7 verify SQL fan-out fix
- `production/scripts/feature_replay.py` — B3 stateful `incremental_compute()` fix

### Validation
- `docs/plans/phase-127-validation-report.md` — baseline corpus measurements for Phase 133 acceptance gate comparison

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lifecycle_replay.py._verify_replay()` — the post-rebuild integrity gate; B7 fix makes the totals trustworthy (add `COUNT(DISTINCT se.signal_id)`)
- TimescaleDB hypertable creation pattern already used by `signal_events` and `intelligence_features` — follow same DDL pattern for `trade_frames`

### Established Patterns
- Phase 130 TRUNCATE approach — `reset_pipeline_data.py` already exists; B4 is a one-line replacement of the per-table loop with a single CASCADE statement
- `incremental_compute()` in `feature_replay.py` already exists but is not being called; B3 is switching from `compute_full()` to `incremental_compute()` with state dict maintenance

### Integration Points
- C1 hypertable conversion requires `trade_executions.signal_ts` column be added (FK anchor denormalization); this changes the `trade_executions` schema. Check that Phase 131/132 lifecycle replay and signal writer code don't break with the new column.
- B4 CASCADE TRUNCATE will cascade to `signal_ai_enrichment`, `instrument_annotations`, and any other FK dependents — verify the cascade scope with a dry-run before executing.

</code_context>

<specifics>
## Specific Ideas

- Dry-run verification for B4: `BEGIN; TRUNCATE TABLE signal_events, trade_frames, trade_executions CASCADE; ROLLBACK;` — check what rows would be affected before committing.
- B6 backfill integrity crash: run `EXPLAIN ANALYZE` on the assertion SQL BEFORE the rebuild. If it's a full-table scan, batch it by symbol or chunk by time window. Don't discover this mid-rebuild.
- After rebuild, the definitive acceptance check: `SELECT setup_plugin, COUNT(*) FROM signal_events GROUP BY 1 ORDER BY 2` must show 35 distinct plugins (not 30 as in the current corpus).

</specifics>

<deferred>
## Deferred Ideas

- CounterfactualTracker daemon — v2.11; populates `counterfactual_pnl_r` on live signals after corpus is clean
- `setup_performance` refresh — requires 30+ labeled signals per setup; post-CounterfactualTracker
- GIN index on `context_features`/`factor_scores` — deferred from Phase 128; add only if ML queries filter JSONB inline (check query patterns at Phase 134+)
- FX-specific plugin tuning for EURUSD/GBPUSD/USDCHF/USDJPY — future milestone; FX model gap documented, not addressed here
- ML training (Phase 134+) — not in scope until all Phase 133 acceptance criteria are green

</deferred>

---

*Phase: 133-clean-corpus-rebuild*
*Context gathered: 2026-06-17*
