---
status: completed
priority: P2
filed: 2026-11-04
source: /review of the feature_vectors one-name swap (todo 584 items 3 and 4, migration 570)
---

# Retire the v1 feature_vectors in-place writers

## What

Since migration 570, `feature_vectors` is the kernel table, and its one writer is the rebuild's
`bulk_load` (D-24). It computes regime and regime_volatility in the same pass (R-10). The v1-era
writers below still target the name with in-place UPDATEs. Each would overwrite the rebuild's
walk-forward labels behind provenance that still names the rebuild, so S0's B1j check would pass
over mutated values. They are now refused loudly, because `feature_vectors` left
`_WRITE_SESSION_HARDENED_TABLES` and `bulk_update_by_key` refuses a compressed hypertable without a
session. Refused but kept, they are dead code that reads as live:

- `services/regime_writer.py` (no unit installed)
- `scripts/ops/corpus/ops_regime_null_out_and_verify.py`
- `scripts/ops/corpus/ops_stale_k3_hmm_fields_cleanup.py`
- `scripts/ops/corpus/ops_ctf_columns_recompute_15m.py`

Retire them as one block. Do a repo-wide grep first, then repair the allow-lists that name them:
`tests/unit/test_feature_vectors_read_boundary.py`, `test_compressed_hypertable_write_boundary.py`,
`test_single_writer_registry.py`, `tools/vulture_whitelist.py` and the docs that cite them.
`regime_coverage_auditor` stays: it reads the kernel table's `regime` column.

## Done when

The four files and their tests are gone, every reference is repaired (CI-enforced), and the
single-writer registry lists `bulk_load` as the only writer of `feature_vectors`.

## Closed 2026-11-04 (indicagent-cb; migration 576)

- Deleted: `services/regime_writer.py`, `ops_regime_null_out_and_verify.py`,
  `ops_stale_k3_hmm_fields_cleanup.py`, `ops_ctf_columns_recompute_15m.py`,
  `ops_regime_monitor.sh`, their writer-only tests, the three `regime_writer_*` metrics, the
  `indicagent-regime-writer` service-auditor entries, and the dead v1 `FEATURE_VECTOR_UPSERT_SQL`
  plus its psycopg variants (the in-place recompute path).
- Moved, not lost: kernel-function tests now import `kernels/_hmm.py` directly
  (`tests/unit/intelligence/test_hmm_*.py`); the writer's full-series bar fetch is
  `services/_batch_utils.fetch_tradeable_series` (same SQL, block size now APR
  `infra.tradeable_series.fetch_block_rows`), used by the refusal screen, the coverage sweep and
  the golden capture. Migration 576 retires `infra.regime_writer.workers` and seeds that key.
- Sole writer, three layers: `tests/unit/test_feature_vectors_writer_boundary.py` (the single-writer
  registry's write scanner), `BulkLoadSpec` refusing any writer but the rebuild for
  `feature_vectors` (exact name, the reader's match) and any but `ic_measure.<job>` for
  `feature_ic_scores` (`SOLE_BULK_LOAD_WRITERS`, tied by test to the writers' own constants), and
  no in-place write session on `feature_vectors`. The compressed-hypertable raw-UPDATE allow-list
  is now empty.
- Kept one cycle on purpose: `regime_writer` in `LIVE_RUN_PROCESS_PATTERN` (an older worktree's
  copy could still write). `ops_corpus_pipeline_run.sh` and `ops_pipeline_monitor.sh` still name
  the writer; both go with todo 593.

