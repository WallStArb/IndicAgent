# trade_frames → hypertable conversion (Migration 142)

**Phase:** Early Phase 130 (before CounterfactualTracker goes live in production)

## What
Convert `trade_frames` from a regular table to a TimescaleDB hypertable on `signal_ts`.

## Why
- Currently 851 MB uncompressed with no compression path
- Will grow 5x faster once CounterfactualTracker adds multiple entry_types per signal
- ML training queries (Phase 130+) will full-scan this table repeatedly for labeled data
- Compression with `compress_segmentby = 'symbol,tf'` expected 10-20x reduction

## Schema changes required
1. Drop `fk_trade_executions_frame` FK from `trade_executions → trade_frames`
2. Drop existing `trade_frames_pkey` (UUID-only PK)
3. Create new `signal_events`-style hypertable on `signal_ts` with chunk_time_interval = 7 days
4. Recreate PK as `(frame_id, signal_ts)` — hypertable composite PK requirement
5. Add `signal_ts` to `trade_executions` as FK anchor (denormalize, same pattern as trade_frames.signal_ts)
6. Recreate FK from `trade_executions (frame_id, signal_ts) → trade_frames (frame_id, signal_ts)`
7. Enable compression: `compress_segmentby = 'symbol,tf'`, `compress_orderby = 'signal_ts DESC'`
8. Add compression policy: INTERVAL '7 days'

## Timing
- Do BEFORE CounterfactualTracker starts writing in production (shadow mode window is safe)
- Do NOT block Phase 130 planning on this — it is an early Phase 130 task, not a prerequisite

## Related
- Migration 139 already dropped `fk_trade_frames_signal` (trade_frames → signal_events)
- Migration 141 added `idx_trade_frames_labeled` partial index (will survive hypertable conversion)
- Also re-create `idx_trade_frames_entry_type_pnl` after conversion once entry_type diversity exists
