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
    - "market_regimes row count differs from pre-fix 819,020 or is reproduced from scratch — either is acceptable; stale data is not"
    - "feature_ic_scores WHERE is_pooled=true has rows (cross-sectional IC recomputed with corrected regime labels)"
    - "ensemble_weights has rows (recomputed from corrected cross-sectional IC)"
    - "alpha_events has rows (alpha_publisher --skip-kafka rerun complete)"
    - "market_regimes regime distribution: SELECT regime, COUNT(*) FROM market_regimes GROUP BY regime shows no single label covering >85% of rows (not a degenerate single-regime collapse)"
    - "config_state has regime.eq_model.realized_vol_window=20, regime.eq_model.vix_z_window=252, regime.eq_model.ma_window=200 (APR migration 182 applied)"
    - "equity_regime_model.py reads realized_vol_window, vix_z_window, ma_window from APR via cfg.get_sync() in run() and passes them as parameters — no bare module-level constants used in _compute_vix_pct_rank or _compute_breadth_fraction"
    - ".venv/bin/pytest tests/unit/ -q exits green"
---

<objective>
Fix two known validity threats before any CORPUS analysis runs on Phase 141 data.

V3 (BaseBatch JSONB codec): BaseBatch._setup_pool calls bare asyncpg.create_pool with no codec registration. alpha_publisher works around this with json.dumps() + ::jsonb cast — a CLAUDE.md violation and latent double-encode trap. Fix: use database_manager.create_pool atomically with workaround removal.

V1 (equity_regime_model look-ahead bias): _compute_vix_pct_rank uses .rank(pct=True) over the full corpus — global rank computed with knowledge of all future values. Biases all 54,036 cross-sectional IC scores in feature_ic_scores and the 328 ensemble_weights derived from them. Fix: causal bisect-based expanding rank + TF-normalized windows (V1b). Then rerun market_regimes → ic_engine --cross-sectional-only → ensemble_trainer → alpha_publisher.

V2 (cost-aware net scoring) is deferred: alpha_score is in weighted z-score product units, not return units. Correct cost subtraction requires IC × return_scale calibration produced in P2. V2 gets its own plan after Phase 141.

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
  <title>APR Migration 182 — equity_regime_model window constants</title>
  <wave>1</wave>
  <read_first>
    - production/migrations/181_ensemble_trainer_workers.sql — migration format reference
    - services/equity_regime_model.py:74-76 — current hard-coded constants to migrate
    - services/equity_regime_model.py:320-330 — existing APR load pattern (cfg.get_sync)
    - services/equity_regime_model.py:161-175 — _compute_vix_pct_rank (needs rv_window, z_window params)
    - services/equity_regime_model.py:178-251 — _compute_breadth_fraction (needs ma_window param)
    - services/equity_regime_model.py:348-364 — call sites for both functions
  </read_first>
  <action>
    CLAUDE.md migrate-as-you-go: _REALIZED_VOL_WINDOW=20, _VIX_Z_WINDOW=252, _MA_WINDOW=200 in
    equity_regime_model.py are rolling-window calibration parameters (tunable, not statistical
    concept definitions). They must be APR-backed before the V1 code change commits.

    Step 1 — Create production/migrations/182_equity_regime_model_apr.sql:

      BEGIN;
      INSERT INTO config_schema (config_key, value_type, default_value, description)
      VALUES
        ('regime.eq_model.realized_vol_window', 'int', '20',
         'Rolling window (daily bars) for SPY realized vol (log-return std). [initial_estimate] Scaled to TF bars via _tf_window(daily, tf). ML target: No.'),
        ('regime.eq_model.vix_z_window', 'int', '252',
         'Rolling window (daily bars) for VIX z-score mean/std normalization. [conventional] 252 trading days scaled via _tf_window(). ML target: No.'),
        ('regime.eq_model.ma_window', 'int', '200',
         'Rolling window (daily bars) for 200MA breadth signal. [conventional] Scaled via _tf_window(). ML target: No.')
      ON CONFLICT (config_key) DO NOTHING;

      INSERT INTO config_state (config_key, config_value, version)
      VALUES
        ('regime.eq_model.realized_vol_window', '20', 1),
        ('regime.eq_model.vix_z_window', '252', 1),
        ('regime.eq_model.ma_window', '200', 1)
      ON CONFLICT (config_key) DO NOTHING;
      COMMIT;

    Step 2 — Apply migration:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/182_equity_regime_model_apr.sql

    Step 3 — Verify:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'regime.eq_model.%' ORDER BY config_key"
      Expected: 3 rows with values 20, 252, 200.

    Step 4 — Update equity_regime_model.py APR load block (around line 326): add three reads after the existing four:
      realized_vol_window = int(cfg.get_sync("regime.eq_model.realized_vol_window", 20))
      vix_z_window = int(cfg.get_sync("regime.eq_model.vix_z_window", 252))
      ma_window_days = int(cfg.get_sync("regime.eq_model.ma_window", 200))

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

    Step 7 — Update call sites in run() TF loop (lines 357-363):
      vix_pct_rank = _compute_vix_pct_rank(spy_ts, spy_close, tf=tf,
                                            rv_window_days=realized_vol_window,
                                            z_window_days=vix_z_window)
      breadth_fraction = _compute_breadth_fraction(dsn, tf, spy_ts,
                                                    ma_window_days=ma_window_days)

    Step 8 — Commit migration and code change together:
      git add production/migrations/182_equity_regime_model_apr.sql services/equity_regime_model.py
      git commit -m "feat(config): APR migration 182 — equity_regime_model window constants

      Migrate _REALIZED_VOL_WINDOW=20, _VIX_Z_WINDOW=252, _MA_WINDOW=200 to
      regime.eq_model.* APR keys. Functions accept optional override params with
      module-level constants as defaults (safe for unit tests without APR)."
  </action>
  <output_gate>production/migrations/182_equity_regime_model_apr.sql exists and is applied; config_state has 3 new regime.eq_model.* keys; _compute_vix_pct_rank and _compute_breadth_fraction accept window params from APR call sites; commit exists</output_gate>
