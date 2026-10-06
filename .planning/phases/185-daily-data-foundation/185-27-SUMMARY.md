---
phase: 185-daily-data-foundation
plan: 27
subsystem: bars / Tradier daily loader / D2 daily stage
tags: [D-06, D-07, D-08, D-12, tradier, lineage, digest, scrub, single_writer]
requires: [185-26]
provides: [tradier-v1 lineage, loader scrub and digests, D1 elision, new-and-changed-only canonical upsert, write_1d_digests, lineage/digest writer boundary, migration 441]
affects: [infrastructure_run_tradier_daily, bar_derivation daily stage, bar_derivation_batch, canonical_bar_lineage, bar_content_digest, ohlcv_observation growth]
tech-stack:
  added: []
  patterns: ["INSERT ... SELECT lineage upsert keyed on the latest equal observation, rewriting only rows whose rule or provenance changed"]
key-files:
  created:
    - production/migrations/441_bar_derivation_batch_tradier_stage.sql
    - tests/unit/scripts/test_tradier_daily_lineage.py
    - tests/unit/test_canonical_lineage_digest_writer_boundary.py
  modified:
    - src/intelligence/bars/sources.py
    - services/bar_derivation.py
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - tests/unit/scripts/test_tradier_daily_plan.py
    - tests/unit/services/test_bar_derivation_daily.py
decisions:
  - "D1 elision compares exactly (not within _VALUE_TOLERANCE): D1 is the raw record, so any vendor revision lands; the lineage match uses the loader's tolerance, and an elided bar is exactly equal, so the two rules never disagree"
  - "The role switch to bar_derivation_writer now happens on every accepted load (lineage needs it), after ohlcv_load/ohlcv_revision and the bar upsert; the split insert stays after it"
  - "A LineageGapError rolls the load back and the run records a separate 'failed' ohlcv_load row with the error as detail; the name counts as refused (exit 4), not a runtime error"
  - "Scrub set = loaded names with n_new + n_changed > 0 or a non-zero lineage rowcount; digests run for every loaded name; both after the fetch loop, under the run's one stage-tradier batch"
  - "The scrub pool is create_pool(min_size=1, max_size=1): scrub_symbols holds a single acquire, and the pool exists for the jsonb codecs; structural, not a tunable"
metrics:
  duration: 25min
  completed: 2026-10-06
  tasks: 2
  files: 8
---

# Phase 185 plan 27: Tradier write path gets lineage, scrub and digests; D1 grows by changes only

The Tradier loader now traces every stored Tradier 1d bar to its D1 observation at rule tradier-v1 inside the bar write's transaction, reruns the D2a scrub over the names it changed and writes fresh 1d digests after it, under one `stage tradier` batch. D1 and `market_data_ohlcv` receive only new and changed bars, and D2's own digests now follow its scrub.

## What changed

- Migration 441 (`bar_derivation_batch_stage_check` adds `tradier`), applied live and committed with the code. The live constraint now reads `... 'legacy'::text, 'tradier'::text`.
- `sources.py`: `CANONICAL_1D_SOURCES = ("ibkr_named", "ibkr_venue", "tradier")`, `TRADIER_RULE_VERSION = "tradier-v1"`.
- `services/bar_derivation.py`: `_write_daily_digests` lifted to module-level `write_1d_digests(conn, *, symbol, batch_id, rule_version)`, reading `_SELECT_DIGEST_1D_SQL` over `CANONICAL_1D_SOURCES`. D2's daily stage calls it once per derived symbol after `scrub_symbols`, appending failures to `failed` the way the scrub does. `_SELECT_STORED_1D_SQL` (D2's comparison) keeps its IBKR-only list. The dead synthetic_fill comments were removed; `_ARCHIVE_VERIFY_SQL` was left untouched (185-31 owns it).
- Loader:
  - `d1_bars_to_land` (pure) and `_SELECT_LATEST_OBSERVED_SQL` (one query per name). `_land_in_d1` keeps `n_bars` as the full answer length and lands only the kept bars. `--raw-only` and first loads land every bar.
  - `LoadPlan.writes` (new and changed bars). `_record_load` upserts only those, then runs `SET LOCAL ROLE bar_derivation_writer`, `TRADIER_LINEAGE_UPSERT_SQL` ($1 symbol, $2 batch_id) and the unmatched check (`_TRADIER_LINEAGE_UNMATCHED_SQL`), and finally the split insert. A non-empty unmatched list raises `LineageGapError`, the transaction rolls back, and the run records the load as `failed`.
  - A write run opens one batch (`stage tradier`, `tradier-v1`, APR snapshot `infra.tradier.*`). After the loop, `_scrub_and_digest` runs the scrub and then `write_1d_digests` for every loaded name. The batch closes `completed`, or `failed` with exit 1 when the scrub or a digest write raised.
  - The dead `source <> 'synthetic_fill'` filters were removed from `_SELECT_EXISTING_SQL`, `_SELECT_MISSING_SQL` and `_SELECT_NIGHTLY_SQL`.
