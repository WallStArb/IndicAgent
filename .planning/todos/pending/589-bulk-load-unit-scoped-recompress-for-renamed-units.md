---
status: pending
priority: P2
filed: 2026-11-04
source: /simplify altitude review of the feature_vectors one-name swap (todo 584 items 3 and 4, migration 570)
---

# bulk_load: rewrite a renamed unit inside a compressed chunk without decompressing the table

## What

Since migration 570 the rebuild writer compresses `feature_vectors` chunks at every stage end,
once no pending unit of the full scope can still write into them (`compression_bound` in
`services/backfill_feature_factory.py`). A completed unit can still be renamed after its chunk
compressed: under raw last-wins a restated bar moves the unit's input digest, an APR change moves
its snapshot, and onboarding a name reshuffles the symbol chunks. The next run then plans that unit
as pending, and `bulk_load` refuses it ("compressed chunk(s) ... overlap the unit range"). That is
a loud failure, never a silent write, but the only recovery today is a manual decompress of the
chunk.

The refusal lives in the shared primitive (`_bulk_load_precheck` in `services/_batch_utils.py`),
which is also why no writer can coexist with a scheduled compression policy. The general fix sits
at that depth: a unit-scoped path that decompresses only the chunks overlapping the unit range,
under the existing headroom guard (`check_decompress_headroom`) and write session
(`compressed_hypertable_write_session`), loads the unit, and recompresses those chunks in the same
call.

## Done when

- `bulk_load` can rewrite a unit whose range overlaps compressed chunks, decompressing and
  recompressing only those chunks, refusing when the headroom guard fails.
- Its tests cover the renamed-unit case end to end (restated bar after compression).
- The `compression_bound` docstring and the 584 item 4 note no longer describe the refusal as the
  recovery path.

Not urgent: the rerun writes into an empty table, and the refusal is loud. It matters from the
first restatement after the rerun's chunks compress.
