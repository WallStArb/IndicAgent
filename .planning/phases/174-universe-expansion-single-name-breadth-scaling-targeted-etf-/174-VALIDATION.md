---
phase: 174
slug: universe-expansion-single-name-breadth-scaling-targeted-etf
status: planned
nyquist_compliant: true
wave_0_complete: n/a
created: 2026-09-15
updated: 2026-09-15
revision: cross-AI review pass (174-REVIEWS.md) — rows updated only where a fix created a new test obligation
---

# Phase 174 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 6.0+, `pytest-asyncio` (`asyncio_mode=auto`) |
| **Config file** | `/home/bg/dev/indicagent/pytest.ini` |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_batch_utils.py tests/unit/test_ic_engine_compute_split.py -v` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~120 seconds (full suite) |

---

## Sampling Rate

- **After every task commit:** Run the relevant narrow test file(s) from the Per-Task Verification Map below.
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q` (must stay green — standing CI gate).
- **Before `/gsd:verify-work`:** Full suite green, plus Plan 11's manual re-run of the previously-OOM'd 182-symbol `5m/high_bear` cell under the disk-bound path. No Russell-3000-scale backfill/compute proceeds until that measurement lands (enforced structurally: Plan 12 depends on Plan 11, and `alpha.universe.target_sample_size` stays `0`/crash-loud-unset until Plan 11 sets it).
- **Max feedback latency:** 120 seconds

---

## Wave 0 status

**No separate Wave 0 is needed.** TDD_MODE is off for this phase, so each implementation plan
carries its own test task in the same plan rather than deferring to a scaffolding wave. Every
test file the earlier draft listed as a Wave 0 gap is now created inside the plan that needs it:

