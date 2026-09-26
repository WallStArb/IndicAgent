---
phase: 174
reviewers: [antigravity, codex]
reviewed_at: 2026-09-15T11:52:46Z
plans_reviewed: [174-01-PLAN.md, 174-02-PLAN.md, 174-03-PLAN.md, 174-04-PLAN.md, 174-05-PLAN.md, 174-06-PLAN.md, 174-07-PLAN.md, 174-08-PLAN.md, 174-09-PLAN.md, 174-10-PLAN.md, 174-11-PLAN.md, 174-12-PLAN.md]
---

# Cross-AI Plan Review — Phase 174

Claude (this session) is excluded as a reviewer for independence — it authored the plans being reviewed.

## Antigravity Review

# Phase 174: Cross-AI Plan Review

**Phase Goal:** Raise IndicAgent corpus breadth beyond $\approx 8.4$ by onboarding a market-cap-stratified random sample of the Russell 3000 single-name population, landing the structural `ic_engine` memory fix (eliminating whole-cell RAM materialization and correlation transients), establishing a 3-way instrument governance split (`is_active` / `compute_eligible` / `live_tradeable`), enforcing atomic metadata-mandatory instrument onboarding, and closing confirmed ETF exposure gaps (EM-FX and volatility).

---

## Executive Summary

Phase 174 is exceptionally well-researched, methodologically disciplined, and structurally coherent. Rather than treating universe expansion as a trivial list of tickers, the phase addresses the fundamental architectural bottlenecks that broke prior expansions:
1. **Memory scalability (todo 371 / D-04):** It identifies not only the `Float32ChunkAccumulator.finalize()` `np.vstack` duplication, but also the previously unflagged $\sim 30\text{ GB}$ float64 allocation inside `np.corrcoef(X_nd.T)` and the fancy-indexing copy in `X_nd = X_raw[:, cluster_input_mask]`.
2. **Governance safety (todo 274 / D-07):** It decouples backfill, batch compute, and live execution, safeguarding IBKR's strict 80-simultaneous-subscription cap.
3. **Data integrity (todo 282 / D-08 & todo 376 / D-03):** It enforces atomic 4-table writes for new instruments and correctly handles survivorship bias research in parallel without stalling the pilot.
4. **Empirical rigor:** It explicitly caught a factual error in the phase context regarding factor ETFs (MTUM/QUAL/USMV already exist in the database) and adjusted scope accordingly.

Across 12 plans structured into 5 waves, the sequencing is largely sound. However, there are critical implementation nuances—specifically surrounding async/sync connection boundaries in onboarding, mmap descriptor and slice lifecycle management, disk usage accounting during dual-memmap phases, and the synthetic 400-symbol scale-up test mechanics—that require hardening before execution.

---

## Plan-by-Plan Detailed Review

---

### Plan 174-01: Disk-backed `Float32ChunkAccumulator` Mode & APR Keys

#### 1. Summary
Plan 174-01 implements the storage foundation of D-04 by extending the existing `Float32ChunkAccumulator` in `services/_batch_utils.py` with an additive, disk-backed `np.memmap` mode and registering `infra.ic_engine.memmap_scratch_dir` and `infra.ic_engine.disk_backed_min_rows` via Migration 336. Existing in-RAM callers remain byte-for-byte unaffected, and the class gains context-manager and explicit `close()` cleanup semantics.

#### 2. Strengths
- **Single implementation maintained:** Reuses `Float32ChunkAccumulator` rather than forking a parallel class, honoring the lesson from Migration 249.
- **Strict backward compatibility:** `disk_backed` is keyword-only with default `False`, ensuring zero breaking changes for existing positional callers like `_compute_symbol_tf`.
- **Defensive APR registration:** Adheres to the established `config_schema` / `config_state` paired pattern with explicit provenance tags (`[initial_estimate]`) and ML learning target disclaimers.
- **Fail-loud allocation guard:** Under-estimated `estimated_rows` raises `ValueError` on overflow rather than truncating, preventing corrupted sample measurements.

#### 3. Concerns
- **File descriptor leak on `NamedTemporaryFile` (`MEDIUM`):** In Task 2, `self._tmpfile = tempfile.NamedTemporaryFile(dir=scratch_dir, suffix=".memmap", delete=False)` opens a file handle. Calling `np.memmap(self._tmpfile.name, ...)` opens a separate descriptor via the OS `mmap`. In `close()`, closing `self._memmap._mmap` and unlinking the path without calling `self._tmpfile.close()` leaks Python file descriptors across thousands of cell iterations.
- **Unverified directory creation in library code (`LOW`):** Task 1 creates `/var/tmp/ic_engine_scratch` manually via bash, but `Float32ChunkAccumulator` should defensively execute `os.makedirs(scratch_dir, exist_ok=True)` when `disk_backed=True` to prevent `FileNotFoundError` in containerized test runners or scratch environments.

#### 4. Suggestions
- Ensure `Float32ChunkAccumulator.close()` explicitly executes `if hasattr(self, "_tmpfile"): self._tmpfile.close()` before or immediately after closing the mmap buffer.
- Add an explicit test case in `test_batch_utils.py` verifying that OS open file descriptors do not increase after creating, writing, and closing a disk-backed accumulator.

#### 5. Risk Assessment: LOW
The design is isolated, additive, and well-covered by synthetic unit tests. The core logic relies on standard NumPy `memmap` behaviors without third-party dependencies.

---

### Plan 174-02: `instruments` Governance Split & Eligibility Audit

#### 1. Summary
Plan 174-02 addresses D-07 and todo 274 by adding `compute_eligible` and `live_tradeable` boolean columns to `instruments` via Migration 337. It guarantees non-breaking defaults for existing consumers, executes an audit script (`instrument_compute_eligibility_audit.py`) to verify that today's 231 active instruments actually possess tradeable history, and comments the schema to codify the 80-subscription cap constraint.

#### 2. Strengths
- **Non-breaking additive schema:** Keeps `is_active` intact and functioning as "backfill-eligible", avoiding risky mass-refactors across 37 downstream call sites.
- **Evidence-based migration:** Rather than assuming all 231 existing active rows are compute-ready, Task 1 measures history depth across all 4 timeframes via `market_data_ohlcv_tradeable`.
- **Subscription cap defense:** Enforces `live_tradeable boolean NOT NULL DEFAULT false`, ensuring newly added instruments can never accidentally be subscribed to by live daemons.

#### 3. Concerns
- **Full hypertable scan overhead in audit (`MEDIUM`):** `instrument_compute_eligibility_audit.py` aggregates row counts and timestamp bounds over `market_data_ohlcv_tradeable` for 231 symbols across 4 timeframes. Scanning hundreds of millions of rows across all chunks in a single script run could take 15–30+ minutes and cause I/O contention if not bounded or indexed efficiently.
- **Semantic handling of empty symbols (`LOW`):** If the audit discovers active symbols with 0 tradeable rows, setting them to `compute_eligible=true` (for backward-compatibility) preserves existing behavior but propagates known dead weight to compute daemons.

