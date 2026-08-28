# 288 - `feature_vectors` hypertable left fully decompressed after Phase 172's corpus relabel

**Filed:** 2026-08-09
**Source:** Phase 172 plan 172-05 (corpus-wide `regime_volatility` relabel) execution
**Status:** CLOSED 2026-08-28, both halves resolved by other work (see Closure section)

## The situation

Plan 172-05 hit a genuine TimescaleDB compressed-chunk write-cost blocker while relabeling
`feature_vectors.regime_volatility` corpus-wide — a third incident of the same shape as
CLAUDE.md-documented todos 149/161. A single-cell `UPDATE ... FROM <temp table>` write hung
indefinitely (`wait_event=IO/DataFileRead`) because 80/83 `feature_vectors` chunks were
compressed; TimescaleDB's compressed-chunk UPDATE path forces full-chunk decompression
regardless of WHERE/JOIN selectivity (`EXPLAIN` cost ~4.9M scanning all compressed chunks,
dropping to ~91k after decompression).

The plan's fix was to decompress the entire hypertable once (~24 min) before the staged
relabel, which unblocked the write and completed correctly with zero data loss. The corpus
was deliberately left decompressed afterward — recompression is a storage/ops tradeoff, not
a correctness requirement of that plan, so it wasn't done unilaterally mid-plan.

## What's needed

`feature_vectors` currently has 0/83 chunks compressed (was 80/83 before Phase 172). No active
compression policy exists to reverse this automatically. Decide and execute:
1. Re-enable/re-run compression on `feature_vectors` (if the storage cost of staying
   decompressed matters), or
2. Confirm decompressed is acceptable going forward given how often this table now gets
   batch-UPDATEd by regime/HMM relabels, and adjust the compression policy design so future
   batch UPDATE jobs don't hit the same wall (todos 149/161/this one are the same bug shape
   three times — the SOP already tells engineers to check chunk compression status as a first
   suspect, but nothing yet stops the hypertable from re-compressing into the same trap after
   the next relabel).

## Where

- `docs/foundation/performance-investigation-sop.md` — the existing SOP this incident confirms,
  a third time
- `.planning/phases/172-hmm-regime-volatility-only-redesign/172-05-SUMMARY.md` — full incident
  writeup with `EXPLAIN` costs and timings

## Closure (2026-08-28)

Closed on live verification, both option-branches of the "decide and execute" mooted:

1. **State restored, not by manual recompress:** `feature_vectors` is back to **85/85 chunks
   compressed** (verified live 2026-08-28 via `timescaledb_information.chunks`). The compression
   policy this file said didn't exist is present and scheduled -- todo 306's 2026-08-15 check
   first caught policy job 1065 recompressing everything after a crashed session left chunks
   decompressed mid-write, and the table has stayed compressed since.
2. **Systemic half addressed:** todo 306's `compressed_hypertable_write_session` /
   `async_compressed_hypertable_write_session` (`services/_batch_utils.py`) brackets a batch's
   writes as decompress-all -> write-all -> recompress-all + bare `VACUUM`, wired into every
   raw/`bulk_update_by_key` writer against `feature_vectors`/`feature_ic_scores`, with a CI
   guard (`tests/unit/test_compressed_hypertable_write_boundary.py`) against future bypasses.
   Future batch-UPDATE relabels no longer hit the compressed-chunk write wall this incident
   exemplified (the todos 149/161/288 failure shape).

"Confirm decompressed is acceptable going forward" is therefore moot as a standalone decision:
the policy auto-restores compression, and the write path no longer fights it.
