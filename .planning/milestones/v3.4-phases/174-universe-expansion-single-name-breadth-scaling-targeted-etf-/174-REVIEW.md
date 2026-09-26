---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf-
reviewed: 2026-09-23T00:00:00Z
depth: standard
files_reviewed: 32
files_reviewed_list:
  - docs/research/phase174-down-cap-correlation-gate-verdict.md
  - docs/research/phase174-etf-gap-fill-ticker-selection.md
  - docs/research/russell3000-sourcing-and-delisted-feasibility.md
  - production/migrations/336_ic_engine_disk_backed_cell_apr_keys.sql
  - production/migrations/337_instruments_governance_split.sql
  - production/migrations/338_factor_and_vol_exposure_tag_taxonomy.sql
  - production/migrations/339_universe_sampling_apr_keys.sql
  - production/migrations/340_ic_engine_streaming_correlation_apr_key.sql
  - production/migrations/341_instruments_compute_eligible_1d.sql
  - production/migrations/342_universe_pilot_sample_size_apr_key.sql
  - scripts/analysis/instrument_compute_eligibility_audit.py
  - scripts/analysis/universe_expansion_correlation_structure_check.py
  - scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py
  - scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py
  - scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py
  - scripts/infrastructure/universe_expansion_pilot_draw.py
  - scripts/infrastructure/universe_expansion_promote_compute_eligible.py
  - scripts/infrastructure/universe_expansion_stratified_sourcing.py
  - services/_batch_utils.py
  - services/ic_engine.py
  - src/config/instrument_onboarding.py
  - src/config/settings.py
  - tests/unit/config/test_instrument_onboarding.py
  - tests/unit/config/test_settings_active_contracts_dimension.py
  - tests/unit/scripts/test_universe_expansion_correlation_structure_check.py
  - tests/unit/scripts/test_universe_expansion_fetch_iwv_holdings.py
  - tests/unit/scripts/test_universe_expansion_stratified_sourcing.py
  - tests/unit/services/test_service_contract_resolution.py
  - tests/unit/test_batch_utils.py
  - tests/unit/test_ic_engine_cell_memory_bound.py
  - tests/unit/test_ic_engine_clustering.py
  - tests/unit/test_ic_engine_streaming_correlation.py
findings:
  critical: 3
  warning: 7
  info: 7
  total: 17
status: issues_found
---

# Phase 174: Code review report

**Reviewed:** 2026-09-23
**Depth:** standard (Phase 174 hunks, `git diff e722a18f8^..e046ed5d2`, verified against current file state and the live DB)
**Files reviewed:** 32
**Status:** issues_found

## Summary

Reviewed the governance split (migrations 337/341, `get_active_contracts(dimension=)`), the onboarding helper, the universe-expansion scripts, the D-10 correlation gate, and the ic_engine disk-backed cell / streaming correlation work (migrations 336/340, `Float32ChunkAccumulator`).

The three critical findings:

1. The D-10 pre-registered gate silently passes when the correlation it tests is NaN. I confirmed this by running it.
2. The `live` dimension has no consumer. The IBKR provider still reads the default `compute` universe (233 symbols), so the 80-subscription-cap problem that motivated migration 337 is still open for the planned streaming restart (todo 366).
3. The disk-backed cross-sectional cell still makes a full-cell float64 copy in `np.std`, which undoes the bounded-memory guarantee at the scale this phase targets.

Several `is_active` readers now silently include the 40-symbol failed-gate pilot cohort. TagCalibrator has already written 218 empirical tag rows for 32 of those symbols.

Todo 386 (pre-flight estimate overstates rows, `alpha.ic.max_cell_rows` loosened to 100M) is not re-reported. The double-JSON-encoding bug fixed in eb32c339b is resolved. No similar encoding issue remains in `onboard_instrument`: every jsonb argument is a dict bound on a pooled connection.

## Narrative findings (AI reviewer)

## Critical issues

### CR-01: D-10 gate passes when the measured correlation is NaN

**File:** `scripts/analysis/universe_expansion_correlation_structure_check.py:129, 184, 196`