| Original Wave 0 gap | Now created by |
|---------------------|----------------|
| Pre-flight `_check_cell_size` test file | 174-05 Task 3 (`tests/unit/test_ic_engine_cell_memory_bound.py`) |
| `disk_backed=True` cases in `test_batch_utils.py` | 174-01 Task 3 |
| `get_active_contracts` `dimension=` coverage | 174-06 Task 2 (`tests/unit/config/test_settings_active_contracts_dimension.py`) |
| Stratified-sampling reproducibility test | 174-08 Task 3 |
| `@pytest.mark.performance` memory-bounded ic_engine test | 174-05 Task 3 case 9 |

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-T1 | 174-01 | 1 | D-04b | T-174-05 | Scratch-dir and disk-backed threshold are APR-backed; scratch dir is non-tmpfs, owner-only | migration/DB | `psql -tA -c "SELECT config_key FROM config_state WHERE config_key LIKE 'infra.ic_engine.%'"` includes both new keys | created by task | ⬜ pending |
| 01-T2 | 174-01 | 1 | D-04b | T-174-06 | Over-capacity memmap write raises rather than truncating the cell | unit | `.venv/bin/pytest tests/unit/test_batch_utils.py -q` | created by task | ⬜ pending |
| 01-T3 | 174-01 | 1 | D-04b | T-174-04 | Disk-backed output row-identical to in-RAM; scratch files unlinked on close and context exit | unit | `.venv/bin/pytest tests/unit/test_batch_utils.py -k disk_backed -x` | created by task | ⬜ pending |
| 02-T1 | 174-02 | 1 | D-07a | T-174-07 | compute_eligible default is backed by a measured history-depth audit, not an assumption | script | `.venv/bin/python scripts/analysis/instrument_compute_eligibility_audit.py` | created by task | ⬜ pending |
| 02-T2 | 174-02 | 1 | D-07a | T-174-01 | No row is live_tradeable by default; is_active semantics unchanged for 37 call sites | migration/DB | `psql -tA -c "SELECT count(*) FROM instruments WHERE live_tradeable = true"` returns 0 | created by task | ⬜ pending |
| 03-T1 | 174-03 | 1 | D-08 | T-174-02, T-174-09 | Parameterized writes only; metadata omission impossible without a logged reason | static/import | `.venv/bin/ruff check src/config/instrument_onboarding.py` + import assertion | created by task | ⬜ pending |
| 03-T2 | 174-03 | 1 | D-08, V5 | T-174-03, T-174-10, T-174-42 | Unqualified ticker writes nothing; hostile symbol never reaches SQL text; partial write unwinds; the helper never commits or rolls back a bulk caller's outer transaction | unit | `.venv/bin/pytest tests/unit/config/test_instrument_onboarding.py -v` | created by task | ⬜ pending |
| 04-T1 | 174-04 | 1 | D-02 | T-174-12, T-174-48 | Raw holdings bytes persisted before parsing, so any sample is auditable to a file; browser-like headers sent and HTTP status / content-type / body plausibility verified before saving, so a CDN 403 challenge page is never parsed as a population | script | `.venv/bin/python scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py --dest /var/tmp/iwv_holdings.csv` | created by task | ⬜ pending |
| 04-T2 | 174-04 | 1 | D-02, V5 | T-174-03, T-174-02 | Header drift fails loud; ticker regex rejects SQL metacharacters; bad market caps rejected not coerced | unit | `.venv/bin/pytest tests/unit/scripts/test_universe_expansion_fetch_iwv_holdings.py -v` | created by task | ⬜ pending |
| 04-T3 | 174-04 | 1 | D-03 | — | Delisted-data feasibility answered with named tickers and a one-word verdict; pilot stays active-only | doc gate | `grep -qE "OBTAINABLE\|NOT OBTAINABLE\|UNRESOLVED" docs/research/russell3000-sourcing-and-delisted-feasibility.md` | created by task | ⬜ pending |
| 05-T1 | 174-05 | 2 | D-04a | — | New knobs are APR-backed config fields, no ceiling recalibration | unit | `.venv/bin/pytest tests/unit/test_ic_engine_fingerprint.py -q` + dataclass field assertion | exists | ⬜ pending |
| 05-T2 | 174-05 | 2 | D-04a | T-174-06, T-174-04 | Oversized cell fails before the first fetch; no auto-degrade handler; scratch cleaned in `finally` | unit | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_routing.py -q` | exists | ⬜ pending |
| 05-T3 | 174-05 | 2 | D-04a, D-04c | T-174-06, T-174-04, T-174-43 | Guard reachability, mode threshold, both cleanup paths, no-degrade source check, bounded peak RSS, `close()` strictly after the cell consumer returns (with a real read through `X_raw` inside the spied consumer), and a 2.2x two-scratch-file disk-headroom check | unit + performance | `.venv/bin/pytest tests/unit/test_ic_engine_cell_memory_bound.py -v` | created by task | ⬜ pending |
| 06-T1 | 174-06 | 2 | D-07a, D-07b | T-174-16, T-174-17 | Invalid dimension raises before any query; cache keyed by dimension | unit | `.venv/bin/pytest tests/unit/config/ tests/unit/services/test_service_contract_resolution.py -q` | exists | ⬜ pending |
| 06-T2 | 174-06 | 2 | D-07a, D-07b | T-174-01, T-174-16 | Default call returns today's identical symbol set; live dimension empty; no cross-dimension poisoning, including under 8-way concurrent cross-dimension contention on `_settings_lock` | unit/regression | `.venv/bin/pytest tests/unit/config/test_settings_active_contracts_dimension.py -v` | created by task | ⬜ pending |
| 07-T1 | 174-07 | 2 | D-06 | T-174-19, T-174-20 | Seed tags written `source='human'`; exposure vs sensitivity kept distinct; coarse tag preserved; `TagCalibrator` tolerates the new vocabulary rows without a schema/contract error | migration/DB + unit | `psql -tA -c "SELECT count(*) FROM tag_vocabulary WHERE tag IN ('eq_momentum','eq_quality','eq_low_vol','vol_proxy') AND category='exposure'"` returns 4, and `.venv/bin/pytest tests/unit/test_tag_calibrator.py -q` exits 0 | created/exists | ⬜ pending |
| 07-T2 | 174-07 | 2 | D-05, D-06 | T-174-18, T-174-21 | Ticker picks screened for structural price-series discontinuity, not liquidity alone | doc gate | `grep -q "Correction to CONTEXT.md D-06" docs/research/phase174-etf-gap-fill-ticker-selection.md` | created by task | ⬜ pending |
| 08-T1 | 174-08 | 2 | D-01, D-02 | T-174-24 | target_sample_size defaults to 0/unset; sampler fails loud rather than picking a number | migration/DB | `psql -tA -c "SELECT count(*) FROM config_state WHERE config_key LIKE 'alpha.universe.%'"` returns 3 | created by task | ⬜ pending |
| 08-T2 | 174-08 | 2 | D-02, V5 | T-174-02, T-174-03, T-174-23, T-174-50 | Dry-run default; writes only via the qualification-gated helper; no literal RNG seed; `--commit` aborts on an unreachable ib-gateway before the onboarding loop rather than mass-rejecting every symbol | static/script | `.venv/bin/ruff check` + dry run naming `alpha.universe.target_sample_size` | created by task | ⬜ pending |
| 08-T3 | 174-08 | 2 | D-02 | T-174-22, T-174-49 | Same seed draws an identical ordered list; a different seed does not; remainder allocation deterministic and directed at the smallest-cap buckets; bucket 0 proven to be the smallest-market-cap stratum with monotonic per-bucket means and per-row `cap_bucket_min`/`cap_bucket_max` bounds | unit | `.venv/bin/pytest tests/unit/scripts/test_universe_expansion_stratified_sourcing.py -v` | created by task | ⬜ pending |
| 09-T1 | 174-09 | 3 | D-04d | T-174-27 | Correlation block size is a throughput knob that cannot change results | migration/DB | `psql -tA -c "SELECT config_value FROM config_state WHERE config_key='infra.ic_engine.corr_row_block'"` returns 1000000 | created by task | ⬜ pending |
| 09-T2 | 174-09 | 3 | D-04d | T-174-25, T-174-04, T-174-43 | No whole-cell float64 copy; no whole-array boolean fancy-index; `X_nd`'s scratch file torn down from Plan 05's single cell-scoped `finally` (no nested cleanup `finally` inside the cell function) with the `NamedTemporaryFile` handle closed alongside the mmap | unit | `.venv/bin/pytest tests/unit/test_ic_engine_clustering.py tests/unit/test_ic_engine_compute_split.py -q` | exists | ⬜ pending |
| 09-T3 | 174-09 | 3 | D-04d | T-174-25, T-174-26, T-174-44 | Cluster labels array-equal to the `np.corrcoef` reference; stable on the catastrophic-cancellation case; identity held for exactly-constructed correlations just below / at / just above `cluster_max_corr`'s linkage cut across three deltas and three `row_block` values, or any residual boundary band recorded as a named numeric tolerance policy rather than a widened `atol` | unit | `.venv/bin/pytest tests/unit/test_ic_engine_streaming_correlation.py -v` | created by task | ⬜ pending |
| 10-T1 | 174-10 | 3 | D-06 | T-174-29, T-174-30 | Gateway proven to serve bars by a real request, not by container status; log caps intact | CLI | `docker ps --filter name=ib-gateway --format '{{.Status}}' \| grep -qi up` | n/a | ⬜ pending |
| 10-T2 | 174-10 | 3 | D-05, D-06, V5 | T-174-03, T-174-01 | Both ETFs qualified before any write; all four onboarding tables populated; not live-tradeable | DB | `psql -tA -c "SELECT count(DISTINCT symbol) FROM instrument_tags WHERE tag IN ('fx_em','vol_proxy')"` returns 2 | created by task | ⬜ pending |
| 10-T3 | 174-10 | 3 | D-06 | T-174-28, T-174-47 | Promotion gated on completed backfill AND non-zero tradeable rows in all four timeframes, reached only after all 8 (symbol, tf) pairs report `fetch_complete`; backfill launched `setsid`-detached with progress polled through `backfill_status`, not a log tail | DB | 8 non-empty (symbol, timeframe) groups in `market_data_ohlcv_tradeable` for the two new symbols, plus `SELECT count(*) FROM backfill_status WHERE symbol = ANY(...) AND fetch_complete` returning 8 | n/a | ⬜ pending |
| 11-T1 | 174-11 | 4 | D-04c | T-174-32, T-174-35 | Peak RSS measured and phase-attributed on the exact cell that OOM'd; no ceiling bump | manual + doc gate | `grep -q "5m/high_bear" docs/research/phase174-ic-engine-memory-fix-verification.md` | created by task | ⬜ pending |
| 11-T2 | 174-11 | 4 | D-04c | T-174-33 | Stopgap swapfile removed only if measurements show it is unneeded; fix re-proven without it | manual + CLI | `swapon --show` no longer lists `/swapfile_iceng`, or the document records the measured reason | created by task | ⬜ pending |
| 11-T3 | 174-11 | 4 | D-01 | T-174-31, T-174-34, T-174-45 | Supported count stated as "N symbols, bound by X" from a measured rows-to-cost curve at >=3 sizes with ACHIEVED row counts recorded; the above-corpus point reached by chunk-stream replay under aliased symbol names (not a duplicated `IN` list, which cannot multiply rows); zero result-table writes proven by before/after `count(*)` on `feature_ic_scores`, `feature_ic_scores_history` and `ic_cell_fingerprints` | DB + static | `psql -tA -c "SELECT config_value FROM config_state WHERE config_key='alpha.universe.target_sample_size'"` is a positive integer; `grep -ci "insert into" scripts/analysis/ic_engine_cell_scale_harness.py` returns 0; `.venv/bin/ruff check scripts/analysis/ic_engine_cell_scale_harness.py` clean | created by task | ⬜ pending |
| 12-T1 | 174-12 | 5 | D-02, D-03, V5 | T-174-02, T-174-03, T-174-22, T-174-23 | Sample traceable to file sha256 + seed + APR values; zero partial onboardings | DB | `psql -tA -c "SELECT count(*) FROM instruments i WHERE i.is_active AND NOT EXISTS (SELECT 1 FROM instrument_metadata m WHERE m.symbol=i.symbol AND i.compute_eligible=false)"` returns 0 | created by task | ⬜ pending |
| 12-T2 | 174-12 | 5 | D-02 | T-174-38, T-174-47 | Progress measured through `backfill_status`; zero-row fetch treated as failure, not success; backfill launched `setsid`-detached and proven session-independent, with launch/status/restart/reap commands recorded literally and IBC nightly-restart handling stated | DB + CLI | `psql -tA -c "SELECT count(*) FROM backfill_status WHERE status <> 'pending'"` greater than 0, and `ps -o pid,ppid,sid,cmd -p <PID>` shows the run in its own session | n/a | ⬜ pending |
| 12-T3 | 174-12 | 5 | D-01, D-02 | T-174-28, T-174-01, T-174-37, T-174-46 | Promotion doubly-gated on Plan 02's imported `COMPUTE_READY_PREDICATE_SQL` (all four timeframes, never a bare `EXISTS`); nothing live-tradeable; effective breadth explicitly not reclaimed; the three-tier implementation/data/empirical completion table reproduced with reached/not-reached marks | DB + static | `psql -tA -c "SELECT count(*) FROM instruments i WHERE i.compute_eligible AND (SELECT count(*) FROM backfill_status b WHERE b.symbol=i.symbol AND b.fetch_complete) < 4"` returns 0, and `grep -q COMPUTE_READY_PREDICATE_SQL scripts/infrastructure/universe_expansion_promote_compute_eligible.py` | created by task | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Requirement IDs

`phase_req_ids` was null in ROADMAP.md — this phase was scoped directly via `/gsd-discuss-phase`.
CONTEXT.md's decisions function as the requirement set. IDs used consistently across plan
frontmatter and this map:

| ID | Requirement | Plans |
|----|-------------|-------|
| D-01 | Do not lock a target instrument count; determine it from what the OOM fix supports | 174-08, 174-11, 174-12 |
| D-02 | Russell 3000 population, market-cap-stratified random sample | 174-04, 174-08, 174-12 |
| D-03 | Pilot is active-only; delisted feasibility researched in parallel, non-blocking | 174-04, 174-08, 174-12 |
| D-04a | Pre-flight cell-size estimate makes `_check_cell_size` reachable | 174-05 |
| D-04b | Disk-bounded incremental accumulation | 174-01 |
| D-04c | Peak memory bounded by chunk size, verified empirically | 174-05, 174-11 |
| D-04d | Remaining whole-cell copy points eliminated (`X_nd`, correlation) | 174-09 |
| D-05 | ETF gap-fill bundled into this phase | 174-07, 174-10 |
| D-06 | Factor / EM-FX / vol exposure gaps closed | 174-07, 174-10 |
| D-07a | 3-way backfill / compute / live eligibility schema split | 174-02, 174-06 |
| D-07b | Live dimension addressable and empty by default | 174-06 |
| D-08 | Onboarding writes an `instrument_metadata` row or logs an explicit skip | 174-03 |
| V5 | External ticker strings validated via `qualify_instrument()` before any DB write | 174-03, 174-04, 174-08, 174-10, 174-12 |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full-scale ic_engine run against the disk-bound fix | D-04c | Requires real multi-GB cell materialization and wall-clock/memory observation on the live server — not reproducible in a unit test | Plan 11 Task 1: re-run the 182-symbol `5m/high_bear` cell; confirm completion, sample peak RSS/swap/scratch size, attribute the peak to a phase, compare against Plan 09's predicted allocation sizes per `docs/foundation/performance-investigation-sop.md` |
| Swapfile removal safety | D-04c | Depends on the measured swap usage of the real run | Plan 11 Task 2: remove only if Task 1 measured negligible attributable swap; re-run the same cell without it |
| Supported-scale determination | D-01 | Requires running at two real symbol counts and measuring wall-clock and disk | Plan 11 Task 3: run at ~182 and ~400 symbols, record peak RSS / wall-clock / scratch size vs. count, name the binding constraint |
| IWV holdings file structure | D-02 | Requires live inspection of the actual downloaded file | Plan 04 Task 1: download the current IWV holdings export, record the header row index, verbatim column list, filler-row count, and whether market cap is direct or derived |
| ib-gateway bring-up | D-06 | Container state and IBKR session are external | Plan 10 Task 1: restart, confirm port 7497, and prove it serves bars with a real bounded historical request for an existing corpus symbol |
| Multi-day backfill completion | D-02 | Runs past the phase window, as Phase 173's corpus recompute did | Plan 12 Task 2: launch `setsid nohup ... & disown`, record PID, poll the `backfill_status` aggregate (never a log tail — todo 315's 0-byte-log class of bug), relaunch with the same command after any interruption having first reaped orphaned workers. Phase 174 closes at tier (a) implementation-complete; tier (b) data-complete and tier (c) empirical-complete are post-phase, per Plan 12's three-tier table |
| Scale-up row multiplication beyond the 231-symbol corpus | D-01 | No 400-symbol real peer set exists; duplicate values in a symbol list do not multiply returned rows | Plan 11 Task 3 Arm B: `scripts/analysis/ic_engine_cell_scale_harness.py` replays the real chunk stream K times under aliased symbol names, writes nothing, and records the achieved row count from the accumulator's write offset. Verify zero deltas on `feature_ic_scores` / `feature_ic_scores_history` / `ic_cell_fingerprints` before and after every run |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a documented manual-only entry with a measurement procedure
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Every previously-listed Wave 0 gap is created by the plan that needs it (no separate Wave 0 required — TDD_MODE off)
- [x] No watch-mode flags
- [x] Feedback latency < 120s for the unit-test tier
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned 2026-09-15