#### 4. Suggestions
- In `instrument_compute_eligibility_audit.py`, structure the query to leverage hypertable chunk metadata or index scans on `(symbol, timeframe, timestamp)` rather than doing an unconstrained sequential scan of the full view.
- If any active symbols have 0 tradeable rows across all timeframes, record them in the migration header and open a tracked follow-up item for explicit decommission.

#### 5. Risk Assessment: LOW
`ALTER TABLE instruments ADD COLUMN ... DEFAULT` is instantaneous on PostgreSQL 11+ (metadata-only update). The table is small (~253 rows) and not a hypertable.

---

### Plan 174-03: `onboard_instrument()` Transactional Helper

#### 1. Summary
Plan 174-03 creates `src/config/instrument_onboarding.py`, providing a unified, atomic entry point (`onboard_instrument()`) for registering new instruments. It enforces contract qualification via IBKR (ASVS V5), requires `instrument_metadata` (preventing recurrence of todo 282), writes `backfill_status` seed rows, tags the instrument with `source='human'`, and wraps all operations in a single database transaction.

#### 2. Strengths
- **Enforces 4-table atomicity:** Bundles `instruments`, `instrument_tags`, `instrument_metadata`, and `backfill_status` into one atomic unit, completely eliminating partial onboarding states.
- **Protocol abstraction:** Defines `InstrumentQualifier` as a `typing.Protocol`, avoiding circular imports with `src/providers/ibkr.py` and keeping unit tests clean of network dependencies.
- **Elimination of silent skips:** Makes omitting `instrument_metadata` impossible without an explicit `metadata_skip_reason`, which triggers a loud structlog warning.
- **Strict SQL injection defense:** Enforces parameterized queries exclusively and includes automated test cases asserting injection strings are never interpolated into SQL text.

#### 3. Concerns
- **Async/Sync connection impedance mismatch (`HIGH`):** The signature is `async def onboard_instrument(conn, instrument, *, qualifier, ...)` and awaits `qualifier.qualify_instrument()`. However, the plan states `conn` is "an open psycopg connection owned by the caller." In psycopg 3, `psycopg.Connection` (sync) and `psycopg.AsyncConnection` (async) have incompatible interfaces. If `conn` is synchronous, executing blocking cursor calls inside an async function blocks the event loop; if `conn` is async, every execute must be awaited (`await cur.execute(...)`). The plan must be unambiguous on whether `conn` is an `AsyncConnection` or a sync connection run in an executor.
- **Transaction boundary collision (`MEDIUM`):** The plan states the helper "opens ONE transaction and either commits every write or rolls all of them back", while simultaneously stating `conn` is "owned by the caller." If `onboard_instrument()` calls `conn.commit()`, it closes the caller's transaction context, preventing callers from managing batch transactions. It should instead use an explicit context-managed transaction (`with conn.transaction():` or `async with conn.transaction():`) or a SAVEPOINT.

#### 4. Suggestions
- Explicitly declare the type of `conn` as `psycopg.AsyncConnection` (or `asyncpg.Connection` if that is the repo standard for async code), and ensure all cursor calls use `await cur.execute()`.
- Use a nested transaction/savepoint (`async with conn.transaction():`) so that callers executing bulk onboarding can maintain outer batch transactions without unexpected commits.

#### 5. Risk Assessment: MEDIUM
High architectural value, but the async/sync connection mechanics must be clearly defined to prevent runtime typing and event loop blocking errors.

---

### Plan 174-04: IWV Holdings Sourcing & Delisted Feasibility

#### 1. Summary
Plan 174-04 resolves the data sourcing prerequisites for stratified sampling by implementing `scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py`. It downloads the official iShares Russell 3000 ETF (IWV) holdings export, parses and validates constituents defensively, confirms whether market cap is directly available or derived, and investigates the feasibility of obtaining historical data for delisted constituents (todo 376) without gating the active-only pilot.

#### 2. Strengths
- **Defensive input parsing:** Treats downloaded CSVs as untrusted input with uppercase bounded regex validation (`^[A-Z][A-Z0-9.\-]{0,9}$`), schema mismatch checks, and positive float market-cap assertions.
- **Non-blocking parallel research:** Satisfies D-03 by investigating delisted constituent feasibility in parallel, producing an explicit verdict (`OBTAINABLE`, `NOT OBTAINABLE`, or `UNRESOLVED`) while locking the Phase 174 pilot to active-only.
- **Auditable byte retention:** Writes downloaded holdings files to disk verbatim before parsing, ensuring that any generated universe sample can be traced back to exact source bytes.

#### 3. Concerns
- **iShares CDN bot-blocking / HTTP 403 (`MEDIUM`):** iShares / BlackRock endpoints frequently block default Python `urllib` and `requests` User-Agents with HTTP 403 Forbidden or Cloudflare/Akamai challenge screens. If the script uses bare HTTP requests without standard browser headers, downloads will fail.
- **Encoding and delimiter anomalies (`LOW`):** Issuer CSV exports periodically switch between UTF-8 and Latin-1/Windows-1252, or include trailing metadata footnotes that break generic CSV line iterators.

#### 4. Suggestions
- Implement explicit HTTP request headers (standard browser `User-Agent`, `Accept`, `Accept-Language`) and verify HTTP status and MIME types before saving `/var/tmp/iwv_holdings.csv`.
- In `parse_holdings()`, handle possible file encodings gracefully (`encoding='utf-8'` with fallback to `latin1`) and verify the header row search handles preamble variations.

#### 5. Risk Assessment: LOW
Low risk. Sourcing is decoupled from the live database, and unit tests use isolated mock CSV fixtures.

---

### Plan 174-05: `ic_engine` Pre-flight Check & Disk-backed Accumulation

#### 1. Summary
Plan 174-05 wires the D-04 structural memory fix into `services/ic_engine.py`. It inserts a pre-flight upper-bound cell-size check (`len(regime_timestamps) * len(symbol_list)`) right after fetching timestamps to make `_check_cell_size` reachable before data fetching. It switches accumulation to `Float32ChunkAccumulator(disk_backed=True)` when estimated rows exceed `infra.ic_engine.disk_backed_min_rows`, and wraps cell compute in a `finally` block to ensure scratch files are unlinked on all exit paths.

#### 2. Strengths
- **True pre-flight guard (D-04a):** Eliminates the unreachable guard flaw (where the check previously ran only after full in-memory materialization) by evaluating the theoretical upper-bound row count before issuing SQL queries.
- **Scratch disk headroom pre-check:** Executes `shutil.disk_usage` before allocating the memmap, preventing mid-run disk-fill crashes reminiscent of the 2026-08-13 incident.
- **Static verification of no-degrade contract:** Includes an automated test that inspects AST/source code to verify no automatic subsampling or stride-widening fallback was introduced for `CellTooLargeError`.