**Issue:** `correlation_structure()` returns `avg_pairwise_corr = float("nan")` when no pair clears `min_periods=20`. That happens when the coverage filter leaves 0 or 1 symbols, or when a regime slice has fewer than 20 overlapping rows. `evaluate_d10_gate()` fails closed only on `None`. For NaN, `nan > 0.10` is `False`, so the gate records no failed condition and returns `passed: True`, which gives exit code 0. I verified this directly: a 1-symbol unconditional frame plus a 10-row `high_bear` frame produced `{'passed': True, 'unconditional_corr': nan, 'high_bear_corr': nan, 'failed_conditions': []}`.

The docstring says the gate "fails closed ... never a pass by omission". Right now it passes by omission. The pilot's recorded FAIL verdict (0.3025 / 0.4303) is unaffected. Any future cohort run through `--gate` is exposed, especially small or sparse down-cap draws, where the 95% coverage filter already dropped 13 of 40 symbols.

**Fix:**
```python
def _gate_value(result, label, failed):
    v = result.get("avg_pairwise_corr") if result is not None else None
    if v is None or not math.isfinite(v):
        failed.append(f"{label} avg_pairwise_corr missing or non-finite ({v!r}) -- fails closed")
        return None
    return v
```
Use this for both thresholds. Also consider failing when `n_symbols < 2`. Add a unit test for the NaN case next to `test_gate_missing_high_bear_fails_closed`.

### CR-02: The `live` dimension has no consumer; the IBKR provider still subscribes to the full compute universe

**File:** `src/providers/base_provider_agent.py:482` (interacts with `src/config/settings.py:383-388`, `production/migrations/337_instruments_governance_split.sql`)

**Issue:** Migration 337 says it closes todo 274. Its header gives the reason for the split: an `indicagent-ibkr-provider` restart against an unsplit universe would breach IBKR's 80-simultaneous-subscription cap. `get_active_contracts(dimension="live")` was added, but a repo-wide grep finds no caller that passes it. `BaseProviderAgent._get_instruments()` calls `get_active_contracts(self.settings)`, which now means `compute`: 233 symbols today, with 0 `live_tradeable` rows. `provider_merger`, `feature_vector_pipeline`, and `bar_auditor` also use the default.

Live streaming is currently down (todo 366). When it restarts, the provider will request about 3x the cap and IBKR will reject subscriptions nondeterministically. That is the exact failure the migration says it prevents. No test covers this: `test_service_contract_resolution.py` only asserts call shapes.

**Fix:** In `BaseProviderAgent._get_instruments()`, return `get_active_contracts(self.settings, dimension="live")`. Then add a startup guard that fails loudly if `len(instruments) > <APR infra.ibkr.max_live_subscriptions>` or if the list is empty. Add a unit test that pins `dimension="live"` for the streaming provider. Decide explicitly which dimension each of the other default-dimension daemons should use instead of inheriting `compute`.

### CR-03: The disk-backed cross-sectional cell still allocates a full-cell float64 copy in `np.std`

**File:** `services/ic_engine.py:3984` (also `4347`)

**Issue:** Plans 05 and 09 claim peak RSS for a disk-backed cell is bounded by one chunk or one row block. They removed the `np.vstack` and `np.corrcoef` float64 casts. However, `_compute_one_cross_sectional_cell` still runs `np.std(X_raw, axis=0, dtype=np.float64)` on the memmap view before any of that code. NumPy's `_var` computes `arr - arrmean` as a full float64 array (n_rows x n_features x 8 bytes). I measured this: for a 400 MB float32 input, `np.std` peaked at 800 MB traced.

With 300 features that is about 2.4 KB per row. On this 30 GB host, a cell of roughly 11-12M actual rows OOMs here, no matter how X_raw is stored. `alpha.ic.max_cell_rows` is now 100M, so the guard no longer stops this before it happens. `X_bc = X_raw[:, broadcast_mask]` (line 4347) is a second unbounded in-RAM copy (n_rows x n_broadcast x 4). Current-scale runs finish because actual cells are smaller than this, but the universe expansion this phase exists to enable will not. `test_disk_backed_accumulator_bounds_peak_growth_and_matches_in_ram` only covers the accumulator, not the cell.