</task>

<task id="P0-T1" type="execute">
  <title>V3 — BaseBatch JSONB Codec Fix (atomic)</title>
  <wave>1</wave>
  <read_first>
    - src/core/agent/base_batch.py:122-128 — _setup_pool current implementation
    - src/core/database_manager.py:19-30 — create_pool signature and _setup_codecs
    - services/alpha_publisher.py:30,132-144,308,376 — import json, INSERT_SQL ::jsonb cast, json.dumps() call sites
  </read_first>
  <action>
    Follow Tasks 1-2 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

    Step 1 — Write failing test: tests/unit/test_base_batch_jsonb.py
    Step 2 — Run pytest to confirm FAIL
    Step 3 — Apply atomic fix (BOTH files in ONE commit):
      - base_batch.py: add `from src.core.database_manager import create_pool` import; replace asyncpg.create_pool() call in _setup_pool with create_pool(self._db_dsn, pool_name=self.job_name, min_size=1, max_size=10)
      - alpha_publisher.py: remove `import json`; remove `::jsonb` from INSERT_SQL line 142; replace json.dumps(top_features) at line 308 and json.dumps(e["top_features"]) at line 376 with plain dict references
    Step 4 — Grep other BaseBatch subclasses for remaining json.dumps JSONB workarounds (ensemble_trainer, ic_engine, forward_return_writer, regime_writer)
    Step 5 — Run: .venv/bin/pytest tests/unit/test_base_batch_jsonb.py tests/unit/test_alpha_publisher.py -v
    Step 6 — Run: .venv/bin/pytest tests/unit/ -q (must be green)
    Step 7 — Commit (atomic, both files)
  </action>
  <output_gate>test_base_batch_jsonb.py PASS; test_alpha_publisher.py PASS; full unit suite green; one commit containing both base_batch.py and alpha_publisher.py changes</output_gate>
</task>

<task id="P0-T2" type="execute">
  <title>V1 — equity_regime_model Causal Expanding Rank + TF Windows</title>
  <wave>2</wave>
  <read_first>
    - services/equity_regime_model.py:68-76 — constants, _REALIZED_VOL_WINDOW, _VIX_Z_WINDOW, _MA_WINDOW
    - services/equity_regime_model.py:161-175 — _compute_vix_pct_rank current implementation
    - services/equity_regime_model.py:225-231 — _compute_breadth_fraction _MA_WINDOW usage
    - services/equity_regime_model.py:351-357 — call site for _compute_vix_pct_rank
  </read_first>
  <action>
    Follow Tasks 3-5 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

    Step 1 — Write failing tests: tests/unit/services/test_equity_regime_model_causal.py
    Step 2 — Run pytest to confirm FAIL
    Step 3 — Add _BARS_PER_DAY dict and _tf_window() helper after line 76
    Step 4 — Add `import bisect` to imports
    Step 5 — Replace _compute_vix_pct_rank with causal bisect-based expanding rank version (accepts tf= parameter, uses _tf_window for rv_window and z_window)
    Step 6 — Update call site ~line 357: add tf=tf argument
    Step 7 — Scale _MA_WINDOW in _compute_breadth_fraction: add ma_window = _tf_window(_MA_WINDOW, tf) and replace both _MA_WINDOW usages
    Step 8 — Run: .venv/bin/pytest tests/unit/services/test_equity_regime_model_causal.py -v (all PASS)
    Step 9 — Run: .venv/bin/pytest tests/unit/ -q (green)
    Step 10 — Commit
  </action>
  <output_gate>test_vix_pct_rank_causal_property PASS (verifies no look-ahead); all V1 tests PASS; full unit suite green</output_gate>
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
  <output_gate>All four tables non-zero; market_regimes and alpha_events repopulated from scratch with corrected regime labels; no single regime label covers >85% of rows; STATE.md updated</output_gate>
</task>

</tasks>
