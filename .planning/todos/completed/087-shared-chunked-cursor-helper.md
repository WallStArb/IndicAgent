---
**Created:** 2026-07-09
**Completed:** 2026-07-13
**Area:** services (ic_engine.py OOM-mitigation infra)
**Type:** reuse/DRY
**Priority:** P2
**Effort:** S
**Benefit:** One reusable, tested primitive for the "buffer rows -> float32 chunk -> vstack once"
idiom instead of two independently hand-rolled copies; the next symbol/tf-shaped OOM fix
doesn't need to rediscover this from scratch
**Risk:** low — pure bookkeeping extraction, query/cursor/pagination mechanics untouched at both
call sites, full unit suite green
---

## Resolution (2026-07-13)

Built `Float32ChunkAccumulator` in `services/_batch_utils.py` (TDD'd:
`tests/unit/test_batch_utils.py::TestFloat32ChunkAccumulator`, 6 tests) and wired it into both of
the two call sites that actually share the idiom:

- `_compute_symbol_tf` — row-by-row streaming cursor, now calls `acc.append_row(r[2:])` per row
  and `acc.finalize()` once instead of hand-rolling `buf_X`/`X_chunks`/`np.vstack`.
- `_compute_cross_sectional_tf` — whole-batch-per-query-chunk, now calls
  `X_acc.append_chunk(...)` per chunk and `X_acc.finalize()` once, replacing its own
  `X_chunks`/`np.vstack` bookkeeping. The `ret_chunk`/`cmp_chunk` matrices (different dtypes,
  NULL-substitution logic) are NOT the same shape as the X-matrix idiom and were correctly left
  alone — folding them in would be a premature abstraction, not a real dedup.

**Scope correction from the original filing:** `ensemble_ic_engine.py`'s pooled worker fetch
(the todo's 3rd example) does **not** get folded into this helper. On inspection its named
cursor + itersize setup is superficially similar, but its consumption loop reduces via
`_aggregate_pooled_series` as a generator and never materializes a chunked float32 matrix at
all — a genuinely different shape (streaming reduce vs. full materialization), not an instance
of the same idiom. Forcing it into `Float32ChunkAccumulator` would have required either warping
the accumulator's interface to support a non-materializing mode it doesn't need, or discarding
the memory-efficiency property that is the entire point of that function's own OOM fix. Left
untouched, exactly as it was before this todo — the two-implementation dedup the code actually
supports, not the three the original filing counted.

Verified: `tests/unit/test_batch_utils.py` (15 tests) + all 16 `ic_engine.py`-touching unit test
files (146 tests total) pass unmodified; ruff/black clean on all 3 changed files; full
`tests/unit/` suite green apart from the pre-existing unrelated
`test_no_smooth_or_backward_in_factory` failure (unaffected by this change).

# 087 — Shared chunked-cursor-to-numpy helper

Filed 2026-07-09 from the `/simplify` 4-agent review of that day's `ic_engine.py` per-symbol OOM
fix. See git history for the original filing text (full 3-site inventory, unchanged by this
resolution's scope correction above).