**Fix:** Compute per-column variance with the same blocked two-pass loop as `_streaming_feature_correlation`: pass 1 takes float64 sums over `corr_row_block` rows, and pass 2 sums squared deviations. You can reuse pass 1's means and the Gram diagonal, since `diag(gram)/n` is the population variance. For X_bc, fill a column-wise memmap the way `_build_column_wise_x_nd` does, or gather `group_starts` rows first when the broadcast columns are what's being collapsed. Add a tracemalloc test that runs `_compute_one_cross_sectional_cell(disk_backed=True)` end-to-end and asserts peak much less than `X_raw.nbytes`.

## Warnings

### WR-01: `is_active` readers silently include the non-compute pilot cohort; TagCalibrator already measured it

**File:** `services/tag_calibrator.py:1284`, `services/ic_engine.py:6481`, `services/cross_sectional_spread_tracker.py:840`, `services/signal_metrics_analyzer.py:130`, `src/intelligence/pipeline/cache_manager.py:451` (premise in `production/migrations/337_instruments_governance_split.sql` header)

**Issue:** Migration 337 left `is_active` unchanged on the grounds that "every one of the current 231 active rows is both backfilled AND compute-consumed" and that existing readers are therefore untouched. The pilot draw (Plan 15) broke that premise: live DB has 40 rows with `is_active=true, compute_eligible=false`. Readers that filter on `is_active` directly, and mean "compute universe", now include those 40.

Measured: `instrument_tags` holds 218 `source='empirical'` rows for 32 of those failed-gate symbols. TagCalibrator's run-level BH-FDR family now includes their tests, which changes the q-values of every other symbol's tags without anyone deciding it should. ic_engine's routing also pulls them into `tags_by_symbol`. That part is harmless today because the symbol set comes from `feature_vectors`, but it adds noise to the unrouted-symbol warning.

**Fix:** Point these queries at `compute_eligible = true` (or `compute_eligible_1d` where 1d-only is intended), or route them through `get_active_contracts(dimension=...)`. Decide whether the 218 empirical rows should be expired and the affected calibrator run redone.

### WR-02: The 1d-only cohort is never refreshed and never demoted

**File:** `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py:127`, `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py:1116-1128`, `scripts/infrastructure/universe_expansion_promote_compute_eligible.py:164-167`

**Issue:** The nightly backfill scopes to `compute_eligible = true` and passes no `--dimension`/`--timeframes`, so the 40 `compute_eligible_1d=true` symbols are never refreshed. Their last 1d bar is 2026-09-16; the rest of the corpus is at 2026-09-23. The promotion tool only flips false to true, and nothing demotes a stale symbol, so `dimension="compute_1d"` keeps returning symbols whose series quietly stops. Any future 1d cross-sectional consumer gets a panel where these names drop out at a date nobody chose. The pipeline's `--dimension` default of `compute` also means that re-backfilling the cohort with `--dimension backfill` and no `--timeframes 1d` pulls all six timeframes, the cost D-09 set out to avoid.

**Fix:** Either add a 1d-only nightly leg (`--dimension compute_1d --timeframes 1d` over `compute_eligible_1d AND NOT compute_eligible`), or demote the cohort's `compute_eligible_1d` now that its gate failed. Make `--dimension backfill` require an explicit `--timeframes`.

### WR-03: `onboard_instrument` reports success on a no-op insert and resets existing backfill checkpoints

**File:** `src/config/instrument_onboarding.py:55-59, 84-91, 245-264`

**Issue:** `_INSERT_INSTRUMENT_SQL` uses `ON CONFLICT (symbol) DO NOTHING`, but `instrument_inserted = True` is set unconditionally, and `tags_inserted` also counts `DO NOTHING` rows. For a symbol that already exists, including the 22 `is_active=false` futures/FX rows, the helper:

- leaves `is_active`/`compute_eligible` unchanged, so an inactive symbol stays inactive;
- still writes tags and metadata;
- upserts `backfill_status` with `status = EXCLUDED.status` ('pending') while `GREATEST` keeps `fetch_complete=true`.

