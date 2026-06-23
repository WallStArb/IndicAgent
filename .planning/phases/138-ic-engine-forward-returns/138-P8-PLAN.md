---
phase: 138-ic-engine-forward-returns
plan: 08
type: execute
wave: 7
depends_on: ["138-05", "138-06", "138-07"]
files_modified:
  - feature_vectors (DB — regime + HMM probability columns populated)
  - forward_returns (DB — causal log returns populated)
  - feature_ic_scores (DB — IC, CI, BH-FDR, walk-forward, IC Sharpe populated)
  - docs/analysis/ic-discovery-report.md
  - docs/analysis/ic-discovery-report.json
autonomous: true

must_haves:
  truths:
    - "backfill_feature_factory has completed for 4 symbols (SPY, TLT, XLF, QQQ) x 4 TFs in feature_vectors before any task in this plan runs"
    - ">95% of feature_vectors rows have canonical regime labels + full HMM alpha vector after regime_writer corpus run"
    - "hmm_prob_trending_up + hmm_prob_ranging + hmm_prob_trending_down sum to 1.0 per bar globally"
    - "forward_returns populated for 4 symbols (SPY, TLT, XLF, QQQ) x 4 TFs; every row has a matching feature_vectors row"
    - "feature_ic_scores populated for 4 symbols (SPY, TLT, XLF, QQQ) x 4 TFs; no is_pooled=false rows with regime=NULL"
    - "At least one feature passes_walkforward across the 4-symbol corpus"
    - "IC discovery report (markdown + JSON) exists with passing_features array for Phase 139 automation"
    - "JSON sidecar parseable by json.load(); passing_features contains only passes_walkforward=true rows"
  artifacts:
    - path: "docs/analysis/ic-discovery-report.md"
      provides: "IC discovery report (markdown) with per-feature IC Sharpe table, FDR + walk-forward pass counts by regime and TF"
      contains: "IC Sharpe"
    - path: "docs/analysis/ic-discovery-report.json"
      provides: "Machine-readable passing features for Phase 139 ensemble construction"
      contains: "passing_features"
  key_links:
    - from: "regime_writer corpus run"
      to: "feature_vectors.regime + hmm_prob_* columns"
      via: "UPDATE WHERE symbol=%s AND tf=%s AND bar_ts=%s"
      pattern: "regime_writer"
    - from: "forward_return_writer corpus run"
      to: "forward_returns table"
      via: "INSERT ... ON CONFLICT (symbol, tf, bar_ts) DO NOTHING"
      pattern: "forward_return_writer"
    - from: "ic_engine corpus run"
      to: "feature_ic_scores table"
      via: "INSERT ... ON CONFLICT ... DO NOTHING (pooled + regime partial indexes)"
      pattern: "ic_engine"
---

<objective>
Run the 4-symbol IC pipeline (SPY, TLT, XLF, QQQ) and generate the IC discovery report. This plan is entirely data execution — no code is written. All services were built and unit-tested in P5-P7; this plan runs them against the 4-symbol feature_vectors subset.

Order: (1) regime_writer (parallel with forward_return_writer) → (2) forward_return_writer → (3) IC engine → (4) IC discovery report.

Precondition: backfill_feature_factory must have completed for the 4 symbols before this plan starts. All tasks in this plan fail meaningfully (crash-loud gates) if their upstream data is missing.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md
@services/regime_writer.py
@services/forward_return_writer.py
@services/ic_engine.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backfill 4 symbols (SPY, TLT, XLF, QQQ)</name>
  <files>feature_vectors (DB — populated with 4-symbol corpus)</files>
  <read_first>
    - services/backfill_feature_factory.py (--symbols flag usage)
  </read_first>
  <action>
    Run backfill_feature_factory for the 4 symbols only. This fetches OHLCV data (if needed) and computes feature vectors.

    Stage 1 — Fetch OHLCV (if not already in market_data_ohlcv):
      .venv/bin/python services/backfill_feature_factory.py --symbols SPY,TLT,XLF,QQQ --fetch-only

    Stage 2 — Compute feature vectors:
      .venv/bin/python services/backfill_feature_factory.py --symbols SPY,TLT,XLF,QQQ --compute-only

    Or both stages in one run:
      .venv/bin/python services/backfill_feature_factory.py --symbols SPY,TLT,XLF,QQQ

    Monitor progress in logs/backfill_feature_factory.log. Expected runtime: ~5-10 minutes for 4 symbols x 4 TFs.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM feature_vectors WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns 4
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT tf, count(*) FROM feature_vectors WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) GROUP BY tf ORDER BY tf;"` returns 4 rows (5m, 15m, 1h, 1d)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_vectors WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns >= 100,000
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT symbol, tf, count(*) FROM feature_vectors WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) GROUP BY symbol, tf ORDER BY symbol, tf;"</verify>
  <done>4-symbol backfill complete; feature_vectors populated for SPY, TLT, XLF, QQQ across all 4 TFs.</done>