#### 3. Concerns
- **Premature mmap closure during downstream consumption (`HIGH`):** In Task 2 (c), `X_acc.close()` is placed in a `finally` block. `X_acc.finalize()` returns a slice view over the memmap: `X_raw = self._memmap[: self._write_offset]`. If `_compute_one_cross_sectional_cell` executes asynchronously or if `close()` is called before all downstream consumers (including feature standardization and correlation passes) finish reading `X_raw`, accessing `X_raw` will raise `ValueError: mmap can't access closed memory` or trigger a SIGSEGV. The `finally` block must wrap the entire cell processing pipeline, and cannot execute until `_compute_one_cross_sectional_cell` has completely returned.
- **Dual-memmap disk accounting gap (`MEDIUM`):** The pre-allocation disk check computes `n_estimated * n_cols * 4` bytes. However, Plan 09 introduces a second memmap (`X_nd`) of comparable row dimension. Peak scratch disk usage is therefore $\approx 2 \times (\text{rows} \times \text{cols} \times 4)$. Checking only for a single memmap could under-report required scratch space.

#### 4. Suggestions
- Structure the `finally` block in `_compute_cross_sectional_tf` with extreme care: ensure `_compute_one_cross_sectional_cell` runs synchronously within the `try:` scope, and confirm that no returned objects hold open buffer references to the closed mmap.
- Update the disk headroom check formula to `2.2 * n_estimated * n_cols * 4` bytes to comfortably cover both `X_raw` and `X_nd` scratch allocations.

#### 5. Risk Assessment: MEDIUM
Directly modifies the core compute loop of `ic_engine.py`. Correct placement of the mmap lifecycle boundary is critical to avoid memory corruption or access-after-close errors.

---

### Plan 174-06: `get_active_contracts(dimension=)` & Cache Isolation

#### 1. Summary
Plan 174-06 parameterizes `get_active_contracts()` in `src/config/settings.py` with an optional `dimension: str = "compute"` argument mapping to `"backfill"`, `"compute"`, and `"live"`. It refactors the module-level cache from a single list into a per-dimension dictionary guarded by the existing `_settings_lock`, preventing cross-dimension cache poisoning.

#### 2. Strengths
- **Elimination of cache poisoning (T-174-16):** Keying `_active_contracts_cache` and its TTL timestamps by dimension prevents a `dimension="live"` call (which returns empty) from poisoning subsequent `dimension="compute"` callers.
- **Default-equivalence guarantee (D-07a):** Because Migration 337 set `compute_eligible=true` for all existing active instruments, `dimension="compute"` returns the exact symbol set previously returned by the unparameterized query.
- **Fail-loud dimension validation:** Unrecognized dimensions immediately raise `ValueError` before executing SQL, preventing accidental fallback to default behavior.

#### 3. Concerns
- **Cold-start fallback cache scoping (`LOW`):** On database query failure, the fallback retrieves the warm cache for that specific dimension. If cold-starting and the database is unreachable, it logs a critical error and returns `[]`. This is correct, but ensure that invalidating the cache (`invalidate_active_contracts_cache()`) clears all dimension keys cleanly without leaving stale timestamps.

#### 4. Suggestions
- Confirm that `invalidate_active_contracts_cache()` accepts an optional `dimension: str | None = None` parameter (clearing all dimensions when `None`, or a single dimension when specified), retaining its zero-argument signature for existing event handlers.
- Add a thread-concurrency test validating that simultaneous calls across different dimensions under contention never block or corrupt cache state.

#### 5. Risk Assessment: LOW
Well-contained, highly backward-compatible modification to `src/config/settings.py` with clear regression test coverage.

---

### Plan 174-07: Factor & Vol Exposure Tag Taxonomy & Ticker Decision

#### 1. Summary
Plan 174-07 corrects a critical misconception from the phase context by documenting that momentum (`MTUM`), quality (`QUAL`), and low-vol (`USMV`) factor ETFs already exist in the database with full OHLCV history. It adds `eq_momentum`, `eq_quality`, `eq_low_vol`, and `vol_proxy` to `tag_vocabulary` via Migration 338, re-tags the existing ETFs without dropping `eq_factor`, and records evidence-backed decisions for EMLC (EM-FX) and VIXY (volatility proxy).

#### 2. Strengths
- **Factual correction and scope reduction:** Avoids redundant instrument onboarding and wasteful backfill compute by proving that factor exposure already exists in the corpus.
- **Preservation of taxonomy hierarchy:** Retains the parent `eq_factor` tag while adding granular factor sub-tags, maintaining compatibility with existing coarse-grained filters.
- **Discontinuity screening (T-174-18):** Selects `VIXY` over `VXX` explicitly because VXX's March 2022 share creation halt caused it to trade at an artificial premium, which would introduce severe regime artifacts into model features.

#### 3. Concerns
- **TagCalibrator interaction (`LOW`):** `TagCalibrator` operates on `tag_vocabulary` and calibrates empirical sensitivities. The new tags are marked category `exposure` and `source='human'`, which according to ITR rules protects them from calibration or expiration. However, tests should verify that `TagCalibrator` does not raise schema or contract errors when encountering the new vocabulary.

#### 4. Suggestions
- In the `evidence` JSONB payload for `EMLC`, explicitly record the duration and sovereign credit contamination caveat so that residualization pipelines are documented to strip non-currency factor loadings.
- Ensure that `tests/unit/test_tag_calibrator.py` passes cleanly with the new tags present in `tag_vocabulary`.

#### 5. Risk Assessment: LOW
Zero code changes to compute daemons; pure SQL metadata migration and research documentation.

---

### Plan 174-08: Stratified Sampler & Reproducible Draw

#### 1. Summary
Plan 174-08 registers `alpha.universe.*` APR keys (random seed, bucket count, and a crash-loud unset target size of `0`) via Migration 339, and implements `scripts/infrastructure/universe_expansion_stratified_sourcing.py`. The script performs quantile discretization (`pandas.qcut`) on market cap, draws an even, APR-seeded random sample across strata, and provides `--dry-run` and `--commit` execution modes that write exclusively through `onboard_instrument()`.

#### 2. Strengths
- **Unbiased empirical hypothesis test (D-02):** By sampling across all market-cap deciles rather than cherry-picking small-caps, the design eliminates selection bias and tests the down-cap alpha hypothesis objectively.
- **Enforces D-01 via crash-loud default:** `alpha.universe.target_sample_size` defaults to `0`, ensuring the script refuses to run until Plan 11 empirically measures supported scale.
- **Auditable reproducibility:** Pins the NumPy random generator seed to APR, records holdings file SHA256, and uses deterministic remainder allocation across buckets without consuming extra RNG draws.

#### 3. Concerns
- **Missing gateway pre-flight check in commit mode (`MEDIUM`):** In `--commit` mode, the script iterates through drawn symbols and calls `onboard_instrument()`, which awaits `qualify_instrument()`. If `ib-gateway` is stopped or logged out, all hundreds of qualification checks will fail sequentially, logging hundreds of rejections. The script must execute a quick pre-flight connectivity check against IBKR before starting the loop.
- **Stratum depletion under IBKR rejection (`LOW`):** If micro-cap symbols in the lowest deciles have high qualification failure rates (e.g., OTC listings, non-standard trading classes), the lowest buckets may end up under-represented in the committed sample. The plan records rejections, but does not provide an automated mechanism to draw replacement candidates from the same bucket.

