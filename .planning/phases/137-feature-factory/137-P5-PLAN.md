---
phase: 137-feature-factory
plan: 5
type: execute
wave: 3
depends_on: [1, 3]
files_modified:
  - services/backfill_feature_factory.py
  - tests/unit/service_tests/test_backfill_feature_factory.py
autonomous: true
requirements: [SC-4, SC-5]

threat_model:
  assets:
    - "feature_vectors historical corpus (the IC research data - Phase 138 gate, D-06)"
    - "backfill_status checkpoint state (resume integrity across interruptions)"
    - "IBKR client connection (fetch path)"
  threats:
    - id: T1
      description: "Backfill reads from intelligence_features (lookahead-biased smoothed labels, old futures data) instead of market_data_ohlcv - corpus contamination (D-05)"
      severity: high
      mitigation: "Source is market_data_ohlcv only; acceptance criterion greps for zero intelligence_features references in the backfill script"
    - id: T2
      description: "IBKR client_id collision (35=provider, 56+ exceeds _MAX_CLIENT_ID=50) - fetch fails or disrupts live provider"
      severity: high
      mitigation: "Fetch uses --client-id 40; acceptance criterion asserts the default/passed client id is 40"
    - id: T3
      description: "Loading full symbol history into memory for backfill - OOM at 5m over 5 years across 58 symbols"
      severity: medium
      mitigation: "Chunked sliding-window read from market_data_ohlcv (~500-bar warm-up window); never SELECT * whole symbol"
    - id: T4
      description: "Interruption restarts backfill from scratch, re-fetching and re-computing completed pairs (D-11)"
      severity: medium
      mitigation: "backfill_status checkpoint per (symbol, tf): fetch_complete flag for the fetch stage and status='complete' for compute; resume skips already-fetched and already-computed pairs; acceptance criterion asserts both are skipped on re-run"
  block_on: [T1, T2]

must_haves:
  truths:
    - "Backfill fetches IBKR history into market_data_ohlcv for 58 ETFs at target depths using client-id 40 (market_data_ohlcv is currently empty)"
    - "Backfill computes FeatureFactory.compute() over rolling windows from market_data_ohlcv and batch-inserts into feature_vectors with regime_label_source='filtered'"
    - "Backfill is resumable at both stages: a (symbol, tf) pair with fetch_complete=true skips the IBKR download; a pair with status='complete' skips compute"
    - "Per (symbol, tf) row count vs theoretical_max is recorded; pairs below 80% are flagged"
  artifacts:
    - path: "services/backfill_feature_factory.py"
      provides: "Oneshot backfill: IBKR fetch + FeatureFactory compute + two-stage checkpoint/resume + coverage accounting"
      min_lines: 200
      contains: "FeatureFactory"
  key_links:
    - from: "services/backfill_feature_factory.py"
      to: "market_data_ohlcv"
      via: "chunked sliding-window read (source of truth)"
      pattern: "market_data_ohlcv"
    - from: "services/backfill_feature_factory.py"
      to: "feature_vectors"
      via: "batch INSERT after FeatureFactory.compute()"
      pattern: "feature_vectors"
    - from: "services/backfill_feature_factory.py"
      to: "backfill_status"
      via: "checkpoint write per (symbol, tf): fetch_complete + status"
      pattern: "backfill_status"
---