- `tests/unit/test_canonical_lineage_digest_writer_boundary.py`: `canonical_bar_lineage` writers are `services/bar_derivation.py` and the loader. `bar_content_digest`'s only writer is `services/bar_derivation.py`. The test matches INSERT/UPDATE/COPY and `copy_records_to_table`, and checks for stale entries.

## Live three-name run (2026-10-06 12:59:45 UTC, `--symbols SPY,AAPL,XOM`)

A dry run came first: `{'loaded': 3}`, with totals new 0, changed 0 and d1_land 0. The live run then exited 0:

| Measure | Value |
|---|---|
| D1 observations landed | 0 (each of the three request rows has n_bars 6729 and 0 observations; the 12:36 nightly's requests, from the pre-change code, carry 6729 each) |
| market_data_ohlcv upsert rows | 0 (n_new 0, n_changed 0 on all three ohlcv_load rows) |
| canonical_bar_lineage at tradier-v1 | 6729 per name, 20,187 total (the earlier d2-v1 rows on these dates were rewritten; 0 non-tradier-v1 rows remain for the three names) |
| Stored tradier bars without tradier-v1 lineage (acceptance query) | 0 |
| Scrub | 3 names; per-rule counts ohlc_invariant 51, volume_outlier 8, vol_scaled_jump 2, return_magnitude 1, others 0; 1d flag rows per name unchanged (SPY 31, AAPL 9, XOM 23) |
| bar_content_digest rows at tradier-v1 | 966 (322 months per name; all current in bar_content_digest_current) |
| Batch | `661780d4-27a0-4cd1-a977-1ab30ea001a7`, stage tradier, rule tradier-v1, completed, n_symbols 3 |

## Verification

- Task 1 gate (`test_bar_derivation_daily`, `test_bar_derivation_batch`, `test_migration_number_uniqueness`, `test_market_data_ohlcv_writer_boundary`): passed.
- Task 2 gate (`test_tradier_daily_plan`, `test_tradier_daily_lineage`, `test_nightly_tradier_leg`, `test_market_data_ohlcv_boundary`, `test_canonical_lineage_digest_writer_boundary`, `test_compressed_hypertable_write_boundary`): passed. `test_market_data_ohlcv_scrub_input_boundary`, `test_bar_derivation_grid` and `test_bar_scrub` also passed.
- Full `pytest tests/unit/ -x`: exit 0. ruff and black are clean on every touched file.
- Not run: `repro_frozen`. No file under `src/intelligence/research/` or `statistics/` was touched.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 2 - Missing critical] The run records a rolled-back load as failed**
- The plan says an unmatched lineage count "raises inside the transaction so the load rolls back and is recorded failed". Recording it needs a second `_record_load` call after the rollback (outcome failed, detail = the error). `run()` catches `LineageGapError` only; any other exception stays a runtime error.
- Commit: 32842eaac

**2. [Rule 2] The dry run reports `d1_land`**
- The dry-run totals now include how many observations a write run would land. This is a read-only probe, and it was used before the live run.
- Commit: 32842eaac

