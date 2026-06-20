---
phase: A-feature-factory
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
    - "feature_vectors historical corpus (the IC research data - Phase B gate, D-06)"
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
      mitigation: "backfill_status checkpoint per (symbol, tf); resume skips status='complete'; acceptance criterion asserts complete pairs are skipped on re-run"
  block_on: [T1, T2]

must_haves:
  truths:
    - "Backfill fetches IBKR history into market_data_ohlcv for 58 ETFs at target depths using client-id 40 (market_data_ohlcv is currently empty)"
    - "Backfill computes FeatureFactory.compute() over rolling windows from market_data_ohlcv and batch-inserts into feature_vectors with regime_label_source='filtered'"
    - "Backfill is resumable: a completed (symbol, tf) pair is skipped on re-run via backfill_status"
    - "Per (symbol, tf) row count vs theoretical_max is recorded; pairs below 80% are flagged"
  artifacts:
    - path: "services/backfill_feature_factory.py"
      provides: "Oneshot backfill: IBKR fetch + FeatureFactory compute + checkpoint/resume + coverage accounting"
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
      via: "checkpoint write per (symbol, tf)"
      pattern: "backfill_status"
---

<objective>
Build the historical backfill oneshot. Two stages: (1) fetch IBKR OHLCV history into `market_data_ohlcv` for the 58 active ETFs at target depths (the table is currently EMPTY - this is Phase A's first data step, not a precondition); (2) run `FeatureFactory.compute()` over rolling windows from `market_data_ohlcv` and batch-insert into `feature_vectors`. Checkpoint/resume per `(symbol, tf)` via `backfill_status` (D-11). Record per-pair coverage vs theoretical max (D-06 gate for Phase B).

Purpose: SC-4 (historical backfill complete: 58 ETFs × 4 TFs at target depths). This produces the IC research corpus. The backfill is the data half of Phase A; the cutover (P6) is gated on this being complete and within 5% of theoretical max.
Output: `backfill_feature_factory.py` oneshot, unit tests for checkpoint/resume and proxy correctness, and a populated `feature_vectors` table.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/A-feature-factory/A-CONTEXT.md
@.planning/phases/A-feature-factory/A-RESEARCH.md
@.planning/phases/A-feature-factory/A-PATTERNS.md
@CLAUDE.md
@production/scripts/run_historical_pipeline.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backfill oneshot - IBKR fetch + FeatureFactory compute + checkpoint/resume</name>
  <files>services/backfill_feature_factory.py</files>
  <read_first>
    - production/scripts/run_historical_pipeline.py (FULL structure: imports lines 55-119, _TF_FETCH_CONFIG depths, --fetch-only path, chunked IBKR fetch lines 499-540, psycopg2 batch insert, --client-id handling. This is the analog for IBKR fetch + chunked read + batch insert.)
    - src/intelligence/feature_factory.py (FeatureFactory, FeatureFactoryConfig, FeatureCache usage from P3 - the compute contract)
    - src/intelligence/feature_cache.py (FeatureCache + update_cross_asset + refresh_regime - backfill must drive the cache cadence)
    - src/config/config_service.py (load feature.* APR keys to build FeatureFactoryConfig at init)
    - src/config/settings.py (get_active_contracts(settings) -> 58 active ETFs)
    - .planning/phases/A-feature-factory/A-PATTERNS.md (section "services/backfill_feature_factory.py" - imports, checkpoint/resume SQL, chunked read, oneshot D-06 exit metric, target timeframes, client-id rule)
    - .planning/phases/A-feature-factory/A-RESEARCH.md (Pitfall 5 empty market_data_ohlcv; Pitfall 7 chunk size; Pitfall 10 client-id; Open Question 2 warm-up handling)
  </read_first>
  <action>
    Create an argparse + asyncio.run(main()) oneshot (NOT a daemon; follows the _agent oneshot exception pattern). Two stages controllable by flags (e.g. --fetch-only, --compute-only, default both):

    STAGE 1 (IBKR fetch): For each active ETF (get_active_contracts(settings), is_active=true equity), fetch OHLCV for target TFs into market_data_ohlcv using the existing run_historical_pipeline fetch mechanism with --client-id 40. Target TFs and depths: 5m (~1631d/5y), 15m (~3650d/10y), 1h (~5475d/15y), 1d (~7300d/20y). Reuse run_historical_pipeline's chunked named-contract fetch (do not reimplement IBKR chunking). 1m is NOT a backfill target (live pipeline owns 1m).

    STAGE 2 (compute): Build FeatureFactoryConfig once from ConfigService feature.* keys. For each (symbol, tf) pair NOT status='complete' in backfill_status:
      - mark in_progress (INSERT ... ON CONFLICT DO UPDATE)
      - chunked sliding-window read from market_data_ohlcv (warm-up window ~500 bars; never load full history - T3)
      - maintain a FeatureCache per (symbol, tf); refresh regime features every config.regime_cache_refresh_bars; update cross-asset cache from SPY/TLT/SHY bar history (pre-load these cross-asset series once)
      - call FeatureFactory.compute(window, symbol, tf, cache, config) per bar; warm-up bars write 0.0 continuous features (Open Question 2)
      - batch INSERT into feature_vectors (regime_label_source='filtered', pipeline_version set) every ~500 rows via executemany
      - on completion: UPDATE backfill_status status='complete', rows_written, theoretical_max (computed from TF bar-seconds × depth), completed_at; on exception: status='failed', error_msg
      - resume: SELECT pairs WHERE status != 'complete' ORDER BY symbol, tf - skip complete pairs

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
    - The script writes/reads backfill_status for checkpoint/resume
    - INSERTs into feature_vectors set regime_label_source='filtered' and pipeline_version
    - Emits job_completed_total at exit
    - `.venv/bin/ruff check services/backfill_feature_factory.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Unit tests for checkpoint/resume, coverage accounting, source correctness</name>
  <files>tests/unit/service_tests/test_backfill_feature_factory.py</files>
  <read_first>
    - services/backfill_feature_factory.py (the functions to test: pair selection/resume, theoretical_max computation, chunked-read generator, params builder)
    - .planning/phases/A-feature-factory/A-RESEARCH.md (D-06 coverage gate; theoretical bar count per TF/depth)
    - tests/unit/service_tests/ (existing oneshot test style for fixtures/mocks)
  </read_first>
  <action>
    Unit tests (no live IBKR, no live DB - mock the DB layer and pass synthetic bars):
    - resume skips pairs with status='complete' (given a mocked backfill_status query, only non-complete pairs are processed)
    - theoretical_max computation matches expected bar count for a known TF/depth (e.g. 5m over a fixed window)
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
    - A test asserts status='complete' pairs are skipped on resume
    - A test asserts the coverage gate flags pairs below 80% of theoretical_max
    - A test asserts the params builder sets regime_label_source='filtered'
    - Tests use no network and no live DB (mocked)
  </acceptance_criteria>
</task>

</tasks>

<verification>
- Backfill oneshot: IBKR fetch (client-id 40) + chunked compute from market_data_ohlcv -> feature_vectors
- Checkpoint/resume via backfill_status; complete pairs skipped
- Coverage accounting vs theoretical_max (D-06 gate)
- regime_label_source='filtered' on every row
- Source is market_data_ohlcv only (D-05)
- Unit tests green and CI-clean
</verification>

<success_criteria>
SC-4 (historical backfill complete: 58 ETFs × 4 TFs at target depths) machinery delivered; the run itself populates feature_vectors and is verified against the D-06 5%-coverage gate before P6 cutover.
SC-5 (regime_label_source='filtered') enforced by the backfill writing 'filtered' on every row.
</success_criteria>

<output>
After completion, create `.planning/phases/A-feature-factory/A-P5-SUMMARY.md`. Record actual per-(symbol, tf) coverage vs theoretical_max and list any pairs below 80% (excluded from Phase B IC per D-06).
</output>
