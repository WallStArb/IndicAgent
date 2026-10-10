# Simplify findings: 185/189 load-bearing code (wave 2, 2026-10-10)

Status: findings only, none applied. Four agents, one per surface, all four
quality angles each. Filed as the post-backfill cleanup backlog (todo 527).
Context: the 5m backfill is live; queue and write-path edits wait for it unless
trivial and test-verified. 187/188 have no code yet; nothing to sweep there.
The Alpaca loader was excluded (simplified separately by its own session).

## Surface: derivation and D7 (services/bar_derivation.py, services/bar_reconciliation_audit.py)

Review complete. I read both files in full plus the shared modules they draw on (`src/intelligence/bars/session_grid.py`, `integrity_checks.py`, `digest.py`, `gap_plan.py`) to check reuse claims. No edits made.

## Findings, ordered by cost

**1. Answered-window SQL exists in three in-scope copies (five in the repo)**
- `services/bar_derivation.py:192` (`_SELECT_ANSWERED_WINDOWS_SQL`), `services/bar_reconciliation_audit.py:944` (`_ANSWERED_5M_SQL`), plus `services/bar_auditor.py:92`, `scripts/infrastructure/backfill/_empty_history.py`, `_d1_gaps.py`.
- The audit already imports ten `_SELECT_*` constants from bar_derivation, yet keeps its own parameterized copy of this one. Cost: the corroboration rule ("a `bars` answer counts only when a stored row exists") is the todo-462 coverage contract; a change to it must be replicated by hand in five places, and a miss reads as silent coverage drift in exactly the check that exists to catch drift.
- Simpler form: one parameterized constant (`$1 symbol, $2 timeframe`) in `src/intelligence/bars/gap_plan.py` next to `AnsweredWindows`, imported by all three services.

**2. The 5m load-and-shape logic is copy-pasted between writer and auditor, with doubled timestamp conversion**
- `services/bar_derivation.py:1111-1132` (`_run_symbol`) and `services/bar_reconciliation_audit.py:1288-1311` (`_FiveMinute.from_rows`) implement the same recipe: quarantine set from flag rows, `rules_by_ts` of non-quarantine rules, keep-filter, six numpy columns, `rules_per_row`. The audit's copy is the one that judges the writer's digests, so recipe drift here is self-masking.
- Cost also runtime: `_run_symbol` converts each 5m timestamp via `_epoch_seconds` three times (keep-filter line 1121, `ts_seconds` line 1125, `stored_slots` line 1185); `_FiveMinute.from_rows` calls `.timestamp()` twice per row twice over. At roughly 200k 5m bars per name and 233 names, that is on the order of 10^8 Python datetime conversions per night for zero information.
- Simpler form: one pure shaper (e.g. `bars/sources.py` or a small `bars/five_minute.py` dataclass with `from_rows`) used by both, computing stamps once.

**3. Month-digest loop implemented three times**
- `services/bar_derivation.py:826` (`_month_digest_rows`), `services/bar_derivation.py:744-757` (`write_1d_digests` re-inlines the identical mask + `bar_content_digest` body), and `src/intelligence/bars/integrity_checks.py:173` (`month_digests`, whose docstring says "the same recipe as services/bar_derivation.write_1d_digests").
- Cost: the digest recipe is D-07's identity contract; a third copy in `write_1d_digests` is the one that writes the stored digests the other two are compared against. `write_1d_digests` can call `_month_digest_rows` directly (it returns `(start, end, digest, n_rows)`, exactly its `digest_args` shape); ~25 lines removed.

**4. Verbatim post-apply scrub-and-digest block duplicated**
- `services/bar_derivation.py:1552-1574` (`_execute_daily`) and `services/bar_derivation.py:1927-1947` (`_execute_restore`) are the same `scrub_symbols` + per-symbol `write_1d_digests` sequence, including the two try/except-appends.
- Simpler form: `async def _scrub_and_digest(pool, conn, applied, batch_id) -> list[str]`. Plan 185-27's ordering rule (scrub before digests) then lives in one place.

**5. `_route_disagreement` runs the whole check twice and triplicates its "judged" predicate**
- `services/bar_reconciliation_audit.py:1701-1706`: `check_route_disagreement(venue + smart, ...)` is invoked a second time without `listing` only to log `n_disagreeing`. Each call rebuilds the `smart` dict and re-sorts all samples.
- Also lines 1695-1700 re-derive the `judged()` predicate (SMART pair + alias-to-listing match) that `check_route_disagreement` already owns internally.
- Simpler form: have the check return `(CheckResult, n_judged, n_unlisted_disagreements)` or split a `judged_pairs()` helper out of it; the loader then calls it once.