**3. [Rule 3] Test fake for D2 digests**
- `FakeConn` in `test_bar_derivation_daily.py` now serves the new `source = ANY($2)` digest read and filters the IBKR comparison read by source.
- Commit: 1ffc77f06

No CLAUDE.md-driven adjustments were needed. The plan's "names to the scrub" rule was implemented as written.

## Constraints honored

- The HTF lane was not running during execution (no `intraday_chain` process; it was checked before editing). Neither modified module is in its import list. The lane's daily stage runs `bar_derivation.py` as a fresh subprocess, so the only effect there is that the digest write moves after the scrub. `services/ohlcv_observation_writer.py` was not edited; the elision happens on the loader side before `sink.on_observation`.
- Phase 189 files were not touched. 189-06's caller (`indicagent-tradier-daily.service`, JOB `tradier-daily`) was preserved, and this plan builds on its version of the loader.
- Unit tests use fakes only. The only live writes were migration 441 and the three-name run the plan specifies.
- `ohlcv_request.n_bars` consumers: `ops_intraday_venue_recovery.py` reads it for intraday venue routes only, and D7 (`_VENDOR_PAIRS_SQL`) and `listing_venue_writer` (`_OFFICIAL_CLOSE_SQL`) take the latest observation per date, so the elision changes none of their answers. No reader equates `n_bars` with an observation count.

## Notes for plans 185-28 to 185-35

- **185-30 (lineage/digest backfill):** the next Tradier nightly run (`indicagent-tradier-daily.service`) does this backfill for every name it loads. On its first post-change run, every loaded name gets a non-zero lineage rowcount, so all of them (about 1,266) go into one scrub call and then get digests. That covers the backfill for every owned name that loads cleanly. 185-30 still needs names whose latest refetch is refused (27 short_history on 2026-10-06, plus any gated): the loader writes no lineage for them. SPY, AAPL and XOM are already done.
- **185-30 / 185-33:** for a Tradier-owned name, d2-v1 lineage rows survive only on dates that have no stored tradier bar. For SPY, AAPL and XOM there were none. Across the full set, such rows are stale-lineage candidates for 185-33's check.
- **D1 volume already appended:** today's 12:36 UTC nightly ran the pre-change code and appended a full history for each of about 1,266 names (about 8M observations). Each owned name now holds about three full Tradier copies in D1. D1 is append-only and nothing was removed; growth from now on is changes only.
- **Batch `code_commit` carries `-dirty`:** another session's tracked edit (`docs/research/construction-verdict-ledger.md`) was uncommitted during the live run. `current_code_commit()` marks any tracked change as dirty, so any loader or D2 batch run from this shared checkout can carry the suffix.
- **Batch APR snapshot:** the loader's batch snapshots `infra.tradier.*` (per the plan). The scrub's `threshold.bar_scrub.*` values are not in it, the same gap D2's batch has (D2 snapshots only `infra.bar_derivation.*`). This is for 185-33 to decide if provenance should cover the scrub thresholds.
- **185-35 (ETHA nightly split check):** the split insert now runs after the lineage upsert and the unmatched check in the same transaction. The new-scale observations land in D1 before `_record_load`, so a split refetch lineages to the new observations.

## Known Stubs

None.

## Threat Flags

None. The role, grants and tables used were already in the threat model (T-185-27-04 accepted).

## TDD Gate Compliance

- RED: 1ffc77f06 (Task 1 tests) and 3b7e8363b (Task 2 tests), both failing before implementation.
- GREEN: 56e8158e3 (Task 1) and 32842eaac (Task 2).

## Commits

- 1ffc77f06 test(185-27): failing tests for the shared 1d digest writer and D2 digest-after-scrub
- 56e8158e3 feat(185-27): migration 441 tradier batch stage; shared write_1d_digests; D2 digests after its scrub
- 3b7e8363b test(185-27): failing tests for the Tradier loader's lineage, scrub, digest and D1 elision
- 32842eaac feat(185-27): Tradier loader write path traces, scrubs and digests; D1 lands changes only

## Self-Check: PASSED

All created files exist and all four commit hashes resolve in `git log`.