#### 4. Suggestions
- Add an explicit gateway connectivity check at the beginning of `main()` when `--commit` is passed, aborting immediately if IBKR is unreachable.
- Consider adding an optional `--auto-fill-shortfall` flag that draws supplementary random candidates from the same decile if initial picks fail IBKR qualification, preserving target stratum balance.

#### 5. Risk Assessment: LOW
Pure CLI utility and APR migration; no changes to production daemons. Testing is completely decoupled via synthetic pandas DataFrames.

---

### Plan 174-09: Streaming Correlation & Column-wise `X_nd`

#### 1. Summary
Plan 174-09 addresses the primary root cause of cross-sectional cell OOMs by replacing `np.corrcoef(X_nd.T)` with a two-pass blocked streaming correlation (`_streaming_feature_correlation`), eliminating a hidden $\sim 30\text{ GB}$ float64 allocation. It registers `infra.ic_engine.corr_row_block` via Migration 340, refactors `_cluster_features` to accept precomputed correlation matrices, and constructs `X_nd` column-by-column into a scratch memmap to eliminate fancy-indexing memory spikes.

#### 2. Strengths
- **Deep architectural diagnosis:** Pinpoints the hidden float64 conversion in NumPy's correlation routine that caused memory usage to explode at 15M rows $\times$ 250 columns.
- **Numerically stable two-pass formulation:** Uses centered Gram matrix accumulation ($\Sigma (x-\mu)(x-\mu)^T$) in float64 over row blocks, avoiding the catastrophic cancellation risks inherent in single-pass naive variance algorithms.
- **Strict output identity:** Verifies that cluster assignments downstream of `fcluster` remain bit-identical to the reference implementation across multiple synthetic feature distributions.

#### 3. Concerns
- **Lifecycle and cleanup of the second memmap (`MEDIUM`):** In Task 2 (b), `X_nd` is built as a second memmap in `config.memmap_scratch_dir`. While Plan 05 cleans up `X_acc`, `X_nd` is allocated inside `_compute_one_cross_sectional_cell`. If an exception occurs during the per-scale ranking or correlation pass, `X_nd`'s temporary file on disk could be leaked unless wrapped in its own explicit `try...finally` block.
- **I/O performance under multi-pass disk access (`MEDIUM`):** Computing means in Pass 1 and covariance in Pass 2 across 15M rows requires reading the full feature array twice from disk. While sequential NVMe reads are fast, on systems with high I/O wait, this could prolong cell wall-clock time. `corr_row_block` (default 1,000,000 rows $\approx 1\text{ GB}$) is reasonably sized, but must be profiled during execution.

#### 4. Suggestions
- Wrap the creation, usage, and unlinking of `X_nd` inside a dedicated context manager or `try...finally` block within `_compute_one_cross_sectional_cell`, ensuring it does not rely on the outer accumulator's cleanup logic.
- Benchmark Pass 1 and Pass 2 elapsed time in `test_ic_engine_streaming_correlation.py` to confirm that page-cache caching keeps the second pass I/O overhead negligible.

#### 5. Risk Assessment: MEDIUM
Touches mathematical core and memory management of `ic_engine`. The logic is thoroughly tested, but mmap lifecycle management requires strict scoping.

---

### Plan 174-10: `ib-gateway` Bring-up & Gap-Fill ETF Onboarding

#### 1. Summary
Plan 174-10 serves as the end-to-end canary test for the new onboarding pipeline. It restarts the `ib-gateway` container (dormant since 2026-09-07), validates historical bar data delivery via a test query on `SPY`, executes `scripts/infrastructure/universe_expansion_onboard_gap_fill_etfs.py` to onboard EMLC and VIXY through `onboard_instrument()`, executes their historical backfill across 4 timeframes, and promotes them to `compute_eligible=true` only after data is verified in `market_data_ohlcv_tradeable`.

#### 2. Strengths
- **Safe canary validation:** Proves the complete onboarding, qualification, backfill, and promotion stack on 2 instruments before executing at Russell-3000 scale.
- **Authentic operational verification:** Verifies gateway health with an actual historical bar request rather than assuming container `Up` status implies authentication.
- **Doubly-gated promotion:** Promotion to `compute_eligible` requires both `fetch_complete=true` in `backfill_status` and non-zero rows in `market_data_ohlcv_tradeable`, preventing phantom promotions.

#### 3. Concerns
- **Asynchronous backfill duration vs. synchronous task completion (`MEDIUM`):** Backfilling 5m bars back to listing date (e.g., 2010 for EMLC, 2011 for VIXY) involves over a decade of intraday data. Due to IBKR pacing restrictions (maximum 60 historical requests per 10 minutes), fetching two full intraday histories can take several hours. Task 3 mentions running in the background, but its acceptance criteria require all 8 timeframes to be completed. The plan must clarify that Task 3 execution will pause or wait for the background backfill to finish before running the verification queries.
- **IBKR authentication / 2FA blocker (`MEDIUM`):** If IBKR Gateway encounters a credential expiration or requires mobile 2FA authorization upon restart, automated bring-up will stall. The plan explicitly provides a stop-and-record fallback, which is safe, but this remains an external dependency risk.

#### 4. Suggestions
- In Task 3, specify the exact polling mechanism or systemd/tmux monitoring command used to observe backfill progress until completion before invoking the promotion UPDATE.
- Add an explicit timeout and notification step if IBKR Gateway remains unauthenticated for more than 5 minutes after container start.

#### 5. Risk Assessment: MEDIUM
Relies on external IBKR Gateway networking and authentication, and involves long-running historical backfill execution.

---

### Plan 174-11: Empirical Memory Verification & Scale Determination

#### 1. Summary
Plan 174-11 validates the memory fixes empirically in accordance with the project's Performance Investigation SOP. It re-runs the fatal `5m/high_bear` cell (182 symbols) and measures peak RSS and phase attribution. It then removes the 96GB swapfile (`/swapfile_iceng`) if swap usage is negligible, re-tests, and executes an incremental scale-up run (~400 symbols) to determine the true binding constraint and populate `alpha.universe.target_sample_size` via an auditable APR update.

#### 2. Strengths
- **Follows Performance SOP strictly:** Replaces theoretical reasoning with empirical measurement, profiling peak RSS across each specific execution phase.
- **Elimination of "bigger box" stopgap:** Actively removes the 96GB swapfile, ensuring the architecture is genuinely memory-bounded rather than leaning on disk thrashing.
- **Direct resolution of D-01:** Derives target universe size from measured memory and extrapolated wall-clock curves rather than committing to an unverified arbitrary target.