**6. Row-to-dataclass mapping duplicated between the two files**
- `services/bar_reconciliation_audit.py:1074-1117` (`_policy_rows`, `_observations`, `_splits`) duplicate the inline comprehensions in `services/bar_derivation.py:1491-1502` (policy), `1631-1639` (splits), `1640-1655` (observations).
- Cost: four-field copy-paste variation against `daily_rule.PolicyRow` and `derivation.Observation/SplitRecord`; adding a field to any of those dataclasses breaks one copy silently at runtime.
- Simpler form: `from_rows` classmethods on `PolicyRow`/`Observation`/`SplitRecord` (Ring 1 owns the shape), both services call them.

**7. Identical upsert SQL constants in one file**
- `services/bar_derivation.py:316` (`_UPSERT_DERIVED_SQL`) and `:551` (`_UPSERT_1D_SQL`) are character-identical statements (the comment even says so). One constant; the "changed set only, never raw UPDATE" fence then has one CI-referenced name.

**8. `session_slots` and `bucket_fine_volume` re-implement gap_plan's slot arithmetic**
- `services/bar_reconciliation_audit.py:470-506` vs `src/intelligence/bars/gap_plan.py:217-228` (`_rth_grid_slots`, same session-anchored walk, inclusive vs exclusive end) and the same `[open + (ts-open)//interval*interval]` bucketing in `bucket_fine_volume` line 504.
- Simpler form: lift `session_slots` into `gap_plan` (or `session_grid.py`, its natural neighbor) with the end-inclusive flag; `bucket_fine_volume` stays local but reuses the slot-start formula.

**9. Duplicated private constants across the pair**
- `_PARTIAL_RULE` at `services/bar_derivation.py:141` and `services/bar_reconciliation_audit.py:739`; `_SESSION_MARGIN_DAYS` at `bar_derivation.py:162` and `bar_reconciliation_audit.py:1269`. The audit already imports nine SQL constants and both helpers from bar_derivation; these two belong in the same import block. A rule-name typo in one copy would strand flags the other copy counts.

**10. Per-timeframe and per-symbol round trips in the 1,502-name loops**
- `services/bar_reconciliation_audit.py:1931`: `_HAS_REAL_BEFORE_SQL` is fetched once per (symbol, timeframe) inside the tf loop — one `timeframe = ANY($2)` query per symbol removes ~3,000 sequential round trips per run.
- `services/bar_reconciliation_audit.py:1787-1797` (`_late_heads`): two `fetchval` calls per moved name inside the loop; both are set-able with a join/`GROUP BY`.
- `services/bar_reconciliation_audit.py:2353-2369` (`_intraday_inputs`): the 5m, flags, answered, archive and digest fetches are mutually independent; `asyncio.gather` over the one connection (asyncpg pipelines) overlaps them across 233 names. Modest on localhost, but it is the intraday report's per-name critical path.

**11. Redundant derived state: APR snapshot re-filters what the loader already filtered**
- `services/bar_derivation.py:939-943` (`_execute_grid`) and `:1825-1831` (`_open_daily_batch`): the dict comprehensions keep keys starting with the exact prefix patterns just passed to `load_apr_dict_async` five lines earlier. The filter can only ever be the identity; delete it or drop the patterns from the loader call — carrying both invites them to diverge.

**12. Load-row insert duplicated between daily and restore paths**
- `services/bar_derivation.py:1760-1793` (`_write_daily`) and `:1995-2021` (`_restore_symbol`) build the same 18-arg `_INSERT_LOAD_SQL` tuple with only caller, detail and outcome differing. A `_insert_load(conn, *, symbol, tf, caller, detail, ...)` helper removes the positional-argument drift risk on an 18-parameter statement.

