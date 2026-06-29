---
plan: 141-P0
phase: "141"
title: "Validity Fixes + Corpus Rerun"
wave: 0
depends_on: []
files_modified:
  - production/migrations/182_equity_regime_model_apr.sql
  - src/core/agent/base_batch.py
  - services/alpha_publisher.py
  - services/equity_regime_model.py
  - tests/unit/test_base_batch_jsonb.py
  - tests/unit/services/test_equity_regime_model_causal.py
autonomous: true
must_haves:
  goal: "Two validity threats fixed, partial corpus rerun complete, corpus ready for CORPUS-01 through CORPUS-07"
  truths:
    - "BaseBatch._setup_pool imports and calls database_manager.create_pool — not bare asyncpg.create_pool"
    - "alpha_publisher.py contains no json.dumps() calls and no ::jsonb explicit cast in INSERT_SQL"
    - "equity_regime_model._compute_vix_pct_rank accepts tf parameter and uses bisect-based causal expanding rank"
    - "_tf_window(200, '5m') returns 15600 and _tf_window(252, '1h') returns 1764"
    - "causal expanding rank propagates NaN: a NaN input value produces a NaN rank at that position (no insertion into the bisect window, no error)"
    - "causal expanding rank uses average-rank tie handling: two equal values produce rank 0.5 (not 0.0 from bisect_left)"
    - "market_regimes row count differs from pre-fix 819,020 or is reproduced from scratch — either is acceptable; stale data is not"
    - "feature_ic_scores WHERE is_pooled=true has rows (cross-sectional IC recomputed with corrected regime labels)"
    - "ensemble_weights has rows (recomputed from corrected cross-sectional IC)"
    - "alpha_events has rows (alpha_publisher --skip-kafka rerun complete)"
    - "market_regimes regime distribution: SELECT regime, COUNT(*) FROM market_regimes GROUP BY regime shows no single label covering >85% of rows (not a degenerate single-regime collapse)"
    - "config_state has alpha.regime.realized_vol_window=20, alpha.regime.vix_z_window=252, alpha.regime.ma_window=200 (APR migration 182 applied)"
    - "config_state has alpha.validation.oos_start (empty string, set in P1-T1.5)"
    - "config_state has alpha.ic.min_obs_per_regime=3000"
    - "equity_regime_model.py reads realized_vol_window, vix_z_window, ma_window from APR via cfg.get_sync() in run() and passes them as parameters — no bare module-level constants used in _compute_vix_pct_rank or _compute_breadth_fraction"
    - ".venv/bin/pytest tests/unit/ -q exits green"
---

<objective>
Fix two known validity threats before any CORPUS analysis runs on Phase 141 data.

V3 (BaseBatch JSONB codec):
  CURRENT: BaseBatch._setup_pool calls bare asyncpg.create_pool — no JSONB codec
  registration, no pool metrics. alpha_publisher works around this with json.dumps()
  + ::jsonb cast — a CLAUDE.md violation and latent double-encode trap.
  FIX: replace the bare asyncpg.create_pool call with database_manager.create_pool(),
  which registers JSONB codecs and pool metrics atomically, then remove the
  alpha_publisher json.dumps() + ::jsonb workaround in the same commit.

V1 (equity_regime_model look-ahead bias): _compute_vix_pct_rank uses .rank(pct=True) over
the full corpus — global rank computed with knowledge of all future values. Biases all
54,036 cross-sectional IC scores in feature_ic_scores and the 328 ensemble_weights derived
from them. Fix: causal bisect-based expanding rank + TF-normalized windows (V1b). Then rerun
market_regimes → ic_engine --cross-sectional-only → ensemble_trainer → alpha_publisher.

V2 (cost-aware net scoring) is deferred: alpha_score is in weighted z-score product units,
not return units. Correct cost subtraction requires IC × return_scale calibration produced
in P2. V2 gets its own plan after Phase 141.

Full task detail: docs/plans/2026-06-28-validity-fixes-and-phase-141.md (Tasks 1-6)
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@docs/plans/2026-06-28-validity-fixes-and-phase-141.md
@docs/plans/2026-06-28-renaissance-obstacle-map.md
@src/core/agent/base_batch.py
@src/core/database_manager.py
@services/alpha_publisher.py
@services/equity_regime_model.py
</context>