#### 3. Concerns
- **Mechanism for the 400-symbol synthetic peer set (`HIGH`):** Task 3 states: "Run the same 5m/high_bear cell at a materially larger synthetic peer-set size — approximately 400 symbols, achieved by extending the symbol list with existing corpus symbols so the cell's row count roughly doubles." However, the entire active corpus currently contains only 231 symbols! In SQL, querying `WHERE symbol IN ('AAPL', 'AAPL', ...)` evaluates identical symbols only once; duplicate symbols in the `symbol_list` will not double the extracted rows from `feature_vectors`. To genuinely double the cell size to 400 symbols, the test must either query multiple distinct timeframes/regimes, synthesize data, or cross-join in SQL.
- **Sudo requirement for swapoff (`LOW`):** Removing `/swapfile_iceng` requires `sudo swapoff`. The plan cites `operations-infrastructure.md`, but execution must ensure sudo credentials or permissions are available in the running environment.

#### 4. Suggestions
- Clarify Task 3's implementation for achieving 400 symbols: if using live DB data, explicitly define how the row multiplier is achieved (e.g., mocking the database cursor to return duplicate chunks with modified symbol names, or querying an expanded set of synthetic symbols).
- Ensure that the empirical verification document explicitly records CPU iowait percentages during the streaming correlation phase to assess NVMe vs. CPU bottlenecks.

#### 5. Risk Assessment: MEDIUM
Involves system-level swap reconfiguration and stress-testing batch compute to its operational limits.

---

### Plan 174-12: Universe Sourcing, Backfill Launch & Promotion

#### 1. Summary
Plan 174-12 executes the phase objective: drawing the Russell 3000 stratified sample at the scale determined by Plan 11, onboarding all qualifying symbols across all 4 tables with `compute_eligible=false`, launching background historical backfill across 4 timeframes, deploying `universe_expansion_promote_compute_eligible.py` for automated promotion, and documenting the breadth delta without premature claims of effective breadth expansion.

#### 2. Strengths
- **Complete input provenance:** Records IWV holdings URL, download timestamp, SHA256 hash, and APR parameters in `phase174-universe-expansion-sample-record.md`, guaranteeing full reproducibility.
- **Clean promotion automation:** Provides a standalone, doubly-gated promotion script that can be run periodically or via cron as multi-day backfills land.
- **Honest reporting of effective breadth:** Explicitly refuses to claim an updated effective breadth ($\approx 8.4$) until a full out-of-sample corpus recompute is executed, adhering strictly to core project values.

#### 3. Concerns
- **Multi-day backfill execution vs. phase sign-off (`HIGH`):** Backfilling 200–400 newly onboarded equity tickers across 4 timeframes (5m, 15m, 1h, 1d) via IBKR will take several days due to pacing constraints (60 requests / 10 minutes). When Plan 12 finishes, Task 3 will run `universe_expansion_promote_compute_eligible.py`, but almost zero newly added symbols will have completed all timeframes yet! Consequently, `compute_eligible` will remain `false` for almost the entire new sample at the moment Phase 174 is marked complete. While the plan notes that backfill continues past the phase boundary (mirroring Phase 173), stakeholders must be acutely aware that corpus breadth in `feature_vectors` and `ic_engine` will not actually expand until days later.
- **Systemd / process supervision for long-running backfill (`MEDIUM`):** Launching a multi-day background task via CLI without explicit systemd unit or persistent tmux/screen management creates a high risk of process termination if the user session disconnects.

#### 4. Suggestions
- Provide a systemd service template or hardened tmux/nohup execution guide for `infrastructure_run_historical_pipeline.py`, complete with restart-on-failure handling for nightly IBC restarts.
- Include a progress-tracking command in the plan summary so that users can check backfill completion percentage and trigger `universe_expansion_promote_compute_eligible.py` post-phase completion.

#### 5. Risk Assessment: HIGH
High operational complexity involving multi-day background data ingestion across hundreds of instruments, subject to IBKR rate limits and network interruptions.

---

## Cross-Cutting Analysis

### 1. Missing Edge Cases & Error Handling
- **Async/Sync Database Drivers:** `onboard_instrument()` in Plan 03 combines async qualification with database operations. The plans must ensure that the connection object passed to `onboard_instrument` matches the execution context (using an `AsyncConnection` for async callers or wrapping sync calls in an executor).
- **Mmap View Invalidation:** When `Float32ChunkAccumulator.close()` unlinks and closes mmap handles, any outstanding NumPy array slices become invalid. The `finally` blocks in Plans 05 and 09 must guarantee that all downstream compute has concluded before closing buffers.
- **Dual Memmap Disk Space:** The pre-flight disk check must account for the simultaneous existence of both `X_raw` and `X_nd` scratch files.

### 2. Dependency Ordering & Wave Structure
The 5-wave structure is logically sequenced:
- **Wave 1 (Foundation):** Accumulator memmap mode (01), Schema split (02), Onboarding helper (03), Holdings sourcing (04). *All independent.*
- **Wave 2 (Wiring & Design):** `ic_engine` pre-flight (05), `get_active_contracts(dimension=)` (06), Tag taxonomy & ETF decisions (07), Stratified sampler (08). *Strictly depends on Wave 1.*
- **Wave 3 (Elimination & Canary):** Streaming correlation (09), ETF onboarding/backfill canary (10). *Depends on Wave 2.*
- **Wave 4 (Verification):** Empirical memory test & scale determination (11). *Depends on Wave 3.*
- **Wave 5 (Execution):** Full universe draw, onboarding, backfill launch (12). *Depends on Wave 4.*

*Verdict:* The dependency DAG is completely acyclic and sound. Prerequisite infrastructure is proven on a 2-symbol canary (Plan 10) and an empirical benchmark (Plan 11) before bulk execution (Plan 12).

### 3. Scope Creep & Over-Engineering
- **Restraint demonstrated:** Futures continuous contract construction (todo 377) was correctly excluded. Low-vol factor addition was eliminated after discovering existing coverage. Delisted constituent research was kept non-blocking (todo 376).
- **Appropriate engineering:** The streaming correlation and column-by-column `X_nd` implementations in Plan 09 might appear complex, but are entirely justified: `np.corrcoef` would have created a fatal 30GB float64 allocation at universe scale.

### 4. Security Considerations (ASVS V5 & STRIDE)
- **Input Validation (ASVS V5):** External CSV tickers are strictly validated against regex `^[A-Z][A-Z0-9.\-]{0,9}$` and must resolve via IBKR's `qualify_instrument()` allowlist before reaching SQL.
- **SQL Injection:** Parameterized queries (`%(param)s`) are enforced across all migrations, helpers, and scripts, backed by grep assertions and malicious payload unit tests.
- **Elevation of Privilege:** `live_tradeable` defaults to `false` across all schemas and scripts, protecting IBKR's 80-subscription cap.

### 5. Performance Implications
- **Memory:** Bounded from $O(\text{cell\_size})$ to $O(\text{chunk\_size})$ during accumulation and $O(\text{corr\_row\_block})$ during clustering. Peak RAM will remain well within the 29GB system limit even at 15M rows.
- **Disk I/O:** Two-pass streaming correlation requires sequential reads of 20–50 GB scratch arrays. On NVMe SSDs, this overhead is minimal ($\approx 15\text{–}30\text{ seconds}$), but requires monitoring.
- **Wall-Clock Backfill:** Sourcing 200–400 instruments across 4 intraday timeframes will take 48–96+ hours due to IBKR historical pacing limits. The plan correctly decouples backfill completion from phase closure.