The result is an inconsistent `pending`/`fetch_complete` row, and `backfill_feature_factory` recomputes any row that isn't `complete`. Re-running `universe_expansion_onboard_gap_fill_etfs.py --commit` would reset EMLC/VIXY this way and report "n_onboarded: 2".

**Fix:** Check the command tag (`result == "INSERT 0 1"`). On conflict, either raise `OnboardingRejected("already present")` or skip the tag/metadata/backfill writes. Change the backfill upsert to `status = CASE WHEN backfill_status.status = 'complete' THEN backfill_status.status ELSE EXCLUDED.status END`, or to `DO NOTHING`.

### WR-04: The compute-readiness gate can be bypassed by the other insert paths (DEFAULT true)

**File:** `production/migrations/337_instruments_governance_split.sql:54-56`; `src/api/routes/instruments.py:153`; `src/core/database_manager.py:139`

**Issue:** `compute_eligible` is `NOT NULL DEFAULT true`, so every insert that doesn't name the column gets a compute-eligible row. `POST /instruments` inserts `is_active=true` without the column, and on conflict it re-activates an existing row whose `compute_eligible` is already true (all 22 inactive futures/FX rows are true). A symbol added or re-activated through the API skips the COMPUTE_READY predicate entirely and is picked up by the feature factory and nightly backfill immediately. It also gets `compute_eligible_1d=false` (341's default), which contradicts the rule that every four-timeframe symbol is also 1d-eligible. The column comment says "Newly onboarded symbols are set false", but only `onboard_instrument` enforces that.

**Fix:** `ALTER TABLE instruments ALTER COLUMN compute_eligible SET DEFAULT false;` in a new migration. Update the API and `upsert_instruments` to write `compute_eligible=false` explicitly, or route them through `onboard_instrument`.

### WR-05: The disk-headroom check runs on the DB's filesystem with no reserve floor

**File:** `services/ic_engine.py:4910-4925`; `production/migrations/336_ic_engine_disk_backed_cell_apr_keys.sql`

**Issue:** `/var/tmp/ic_engine_scratch` is on `/`, the same LV as the TimescaleDB volume (`/var/lib/docker/volumes/ssfi_ssfi-timescale-data`), with 515 GB free. The check only requires `free >= 2.2 x estimate`. It does not reserve anything for the database, which keeps writing WAL and `feature_ic_scores` during the run. The memmap files are sparse, so free space shrinks as rows land rather than at the check. With the 100M-row cap, one cell can legitimately claim about 264 GB. That is the same disk-full shape as the 2026-08-13 incident. The migration's description also says nothing about sharing a filesystem with the DB.

**Fix:** Add an APR `infra.ic_engine.scratch_min_free_after_bytes` (or a fraction) and require `free - required >= reserve`. Better, point `memmap_scratch_dir` at a filesystem separate from the DB volume and document why.

### WR-06: The explicit `_mmap.close()` turns any stale view into a segfault or a silent read of another cell's data; comments describe the wrong failure mode

**File:** `services/_batch_utils.py:1248`, `services/ic_engine.py` `_build_column_wise_x_nd` cleanup, comments at `services/ic_engine.py:4722, 4737`

**Issue:** Both teardown paths call `memmap._mmap.close()` while caller-held views may still exist. On this host (numpy 2.4.6) a read after close segfaults the process; I confirmed it, rc=139, and `test_ic_engine_streaming_correlation.py` Case 10 records the same. The ic_engine comments still say the read "raises `ValueError: mmap closed or invalid` on Linux". Worse, after `munmap` the next cell's `np.memmap` can land at the same virtual address, so a view that escaped into a result would read the next cell's data without any error. The design depends entirely on invariants (1) and (2) holding forever. The same 16-line comment block also appears twice in a row (lines 4718-4733 and 4733-4748).

**Fix:** Drop the explicit `_mmap.close()`. Closing the tmpfile fd, unlinking, and dropping the references is enough. The kernel frees the pages once the last view is garbage-collected, and a stale read then stays memory-safe. Correct the comment and delete the duplicate block.

### WR-07: APR violations in `services/` and `src/`

**File:** `services/ic_engine.py:225`; `src/config/instrument_onboarding.py:93`