<tasks>

<task id="P0-T0" type="execute">
  <title>APR Migration 182 — equity_regime_model window constants + validation/floor keys</title>
  <wave>1</wave>
  <read_first>
    - production/migrations/181_ensemble_trainer_workers.sql — migration format reference
    - production/migrations/174_market_regimes.sql:64-104 — existing alpha.regime.* APR block (same namespace this migration extends)
    - services/equity_regime_model.py:74-76 — current hard-coded constants to migrate
    - services/equity_regime_model.py:319-338 — existing APR load pattern (cfg.get_sync, alpha.regime.* keys)
    - services/equity_regime_model.py:161-175 — _compute_vix_pct_rank (needs rv_window, z_window params)
    - services/equity_regime_model.py:178-251 — _compute_breadth_fraction (needs ma_window param)
    - services/equity_regime_model.py:356-363 — call sites for both functions
  </read_first>
  <action>
    CLAUDE.md migrate-as-you-go: _REALIZED_VOL_WINDOW=20, _VIX_Z_WINDOW=252, _MA_WINDOW=200 in
    equity_regime_model.py are rolling-window calibration parameters (tunable, not statistical
    concept definitions). They must be APR-backed before the V1 code change commits.

    APR NAMESPACE: use the existing alpha.regime.* namespace that the service already reads
    (alpha.regime.vix_low_pct, alpha.regime.vix_high_pct, alpha.regime.breadth_bear,
    alpha.regime.breadth_bull from migration 174). Do NOT create a second regime.eq_model.*
    namespace — that would split the registry and the new keys would be invisible to the
    running code's existing alpha.regime.* load block.

    Step 1 — Create production/migrations/182_equity_regime_model_apr.sql:

      BEGIN;
      INSERT INTO config_schema (config_key, value_type, default_value, description)
      VALUES
        ('alpha.regime.realized_vol_window', 'int', '20',
         'Rolling window (daily bars) for SPY realized vol (log-return std). [initial_estimate] Scaled to TF bars via _tf_window(daily, tf). ML target: No.'),
        ('alpha.regime.vix_z_window', 'int', '252',
         'Rolling window (daily bars) for VIX z-score mean/std normalization. [conventional] 252 trading days scaled via _tf_window(). ML target: No.'),
        ('alpha.regime.ma_window', 'int', '200',
         'Rolling window (daily bars) for 200MA breadth signal. [conventional] Scaled via _tf_window(). ML target: No.'),
        -- CORPUS-02: OOS holdout boundary (the most recent 6 months of feature_vectors)
        ('alpha.validation.oos_start', 'string', '',
         'OOS holdout start timestamp (ISO8601 UTC). Set once during Phase 141 CORPUS-02. All IC measurement uses data BEFORE this timestamp. OOS used for final validation at Phase 142 exit gate only. [user_preference] ML target: No.'),
        -- CORPUS-06: Per-regime observation floor
        ('alpha.ic.min_obs_per_regime', 'int', '3000',
         'Minimum independent observations per (symbol, tf, regime) cell required for IC score to count toward BH-FDR gate and ensemble weighting. [initial_estimate] IC Sharpe on <3K obs too noisy to survive BH-FDR. ML target: No.')
      ON CONFLICT (config_key) DO NOTHING;

      INSERT INTO config_state (config_key, config_value, version)
      VALUES
        ('alpha.regime.realized_vol_window', '20', 1),
        ('alpha.regime.vix_z_window', '252', 1),
        ('alpha.regime.ma_window', '200', 1),
        ('alpha.validation.oos_start', '', 1),
        ('alpha.ic.min_obs_per_regime', '3000', 1)
      ON CONFLICT (config_key) DO NOTHING;
      COMMIT;

    Step 2 — Apply migration:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/182_equity_regime_model_apr.sql

    Step 3 — Verify:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.regime.%' ORDER BY config_key"
      Expected: existing alpha.regime.vix_low_pct/vix_high_pct/breadth_bear/breadth_bull/equity_model_enabled
      PLUS the 3 new window keys (realized_vol_window=20, vix_z_window=252, ma_window=200).
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key IN ('alpha.validation.oos_start','alpha.ic.min_obs_per_regime') ORDER BY config_key"
      Expected: alpha.ic.min_obs_per_regime=3000; alpha.validation.oos_start='' (empty, set in P1-T1.5).

    Step 4 — Update equity_regime_model.py APR load block (around line 330): add three reads after the existing four:
      realized_vol_window = int(cfg.get_sync("alpha.regime.realized_vol_window", 20))
      vix_z_window = int(cfg.get_sync("alpha.regime.vix_z_window", 252))
      ma_window_days = int(cfg.get_sync("alpha.regime.ma_window", 200))

    Step 5 — Update _compute_vix_pct_rank signature (line 161) to accept optional overrides:
      def _compute_vix_pct_rank(spy_ts: list, spy_close: list[float], tf: str = "1d",
                                 rv_window_days: int = _REALIZED_VOL_WINDOW,
                                 z_window_days: int = _VIX_Z_WINDOW) -> pd.Series:
      Inside the function, replace the two _tf_window calls:
        rv_window = _tf_window(rv_window_days, tf)
        z_window = _tf_window(z_window_days, tf)

    Step 6 — Update _compute_breadth_fraction signature (line 178) to accept optional override:
      def _compute_breadth_fraction(dsn: str, tf: str, spy_ts: list,
                                     ma_window_days: int = _MA_WINDOW) -> pd.Series:
      Inside _process_sym, replace:
        ma_window = _tf_window(ma_window_days, tf)
      (This is the same ma_window variable from V1b — just change the source from _MA_WINDOW to the parameter.)

    Step 7 — Update call sites in run() TF loop (lines 356-363):
      vix_pct_rank = _compute_vix_pct_rank(spy_ts, spy_close, tf=tf,
                                            rv_window_days=realized_vol_window,
                                            z_window_days=vix_z_window)
      breadth_fraction = _compute_breadth_fraction(dsn, tf, spy_ts,
                                                    ma_window_days=ma_window_days)

    Step 8 — Commit migration and code change together:
      git add production/migrations/182_equity_regime_model_apr.sql services/equity_regime_model.py
      git commit -m "feat(config): APR migration 182 — equity_regime_model windows + validation/floor keys

      Migrate _REALIZED_VOL_WINDOW=20, _VIX_Z_WINDOW=252, _MA_WINDOW=200 to the existing
      alpha.regime.* APR namespace (same block the service already reads). Add
      alpha.validation.oos_start (CORPUS-02) and alpha.ic.min_obs_per_regime=3000 (CORPUS-06).
      Functions accept optional override params with module-level constants as defaults
      (safe for unit tests without APR)."
  </action>
  <acceptance_criteria>
    - production/migrations/182_equity_regime_model_apr.sql exists and is applied
    - config_state has alpha.regime.realized_vol_window=20, alpha.regime.vix_z_window=252, alpha.regime.ma_window=200
    - config_state has alpha.ic.min_obs_per_regime=3000 and alpha.validation.oos_start='' (empty)
    - equity_regime_model.py reads the three window keys from alpha.regime.* via cfg.get_sync()
    - _compute_vix_pct_rank and _compute_breadth_fraction accept window params from APR call sites
    - commit exists with both migration and code change
  </acceptance_criteria>
  <output_gate>migration 182 applied; config_state has 3 new alpha.regime.* window keys + alpha.validation.oos_start + alpha.ic.min_obs_per_regime; _compute_vix_pct_rank and _compute_breadth_fraction accept window params from APR call sites; commit exists</output_gate>