### 6. Achievement of Phase Goals (D-01 through D-08)
- **D-01 (Flexible Count):** Achieved via Plan 11's empirical determination and Plan 08's unset default.
- **D-02 (Stratified Russell 3000):** Achieved via Plan 04 and Plan 08's `pandas.qcut` sampler.
- **D-03 (Survivorship Bias):** Achieved via Plan 04's parallel, non-blocking research note.
- **D-04 (ic_engine Structural Memory Fix):** Achieved via Plans 01, 05, and 09.
- **D-05 / D-06 (ETF Gap-Fill):** Achieved via Plan 07's correction and Plan 10's canary onboarding.
- **D-07 (Governance Split):** Achieved via Plan 02 and Plan 06.
- **D-08 (Mandatory Metadata):** Achieved via Plan 03's transactional helper.

---

## Plan Risk Matrix

| Plan | Focus Area | Complexity | Risk Level | Primary Risk Factor |
| :--- | :--- | :---: | :---: | :--- |
| **174-01** | Disk-backed Accumulator | Medium | **LOW** | Potential file descriptor leak if `NamedTemporaryFile` handle is not closed alongside mmap |
| **174-02** | Governance Split DDL | Low | **LOW** | Long-running sequential scan during audit script execution across tradeable view |
| **174-03** | `onboard_instrument()` Helper | Medium | **MEDIUM** | Async/sync impedance mismatch on `conn` and transaction boundary management |
| **174-04** | IWV Sourcing & Delisted Research | Low | **LOW** | Issuer HTTP endpoint blocking Python User-Agent headers |
| **174-05** | `ic_engine` Wiring & Cleanup | Medium | **MEDIUM** | Premature closure of mmap buffers before downstream consumers finish execution |
| **174-06** | `get_active_contracts(dimension=)` | Low | **LOW** | Thread safety under high-concurrency cold-start conditions |
| **174-07** | Factor/Vol Tag Taxonomy | Low | **LOW** | Minor potential schema warnings in `TagCalibrator` |
| **174-08** | Stratified Sampler Script | Medium | **LOW** | Rejection-induced decile shortfall in micro-cap strata |
| **174-09** | Streaming Correlation & `X_nd` | High | **MEDIUM** | Second memmap scratch file lifecycle and I/O wait during two-pass correlation |
| **174-10** | ETF Canary Onboarding & Backfill | High | **MEDIUM** | Multi-hour intraday backfill duration and IBKR Gateway authentication stalls |
| **174-11** | Empirical Verification & Scale Test | High | **MEDIUM** | Synthetic 400-symbol test mechanics on a 231-symbol database |
| **174-12** | Full Sourcing & Backfill Launch | High | **HIGH** | Multi-day backfill execution, process supervision, and decoupled compute eligibility |

---

## Final Recommendation

**VERDICT: APPROVED WITH CONDITIONS (GO)**

The plan set for Phase 174 represents exemplary quantitative software engineering. It is approved to proceed into Wave 1 execution, subject to the following execution-time adjustments:
1. **Clarify DB Connection in Plan 03:** Ensure `onboard_instrument()` explicitly specifies its database connection driver type (`AsyncConnection` vs sync connection run in executor) and uses nested transaction savepoints.
2. **Harden Mmap Scoping in Plans 05 & 09:** Ensure that both `X_raw` and `X_nd` scratch files remain open until all downstream correlation and standardization steps completely finish, with their cleanup handled strictly inside dedicated `finally` blocks.
3. **Refine the 400-Symbol Benchmark in Plan 11:** Detail the exact SQL/mock mechanism used to double row volume during the synthetic scale-up test.
4. **Establish Process Supervision in Plan 12:** Ensure the multi-day background backfill is launched under persistent process management (e.g., tmux or systemd) with explicit instructions for surviving nightly IBC restarts.

---

## Codex Review

## Summary

Overall, Phase 174 is unusually well-scoped for a high-risk infrastructure/data-expansion phase: the plans preserve the core principle of empirical, unbiased measurement; they correctly put the `ic_engine` memory fix and governance split ahead of universe growth; and they repeatedly guard against silent partial writes, silent live-trading eligibility, and selection bias. The strongest design choice is sequencing: Wave 1 builds the primitives, Wave 2 wires and samples, Wave 3 closes remaining memory/onboarding gaps, Wave 4 measures supported scale, and only Wave 5 expands. Main risks are operational complexity, a few dependency mismatches between "autonomous" tasks and live systems, some possible over-test/over-script burden, and a handful of subtle correctness hazards around memmap lifecycle, synthetic scale testing, and promotion queries.

## Strengths

- The phase is aligned with the actual endgame: increasing empirical breadth without hand-picking names or assigning alpha before IC proof.
- D-04 is treated as structural infrastructure, not a config bump. The plans explicitly avoid repeating the `alpha.ic.max_cell_rows` ceiling-bump anti-pattern.
- The 3-way instrument split is well justified and correctly defaults `live_tradeable=false`.
- `onboard_instrument()` is the right abstraction: transactional, qualification-gated, metadata-mandatory, and backfill-status aware.
- The false momentum/quality premise is handled thoughtfully: retag existing MTUM/QUAL/USMV instead of adding redundant instruments.
- The sampler is reproducible and mechanically stratified, which protects the hypothesis test from selection bias.
- Validation is unusually strong: most plans include unit tests, regression tests, idempotent migrations, live verification, and summary artifacts.
- Security posture is good for the risk surface: external ticker strings are parsed defensively, qualified through IBKR, and written only via parameterized SQL.

## Concerns

- **HIGH: Plan 05 memmap cleanup may conflict with downstream consumption.**
  If `Float32ChunkAccumulator.close()` unlinks/closes the memmap backing file while `_compute_one_cross_sectional_cell` or later scale loops still hold views, the returned memmap can become invalid or platform-dependent. The plan notices cleanup must span the whole cell compute, but implementation will need very careful ownership boundaries.

- **HIGH: Plan 09 changes core numerical behavior in a very sensitive path.**
  Replacing `np.corrcoef` with blocked two-pass correlation is directionally right, but exact cluster-label identity can be brittle near threshold boundaries. `atol=1e-6` may still produce linkage differences when distances sit near the cluster cut threshold.

- **HIGH: Plan 11 synthetic scale test may contaminate production result tables.**
  The plan says synthetic-peer-set IC output must not be cited, but it does not clearly require isolation from production `feature_ic_scores` or cleanup/marking of any rows written. That is a measurement-integrity risk.

- **HIGH: Plan 12 accepts long-running backfill continuing past the phase window.**
  That is operationally honest, but it means the phase may "complete" before the actual compute-eligible expansion and effective-breadth remeasurement occur. The success criteria should be very explicit about what is phase-complete versus post-phase continuing work.