**Issue:** `_DISK_BACKED_SCRATCH_HEADROOM_MULTIPLIER = 2.2` is an infrastructure safety margin: the 0.2 is a tunable "10% margin". It is a module-level constant in `services/`, which CLAUDE.md classes as `infra.*`. `_DEFAULT_TIMEFRAMES = ("5m","15m","1h","1d")` in `src/` is a behavioral list controlling what gets seeded (APR category 2), and it duplicates the four-timeframe set hard-coded again in `COMPUTE_READY_PREDICATE_SQL`'s `= 4`, the promote script, and the audit script.

**Fix:** Move the margin to `infra.ic_engine.scratch_headroom_multiplier`. Keep the structural 2.0 (two coexisting files) as derived. Source the timeframe set from one APR JSON key, and derive the predicate's `= 4` from `len(timeframes)`.

## Info

### IN-01: The audit summary ignores `fetch_complete`, although migration 337 cites it as measured

**File:** `scripts/analysis/instrument_compute_eligibility_audit.py:225-235`

**Issue:** `n_with_all_four_tfs` counts only `rows > 0`. The per-cell `bfc` flag is printed but never aggregated. Migration 337's header says the audit measured "non-zero rows AND a fetch_complete backfill_status row in every one of the four timeframes" (n_with_all_four_tfs=231), yet the summary it quotes never tested the second clause. The audit and the promotion predicate therefore test different things.

**Fix:** Compute `has_all_four = all(c > 0 for c in counts_by_tf) and all(bfc_by_tf)` and report the two separately.

### IN-02: `--dry-run` flags do nothing

**File:** `universe_expansion_stratified_sourcing.py:465-470`, `universe_expansion_pilot_draw.py`, `universe_expansion_promote_compute_eligible.py:121-126`, `universe_expansion_onboard_gap_fill_etfs.py`

**Issue:** `store_true` with `default=True` can never be false. Passing `--dry-run --commit` commits.

**Fix:** Delete `--dry-run`, or make it a mutually exclusive group with `--commit`.

### IN-03: Dead assignment in the pilot draw

**File:** `scripts/infrastructure/universe_expansion_pilot_draw.py:225`

**Issue:** `onboarded_symbols = sample["symbol"].tolist()[: result["n_onboarded"]]` is overwritten a few lines later, and the comment next to it says the value is wrong. `_PILOT_COHORT_CSV` also writes the full drawn sample, rejected symbols included, under the name "cohort".

**Fix:** Delete the line, and write only the onboarded symbols (or add an `onboarded` column).

### IN-04: Nondeterministic `session_id` lookup

**File:** `scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py:56-60`

**Issue:** `LIMIT 1` with no `ORDER BY`.

**Fix:** Order by symbol, or read the session_id from a named reference ETF (e.g. SPY).

### IN-05: `market_cap` is actually the IWV position's market value

**File:** `scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py` (`parse_holdings`)

**Issue:** The column parsed is the fund's "Market Value" of each holding, a float-adjusted proxy that is proportional to cap. qcut ranks are preserved, but the printed `cap_min`/`cap_max` are fund-position dollars, not company market caps. Duplicate tickers aren't de-duplicated either.

**Fix:** Rename the column to `index_weight_value` or document the proxy, and add `drop_duplicates("symbol")`.

### IN-06: The sample's reproducibility depends on an unrecorded exclude set

**File:** `scripts/infrastructure/universe_expansion_stratified_sourcing.py:400-401`

**Issue:** `exclude` is the live `instruments` table at run time. Provenance records only `n_excluded`, so the same seed and holdings hash can draw a different sample after any onboarding.

**Fix:** Record a sha256 of the sorted exclude list in the provenance output.

### IN-07: Disk-backed `append_row` buffers without limit

**File:** `services/_batch_utils.py` (`append_row`/`_flush_buf`)

**Issue:** In disk-backed mode with `flush_at=None`, every row stays in the Python list until `finalize()`, so memory isn't bounded. Current callers use `append_chunk`, so this is latent.

**Fix:** Require `flush_at` when `disk_backed=True`.

---

_Reviewed: 2026-09-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
