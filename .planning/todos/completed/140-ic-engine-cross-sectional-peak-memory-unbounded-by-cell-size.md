---
status: closed
priority: P2
filed: 2026-07-19
moved_to_deferred: 2026-07-19
closed: 2026-07-23 — shipped via Phase 162-01 as SC-6
source: /simplify altitude review of commit be74f4a1 (ic_engine cross-sectional OOM fix)
---

**CLOSED 2026-07-23 (Phase 162-01, ROADMAP success criterion 6):** the chunking invariant this
todo asked for now extends into the compute stage — option (a), feature-axis chunking (never
the time axis, which would silently change the rank statistic; see ROADMAP Phase 162's risk #8).
`_subsample_and_rank` processes rank/IC/CI/fold work in bounded feature blocks
(`alpha.ic.feature_block_columns`, migration 249), capping peak transient at
`O(n_sub x block)` instead of `O(n_sub x n_features)`, verified bit-identical to the unblocked
path on a reference cell. Option (b) (a hard cap) also shipped as a backstop: `CellTooLargeError`
raised via `alpha.ic.max_cell_rows` — a cell above the cap fails loudly, never silently routes to
a degraded algorithm. Both tested (`test_cell_too_large_error_raised_by_both_cell_functions`,
`test_subsample_and_rank_feature_blocked_matches_unblocked`).

**Moved to deferred/ 2026-07-19:** folded into ROADMAP **Phase 162 "ic_engine Corpus Pipeline
Throughput"**, plan 162-02 (same functions the fingerprinting rework already touches) --
listed as success criterion 6 in that phase's design. Not an independently-actionable
pending/ item. Revive at `/gsd-plan-phase 162`.

# `_compute_cross_sectional_tf`/`_compute_symbol_tf` peak memory still scales with cell size, unbounded

## Finding

Two incidents now, same root pattern: 2026-07-08 (fixed by switching `X_raw` to
float32, "halved memory rather than bounding it") and 2026-07-18 (fixed by
`be74f4a1`: float32 rankdata casts + view-slicing instead of fancy-indexing,
roughly halving peak memory again). Both fixes reduced the constant factor;
neither changed the underlying scaling law. `_compute_cross_sectional_tf` and
`_compute_symbol_tf` still materialize the entire cell's feature matrix
(`X_raw`/`X_nd`, full timestamp count x ~150 features) before the per-scale loop
starts, and the per-scale loop still allocates several more full-cell-sized
arrays on top of that. Peak memory is `O(cell_size x n_features x const)` with a
smaller `const` than before, not a hard bound. A cell ~2x today's largest
(5m/low_bull, ~599K timestamps) reproduces the identical OOM by the same
mechanism as the corpus grows.

Notably, the DB fetch side already has the right pattern one stage upstream:
`cs_chunk_ts` (migration 183) bounds fetch memory to `O(chunk_rows)` regardless
of cell size. That chunking invariant stops at assembly — once `X_raw`/`X_nd` are
built in memory, the per-scale compute loop (rankdata, subsample, bootstrap CI)
operates on the whole assembled cell at once, not per chunk.

## Fix

Extend the chunking invariant into the compute stage: either (a) stream the
per-scale rankdata/subsample/bootstrap-CI work over row-blocks instead of
ranking/subsampling the whole cell in memory, or (b) enforce an APR-configured
hard cap on cell size (e.g. `alpha.ic.max_cell_size`) that routes oversized cells
through a chunked/streaming path instead of the current single-shot path. Not
urgent today (be74f4a1 bought real headroom, and the corpus isn't at the next
OOM threshold), but this is the third-incident-shaped problem — worth doing
before the corpus grows into the next crash rather than after.