- **MEDIUM: Several "autonomous" plans depend on live DB, Docker, IBKR Gateway, internet downloads, and possibly account login/2FA.**
  Plans 04, 10, 11, and 12 are not fully autonomous in practice. They are executable, but operationally fragile.

- **MEDIUM: Plan 01 tests cleanup by deleting memmap files, but not access-after-finalize semantics.**
  Returning a memmap view and then expecting callers to close it later needs tests that access the result before and after `close()` behavior is defined.

- **MEDIUM: Plan 02 migration default `compute_eligible=true` for all existing active rows preserves behavior but may encode known-bad symbols.**
  The audit records this, but the migration still preserves all active rows even if zero-row symbols exist. That is correct for compatibility, but a follow-up demotion plan may be needed if the audit finds real gaps.

- **MEDIUM: Plan 03's transaction semantics are underspecified for async/sync connection style.**
  The signature accepts `conn`, mentions psycopg, and the function is async because qualification is async. Care is needed to avoid mixing async provider calls with sync transaction handling in a way that blocks or fails tests.

- **MEDIUM: Plan 04 relies on a brittle issuer file schema.**
  Failing loud on header mismatch is good, but the actual iShares holdings endpoint often has changing preambles, disclaimer lines, and footers. The parser should tolerate metadata drift while still validating the true header.

- **MEDIUM: Plan 08 sample allocation may overweight lower buckets by assigning remainder to lowest-numbered buckets.**
  This is deterministic, but whether bucket `0` is smallest or largest depends on `qcut` ordering. The plan should explicitly define "lowest-numbered" as lowest market-cap bucket if that is intended.

- **MEDIUM: Plan 10 backfill success criteria use `market_data_ohlcv_tradeable`; VIX-linked products may have sparse/odd volume behavior.**
  Good to avoid raw synthetic bars, but ensure "tradeable" view semantics do not accidentally discard valid ETF history due to data-provider volume quirks.

- **MEDIUM: Plan 11 removing swapfile is operationally risky.**
  The guard is sensible, but removing `/etc/fstab` entries and swapfiles may require permissions and should be reversible. A lower-risk option is disabling and documenting before deletion.

- **LOW: Heavy grep-based acceptance criteria are useful but brittle.**
  Some criteria may fail because of harmless formatting, comments, or refactors. Prefer semantic tests where possible.

- **LOW: Many plans require creating summary docs.**
  Good for provenance, but it increases execution load. The summary files should be templated or kept concise to avoid documentation drag.

## Suggestions

- Add an explicit memmap ownership model:
  - `finalize()` returns an array-like object whose backing file remains valid until `close()`.
  - The caller owns `close()`.
  - Tests should confirm data remains readable until close and that no code reads after close.

- In Plan 09, add threshold-stress tests:
  - Synthetic correlations just below, exactly at, and just above `cluster_max_corr`.
  - Assert cluster identity or define an acceptable tolerance policy if exact identity is impossible near thresholds.

- In Plan 11, isolate throughput runs:
  - Use a dry-run/no-write mode if available.
  - Or write with a special run marker/version and delete or quarantine rows afterward.
  - Do not allow synthetic peer-set outputs to blend into normal `feature_ic_scores`.

- Add a hard "phase complete" distinction:
  - Phase 174 implementation complete: sample drawn, onboarded, backfill launched, promotion tool exists.
  - Phase 174 data complete: backfill finished, compute eligibility promoted.
  - Phase 174 empirical complete: ic_engine recompute finished and effective breadth remeasured.

- For Plan 02 and Plan 12 promotion checks, require all four completed rows, not merely "at least one completed backfill row." Some automated checks currently look weaker than the prose.

- For Plan 08, make cap-bucket direction explicit and record bucket min/max in the sampled output so "lowest bucket" is unambiguous.

- For Plan 04, store the downloaded holdings file under a project-controlled artifact path or documented `/var/tmp` retention policy. `/var/tmp` is fine operationally, but the reproducibility story depends on retaining the exact file or at least its hash and parsed output.

- For Plans 10 and 12, define how interrupted long-running backfills are supervised:
  - systemd/tmux/background pid file/log path
  - restart command
  - status query
  - owner/action if IBKR disconnects

- Consider adding a small "preflight verify phase state" script before Wave 5:
  - migrations 336-340 applied
  - APR target size positive
  - gateway up
  - live universe empty
  - scratch dir exists/non-tmpfs
  - `alpha.ic.max_cell_rows` unchanged

## Per-Plan Notes

### 174-01
Strong foundational plan. Main risk is memmap lifecycle: returning a view while also exposing cleanup can easily produce invalid access if ownership is unclear. Add explicit tests for readability before close and behavior after close.

### 174-02
Good additive schema design. The measured audit is a strong choice. Risk is that preserving behavior may preserve bad active rows; make any audit-found anomalies into explicit follow-up todos.

### 174-03
Very good abstraction. Biggest implementation risk is async qualification plus sync DB transaction handling. Also ensure `ON CONFLICT DO NOTHING` does not hide divergent existing rows when rerun against a symbol with stale metadata or tags.

### 174-04
Methodologically good. Network/file schema fragility is the main risk. The delisted-feasibility task may be too broad for an execute plan if IBKR is down and external source research is required.

### 174-05
Correctly wires the first half of D-04. The plan is careful not to declare victory before Plan 09. Main hazard is placing `close()` too early relative to downstream memmap consumers.

### 174-06
Excellent cache-risk awareness. Per-dimension cache isolation is essential. Ensure all existing tests that monkeypatch `_active_contracts_cache` are updated for dict shape.

### 174-07
Good correction of D-06. Avoids redundant instruments and improves taxonomy. The only caution is financial-specific evidence freshness; re-verification immediately before Plan 10 is wise.

### 174-08
Strong reproducibility story. Clarify cap-bucket ordering and whether target size means "new successfully onboarded symbols" or "drawn symbols before IBKR rejections."

### 174-09
Necessary and high-value, but highest technical risk. Numerical equivalence and memory behavior need careful testing beyond happy synthetic arrays. This plan is the real D-04 completion point.

### 174-10
Good low-scale rehearsal of onboarding/backfill before Plan 12. Operational dependency on IBKR Gateway makes this less autonomous than marked. Promotion gates are well designed.

### 174-11
Right instinct: measure before setting target size. High operational risk and potential production contamination from synthetic IC runs. Add isolation/cleanup requirements for any generated outputs.

### 174-12
Good final assembly plan and appropriately avoids claiming effective breadth before recompute. Main risk is that it launches a long backfill but cannot fully close the empirical loop within the phase.

## Risk Assessment

**Overall risk: MEDIUM-HIGH.**

The plans are high quality and mostly complete, but the phase touches memory-critical numerical code, live database migrations, IBKR operational dependencies, external holdings data, long-running backfills, and production corpus eligibility flags. The biggest risks are not conceptual; the methodology is sound. They are execution risks: memmap lifecycle bugs, numerical drift in clustering, synthetic verification contaminating production outputs, and long-running operational work being mistaken for completed empirical validation. With the suggested isolation, lifecycle, and completion-boundary improvements, the phase becomes a strong and credible path to safely expanding breadth.

