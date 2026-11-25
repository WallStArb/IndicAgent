---
status: pending
priority: P2
filed: 2026-11-24
source: indicagent-3d, todo 470 merged into 471 (ruled by the lead 2026-11-24)
---

# ic_measure resumes at (job, tf) grain: a kill loses the whole unit, and every run pays a digest pass

## What

(Todo 470, merged.) A unit is (job, tf) and owns its whole scope: a kill loses its computed cells, and every run makes one fetch-and-digest pass over the whole feature family before the skip decision. At 1d this is small (a unit about two to five minutes, the digest pass about 40 percent of a 7-minute 925-name run, measured 2026-09-30; about 1.5 hours at the 12,857-name universe by linear scaling, not measured). At the intraday tfs a unit is hours (15m about 15 hours and 5m about 45 hours by the same scaling, order of magnitude only), so a kill is unaffordable. The `--start` orphan-row defect is fixed (review fix F2, 2026-09-30).

## Done when

Score rows are checkpointed per horizon or per feature block under the unit key and a resume skips the completed ones, and the column digests are cached by the feature table's content watermark if the digest pass is measured to matter (it is measured on the 25 pilot names after the block 2 rerun, light). Resume gives the same rows as an uninterrupted run (a test kills a unit mid-way and compares).

Prerequisite of the scope-all pin; does not block the scope-1d pin. Related: 667 (time-chunk mode), 471 (width ruling).

## Design notes 2026-11-24 (indicagent-fb; no code edited)

Today a unit is (job, tf) and `execute_unit` calls `unit.compute()` for all rows, then one `bulk_load` replaces the prior identity (`services/ic_measure.py:909`); a completed identity is skipped before any compute (`completed_provenance_batch`). A finer grain has to keep that single-writer, replace-where contract, so a checkpoint is a compute cache, not a partial write to the result table.

Proposed mechanism: a per-unit spool of finished cells.
1. Cell grain: one (horizon, feature block) cell of the scan (`feature_blocks`, `scan_family`). After a cell's rows are computed (`_sorted_rows` order), write them to a spool file under `logs/` keyed by the unit key, the cell's horizon and block names, and the input digests the unit already computes (`column_digest`, `features_digest`, `panels_digest`, `labels_digest`); a cell file is valid only for its own digests, so a changed input recomputes it and never reuses a stale one.
2. Resume: `unit.compute()` loads each valid cell file and computes the rest, then assembles the same row list in the same order and hands it to the one `bulk_load`. Resume therefore gives the same rows as an uninterrupted run by construction, and the test is a kill mid-unit against a full run compared row for row.
3. The digest pass (todo 470's other half): cache `column_digest` per column keyed by the feature table's content watermark, only if the pilot measurement shows the pass matters (about 40 percent of a 25-name 1d run at 925 names; light at 25). A wrong cached digest would let a changed column pass as unchanged, so the watermark must be a content digest of the stored column range (the month-granular `bar_content_digests` pattern), never a row count or a timestamp.
4. 667 interaction: with the strided-row gather, the cell grain moves to (horizon, chunk, block); the spool key adds the chunk, and pass 1's mask is itself a cached cell.

Spool cleanup follows the clean-as-you-go rule: a unit's spool is deleted once its `bulk_load` completes. Failure mode to test: a spool file from a killed write (partial) must fail its digest and recompute, not load.

## Build spec 2026-11-24 (indicagent-fb; ready to build once the pin is quiet; supersedes the mechanism sketch above where they differ)

Read from `services/ic_measure.py`: the proposer unit makes one `term_structure` per feature block over all horizons (`compute_proposer_rows`), merges the blocks, then runs Benjamini-Hochberg once over the whole family, so the block, not the horizon, is the checkpoint cell for it; the regime_volatility unit makes rows per (block, horizon) and the monitoring unit per block. A cell therefore stores the block's result, never final rows, and the FDR and row assembly always run after all cells are loaded.

1. Module `services/ic_measure_spool.py` (new, one job: persist and load cell results; no statistic). A cell file is `logs/ic_measure_spool/<unit_key>/<job>-<block_index>-<first_name>.npz`, written to a temporary name and renamed, so a kill never leaves a half file under a final name. Format: numpy `.npz` for a `TermStructure` (arrays: `ic`, `n_obs`, `p_value`, `peak_horizon`, and the proposer `IcCell` arrays; names and horizons as string and int arrays) and for the rows of the disclosure and monitoring cells a column-wise `.npz` of the row tuple fields (datetimes as int64 ns, `None` as a mask array). No pickle.
2. Key: the directory is the unit's `unit_key` from `spec`, which already hashes the job, the bars and panels digests, every column digest, the APR snapshot and `job_code_key(job)` (`_spec`, `_identity`). A changed input, parameter or the module's own code changes the unit key, so an old file is never read; no per-file digest is needed. Inside the file the block's names and the width are stored and compared on load; a mismatch recomputes.
3. Integration: `compute_proposer_rows`, `compute_disclosure_rows` and `compute_monitoring_rows` take an optional spool (None keeps today's behavior and the unit tests as they are). Per block: load the cell if present and valid, else compute and write it. `UnitPlan.compute` receives the spool built from the spec; `execute_unit` deletes the unit's directory after `bulk_load` returns `loaded` or `replaced`, and `skipped` runs leave nothing. A `--no-spool` flag and an APR switch are not needed: the spool changes no value.
4. Resume equivalence (the Done-when test): run a unit with a fake block fetch, kill after k cells (raise in the fetch), rerun with the same spool, and assert the rows equal an uninterrupted run, element for element, including the FDR columns; a second test truncates one cell file mid-write (partial temp name present, no final file) and asserts it recomputes; a third changes one column and asserts the old directory is ignored. Bit-identity holds because each cell is a deterministic function of its inputs and is stored losslessly (float64 arrays).
5. Digest pass: leave it alone in this build. It is needed to form the unit key, so a cell cache cannot skip it; caching `column_digest` by a content watermark of the stored column range is a separate step, taken only if the 25-name pilot measurement (todo 471 Done-when) puts the pass above a quarter of a run.
6. Landing: `services/ic_measure.py` is not in `writer_code_modules()` (checked 2026-11-24, 61 modules, none under `measure`), so `rebuild_code_key()` does not move; but `job_code_key` hashes it, so every IC unit key changes on this edit: land it before the 186-28 IC run is created, never during one. No edit under `src/intelligence/research` or `statistics`. Gates: unit suite, `ruff`, `black`, glossary, `/simplify`, an independent review, and the metric `job_completed_total` unchanged.
7. Compatible with 667: when time chunking lands the cell id gains the chunk index and the pass 1 mask becomes a cached cell with the same key rule.

Failure modes the build must refuse: a spool read when the unit key differs (impossible by directory), a cell loaded for a different block width (compare stored names), a spool left behind after a completed load (cleanup test), two runs writing one unit directory (the temporary-name-then-rename write makes concurrent writers of the same cell harmless because both write identical bytes; if the build finds that is not so, take a file lock from `src/core/file_lock.py`).
