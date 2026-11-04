---
status: pending
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
