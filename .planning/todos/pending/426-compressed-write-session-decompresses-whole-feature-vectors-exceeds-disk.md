---
status: pending
priority: P1
filed: 2026-09-25
source: pre-flight check before todo 421's 1d refresh (performance-investigation SOP: measure first)
---

# compressed_hypertable_write_session on feature_vectors now needs more disk than exists

## What

`services/_batch_utils.py::compressed_hypertable_write_session` decompresses every compressed
chunk of the hypertable on entry and recompresses on exit, with no disk-headroom check.
Measured 2026-09-25: `feature_vectors` is 88 GB (83 of 86 chunks compressed); its chunks'
`before_compression_total_bytes` sum to 491 GB (75 GB compressed). The filesystem has 414 GB
free. Entering the session on `feature_vectors` would need about 416 GB more: a disk-full
incident of the 2026-08-13 shape (migration 312, 768 GB) before a single row is written.

Callers on `feature_vectors`: `regime_writer.py` (corpus orchestrator step 2, both families),
`backfill_feature_factory.py` compute stage (every `--refresh`, and any compute that writes),
`ops_stale_k3_hmm_fields_cleanup.py`, `ops_ctf_columns_recompute_15m.py`,
`ops_regime_null_out_and_verify.py`. It worked on 2026-08-15 (regime_writer, 85 chunks) at a
smaller table size; the table has grown since.

Blocks: todo 421's velocity backfill, todo 411's catch-up, and any corpus orchestrator run.

## What to do

1. Guard (loud, cheap): before decompressing, sum `before_compression_total_bytes` of the
   chunks it will decompress and raise unless free space minus that stays above an APR reserve
   (`infra.*`), the same shape as ic_engine's scratch-headroom check. Test with a fake stats row.
2. Fix: decompress, write, recompress and VACUUM one chunk at a time (callers pass rows grouped by
   chunk time range, or the session exposes a per-chunk context), so peak extra disk is one
   chunk (about 6 GB) instead of the table. A 1d-only write still touches every chunk, since
   compression segments by (symbol, tf) inside time chunks, but only one is decompressed at once.
3. Both edit `_batch_utils.py`, which ic_engine and the phase 179 harness import (code key):
   never while an ic_engine run or a 179 stage run is live or resumable.