</task>

<task id="P0-T1" type="execute">
  <title>V3 — BaseBatch JSONB Codec Fix (atomic)</title>
  <wave>1</wave>
  <read_first>
    - src/core/agent/base_batch.py:122-128 — _setup_pool current implementation (bare asyncpg.create_pool — the broken state)
    - src/core/database_manager.py:19-30 — create_pool signature and _setup_codecs (the correct path)
    - services/alpha_publisher.py:30,132-144,308,376 — import json, INSERT_SQL ::jsonb cast, json.dumps() call sites
  </read_first>
  <action>
    Follow Tasks 1-2 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

    Step 1 — Write failing test: tests/unit/test_base_batch_jsonb.py
    Step 2 — Run pytest to confirm FAIL
    Step 3 — Apply atomic fix (BOTH files in ONE commit):
      - base_batch.py: add `from src.core.database_manager import create_pool` import; replace the bare asyncpg.create_pool() call in _setup_pool with create_pool(self._db_dsn, pool_name=self.job_name, min_size=1, max_size=10) — this registers JSONB codecs and pool metrics atomically
      - alpha_publisher.py: remove `import json`; remove `::jsonb` from INSERT_SQL line 142; replace json.dumps(top_features) at line 308 and json.dumps(e["top_features"]) at line 376 with plain dict references
    Step 4 — Grep other BaseBatch subclasses for remaining json.dumps JSONB workarounds (ensemble_trainer, ic_engine, forward_return_writer, regime_writer)
    Step 5 — Run: .venv/bin/pytest tests/unit/test_base_batch_jsonb.py tests/unit/test_alpha_publisher.py -v
    Step 6 — Run: .venv/bin/pytest tests/unit/ -q (must be green)
    Step 7 — Commit (atomic, both files)
  </action>
  <acceptance_criteria>
    - base_batch.py imports create_pool from src.core.database_manager and _setup_pool calls it (no bare asyncpg.create_pool)
    - alpha_publisher.py has no `import json`, no `::jsonb` cast in INSERT_SQL, no json.dumps() calls
    - test_base_batch_jsonb.py and test_alpha_publisher.py PASS
    - one commit contains both base_batch.py and alpha_publisher.py changes
  </acceptance_criteria>
  <output_gate>test_base_batch_jsonb.py PASS; test_alpha_publisher.py PASS; full unit suite green; one commit containing both base_batch.py and alpha_publisher.py changes</output_gate>
