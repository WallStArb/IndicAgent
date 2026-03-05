# Phase 13: Data Completeness - Context

**Gathered:** 2026-03-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Add `i7 JSONB`, `i8 JSONB`, and `days_to_expiry INTEGER` columns to `intelligence_features`. Wire new enrichment streams so every bar written from this point forward contains complete signal, narrative, and temporal context — no permanently incomplete training rows.

</domain>

<decisions>
## Implementation Decisions

### i7 Content Shape
- **All ranked signals, not just the aggregator winner**
- Every setup that fired is a data point — the ML layer needs the full signal space, not just the aggregator's selection
- i7 JSONB per bar contains a list of all_ranked signals with: `setup_type`, `confidence`, `direction`, `regime_eligible`, `suppression_reason`, `entry`, `stop`, `target`
- Aggregator winner flagged via `is_winner: true` field on the winning entry (null on suppressed entries)
- Rationale: winner selection is a downstream inference task; the ML model learns which signals are worth selecting, which requires seeing everything the system considered

### i7 Stream Wiring
- **New enrichment stream: `intelligence_i7:SYMBOL:TF`**
- `signal_generator_service` publishes all_ranked to this stream after each aggregation cycle
- `feature_writer_service` subscribes and UPSERTs `i7` column (ON CONFLICT DO UPDATE)
- Clean separation from `signals:SYMBOL:TF:aggregated` (winner-only, consumed by ai_narrative) — no changes to existing stream contracts
- New stream added to feature_writer's concurrent `xreadgroup` call alongside existing `intelligence:SYMBOL:TF` streams

### i8 Binding
- **New enrichment stream: `intelligence_i8:SYMBOL:TF`**
- `ai_narrative_service` publishes metadata-only payload to this stream when narrative is generated: `{model, confidence, summary, signal_id, generated_at}`
- Full narrative text stays in `narratives:SYMBOL:TF` (unchanged — consumed by API/dashboard)
- `feature_writer_service` subscribes and UPSERTs `i8` column
- Bars with no narrative: i8 stays as default `'{}'` — sparse is correct, never approximate

### i8 Sparsity Policy
- **Empty `{}` default, never null** — `i8 JSONB NOT NULL DEFAULT '{}'`
- Most bars (low-conf signals, 1m bars, non-LLM-eligible TFs) will have empty i8 — this is expected and correct
- ML model handles sparse JSONB features natively; no imputation needed
- No attempt to synthesize i8 from group narratives — group synthesis is not per-bar

### Historical Rows Migration
- **Accept `{}` for all pre-migration rows** — no retroactive backfill
- Existing ~482K rows get empty i7/i8 via `DEFAULT '{}'` — honest absence, not noisy approximation
- A signal_ledger JOIN backfill would approximate i7 but risks label leakage and doesn't recover i8
- Training dataset is labeled with bar `ts` — ML pipeline can exclude pre-migration rows or treat them as a pre-training regime distinct from fully-populated rows
- Migration adds columns non-destructively: `ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS`

### days_to_expiry Computation
- **Computed at feature_writer write time, not upstream**
- `get_active_contracts()` returns expiry strings (`"20260320"` for most, `"202604"` for VX)
- VX format `"YYYYMM"` → treat as last trading day of that month
- Non-futures (crypto, FX) → `0`
- Cache the expiry map at service startup — it only changes on contract roll (infrequent)
- Formula: `max(0, (expiry_date - bar_ts.date()).days)` — floor at 0, never negative

### DATA-03 Scope
- **feature_writer already uses a single concurrent xreadgroup for intelligence streams**
- DATA-03 work = adding the new `intelligence_i7:SYMBOL:TF` and `intelligence_i8:SYMBOL:TF` streams to the same concurrent call
- No separate "fix sequential polling" work needed — the fix was already applied in a prior refactor
- Verification: confirm lag metric drops below 2s after i7/i8 enrichment streams are added

### Claude's Discretion
- Exact UPSERT SQL for i7/i8 enrichment (whether to merge with existing row or overwrite the column)
- Whether `intelligence_i7` and `intelligence_i8` stream maxlen values (200 is reasonable)
- Consumer group naming for the new streams
- Whether to add GIN indexes on i7/i8 (yes — consistent with i1-i6 pattern, add in same migration)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `feature_writer_service.py:_INSERT_FEATURE_SQL` — existing SQL uses ON CONFLICT DO NOTHING; new i7/i8 enrichment uses separate UPSERT with DO UPDATE SET i7/i8
- `feature_writer_service.py:_stream_map` + concurrent `xreadgroup` — add `intelligence_i7` and `intelligence_i8` streams using same pattern
- `signal_generator_service.py:_process_bar()` — already collects all_ranked from aggregator; publish to new stream here
- `ai_narrative_service.py` — already publishes to `narratives:SYMBOL:TF`; add metadata-only publish to `intelligence_i8:SYMBOL:TF`
- `src/core/stream_keys.py` — add `intelligence_i7()` and `intelligence_i8()` key constructors following existing pattern
- `get_active_contracts()` in `src/config/settings.py` — returns `Instrument` objects with `expiry` field; use at feature_writer startup to build symbol→expiry_date lookup

### Established Patterns
- Enrichment via UPSERT: `ON CONFLICT (ts, symbol, tf) DO UPDATE SET col = EXCLUDED.col` — standard pattern for async enrichment that arrives after the base row
- Consumer groups: `ensure_consumer_group_with_reset(redis_client, stream, group)` from `src/core/stream_utils`
- Stream key constructors: `src/core/stream_keys.py` — all keys built via functions with `env_prefix` parameter
- JSONB columns: all tier columns (i1-i6) are `JSONB NOT NULL DEFAULT '{}'` with GIN index — i7/i8/smc follow identical pattern

### Integration Points
- `signal_generator_service._process_bar()` → add `xadd intelligence_i7` after aggregation
- `ai_narrative_service._process_signal()` → add `xadd intelligence_i8` after narrative generation
- `feature_writer_service._setup_consumer_groups()` → subscribe to 2 new stream patterns
- `feature_writer_service._process_message()` → handle new stream types with UPSERT (vs base INSERT)
- `production/migrations/016_data_completeness.sql` → new migration file

</code_context>

<specifics>
## Specific Ideas

- "Jim Simons would never throw away signal data" — all_ranked in i7, not just winner. The aggregator's current job (picking a winner) may itself be wrong; the ML layer should be able to learn better selection
- The `is_winner` flag inside i7 JSONB lets the ML model train on "what the current aggregator selected" as one feature among many — without hard-deleting the counterfactual signals
- days_to_expiry is a genuine regime feature: liquidity shifts 2-3 weeks before expiry, basis widens, roll behavior is predictable. Include it from day one even though the signal won't be obvious until we have multi-roll history

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 13-data-completeness*
*Context gathered: 2026-03-04*