</task>

<task type="auto">
  <name>Task 2: Verify 4-symbol preconditions</name>
  <files>None (verification only)</files>
  <action>
    Confirm all preconditions are met before running any IC task.

    Check 1 — backfill_feature_factory complete for 4 symbols:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT timeframe, count(DISTINCT symbol) sym_count, count(*) rows
        FROM feature_vectors
        WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ'])
        GROUP BY timeframe ORDER BY timeframe;"
    Must show 4 symbols per TF. If fewer than 4 symbols in any TF, do not proceed — restart backfill_feature_factory with --symbols SPY,TLT,XLF,QQQ and wait.

    Check 2 — bars are complete enough to support IC Sharpe gate (4 symbols per TF with data):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT timeframe, count(DISTINCT symbol)
        FROM market_data_ohlcv
        WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) AND timeframe IN ('5m','15m','1h','1d')
        GROUP BY timeframe ORDER BY timeframe;"

    Check 3 — forward_returns currently empty (pre-run baseline):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM forward_returns;"

    Check 4 — feature_ic_scores currently empty (pre-run baseline):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM feature_ic_scores;"

    Log baseline counts. Proceed only if Check 1 passes.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT min(count) FROM (SELECT count(DISTINCT symbol) AS count FROM feature_vectors WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) GROUP BY tf) sub;"` returns 4
  </acceptance_criteria>
  <done>Baseline counts logged; 4 symbols (SPY, TLT, XLF, QQQ) confirmed in feature_vectors for each TF; proceeding to IC runs.</done>
</task>

<task type="auto">
  <name>Task 3: Regime_writer for 4 symbols (parallel with Task 4)</name>
  <files>feature_vectors (DB — regime + HMM columns populated)</files>
  <read_first>
    - services/regime_writer.py (run flags; --symbols and --tf args default behavior)
  </read_first>
  <action>
    Run regime_writer for the 4 symbols. HMM fitting is CPU-bound. Run:

      .venv/bin/python services/regime_writer.py --symbols SPY,TLT,XLF,QQQ

    Poll progress:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf, regime, count(*) FROM feature_vectors
        WHERE regime IS NOT NULL AND symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ'])
        GROUP BY tf, regime ORDER BY tf, regime;"

    This is idempotent (UPDATE semantics; HMM_RANDOM_STATE=42 produces identical labels on same data).
    Task 3 and Task 4 (forward_return_writer) are INDEPENDENT and can run concurrently — Task 3 writes
    feature_vectors.regime columns; Task 4 only reads feature_vectors.bar_ts. No write conflict.
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0*count(*) FILTER (WHERE regime IS NULL)/count(*),2) FROM feature_vectors;"` returns < 5.0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT regime) FROM feature_vectors WHERE regime IS NOT NULL;"` returns >= 2
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0*count(*) FILTER (WHERE hmm_prob_trending_up IS NULL)/count(*),2) FROM feature_vectors WHERE regime IS NOT NULL;"` returns 0.0 (every labeled row has full alpha vector)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT max(abs(hmm_prob_trending_up + hmm_prob_ranging + hmm_prob_trending_down - 1.0)) FROM feature_vectors WHERE hmm_prob_trending_up IS NOT NULL;"` returns < 1e-9
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, regime, count(*), round(avg(hmm_prob_trending_up)::numeric,3) avg_p_up, round(avg(hmm_entropy)::numeric,3) avg_ent FROM feature_vectors WHERE regime IS NOT NULL GROUP BY tf, regime ORDER BY tf, regime;"</verify>
  <done>>95% of feature_vectors rows have canonical regime labels + full HMM alpha vector; probabilities sum to 1.0 globally.</done>
</task>