</task>

<task id="P0-T2" type="execute">
  <title>V1 — equity_regime_model Causal Expanding Rank + TF Windows</title>
  <wave>2</wave>
  <read_first>
    - services/equity_regime_model.py:68-76 — constants, _REALIZED_VOL_WINDOW, _VIX_Z_WINDOW, _MA_WINDOW
    - services/equity_regime_model.py:161-175 — _compute_vix_pct_rank current implementation
    - services/equity_regime_model.py:225-231 — _compute_breadth_fraction _MA_WINDOW usage
    - services/equity_regime_model.py:356-363 — call site for _compute_vix_pct_rank
  </read_first>
  <action>
    Follow Tasks 3-5 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

    Step 1 — Write failing tests: tests/unit/services/test_equity_regime_model_causal.py
    Step 2 — Run pytest to confirm FAIL
    Step 3 — Add _BARS_PER_DAY dict and _tf_window() helper after line 76
    Step 4 — Add `import bisect` and `import math` to imports (if not already present)
    Step 5 — Replace _compute_vix_pct_rank with causal bisect-based expanding rank version
      (accepts tf= parameter, uses _tf_window for rv_window and z_window).

      In the causal bisect-based expanding rank implementation:

      NaN guard: Before inserting each value into the sorted window, check
        if math.isnan(val):
            result.append(float('nan'))
            continue
      Do not insert NaN values into the bisect list; NaN propagates to the output at that
      position. This preserves bisect's sort invariant (NaN comparisons would otherwise
      corrupt the ordered list).

      Average-rank formula: Use
        (bisect.bisect_left(window, val) + bisect.bisect_right(window, val)) / 2 / len(window)
      instead of raw bisect_left. This matches Pandas 'average' tie behavior: equal values
      receive the average of their rank positions (two equal values → 0.5, not 0.0).

      Insert val into the sorted window via bisect.insort AFTER computing the rank (causal:
      the current value's rank is computed against prior values only, then it joins the window).

    Step 6 — Update call site ~line 357: add tf=tf argument
    Step 7 — Scale _MA_WINDOW in _compute_breadth_fraction: add ma_window = _tf_window(_MA_WINDOW, tf) and replace both _MA_WINDOW usages
    Step 8 — Run: .venv/bin/pytest tests/unit/services/test_equity_regime_model_causal.py -v (all PASS)
    Step 9 — Run: .venv/bin/pytest tests/unit/ -q (green)
    Step 10 — Commit

    Tests in test_equity_regime_model_causal.py MUST include:
      - test_vix_pct_rank_causal_property: rank at index i is computed only from values [0..i],
        proven by appending a large future value and confirming earlier ranks do not change
        (no look-ahead).
      - test_vix_pct_rank_nan_propagates: a series containing a NaN must produce NaN at that
        position (not raise an error, not insert NaN into the window).
      - test_vix_pct_rank_ties_average: two equal values must produce a rank of 0.5
        (average-rank), not 0.0 (raw bisect_left).
      - test_tf_window: _tf_window(200, '5m') == 15600 and _tf_window(252, '1h') == 1764.
  </action>
  <acceptance_criteria>
    - test_vix_pct_rank_causal_property PASS (verifies no look-ahead)
    - test_vix_pct_rank_nan_propagates PASS (NaN input → NaN output, no error)
    - test_vix_pct_rank_ties_average PASS (equal values → rank 0.5)
    - test_tf_window PASS (_tf_window(200,'5m')==15600, _tf_window(252,'1h')==1764)
    - full unit suite green
  </acceptance_criteria>
  <output_gate>test_vix_pct_rank_causal_property PASS; NaN and tie tests PASS; all V1 tests PASS; full unit suite green</output_gate>
</task>

<task id="P0-T3" type="execute">
  <title>Partial Corpus Rerun (market_regimes → cross-sectional IC → ensemble → alpha)</title>
  <wave>3</wave>
  <read_first>
    - .planning/STATE.md — current corpus row counts (pre-fix baseline)
    - scripts/ops/corpus/ops_corpus_pipeline_run.sh — step invocation patterns
  </read_first>
  <action>
    Follow Task 6 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

    Step 1 — Truncate affected tables (market_regimes, feature_ic_scores WHERE is_pooled=true, ensemble_weights, ensemble_alpha, alpha_events). Verify all are zero.
    Step 2 — Rerun equity_regime_model: .venv/bin/python services/equity_regime_model.py
    Step 3 — Capture TRAINING_WINDOW_END from feature_vectors MAX(bar_ts)
    Step 4 — Rerun ic_engine --cross-sectional-only: .venv/bin/python services/ic_engine.py --cross-sectional-only --training-window-end $TRAINING_WINDOW_END
    Step 5 — Rerun ensemble_trainer: .venv/bin/python services/ensemble_trainer.py
    Step 6 — Rerun alpha_publisher --skip-kafka: .venv/bin/python services/alpha_publisher.py --skip-kafka
    Step 7 — Verify row counts: market_regimes, feature_ic_scores (is_pooled=true), ensemble_weights, alpha_events all non-zero
    Step 8 — Verify regime balance (Renaissance invariant — degenerate single-regime collapse means the V1 fix introduced a bug):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT regime, COUNT(*) as cnt, ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER(), 1) AS pct FROM market_regimes GROUP BY regime ORDER BY cnt DESC"
      If any single regime covers >85% of all rows: STOP — causal rank implementation has a bug. Investigate before proceeding.
    Step 9 — Update .planning/STATE.md Current Data State section with new row counts
    Step 10 — Commit STATE.md update
  </action>
  <acceptance_criteria>
    - market_regimes, feature_ic_scores (is_pooled=true), ensemble_weights, alpha_events all non-zero after rerun
    - market_regimes repopulated from scratch with corrected regime labels
    - no single regime label covers >85% of rows
    - STATE.md updated with new row counts and committed
  </acceptance_criteria>
  <output_gate>All four tables non-zero; market_regimes and alpha_events repopulated from scratch with corrected regime labels; no single regime label covers >85% of rows; STATE.md updated</output_gate>
</task>

</tasks>
</output>
