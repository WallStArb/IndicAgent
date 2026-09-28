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

## Unified design adopted 2026-09-26

The `alpha_publisher` instance of the duplicated chunk-flush pattern goes away when phase 186 replaces `alpha_publisher` (adopted unified design, todo 436, section 14); the remaining instances stand.



## Refactor map (2026-09-26)

Folded into refactor map item 3 of the adopted unified design (section 14.6), scoped into phase 186: the duplicated chunk-accumulate-flush pattern is replaced by the single bulk-load primitive.

## Closed 2026-09-28 (phase 186 plan 06)

`bulk_load()` streams rows by COPY without materializing the iterable (commit
`98bdcc466`): accumulate-and-flush no longer exists for new writers, so no
`chunked_executemany` helper is needed. Call-site dispositions: the `alpha_publisher`,
`alpha_frame_writer` and `counterfactual_tracker` instances are deleted in 186-19 with
the rest of the old ensemble chain; no live instance is converted.