<task type="auto">
  <name>Task 4: Forward_return_writer for 4 symbols (parallel with Task 3)</name>
  <files>forward_returns (DB — populated)</files>
  <read_first>
    - services/forward_return_writer.py (run flags)
  </read_first>
  <action>
    Run forward_return_writer for the 4 symbols:

      .venv/bin/python services/forward_return_writer.py --symbols SPY,TLT,XLF,QQQ

    Poll progress:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf, count(*) FROM forward_returns WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) GROUP BY tf ORDER BY tf;"

    After completion verify idempotency:
      COUNT_BEFORE=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM forward_returns WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);")
      .venv/bin/python services/forward_return_writer.py --symbols SPY --tf 1h
      COUNT_AFTER=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM forward_returns WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);")
      # counts must be equal
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM forward_returns WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns 4
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT round(100.0*count(*) FILTER (WHERE complete_5bar)/count(*),1) FROM forward_returns WHERE tf='5m' AND symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns > 95.0
    - Idempotency: re-run inserts 0 new rows (count before == count after)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM forward_returns fr LEFT JOIN feature_vectors fv USING(symbol, tf, bar_ts) WHERE fv.bar_ts IS NULL AND fr.symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns 0
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, count(*) total, count(*) FILTER (WHERE complete_5bar) c5, count(*) FILTER (WHERE complete_60bar) c60 FROM forward_returns WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) GROUP BY tf ORDER BY tf;"</verify>
  <done>forward_returns populated for 4 symbols x 4 TFs; TRAINING_WINDOW_END gate confirmed; idempotent re-run confirmed.</done>
</task>

<task type="auto">
  <name>Task 5: IC engine for 4 symbols</name>
  <files>feature_ic_scores (DB — populated)</files>
  <read_first>
    - services/ic_engine.py (just built in P6; run flags; crash-loud gates)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Finding 3 full-run estimate ~2.8 min bootstrap phase; Risk 3 1h TF marginal)
  </read_first>
  <precondition>
    Both Task 3 (regime_writer) and Task 4 (forward_return_writer) must be complete before this task runs.
    IC engine needs: feature_vectors.regime populated (from T3) AND forward_returns populated (from T4).
    The crash-loud startup gates will raise RuntimeError if either is missing.
  </precondition>
  <action>
    Run the IC engine for the 4 symbols:

      .venv/bin/python services/ic_engine.py --symbols SPY,TLT,XLF,QQQ

    Poll progress:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf, is_pooled, count(*) total, count(*) FILTER (WHERE passes_fdr) fdr, count(*) FILTER (WHERE passes_walkforward) wf
        FROM feature_ic_scores WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) GROUP BY tf, is_pooled ORDER BY tf, is_pooled;"

    After completion verify idempotency:
      COUNT_BEFORE=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);")
      .venv/bin/python services/ic_engine.py --symbols SPY --tf 1h
      COUNT_AFTER=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);")
      # counts must be equal
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(DISTINCT symbol) FROM feature_ic_scores WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns 4
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE passes_walkforward = true AND symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns >= 1
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM feature_ic_scores WHERE is_pooled=false AND regime IS NULL AND symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']);"` returns 0
    - Idempotency: re-run inserts 0 new rows
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, is_pooled, count(*) total, count(*) FILTER (WHERE passes_fdr) fdr, count(*) FILTER (WHERE passes_walkforward) wf FROM feature_ic_scores WHERE symbol = ANY(ARRAY['SPY','TLT','XLF','QQQ']) GROUP BY tf, is_pooled ORDER BY tf, is_pooled;"</verify>
  <done>feature_ic_scores populated for 4 symbols x 4 TFs; is_pooled/regime correctly set; idempotent re-run confirmed; at least one feature passes walk-forward.</done>
</task>