<objective>
Build the historical backfill oneshot. Two stages: (1) fetch IBKR OHLCV history into `market_data_ohlcv` for the 58 active ETFs at target depths (the table is currently EMPTY - this is Phase 137's first data step, not a precondition); (2) run `FeatureFactory.compute()` over rolling windows from `market_data_ohlcv` and batch-insert into `feature_vectors`. Two-stage checkpoint/resume per `(symbol, tf)` via `backfill_status` - the fetch stage and the compute stage are checkpointed independently (D-11). Record per-pair coverage vs theoretical max (D-06 gate for Phase 138).

Purpose: SC-4 (historical backfill complete: 58 ETFs × 4 TFs at target depths). This produces the IC research corpus. The backfill is the data half of Phase 137; the cutover (P6) is gated on this being complete and within 5% of theoretical max.
Output: `backfill_feature_factory.py` oneshot, unit tests for two-stage checkpoint/resume and proxy correctness, and a populated `feature_vectors` table.

THEORETICAL_MAX FORMULA (use exactly this - do not use a vague "TF bar-seconds × depth" estimate):

    theoretical_max(tf, depth_years) = (depth_years × trading_days_per_year × bars_per_trading_day(tf)) - warm_up_bars

Where:
- trading_days_per_year = 252
- bars_per_trading_day(tf): 5m = 78, 15m = 26, 1h = 6 (6.5 RTH hours rounded down), 1d = 1
- warm_up_bars = the longest period required to seed all rolling windows in FeatureFactoryConfig. The first warm_up_bars of each (symbol, tf) history are seed-only and do not produce valid feature rows, so they are subtracted from the theoretical count. Use the longest configured window (momentum zscore_window = 252) plus HMM initialization headroom; floor warm_up_bars at the dominant rolling-window length so the gate is not skewed by the seed region. Read the exact value from FeatureFactoryConfig at runtime rather than hardcoding it.

Depth targets (years): 5m = 5y, 15m = 10y, 1h = 15y, 1d = 20y. 1m is not a backfill target (the live pipeline owns 1m).
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/137-feature-factory/137-CONTEXT.md
@.planning/phases/137-feature-factory/137-RESEARCH.md
@.planning/phases/137-feature-factory/A-PATTERNS.md
@CLAUDE.md
@production/scripts/run_historical_pipeline.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backfill oneshot - IBKR fetch + FeatureFactory compute + two-stage checkpoint/resume</name>
  <files>services/backfill_feature_factory.py</files>
  <read_first>
    - production/scripts/run_historical_pipeline.py (FULL structure: imports lines 55-119, _TF_FETCH_CONFIG depths, --fetch-only path, chunked IBKR fetch lines 499-540, psycopg2 batch insert, --client-id handling. This is the analog for IBKR fetch + chunked read + batch insert.)
    - src/intelligence/feature_factory.py (FeatureFactory, FeatureFactoryConfig, FeatureCache usage from P3 - the compute contract; config is a compute() argument, FeatureFactory is stateless)
    - src/intelligence/feature_cache.py (FeatureCache + update_cross_asset + refresh_regime - backfill must drive the cache cadence)
    - src/config/config_service.py (load feature.* APR keys to build FeatureFactoryConfig at init)
    - src/config/settings.py (get_active_contracts(settings) -> 58 active ETFs)
    - .planning/phases/137-feature-factory/A-PATTERNS.md (section "services/backfill_feature_factory.py" - imports, checkpoint/resume SQL, chunked read, oneshot D-06 exit metric, target timeframes, client-id rule)
    - .planning/phases/137-feature-factory/137-RESEARCH.md (Pitfall 5 empty market_data_ohlcv; Pitfall 7 chunk size; Pitfall 10 client-id; Open Question 2 warm-up handling)
  </read_first>
  <action>
    Create an argparse + asyncio.run(main()) oneshot (NOT a daemon; follows the _agent oneshot exception pattern). Two stages controllable by flags (e.g. --fetch-only, --compute-only, default both):

    STAGE 1 (IBKR fetch) - checkpointed by backfill_status.fetch_complete: For each active ETF (get_active_contracts(settings), is_active=true equity) and each target TF, FIRST check backfill_status: if the (symbol, tf) row has fetch_complete=true, skip the IBKR download and go straight to compute. Otherwise fetch OHLCV for that TF into market_data_ohlcv using the existing run_historical_pipeline fetch mechanism with --client-id 40, and on successful completion of the fetch for that (symbol, tf) pair, UPDATE backfill_status SET fetch_complete=true (INSERT ... ON CONFLICT DO UPDATE) BEFORE starting compute for that pair. Target TFs and depths: 5m (5y), 15m (10y), 1h (15y), 1d (20y). Reuse run_historical_pipeline's chunked named-contract fetch (do not reimplement IBKR chunking). 1m is NOT a backfill target (live pipeline owns 1m).

    STAGE 2 (compute) - checkpointed by backfill_status.status: Build FeatureFactoryConfig once from ConfigService feature.* keys. For each (symbol, tf) pair NOT status='complete' in backfill_status (these have fetch_complete=true from Stage 1):
      - mark status='in_progress' (INSERT ... ON CONFLICT DO UPDATE)
      - chunked sliding-window read from market_data_ohlcv (warm-up window per FeatureFactoryConfig dominant window; never load full history - T3)
      - maintain a FeatureCache per (symbol, tf); refresh regime features every config.regime_cache_refresh_bars; update cross-asset cache from SPY/TLT/SHY bar history (pre-load these cross-asset series once)
      - call FeatureFactory.compute(window, symbol, tf, cache, config) per bar; warm-up bars write 0.0 continuous features (Open Question 2)
      - batch INSERT into feature_vectors (regime_label_source='filtered', pipeline_version set) every ~500 rows via executemany
      - on completion: UPDATE backfill_status status='complete', rows_written, theoretical_max (computed via the exact formula in <objective>: (depth_years × 252 × bars_per_trading_day(tf)) - warm_up_bars), completed_at; on exception: status='failed', error_msg
      - resume: SELECT pairs WHERE status != 'complete' ORDER BY symbol, tf - skip status='complete' pairs; within those, fetch_complete=true pairs skip the download

    Source is market_data_ohlcv ONLY - never intelligence_features (T1, D-05). All numeric params from APR/config. Emit job_completed_total{job=backfill-feature-factory, status=success|failure} OTel counter at exit (D-06 oneshot contract). Log to logs/backfill_feature_factory.log via setup_service_logging. Use structlog non-reserved kwargs (data=, payload=). Timestamps UTC.
  </action>
  <verify>
    .venv/bin/python services/backfill_feature_factory.py --help && .venv/bin/ruff check services/backfill_feature_factory.py
  </verify>
  <acceptance_criteria>
    - `services/backfill_feature_factory.py --help` exits 0 and shows --fetch-only / --compute-only / --client-id flags
    - `grep -n "intelligence_features" services/backfill_feature_factory.py` returns 0 matches (source is market_data_ohlcv only)
    - The default IBKR client id is 40 (asserted in code; not 35, not 56)
    - The script reads market_data_ohlcv and writes feature_vectors (both strings present)
    - The script writes backfill_status.fetch_complete=true on fetch completion BEFORE compute, and on resume a (symbol, tf) with fetch_complete=true skips the IBKR download
    - The script writes/reads backfill_status.status for compute checkpoint/resume
    - theoretical_max is computed via the formula (depth_years × 252 × bars_per_trading_day(tf)) - warm_up_bars, with bars_per_trading_day 5m=78/15m=26/1h=6/1d=1
    - INSERTs into feature_vectors set regime_label_source='filtered' and pipeline_version
    - Emits job_completed_total at exit
    - `.venv/bin/ruff check services/backfill_feature_factory.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Unit tests for two-stage checkpoint/resume, coverage accounting, source correctness</name>
  <files>tests/unit/service_tests/test_backfill_feature_factory.py</files>
  <read_first>
    - services/backfill_feature_factory.py (the functions to test: pair selection/resume, fetch_complete skip, theoretical_max computation, chunked-read generator, params builder)
    - .planning/phases/137-feature-factory/137-RESEARCH.md (D-06 coverage gate; theoretical bar count per TF/depth)
    - tests/unit/service_tests/ (existing oneshot test style for fixtures/mocks)
  </read_first>
  <action>
    Unit tests (no live IBKR, no live DB - mock the DB layer and pass synthetic bars):
    - compute resume skips pairs with status='complete' (given a mocked backfill_status query, only non-complete pairs are processed)
    - fetch resume skips the IBKR download for pairs with fetch_complete=true (given a mocked backfill_status query, the fetch path is not invoked for already-fetched pairs)
    - theoretical_max computation matches the exact formula for a known TF/depth: e.g. 5m over 5y = (5 × 252 × 78) - warm_up_bars; 1d over 20y = (20 × 252 × 1) - warm_up_bars
    - the chunked-read helper yields windows of bounded size (does not load all bars at once)
    - the feature_vectors params builder produces a row with regime_label_source='filtered' and all 35 features present
    - coverage gate: a pair with rows_written < 0.80 * theoretical_max is flagged (per D-06)
    Keep tests CI-clean (no network, no DB) per CLAUDE.md unit test rule.
  </action>
  <verify>
    .venv/bin/pytest tests/unit/service_tests/test_backfill_feature_factory.py -q
  </verify>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/service_tests/test_backfill_feature_factory.py -q` exits 0
    - A test asserts status='complete' pairs are skipped on compute resume
    - A test asserts fetch_complete=true pairs skip the IBKR download on resume
    - A test asserts theoretical_max equals (depth_years × 252 × bars_per_trading_day(tf)) - warm_up_bars for a known TF/depth (e.g. 5m/5y -> (5×252×78)-warmup)
    - A test asserts the coverage gate flags pairs below 80% of theoretical_max
    - A test asserts the params builder sets regime_label_source='filtered'
    - Tests use no network and no live DB (mocked)
  </acceptance_criteria>
</task>

</tasks>

<verification>
- Backfill oneshot: IBKR fetch (client-id 40) + chunked compute from market_data_ohlcv -> feature_vectors
- Two-stage checkpoint/resume via backfill_status: fetch_complete skips download, status='complete' skips compute
- Coverage accounting vs theoretical_max via the exact formula (252 × bars_per_day(tf) × years - warmup) (D-06 gate)
- regime_label_source='filtered' on every row
- Source is market_data_ohlcv only (D-05)
- Unit tests green and CI-clean
</verification>

<success_criteria>
SC-4 (historical backfill complete: 58 ETFs × 4 TFs at target depths) machinery delivered; the run itself populates feature_vectors and is verified against the D-06 5%-coverage gate before P6 cutover.
SC-5 (regime_label_source='filtered') enforced by the backfill writing 'filtered' on every row.
</success_criteria>

<output>
After completion, create `.planning/phases/137-feature-factory/137-P5-SUMMARY.md`. Record actual per-(symbol, tf) coverage vs theoretical_max and list any pairs below 80% (excluded from Phase 138 IC per D-06).
</output>