**13. Long functions doing several jobs (altitude)**
- `services/bar_derivation.py:1103-1348` `_run_symbol` (~245 lines): read, digest, changed-only gate, derive, flag planning, then the write transaction. The `planning` dict built at 1227-1233 only to be splatted with `**` into `_plan_grid` is a parallel-structure smell (CLAUDE.md's parallel-dicts rule): a frozen `_GridInputs` dataclass, or just passing the four arguments directly, deletes the dict.
- `services/bar_reconciliation_audit.py:1898-1991` `_grid_checks` (~94 lines) carries six parallel mutable accumulators (`masked_by_tf`, `masked_derived`, `partial_by_tf`, `masked_samples`, `no_history`, `cells`) through two concerns. Splitting completeness from masked-slots, each returning its own small result, lets `_GridOutcome` assemble them and removes the `dict.fromkeys` / `defaultdict` mixture.

## Explicitly clean

- The audit's import of bar_derivation's `_SELECT_*` SQL and `_derive_for_tf`/`_month_digest_rows` is the right pattern (the audit judges the writer's own recipe); nothing there to change, and the loader-vs-`ops_source_policy.py` writer split was skipped as instructed.
- `_write_verdicts`' read-back, the `_ALREADY_RECORDED_SQL` idempotency guard, the per-symbol read-judge-drop loops against corpus frames, and `_VendorAgreementAccumulator`'s packed-array design are all deliberate and fine as they are.
- `integrity_checks.py` and `session_grid.py` themselves are clean; the duplication is on the services side, not in the shared modules.

---

## Surface: bars integrity modules (src/intelligence/bars/, scripts/ops/bars/)

Review complete. All modules in scope read end to end: `src/intelligence/bars/` (except `labels.py`) and all of `scripts/ops/bars/`. Findings only, ordered by cost. Nothing was edited.

## Findings

1. **`src/intelligence/bars/integrity_checks.py:307,327,354` - judge_name_1d re-buckets observations three times.** `current_closes`, `derive_daily_v2`, and `basis_closes` each internally call `_by_vendor_day(observations, splits)`, which is O(obs x splits) (every observation is tested against every split via `_is_current`). Cost: the D7 full-corpus pass does 3x the split-scanning work per name across ~1,500 names. Simpler: bucket once (`days = _by_vendor_day(...)`) and derive the three views from it; `current_closes`/`basis_closes` already share the identical legacy-filter + `_by_vendor_day` prefix, so a `_smart_days()` helper serving both plus a `derive_daily_v2` overload taking prebuilt days removes two of the three passes.

2. **`integrity_checks.py:100,419` vs `verdict_gate.py:28-56` - the check-name contract is defined twice.** `CHECKS_1D` = `REQUIRED_CHECKS["1d"] + REBUILD_ONLY_CHECKS["1d"]` and `CHECKS_INTRADAY` re-states `REQUIRED_CHECKS["5m"/"15m"/"1h"]` plus `grid_parity` and `stray_vendor_rows`. D7 writes verdict rows from the first pair (`services/bar_reconciliation_audit.py:107-108,2401,2581`), the promotion gate reads the second. Cost: adding a check to one list and not the other silently decouples what D7 judges from what promotion requires, at the repo's highest-stakes boundary; the comment at integrity_checks.py:97 already has to name `verdict_gate.REBUILD_ONLY_CHECKS` in prose. Simpler: verdict_gate imports the per-check constants from integrity_checks (acyclic today) and builds its maps from them, or integrity_checks derives its tuples from `REQUIRED_CHECKS | REBUILD_ONLY_CHECKS` plus an explicit report-order list.

3. **Timeframe-to-bucket-size restated in four modules.** `sources.py:22` `GRID_TIMEFRAMES = {"15m": 15, "1h": 60}` (minutes), `integrity_checks.py:432` `_BUCKET_SECONDS = {"15m": 900, "1h": 3600}`, `gap_plan.py:54` `_GRID_TF_MINUTES`, `scrub_rules.py:56` `_TF_SECONDS`. Cost: `sources.py:30` promises "when 4h joins the derivation this is the only definition that changes", which is false today; a missed second table changes bucket math silently. Simpler: `integrity_checks` and `gap_plan` derive seconds/minutes from `sources.GRID_TIMEFRAMES` (both already import from `sources`); `scrub_rules._TF_SECONDS` can stay as the unit table or absorb the same source.

4. **`scripts/ops/bars/ops_head_rerun.py:296-322` vs `ops_split_detect.py:457-505` - fetcher-subprocess plumbing duplicated.** Both build the same invocation shape (`sys.executable`, `_FETCHER`, `--symbols` join, `--timeframes 1d`, `--full-scan`), spawn via `Popen` with stdout piped, echo lines, detect `line.strip() == LOCK_HELD_MESSAGE`, and map it to exit 3. Cost: the lock-held contract (the thing that stops a refused chunk being read as clean) lives in two hand-maintained copies. Simpler: one `scripts/ops/bars/_fetcher.py` with `fetcher_command(symbols, *, dimension, client_id, extra=...)` and `run_fetcher(command) -> int` doing the echo + lock detection; both callers shrink to one line.

5. **`integrity_checks.py:436-455` (`answered_slots`) vs `gap_plan.py:251-262` (`plan_gaps`) - the "stored-or-answered" slot predicate exists twice with divergent semantics.** `answered_slots` clamps the covered length to the session close (`min(interval, close - slot)`, the half-day last slot); `plan_gaps` uses the fixed interval. Cost: two copies of the coverage rule to keep in agreement; the divergence is the load-bearing subtlety and nothing forces future edits to both. Simpler: a shared `slot_covered(slot, stored, answered, length)` predicate in `gap_plan.py` taking the per-slot length, with each caller supplying its own length rule.

6. **Sync APR loader duplicated across ops scripts.** `ops_head_rerun.py:249`, `ops_venue_study.py:317`, `ops_intraday_venue_recovery.py:180`, `ops_split_detect.py:520` (async), `ops_d1_bootstrap.py:171` (LIKE ANY variant) each hand-roll `SELECT config_key, config_value FROM config_state ...` into a dict; `services/_batch_utils.py` already owns the async versions (`load_apr_dict_async`, line 1608 for the LIKE case). Cost: five copies of the APR-read convention; a new key namespace means touching each. Simpler: one sync `load_apr_dict(conn, keys=|prefixes=)` next to the async one in `_batch_utils`, used by all five.

7. **`integrity_checks.py:39` duplicates `daily_rule.py:96` `_PRIMARY_LABEL`, and `vendor_basis.py:24-25` redefines `daily_rule.py:82-83` `VENDOR_TRADIER/VENDOR_IBKR`.** Cost: the primary-source-to-label mapping is the d2-v3 contract; a third source label (e.g. Alpaca entering canonical 1d) must be added in two dicts. Simpler: integrity_checks imports the mapping and vendor names from daily_rule (it already imports five names from that module).

8. **`ops_split_detect.py:531-586` - `_unexplained_reporter` and `rescale_reporter` are the same closure twice.** Both lazily import psycopg + `emit_integrity_fact_sync`, open a connection, and emit one fact; they differ in metric name, threshold value and log level. Cost: 50 lines for two parameter sets. Simpler: one `_fact_reporter(settings, metric, threshold, log)` factory; the call sites pass the differences.

9. **APR boolean parsing three ways.** `ops_head_rerun.py:67,260` `_TRUTHY = ("true","1","t","yes")`, `ops_intraday_venue_recovery.py:59` `_is_true` (strict "true" only), `ops_data_bar_check.py:498` inline `str(...).strip().lower() == "true"`. Cost: the same config_value can be read as on by one script and off by another; the semantics are undocumented either way. Simpler: one `apr_bool(value, *, strict=True)` in `src/core/service_utils.py` (or `service_utils` already has format/parse helpers where it belongs).

10. **`_BP = 1e4` defined three times** (`daily_rule.py:98`, `vendor_basis.py:27`, `source_admission.py:25`) and the month-advance loop `(y+1, 1) if m == 12 else (y, m+1)` written twice (`digest.py:111`, `integrity_checks.py:571` inside `digest_scope`, which could iterate `month_ranges`-style via a shared next-month helper). Cost: trivial per site, but basis-point conversion is the tolerance unit of three checks. Simpler: one `_BP` in `vendor_basis` or a tiny `src/intelligence/bars` constants home; `digest_scope` reuses a `next_month()` helper exported from digest.

11. **`ops_data_bar_check.py:66-73` imports six underscore-private names from `ops_head_rerun`** (`_APR_VENUES`, `_late_names`, `_load_apr`, `_load_requests`). Cost: the late-name D1 read is shared machinery living under a private prefix, so any refactor of `ops_head_rerun` can break the D-28 gate without a signal. Simpler: either rename the shared pieces public in `ops_head_rerun`, or move the D1 late-name reads (`_late_names`, `_load_requests`, `classify_head`, `island_failed_unlisted`, the APR keys) into a shared `scripts/ops/bars/_late_names.py` both scripts import.

12. **Small repeated literals, one line each:** `{"bars", "no_data"}` as `gap_plan.ANSWERED_OUTCOMES`, `ops_head_rerun._CLEAN_OUTCOMES`, `ops_d1_bootstrap._CLEAN` (three names, one fact); the asyncpg DSN strip `database_url.replace("postgresql+asyncpg://", "postgresql://")` in `ops_source_policy.py:390`, `ops_scrub_historical_pass.py:113`, `ops_d1_bootstrap.py:282` (belongs as a Settings property); `AnsweredWindows.from_rows` (`gap_plan.py:68-76`) re-implements `_merge_windows` with slack zero plus a positive-length filter and can call it.

13. **`daily_rule.py:461-462` - `_with_seam` recomputes the seam window and median that `derive_daily_v2` already computed** at lines 362-367 (`overlap`/`seam_median`). Cost: negligible runtime, but the seam median appears in flag detail from a second computation that could in principle drift from `head_admitted`'s. Simpler: pass `seam_median` (and the window) into `_with_seam`.

14. **`scrub_rules.py:207-219` - `price_sanity` is a pure-Python per-bar loop over the full series** (`for i in range(n)` calling `classify_candidate_bar`). Cost: on the 5m corpus this is the dominant scrub cost; most bars are PLAUSIBLE and could be excluded by a vectorized pre-screen (any of the four field-vs-neighbor ratios exceeding `magnitude_threshold`) before the per-bar classifier runs on the survivor set, exact same verdicts. Simpler form is the pre-screen, not a rewrite of the classifier. Listing last because it is an optimization rather than a simplification, and the loop's semantics are deliberately shared with the dry-run scanner.

## Clean areas

`session_grid.py`, `sources.py`, `write_contract.py`, `seams.py`, `corporate_actions.py`, `sessions.py`, `derivation.py`, `verdict_gate.py` internals, and `_campaign.py` are clean: single-purpose, no dead code found, validation is loud, and `rebucket_5m` vs `aggregate_session_grid` look like duplication but are genuinely different grids (vendor clock buckets vs session-anchored), documented as such. The `verdict_gate.py` pair `gate_symbols`/`ready_predicate_sql` shares the one REQUIRED_CHECKS constant as designed.

---

## Surface: fetch core (scripts/infrastructure/backfill/_history_fetch.py, _history_fetch_item.py)

Review complete. Both files read in full; neighbors checked (`_d1_gaps.py`, `_empty_history.py`, `gap_plan.py`, `session_grid.py`, `ibkr.py`, `ohlcv_history_fetcher.py`, `ConfigService`). Findings only, ordered by practical cost. Nothing edited.

## Findings

**1. Nine copy-paste APR overlay loaders, ten startup DB connections**
`scripts/infrastructure/backfill/_history_fetch.py` lines 394-418, 421-443, 446-482 (two connections in this one loader), 485-513, 526-557, 560-585, 588-606, 789-822, 928-949. Each is the identical connect / query `config_state` / overlay / `except: print(...)` body with different keys and targets, about 200 lines total. Cost: every new `infra.*` key re-copies the body (already done nine times); fetcher startup opens ten separate connections where one would do; failure handling is per-copy. Simpler: one `_apr_rows(settings, where_clause, params) -> dict[str, str]` helper plus per-loader apply loops; collapse to roughly 50 lines. (Adopting async `ConfigService` is not the answer here; the docstrings correctly reject it for a one-shot CLI.)

**2. `FetchContext.get_conn` health probe per call, per chunk**
`scripts/infrastructure/backfill/_history_fetch_item.py` lines 244-256, called from `_ChunkPersister.persist` (line 329) once per provider chunk plus once per plan. Every persist pays a `SELECT 1` round trip (and the probe cursor is never closed). Cost is small against IBKR pacing but it is pure overhead in the hot loop; probing once per item (or relying on the persist failure path to reconnect) is the same safety for fewer round trips.

**3. `cluster_gap_ranges` call defeats its own late-bound default**
`scripts/infrastructure/backfill/_history_fetch_item.py` line 638 passes `max_gap_days=_history_fetch._GAP_CLUSTER_MAX_DAYS` explicitly, but `cluster_gap_ranges`' docstring (`_history_fetch.py` lines 960-964) says the default was deliberately made call-time late-bound precisely so callers would not freeze or re-plumb the global. Call `cluster_gap_ranges(gaps)` and drop the cross-module private read.

**4. `_insert_market_data_rows_waived` is a byte-for-byte clone**
`scripts/infrastructure/backfill/_history_fetch.py` lines 1103-1115 duplicate lines 1081-1100 plus `waived=True`. One function with `waived: bool = False`; `_ChunkPersister` already picks the writer by a `waived` flag, so the selection collapses too.

**5. `fetch_per_contract` re-parses symbols it just generated**
`scripts/infrastructure/backfill/_history_fetch.py` lines 247-258: per iteration it recomputes `prefix`, then recovers month code, year digit, and the 4-digit year by parsing back the string `_generate_contract_symbols` built from `(year, month_num, symbol)` tuples before discarding them. Cost: roughly 15 lines of derivable state and a second copy of the symbol encoding rules (including the year-disambiguation arithmetic). Have `_generate_contract_symbols` return (or be zipped with) its tuples and delete the parse-back.

**6. `_merge_windows` re-implemented locally**
`scripts/infrastructure/backfill/_history_fetch_item.py` lines 362-370 duplicate `src/intelligence/bars/gap_plan.py` lines 121-131 (`_merge_windows` with a `slack` parameter; slack=0 is the local behavior). Promote the gap_plan one to a public `merge_windows` and import it.

**7. `aggregate_bars_from_1m` is the retired aggregator, still live on the FX/crypto derive path**
`scripts/infrastructure/backfill/_history_fetch.py` lines 985-1021. `src/intelligence/bars/session_grid.py`'s module docstring states it "replaces aggregate_bars_from_1m's midnight-UTC flooring (the :00-edge bug D-15 exists to remove)", yet `_fx_derive` still uses the old one, including for 5m (`_FX_DERIVED_TFS` contains 5m at `_history_fetch_item.py` line 103). If an FX/crypto name ever activates, its derived 5m would be midnight-floored while `services/bar_derivation` derives 15m/1h session-anchored from that same 5m. Dormant today (no active FX/crypto names), so this is latent inconsistency rather than runtime cost, but it is one mechanism that should have been retired.

**8. `real_bars_only_for` no longer gates anything**
`scripts/infrastructure/backfill/_history_fetch.py` lines 828-840. `_REAL_BARS_ONLY_TFS` covers every timeframe in `_TF_FETCH_CONFIG` (4h appears in the set but cannot reach the planner because `tf_fetch_config[timeframe]` would KeyError first). So the single production caller, `_plan_gaps` line 542, always takes the True branch; the `else None` is dead. Inline `load_answered_windows` unconditionally and delete the helper, keeping the history in a comment.

**9. Dead module logger plus a local re-import**
`_history_fetch.py` line 51 defines `_logger`, used nowhere in the module; `seed_roll_chain` (lines 672-674) re-imports `structlog` and builds its own local logger instead. Use the module logger and delete the dead global. Related: the whole module reports through `print()` (per-contract progress lines 286/331/336 and every APR-loader failure) while the repo standard is structlog to `logs/<name>.log`, so none of these land in the log file.

**10. Four spellings of "floor to midnight UTC"**
`_history_fetch_item.py:387` `_midnight`, `_d1_gaps.py:177` `midnight_utc` (date-based), and inline `.replace(hour=0, minute=0, ...)` at `_history_fetch.py:236-238` and 521-523. One helper. Trivial.

**11. `nyse_sessions` computed twice for the same range in the 1d refetch branch**
`_history_fetch_item.py` lines 498 and 502: identical arguments, second call discards the first. Hoist `window = nyse_sessions(start_dt.date(), end_dt.date())` above the branch (the `elif` already computes a different, shorter window, so only the refetch path collapses).

**12. Minor redundancies in the window loop**
`_history_fetch_item.py` line 663 `is_oldest = (gap_start, gap_end) == windows[0]` is an obscure tuple compare for "first iteration" (`enumerate` index). Lines 681 and 787 use `getattr(ctx.provider, "last_fetch_failed_chunks", 0)` but `IBKRProvider.__init__` (`src/providers/ibkr.py` line 731) always sets the attribute; plain reads suffice. Lines 646-655: the 1d `on_request_1d` wrapper and the persister branch both reduce to "sink.on_request + clock.touch"; building the wrapper uniformly instead of branching on `d1_capture` would remove the special case.

**13. `_fx_derive` re-reads from the DB what it just persisted**
`_history_fetch_item.py` line 789: after persisting the deep 1m chunks, `fetch_bars` reads the entire stored 1m series back to aggregate, when the fetched bars are already in memory. One full-series read per FX/crypto item; dormant path, listed for completeness.

**14. Duplicated comment header**
`_history_fetch.py` lines 345 and 358 both open with "Per-TF fetch config: (days_of_history, use_continuous_contract)"; the rationale block sits between two copies of the same header. Delete one.

**General altitude note:** `_history_fetch_item` imports about 20 underscore-prefixed names from `_history_fetch`; the privacy convention is nominal between these two modules, which is fine for a leaf/helper pair, but finding 3 shows the friction it causes (reaching in for `_GAP_CLUSTER_MAX_DAYS` when the public API already handles it). If you touch these files anyway, renaming the genuinely shared constants (`_ARCHIVE_TFS`, `_RECORD_PLAN_TFS`, `_TF_MINUTES`) to public names would make the intended interface explicit; not worth a standalone pass.

Not findings: the sequential awaits in the window loop and per-contract loop are mandated by IBKR pacing; the two `DESTINATION_GRID` imports (`"grid"` vs `"market_data_ohlcv"`) are different values from different writers, not duplication; the legacy empty-history gate and the record-planner `gate` dict already share `gap_plan.fresh_empty_span` underneath.

---

## Surface: fetcher service family (ohlcv_history_fetcher.py, _fetcher_lock.py, _intraday_persist.py, _empty_history.py)

Review complete. No edits made. Note: `ibkr_history_fetcher.py` no longer exists; the fetcher module is now `scripts/infrastructure/backfill/ohlcv_history_fetcher.py` (phase 190 rename, frozen externals). I reviewed it plus the three named helpers and the overlap with `_history_fetch.py`.

## Findings, ordered by cost

1. **APR overlay loader family, `_history_fetch.py` lines 394-606, 789-822, 928-949** - Nine near-identical try/connect/query/close/except-print blocks (`_load_tf_fetch_config`, `_load_ibkr_chunk_days_config`, `_load_ibkr_hist_timeout_config` x2 blocks, `_load_ibkr_retry_config`, `_load_ibkr_venue_fallback_config`, `_load_ibkr_rate_limit_config`, `_load_observation_batch_rows`, `_load_ohlcv_insert_batch_size_config`, `_load_gap_cluster_max_days_config`), ~170 lines of copy-paste with drifting error strings. Cost: ~10 sequential connections and 11 queries at every run start, and each new key copies the block again. Simpler: one helper `_apr_overlay_rows(settings, *, pattern=None, keys=None) -> dict[str, str]`; better, `ohlcv_history_fetcher.prepare` already fetches every `infra.%` key in one query (`_read_infra_apr`, fetcher line 615) and throws nothing away - 8 of the 9 loaders read keys that match `infra.%`, so the values are already in memory when the loaders run. Only production callers are this fetcher family plus the rate-limit probe, so consolidation is low-risk.

2. **Run-constant APR re-reads per 1d item, `_empty_history.py` lines 357-384, 480-496 (call site `_history_fetch_item.py:737`)** - `reconcile_empty_history` runs once per fetched 1d item (`symbols=[symbol]`) and re-queries `config_state` twice per call via `_confirmation_timeframe` and `load_venue_routes`, plus one `has_bar_between` query per confirmed span. Cost: ~2-4 redundant round trips per 1d item, roughly 3,000 per session across the active universe, for values that never change during a run and are already overlaid onto `ibkr._VENUE_FALLBACK_*` at startup. Simpler: resolve confirm-tf, venues and slack once per run into `FetchContext` (which already carries run-constant overlays like `empty_reverify_days`).

3. **`_bind_registry` seam indirection, `ohlcv_history_fetcher.py` lines 716-740 (with 595-603, 1128-1144)** - The per-instance registry rebuild exists only to close over `self._provider_factory` and `self._fetch_fn`, yet both are reachable at dispatch time: `_fetch_one` already calls `entry.fetch(...)` and could pass `fetch_fn` as an argument, and leaf construction in `_fetch_and_promote` could honor `self._provider_factory` directly. Cost: ~25 lines plus a two-layer indirection (registry rebuilt per instance, then a closure that reads the seam at call time) that a reader must trace to learn nothing dynamic is happening. Simpler: pass the seams through the existing dispatch; delete `_bind_registry`.

4. **Constant-true gate `real_bars_only_for`, `_history_fetch.py` lines 74, 828-840 (call site `_history_fetch_item.py:542-546`)** - `_REAL_BARS_ONLY_TFS` covers every reachable timeframe (candidates are filtered to `_TF_FETCH_CONFIG`'s five keys, all in the set), so the function is `True` everywhere and the `else None` branch at the call site is dead by construction. Cost: readers trace a set, a function and a test (`test_history_fetch.py:1177`) to learn the answer is unconditional. Simpler: drop the branch, keep one comment line citing plan 185-18/185-32 and migration 444.

5. **Writer-transaction boilerplate x4, `ohlcv_history_fetcher.py` lines 922-951, 1318-1330, 1378-1385** - `_rebuild_coverage`, `_reset_failures`, `_record_outcome` and `_finish_1d` all repeat connect-or-get-conn, `with conn.transaction()`, `SET LOCAL ROLE bar_derivation_writer`, call, close, print/log; the first two are near-clones of each other. Cost: ~30 lines where ~10 carry information; a fifth writer copies it again. Simpler: one `_writer_tx(conn, fn, *args)` helper.

6. **Production-dead helpers in `_empty_history.py`** - `is_fresh` (lines 55-62) is called only by its own unit test (docstring admits it); `load_fresh_heads_per_tf` (lines 265-284) has no caller anywhere, and `_fetch_queue.py:689` reads provider heads with its own SQL, so even after the 190-06 flip nothing reads through it. Cost: two functions plus tests that can never affect production behavior. Simpler: delete `is_fresh` and its test; delete or fold `load_fresh_heads_per_tf` into the 190-06 flip work (its write-side twin `record_head_per_tf` is gated but planned, so leave that one). The `record_head` / `record_head_per_tf` pair itself is an intentional wave-5 gate, not a finding.

7. **`fetch_per_contract` uses the pre-`_fetch_start` window shape, `_history_fetch.py` line 236 vs 516-523** - It computes `end_dt - timedelta(days=fetch_days)` floored to midnight, the exact pattern `_fetch_start`'s docstring says spans one extra date and doubles requests when depth equals chunk size. Cost: one caller keeps the slower window and a second copy of the depth-window arithmetic. Simpler: call `_fetch_start(end_dt, fetch_days)`.

8. **Four near-identical SQL constants for `fetch_bars`, `_history_fetch.py` lines 732-758** - `_FETCH_BARS_SQL`, `_SINCE`, `_BASE`, `_BASE_SINCE` differ only by a `LIKE` and an optional `AND timestamp >= %s`. Cost: four constants and a four-way select at lines 1041-1045 for two boolean axes. Simpler: one template with the two optional fragments.

9. **`chunk_digest` recomputed per request row, `_intraday_persist.py` lines 122, 145-170** - `_with_digest` recomputes the digest of the same `bar_rows` for every bars-answered request row in the chunk, computes `sorted(keyed)` twice, and indexes OHLC by bare `row[3..6]` while `_TS`/`_VOLUME` constants sit three lines below. Cost: redundant O(rows) hashing and unnamed magic indices in digest arithmetic. Simpler: compute the digest once (lazily) before the comprehension, name the OHLC offsets.

10. **Dead pause fallback, `ohlcv_history_fetcher.py` lines 1107-1110 (with 454, 865, 1136)** - `prepare` refuses unknown providers and builds `plans` for every registered one, so `plan.plans.get(row.provider)` is never None in `_loop` or `_fetch_one`; the `plan.inter_item_pause_s` fallback would also apply the default provider's pause to a foreign vendor's item if it ever did run. Cost: a redundant `RunPlan` field plus a misleading fallback path. Simpler: `plan.plans[row.provider].inter_item_pause_s`, drop the field.

11. **`has_bar_before` / `has_bar_between` twins, `_empty_history.py` lines 104-125** - Same EXISTS query differing by one bound. Simpler: `has_bar(conn, symbol, timeframe, start=None, end=None)`.

12. **Single-key APR read duplicated inside `_empty_history.py`, lines 65-74 vs 357-363** - `load_reverify_days` and `_load_apr_list` are the same query-and-raise shape with drifted error text ("migration 354" vs "migration 374"). Simpler: one `_apr_value(conn, key)` both call.

13. **`FetcherLock.close` is an alias of `release`, `_fetcher_lock.py` lines 120-122** - `release` already no-ops when not held; two public names for one operation. Simpler: have `__exit__` call `release` and delete `close`, or keep one documented name.

14. **`aggregate_bars_from_1m` kept past its replacement, `_history_fetch.py` lines 985-1021** - `src/intelligence/bars/session_grid.py` declares it replaces this aggregator's midnight-UTC flooring (the ":00-edge bug"). The FX/crypto 1m derive fallback still uses the old one. Not a drop-in swap (session-anchored vs 24h FX sessions), so flagging as altitude: if the :00-edge matters for derived FX bars, the derive path wants the session-anchored mechanism; if not, a comment on `aggregate_bars_from_1m` saying why the fallback keeps the old arithmetic would prevent the next reader from "fixing" it.

Not findings: the wave-5 gated head pair (item 6 caveat), the two distinct `DESTINATION_GRID` constants in `_history_fetch_item.py` (different values, alias is load-bearing), and `_sd_notify_watchdog`'s function-local import (deliberate). `_fetcher_lock.py` and `_intraday_persist.py` are otherwise clean; the real mass is in the `_history_fetch.py` loader family and the fetcher's transaction/registry boilerplate. Given the 5m backfill is live, items 1-3 are the ones worth a dedicated session after it completes; none are urgent.

---

---

## Application record (2026-10-10, first pass: the safe-now items)

Scoped with indicagent-90 (oversight session): items touching the paused backfill's import graph are
declined until the Alpaca load completes and the 5m backfill resumes. Applied, one commit each:

- real_bars_only_for removed (fb057a54a): dead by construction; the answered windows load
  unconditionally with the plan history in the call-site comment.
- the dead module logger in _history_fetch.py named and used by seed_roll_chain (55c90a613).
- _BP deduped to one BP in vendor_basis.py (d28a04ff2); daily_rule and source_admission import it.

Declined for now:

- is_fresh / load_fresh_heads_per_tf in _empty_history.py: the module is in the 5m backfill import
  graph. Cross-reference for the eventual owner: todo 526's per-TF provider-head migration will
  want per-TF head rows, so its design should state whether load_fresh_heads_per_tf is revived or
  the deletion lands with it.
- Everything in the numbered lists above: post-backfill, per todo 527.