---

## Consensus Summary

Both reviewers independently reached the same overall verdict: methodology and sequencing are sound (D-04 correctly gates Russell-3000-scale work; the momentum/quality correction is handled well; security/injection posture is solid), but a cluster of execution-level correctness hazards around memmap lifecycle and long-running-work-vs-phase-completion needs hardening before/during execution.

### Agreed Strengths
- **D-04 treated as structural infrastructure, not a config bump** — both reviewers singled out that the plans explicitly avoid the `alpha.ic.max_cell_rows` ceiling-bump anti-pattern and instead fix the actual memory-bounding mechanism.
- **The momentum/quality correction (D-06) is handled well** — retagging existing MTUM/QUAL/USMV instead of sourcing redundant instruments, with the correction documented in a durable artifact.
- **Security posture is appropriate for the risk surface** — parameterized SQL, `qualify_instrument()` as a de facto allowlist, defensive parsing of the external IWV holdings file.
- **The 5-wave dependency structure is sound** — Codex called the sequencing "the strongest design choice"; Antigravity called the DAG "completely acyclic and sound," with prerequisite infrastructure proven on a canary (Plan 10) before bulk execution (Plan 12).
- **Honest phase-completion framing in Plan 12** — both reviewers noted the plan correctly refuses to claim a new effective-breadth number before an out-of-sample recompute.

### Agreed Concerns (raised independently by both reviewers — highest priority)
1. **Memmap lifecycle / premature `close()` (Plans 05 and 09) — HIGH.** Both reviewers flagged the same failure mode from different angles: if `Float32ChunkAccumulator.close()` (or `X_nd`'s cleanup) runs before all downstream consumers (correlation, clustering, standardization) finish reading the memmap-backed array, the result is either a `ValueError` on closed mmap access or a platform-dependent invalid-memory read. Antigravity additionally flagged a file-descriptor leak (`NamedTemporaryFile` not explicitly closed alongside the mmap) and a dual-memmap disk-accounting gap (`X_raw` + `X_nd` scratch space not both accounted for in the pre-flight disk check). **Action for execution:** the `finally` blocks in Plans 05/09 must wrap the *entire* cell-processing pipeline, not just accumulator creation, and each memmap needs its own explicit cleanup scope.

2. **Plan 03's async/sync `conn` ambiguity — HIGH (Antigravity) / MEDIUM (Codex).** `onboard_instrument()` is `async def` and awaits `qualify_instrument()`, but the plan describes `conn` only as "an open psycopg connection owned by the caller" without specifying sync vs. async, and separately states the helper "opens ONE transaction and commits/rolls back" while also calling `conn` "owned by the caller" — a potential transaction-boundary collision if `onboard_instrument()` calls `conn.commit()` on a connection the caller expected to keep open. **Action for execution:** pin `conn`'s type explicitly (`AsyncConnection` recommended, since qualification is async) and use a nested transaction/savepoint rather than an outer commit.

3. **Multi-day backfill vs. phase completion (Plan 12) — HIGH (both).** Both reviewers made the identical, sharply-stated point: IBKR pacing limits (60 historical requests / 10 minutes) mean backfilling 200-400 symbols across 4 timeframes takes 2-4+ days, so when Plan 12's promotion task runs at phase-sign-off time, almost none of the newly onboarded symbols will actually be `compute_eligible=true` yet. This is disclosed in the plan (mirrors the Phase 173 precedent) but both reviewers want the "phase complete" vs. "data complete" vs. "empirical complete" distinction made explicit and unmissable, not just implied. Codex proposed exactly this three-tier framing as a suggestion.

4. **Operational fragility of "autonomous" plans (04, 10, 11, 12) — MEDIUM (both).** Both reviewers independently noted that several plans marked `autonomous: true` actually depend on live IBKR Gateway connectivity/authentication, Docker, and external network downloads (IWV holdings CDN) — none of which are guaranteed to succeed unattended. Antigravity additionally flagged that iShares/BlackRock endpoints commonly block non-browser User-Agent headers with HTTP 403.

5. **Long-running background work needs process supervision — MEDIUM (both).** Both reviewers want an explicit answer for how the multi-day backfills in Plans 10/12 survive session disconnects, nightly IBC gateway restarts, and IBKR disconnection — neither plan currently specifies systemd/tmux supervision, a restart command, or a status-query mechanism.

### Reviewer-Specific Findings Worth Flagging Individually

- **Antigravity — Plan 11's 400-symbol synthetic peer-set mechanism is likely broken as described (HIGH, Antigravity only, and the single sharpest catch of the two reviews).** The plan describes doubling the cell to ~400 symbols "by extending the symbol list with existing corpus symbols," but the corpus only has 231 active symbols today, and duplicate values in a SQL `IN (...)` clause do not multiply the returned row count — querying `WHERE symbol IN ('AAPL','AAPL',...)` still returns each `AAPL` row once. As written, Task 3's synthetic scale-up would not actually produce a ~400-symbol-sized cell. **This needs to be resolved before Plan 11 executes** — either by synthesizing distinct symbol names with duplicated feature data, cross-joining in SQL, or another explicit row-multiplication mechanism, and the plan should state which.
- **Codex — Plan 11's synthetic IC output may contaminate production result tables (HIGH, Codex only).** The plan says synthetic-peer-set IC output "must not be cited" downstream, but doesn't clearly require write-isolation from `feature_ic_scores` or a cleanup/quarantine step for any rows the synthetic run writes. Combined with Antigravity's finding above, Plan 11's Task 3 needs the most scrutiny of any task in the phase before execution.
- **Codex — Plan 09's cluster-identity tolerance near threshold boundaries (HIGH, Codex only).** The two-pass streaming correlation replacement is numerically sound, but `atol=1e-6` bit-identity assertions may be brittle for synthetic correlations sitting near `cluster_max_corr`'s cut threshold — Codex suggests explicit stress tests at just-below/at/just-above the threshold rather than relying on happy-path synthetic distributions.
- **Antigravity — TagCalibrator interaction with new tags (LOW, Antigravity only).** Minor: verify `tests/unit/test_tag_calibrator.py` doesn't raise on the new `eq_momentum`/`eq_quality`/`eq_low_vol`/`vol_proxy` vocabulary rows Plan 07 adds.

### Divergent Views
- **Overall risk rating:** Antigravity rated the phase "APPROVED WITH CONDITIONS (GO)" with only Plan 12 at HIGH risk individually; Codex rated the phase overall "MEDIUM-HIGH" without a plan-by-plan risk matrix. The difference is presentation, not substance — both land on the same four HIGH-severity items in aggregate (memmap lifecycle, Plan 09 numerical brittleness, Plan 11 contamination/mechanism risk, Plan 12 multi-day completion framing), just distributed differently across the two reviews' HIGH lists.
- **No outright disagreements on facts or recommended approach were found between the two reviews.**