<task type="auto">
  <name>Task 6: Generate IC discovery report (markdown + JSON sidecar)</name>
  <files>docs/analysis/ic-discovery-report.md, docs/analysis/ic-discovery-report.json</files>
  <read_first>
    - services/ic_engine.py (verify --report-only flag is implemented; it was built in P6 -- if absent, stop and diagnose P6)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§XVIII report format and sections)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (IC Discovery Report Format; Risk 6 mkdir docs/analysis/)
  </read_first>
  <action>
    Ensure docs/analysis/ exists. The ic_engine.py built in P6 implements a --report-only flag
    that queries feature_ic_scores and writes both output files without recomputing IC.
    Verify the flag is present before proceeding: `grep -c "report.only\|report_only" services/ic_engine.py`
    must return >= 2. If it returns 0, P6 was not executed correctly -- stop and diagnose P6.

    Run: .venv/bin/python services/ic_engine.py --report-only

    MARKDOWN REPORT (docs/analysis/ic-discovery-report.md):
      Sections per IC spec §XVIII:
      1. Summary: total cells, N passing FDR, N passing walk-forward, N with non-null IC Sharpe; training_window_end
      2. Per-feature table: feature_name, symbol, tf, regime, is_pooled, lookahead_bars, ic_value, ic_ci_lower, passes_fdr, passes_walkforward, ic_sharpe (sorted by ic_sharpe DESC)
      3. Top 20 features by IC Sharpe (non-null, passes_walkforward=true)
      4. Comparison: pooled vs regime-stratified IC (section header: "Diagnostic: Pooled vs Regime-Stratified" -- pooled rows are diagnostic artifacts only, not for Phase 139 ensemble)
      5. Cells below IC Sharpe gate: (symbol, tf) pairs where n_raw_bars < 20,000

    JSON SIDECAR (docs/analysis/ic-discovery-report.json):
      {
        "generated_at": "<ISO-8601>",
        "training_window_end": "<ISO-8601>",
        "total_cells": N,
        "cells_passing_fdr": N,
        "cells_passing_walkforward": N,
        "passing_features": [
          {
            "feature_name": "...",
            "symbol": "...",
            "tf": "...",
            "regime": "...",
            "is_pooled": false,
            "lookahead_bars": 5,
            "ic_value": 0.042,
            "ic_ci_lower": 0.011,
            "ic_sharpe": 1.23,
            "passes_fdr": true,
            "passes_walkforward": true
          }
        ]
      }
      passing_features contains ONLY rows where passes_walkforward=true AND is_pooled=false.
      Write both files atomically (.tmp then rename).
  </action>
  <acceptance_criteria>
    - `ls docs/analysis/ic-discovery-report.md` succeeds
    - `ls docs/analysis/ic-discovery-report.json` succeeds
    - `grep -c "IC Sharpe\|passes_walkforward\|passes_fdr" docs/analysis/ic-discovery-report.md` returns >= 3
    - `grep -c "Diagnostic\|pooled" docs/analysis/ic-discovery-report.md` returns >= 1
    - `.venv/bin/python -c "import json; d=json.load(open('docs/analysis/ic-discovery-report.json')); assert 'passing_features' in d; assert 'training_window_end' in d; print(f'{len(d[\"passing_features\"])} passing features')"` exits 0
    - `.venv/bin/python -c "import json; d=json.load(open('docs/analysis/ic-discovery-report.json')); pf=d['passing_features']; bad=[f for f in pf if f.get('is_pooled')]; assert not bad, f'{len(bad)} pooled rows in passing_features'; print('ok')"` exits 0 (no pooled rows in passing_features)
    - `.venv/bin/pytest tests/unit/ -q` exits 0 (full suite green, final confirmation)
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT feature_name, tf, regime, round(ic_value::numeric,4) ic, round(ic_sharpe::numeric,3) sharpe, passes_fdr, passes_walkforward FROM feature_ic_scores WHERE is_pooled=false AND passes_walkforward=true ORDER BY ic_sharpe DESC NULLS LAST LIMIT 20;"</verify>
  <done>IC discovery report (markdown + JSON) written; passing_features excludes pooled rows; full tests/unit/ suite green; Phase 138 data pipeline complete.</done>
</task>

</tasks>

<verification>
- feature_vectors: 4 symbols (SPY, TLT, XLF, QQQ) x 4 TFs; >95% rows with regime + full HMM alpha vector; probs sum to 1.0 globally
- forward_returns: 4 symbols x 4 TFs; every row matches a feature_vectors bar_ts
- feature_ic_scores: 4 symbols x 4 TFs; no is_pooled=false+regime=NULL ambiguity; at least one passes_walkforward
- IC discovery report: markdown with pooled-vs-regime comparison section; JSON with passing_features (is_pooled=false, passes_walkforward=true only)
- All idempotency checks pass
- tests/unit/ fully GREEN
</verification>

<success_criteria>
- All task acceptance criteria pass
- At least one feature passes_walkforward across the 4-symbol corpus
- docs/analysis/ic-discovery-report.json is valid and parseable by Phase 139 automation
- .venv/bin/pytest tests/unit/ -q exits 0
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-08-SUMMARY.md` documenting:
- feature_vectors row counts and regime coverage per TF
- forward_returns row counts and completeness fractions per lookahead
- feature_ic_scores counts per (TF, is_pooled): total, passing FDR, passing walk-forward
- Top 10 features by IC Sharpe from the JSON sidecar
- Any (symbol, tf) cells below the 20K IC-Sharpe gate
- Path to both IC discovery report files
</output>
