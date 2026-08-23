---
status: pending
priority: P3
filed: 2026-08-23
source: /simplify's reuse-angle review of the alpha_publisher.py OOM fix
---

# Accumulate-and-flush-at-chunk_size pattern independently duplicated 4x across services/, no shared helper

## What

`services/alpha_publisher.py::_flush_chunk` (this session's fix), `services/alpha_frame_writer.py::_process_partition`, and `services/counterfactual_tracker.py` all implement the identical inline shape: `chunk: list[tuple] = []`, append per row, `if len(chunk) >= chunk_size: executemany(...); chunk.clear()`. None calls a shared helper because none exists -- `services/_batch_utils.py` has `bulk_update_by_key` (COPY+JOIN-UPDATE, different semantics) and `Float32ChunkAccumulator` (numpy-array-specific, ic_engine.py only), neither a fit for this simpler INSERT-executemany-chunking shape.

## Why not fixed now

Confirmed not a reuse bug in the diff that surfaced it -- `_flush_chunk` follows the repo's existing (if duplicated) convention rather than skipping an available utility. Extracting a shared helper would mean touching 3 other already-live, well-tested batch writers outside today's diff -- exactly the kind of broader refactor CLAUDE.md's simplify-scope-discipline says to leave alone during a targeted fix.

## Fix (if picked up)

A `chunked_executemany(pool, sql, chunk, chunk_size)` (or similar) primitive in `services/_batch_utils.py`, matching `bulk_update_by_key`'s precedent of centralizing a repeated batch-write shape. Migrate all 3+ call sites onto it in one dedicated pass, not piecemeal.
