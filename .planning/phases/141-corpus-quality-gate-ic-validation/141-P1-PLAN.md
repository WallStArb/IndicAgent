---
plan: 141-P1
phase: "141"
title: "IC Validation Analysis"
wave: 1
depends_on: [141-P0]
files_modified:
  - docs/analysis/ic-validation-report-58sym.md
  - docs/analysis/corpus-01-feature-audit.md
  - docs/analysis/i7-feature-mapping.json
autonomous: true
must_haves:
  goal: "IC validation report written from V1-corrected corpus; CORPUS-01..07 deliverables produced; gate assessment determines whether Phase 142 shadow mode proceeds"
  truths:
    - "docs/analysis/ic-validation-report-58sym.md exists and is committed"
    - "docs/analysis/corpus-01-feature-audit.md exists: per-feature variance/NaN/cliff audit table (CORPUS-01)"
    - "config_state alpha.validation.oos_start contains an ISO8601 UTC timestamp (6 months before MAX(bar_ts) in feature_vectors) (CORPUS-02)"
    - "Report contains CORPUS-03 null model comparison: IC-weighted vs equal-weight IC Sharpe on OOS window with explicit PASS/FAIL against >0.1 advantage threshold"
    - "Report contains top-30 features ranked by |ic_sharpe_hac| from feature_ic_scores WHERE is_pooled=true AND symbol='POOLED' AND regime != '_pooled'"
    - "Report contains NULL-rate section: counts cells with ic_sharpe_hac IS NULL per TF — 1d absence is expected and documented"
    - "Report contains per-TF IC breakdown with cells_with_sharpe, pass_sharpe_05 (|ic_sharpe_hac|>0.5), ci_lower_positive counts"
    - "Report contains per-regime IC breakdown across all 9 cross-sectional labels ({low,mid,high}_{bull,neutral,bear})"
    - "Report contains CORPUS-06 per-regime floor: (tf, regime) cells below 3000 independent obs listed explicitly"
    - "Report contains demotion candidates: features with max_abs_ic=0 across all regimes (zero-IC features)"
    - "Report contains V2 cost calibration constants: ic_x_return_scale per (tf, regime)"
    - "docs/analysis/i7-feature-mapping.json exists with entries for all active TIER_I7 plugins (CORPUS-07)"
    - "Gate assessment explicitly states PASS or FAIL with: '5m: N features total |ic_sharpe_hac|>0.5 with ic_ci_lower>0 across all regimes (PASS: N≥5)'"
    - "Criterion for PASS: ≥5 features total (across all regimes combined) with |ic_sharpe_hac|>0.5 AND ic_ci_lower>0 in 5m AND ≥5 in 1h; minority regimes with zero qualifying features are noted but do not block PASS"
---

<objective>
Run the Phase 141 IC validation analysis on the V1-corrected corpus and produce the full
CORPUS-01 through CORPUS-07 deliverable set. Read existing feature_ic_scores (cross-sectional
rows), audit the corpus, establish the OOS boundary, run the null-model baseline, produce a
ranked validation report, and determine whether the Phase 141 gate passes.

No new services are written. This plan is query- and script-driven: audit features → split OOS →
compute null-model baseline → read feature_ic_scores → summarize → write report → gate assessment.

Key invariant: all queries filter WHERE return_type = 'executable_open_to_open'
at the forward_returns join level. The IC engine already enforces this; the V2
calibration constant query and the null-model baseline must enforce it explicitly.

Key invariant: 1d has almost no ic_sharpe_hac values (insufficient bars for the
60K subsampled-bar minimum). Do not report 1d IC Sharpe as a signal-bearing result
and do not let 1d NULL rate influence the gate assessment.

CORPUS coverage map:
  CORPUS-01 (feature audit)       → P1-T0
  CORPUS-02 (OOS holdout)         → P1-T1.5 (writes alpha.validation.oos_start)
  CORPUS-03 (null model baseline) → P1-T1.5
  CORPUS-04 (IC discovery report) → P1-T2
  CORPUS-05 (IC Sharpe stability) → P1-T1 / P1-T2
  CORPUS-06 (per-regime floor)    → P1-T2b
  CORPUS-07 (I7→feature mapping)  → P1-T3
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@docs/plans/2026-06-28-validity-fixes-and-phase-141.md
@.planning/STATE.md
</context>

<tasks>

<task id="P1-T0" type="execute">
  <title>CORPUS-01 — Feature Distribution Audit</title>
  <wave>0</wave>
  <read_first>
    - .planning/STATE.md — confirm corpus is V1-corrected (feature_vectors populated)
    - services/feature_factory.py — feature column list written to feature_vectors (source of truth for which columns to audit)
    - docs/foundation/principles.md — "never drop data that could contain signal" (variance audit blocks, does not delete)
  </read_first>
  <action>
    Write and run a one-shot audit script that checks every feature column in feature_vectors.

    Step 1 — Enumerate feature columns:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'feature_vectors'
          AND data_type IN ('double precision','real','numeric')
          AND column_name NOT IN ('symbol','tf')
        ORDER BY column_name;
      "
      These are the columns to audit (exclude id/timestamp/key columns).

    Step 2 — For each feature column, compute three criteria (per symbol, then aggregate):
      (a) variance > epsilon (1e-12): no silent constants.
          Query: SELECT VAR_SAMP(<col>) FROM feature_vectors WHERE symbol=<sym>.
          A column with VAR_SAMP <= 1e-12 for ALL symbols FAILS criterion (a).
      (b) NaN rate < 5% post-warmup: exclude the first 100 bars per symbol, then
          count NULL / NaN rows. NaN rate >= 5% post-warmup FAILS criterion (b).
      (c) no distributional cliff: compute a 4-week rolling std of the feature, then the
          z-score of that rolling-std series. If any |z| > 2.0 (rolling std jumps >2σ from
          its own history) the column FAILS criterion (c).

    Step 3 — Disposition:
      - Features failing (a) → BLOCKED from IC measurement. Emit them to a log line
        ("corpus_01.blocked_zero_variance", features=[...]) AND list them explicitly in
        the audit report. These columns are constant — IC is undefined.
      - Features failing (b) or (c) → WARNING only (flagged, not blocked). Renaissance
        principle: never drop data that could contain signal; a warning surfaces it for
        review without deleting it.

    Step 4 — Write docs/analysis/corpus-01-feature-audit.md:
      A per-feature table with columns: feature | variance_pass | nan_rate_pct | nan_pass |
      cliff_max_abs_z | cliff_pass | disposition (PASS / BLOCKED / WARNING).
      Header notes the epsilon (1e-12), warmup (100 bars), NaN threshold (5%), cliff
      threshold (|z|>2.0). Summary line: N features audited, B blocked, W warnings.

    Step 5 — Commit:
      git add docs/analysis/corpus-01-feature-audit.md
      git commit -m "docs(analysis): CORPUS-01 feature distribution audit — variance/NaN/cliff"
  </action>
  <acceptance_criteria>
    - docs/analysis/corpus-01-feature-audit.md exists with a per-feature audit table
    - every numeric feature_vectors column appears in the table with a PASS/BLOCKED/WARNING disposition
    - zero-variance columns are listed explicitly as BLOCKED
    - report header states the thresholds (epsilon, warmup bars, NaN %, cliff z)
    - committed
  </acceptance_criteria>
  <output_gate>corpus-01-feature-audit.md committed; per-feature variance/NaN/cliff table with explicit dispositions; zero-variance features listed as BLOCKED</output_gate>
</task>

<task id="P1-T1" type="execute">
  <title>IC Validation Queries</title>
  <wave>1</wave>
  <read_first>
    - .planning/STATE.md — current row counts to confirm corpus is V1-corrected
    - docs/plans/2026-06-28-validity-fixes-and-phase-141.md — Steps 7.1–7.5 for exact SQL
    - services/ic_engine.py:114-183 — column names and sentinel values (POOLED, _pooled, is_pooled)
  </read_first>
  <action>
    Run all IC validation queries and capture output for the report.

    Step 1 — Verify corpus is V1-corrected (guard: market_regimes must exist post-P0):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT COUNT(*) FROM market_regimes"
      If 0: STOP — P0 corpus rerun has not completed.

    Step 2 — NULL rate check per TF (establishes baseline before interpreting IC Sharpe counts):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf,
          COUNT(*) AS total_cells,
          COUNT(ic_sharpe_hac) AS cells_with_sharpe,
          ROUND(100.0 * COUNT(ic_sharpe_hac) / COUNT(*), 1) AS pct_with_sharpe
        FROM feature_ic_scores
        WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
        GROUP BY tf ORDER BY tf;
      "
      Expected: 1d pct_with_sharpe ~0-5%; 5m/15m/1h should be substantially higher.
      Capture output.

    Step 3 — Top-30 features by |ic_sharpe_hac| (cross-sectional, all regimes):
      Follow Step 7.1 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.
      Capture output.

    Step 4 — Per-TF IC breakdown:
      Follow Step 7.2 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.
      Capture output.

    Step 5 — Per-regime IC breakdown:
      Follow Step 7.3 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.
      Capture output. Confirm all 9 cross-sectional regime labels appear.
      If fewer than 9 regimes appear: note which regimes are absent (may indicate regime
      imbalance from V1 fix; not an error, but record it).

    Step 6 — Demotion candidates (zero-IC features):
      Follow Step 7.4 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.
      Capture output.

    Step 7 — V2 cost calibration constants:
      Follow Step 7.5 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.
      Ensure WHERE clause includes: fr.return_type = 'executable_open_to_open'
      Capture output.

    Step 8 — Gate assessment (PASS/FAIL computation — GLOBAL, not per-cell):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf,
          COUNT(*) FILTER (WHERE ABS(ic_sharpe_hac) > 0.5 AND ic_ci_lower > 0) AS gate_pass_features
        FROM feature_ic_scores
        WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
          AND tf IN ('5m', '1h')
        GROUP BY tf
        ORDER BY tf;
      "
      PASS criterion: ≥5 features total (across all regimes combined) with |ic_sharpe_hac|>0.5
      AND ic_ci_lower>0 in 5m; AND ≥5 features total in 1h. Minority regimes with zero
      qualifying features are noted in the report but do NOT block PASS — sparse regimes with
      <3000 independent obs are expected to fail per CORPUS-06.

      Also capture the per-(tf, regime) breakdown for the report's informational matrix
      (this does NOT gate — it documents which regimes are sparse):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf, regime,
          COUNT(*) FILTER (WHERE ABS(ic_sharpe_hac) > 0.5 AND ic_ci_lower > 0) AS qualifying_features
        FROM feature_ic_scores
        WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
          AND tf IN ('5m', '1h')
        GROUP BY tf, regime ORDER BY tf, regime;
      "
      Record specific counts.
  </action>
  <acceptance_criteria>
    - all 7 query outputs captured
    - NULL rate by TF recorded
    - global gate_pass_features computed per TF for 5m and 1h
    - informational per-(tf, regime) qualifying-features matrix captured
  </acceptance_criteria>
  <output_gate>All 7 query outputs captured; NULL rate by TF recorded; global gate_pass_features per TF (5m, 1h) computed; informational per-regime matrix captured</output_gate>
</task>

<task id="P1-T1-5" type="execute">
  <title>CORPUS-02 + CORPUS-03 — OOS Holdout Split + Null Model Baseline</title>
  <wave>2</wave>
  <read_first>
    - services/ensemble_trainer.py — how IC-weighted ensemble weights are applied to features (weight schema)
    - services/ic_engine.py — IC Sharpe computation (replicate the metric for the OOS window)
    - production/migrations/182_equity_regime_model_apr.sql — alpha.validation.oos_start key created in P0-T0
  </read_first>
  <action>
    Establish the OOS boundary and compute the null-model baseline. This is a one-shot script.

    Step 1 — Compute OOS start = MAX(bar_ts) minus 6 months:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "
        SELECT to_char((MAX(bar_ts) - INTERVAL '6 months') AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')
        FROM feature_vectors;
      "
      Capture the timestamp as OOS_START.

    Step 2 — Write OOS_START to config_state (CORPUS-02):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        UPDATE config_state
        SET config_value = '<OOS_START>', version = version + 1, updated_at = now()
        WHERE config_key = 'alpha.validation.oos_start';
      "
      Also record the change in config_history with changed_by='corpus_02_oos_split' and
      reason='Phase 141 CORPUS-02: OOS holdout = most recent 6 months of feature_vectors'.
      Verify: SELECT config_value FROM config_state WHERE config_key='alpha.validation.oos_start'
      returns the ISO8601 timestamp.

    Step 3 — Compute equal-weight NULL model IC Sharpe on the OOS window:
      All features weighted 1/N. For each bar in the OOS window (bar_ts >= OOS_START), compute
      the equal-weight composite score, then the IC of that composite vs forward_returns
      (return_type = 'executable_open_to_open' — enforce explicitly). Aggregate to IC Sharpe
      (HAC/Newey-West, same method as ic_engine). Call this null_ic_sharpe.

    Step 4 — Compute IC-weighted ensemble IC Sharpe on the OOS window (no leakage):
      Apply the IN-SAMPLE ensemble_weights (trained on data BEFORE OOS_START) to the OOS bars.
      Critical: weights are frozen from in-sample; they are NOT recomputed on OOS data. Compute
      the weighted composite score per OOS bar, then its IC vs executable_open_to_open forward
      returns, aggregate to IC Sharpe. Call this weighted_ic_sharpe.

    Step 5 — Gate (CORPUS-03):
      advantage = weighted_ic_sharpe - null_ic_sharpe
      PASS if advantage > 0.1. Record both values and the explicit PASS/FAIL.

    Step 6 — Persist results for the report (T2 reads these):
      Write null_ic_sharpe, weighted_ic_sharpe, advantage, OOS_START, and OOS bar count to a
      scratch JSON the report task reads, OR capture directly into the T2 report section.

    Step 7 — Commit (config_state change is DB-side; commit any script artifact):
      git add docs/analysis/ 2>/dev/null; git commit -m "feat(validation): CORPUS-02 OOS split + CORPUS-03 null-model baseline" --allow-empty
  </action>
  <acceptance_criteria>
    - config_state alpha.validation.oos_start contains an ISO8601 UTC timestamp = MAX(bar_ts) - 6 months
    - null_ic_sharpe (equal-weight) and weighted_ic_sharpe (IC-weighted, in-sample weights on OOS bars) both computed on the OOS window
    - both IC computations filter return_type = 'executable_open_to_open'
    - advantage = weighted - null computed with explicit PASS (advantage > 0.1) / FAIL
    - no leakage: OOS weights are frozen from in-sample, not re-fit on OOS
  </acceptance_criteria>
  <output_gate>alpha.validation.oos_start set to ISO8601 timestamp; null and IC-weighted OOS IC Sharpe computed; advantage vs >0.1 threshold recorded with PASS/FAIL</output_gate>
</task>

<task id="P1-T2" type="execute">
  <title>Write IC Validation Report</title>
  <wave>2</wave>
  <read_first>
    - docs/plans/2026-06-28-validity-fixes-and-phase-141.md — Step 7.6 report template
    - docs/analysis/corpus-01-feature-audit.md — CORPUS-01 results to cross-reference
  </read_first>
  <action>
    Write docs/analysis/ic-validation-report-58sym.md following the template at Step 7.6.

    Required sections (in order):
    1. Header with date, corpus description, IC score counts
    2. Executive Summary (2-3 sentences: which TFs have usable IC, top features, gate result)
    3. CORPUS-01 Feature Audit Summary — reference corpus-01-feature-audit.md; list BLOCKED
       (zero-variance) features here so they are visible in the IC report
    4. NULL Rate by TF — paste Step 2 output from T1; note 1d is expected near-zero
    5. Top Features by IC Sharpe (cross-sectional, all regimes) — paste Step 3 output
    6. IC by Timeframe — paste Step 4 output; include note "1d has insufficient data for IC Sharpe (< 5,040 bars vs 60,000 minimum). Do not use 1d IC Sharpe as a decision input."
    7. IC by Regime — paste Step 5 output; note any absent regime labels
    8. CORPUS-03 Null Model Comparison — from P1-T1.5: null_ic_sharpe (equal-weight) vs
       weighted_ic_sharpe (IC-weighted), the advantage, and explicit PASS/FAIL against the
       >0.1 threshold. State OOS_START and OOS bar count.
    9. Demotion Candidates (todo 015) — paste Step 6 output; note "Phase 141 identifies candidates; Phase 143 implements demotion"
    10. V2 Cost Calibration Constants — paste Step 7 output with explanation of ic_x_return_scale units
    11. Phase 141 Gate Assessment — paste Step 8 GLOBAL output; state PASS or FAIL explicitly:
        "Gate PASS: 5m: [N] features total |ic_sharpe_hac|>0.5 with ic_ci_lower>0 across all
         regimes (PASS: N≥5); 1h: [M] features total (PASS: M≥5)" or
        "Gate FAIL: 5m has only [N]<5 qualifying features total across all regimes"
        Include the informational per-(tf, regime) matrix from T1 Step 8 as a sub-table, with
        a note that minority/sparse regimes (per CORPUS-06) are expected to show zero and do
        not block PASS.
    12. Next Steps (Phase 142, V2, todo 015, todo 026 P1a as specified in planning doc)

    Commit:
      git add docs/analysis/ic-validation-report-58sym.md
      git commit -m "docs(analysis): Phase 141 IC validation report — 58-symbol V1-corrected corpus"
  </action>
  <acceptance_criteria>
    - docs/analysis/ic-validation-report-58sym.md exists and is committed
    - report contains all 12 sections including CORPUS-01 summary and CORPUS-03 null-model comparison
    - gate assessment uses the GLOBAL ≥5-features-per-TF criterion (not per-cell)
    - gate section explicitly states PASS or FAIL with specific feature counts for 5m and 1h
  </acceptance_criteria>
  <output_gate>ic-validation-report-58sym.md committed; all 12 sections present; gate assessment states PASS or FAIL via the global ≥5-features-per-TF criterion with specific counts</output_gate>
</task>

<task id="P1-T2b" type="execute">
  <title>CORPUS-06 — Per-Regime Observation Floor Check</title>
  <wave>2</wave>
  <read_first>
    - services/ic_engine.py — n_independent_obs / effective_N column in feature_ic_scores
    - production/migrations/182_equity_regime_model_apr.sql — alpha.ic.min_obs_per_regime=3000
    - docs/analysis/ic-validation-report-58sym.md — report to extend (written in P1-T2)
  </read_first>
  <action>
    After the T1 queries, count independent observations per (tf, regime) cell and flag cells
    below the alpha.ic.min_obs_per_regime=3000 floor.

    Step 1 — Read the floor from APR:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "
        SELECT config_value FROM config_state WHERE config_key='alpha.ic.min_obs_per_regime';
      "
      Expected: 3000.

    Step 2 — Count independent obs per (tf, regime) cell:
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf, regime,
          MAX(n_independent_obs) AS n_obs,
          (MAX(n_independent_obs) < 3000) AS below_floor
        FROM feature_ic_scores
        WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
        GROUP BY tf, regime
        ORDER BY tf, regime;
      "
      (Use the actual independent-obs column name from ic_engine.py — confirm in read_first.)

    Step 3 — Append a CORPUS-06 section to docs/analysis/ic-validation-report-58sym.md listing
      every (tf, regime) cell below 3000 independent obs explicitly. State the floor (3000) and
      note these cells are excluded from BH-FDR gating and ensemble weighting and are the
      expected source of zero-qualifying-feature regimes in the gate matrix (cross-reference
      the gate section).

    Step 4 — Commit:
      git add docs/analysis/ic-validation-report-58sym.md
      git commit -m "docs(analysis): CORPUS-06 per-regime observation floor (min 3000 obs)"
  </action>
  <acceptance_criteria>
    - report contains a CORPUS-06 section listing every (tf, regime) cell below 3000 independent obs
    - the floor value (3000, from alpha.ic.min_obs_per_regime) is stated
    - section cross-references the gate matrix sparse-regime note
    - committed
  </acceptance_criteria>
  <output_gate>CORPUS-06 section appended to ic-validation-report-58sym.md; (tf, regime) cells below 3000 independent obs listed explicitly with the floor value stated; committed</output_gate>
</task>

<task id="P1-T3" type="execute">
  <title>CORPUS-07 — I7→Feature Dimension Mapping</title>
  <wave>3</wave>
  <read_first>
    - src/intelligence/register_plugins.py — TIER_I7 list (active I7 plugins to map)
    - services/feature_factory.py — feature_vectors column names (the target dimensions)
    - docs/intelligence/intelligence-alphaengine.md — feature taxonomy reference
  </read_first>
  <action>
    For each active I7 plugin in the TIER_I7 list, document which feature_vectors columns encode
    the same information.

    Step 1 — Enumerate active I7 plugins from src/intelligence/register_plugins.py TIER_I7.

    Step 2 — For each plugin, identify the feature_vectors columns that encode its constituent
      signal(s). Examples: a momentum-divergence plugin → momentum_z_fast, momentum_z_mid; a
      volume-spike plugin → volume_rank_z.

    Step 3 — Assign mapping_confidence:
      - "high": 1-3 features cleanly encode the plugin signal
      - "medium": features approximate the plugin signal with some loss
      - "ambiguous": >5 features OR cross-cutting logic with no clean feature subset →
        flag as a "direct IC measurement candidate" (the plugin should be measured directly,
        not via constituent features)

    Step 4 — Write docs/analysis/i7-feature-mapping.json:
      {
        "<plugin_name>": {
          "constituent_features": ["momentum_z_fast", "volume_rank_z"],
          "mapping_confidence": "high|medium|ambiguous",
          "ambiguous_reason": "<reason if ambiguous, else empty string>"
        },
        ...
      }
      Include an entry for EVERY active TIER_I7 plugin.

    Step 5 — Commit:
      git add docs/analysis/i7-feature-mapping.json
      git commit -m "docs(analysis): CORPUS-07 I7-to-feature dimension mapping"
  </action>
  <acceptance_criteria>
    - docs/analysis/i7-feature-mapping.json exists
    - every active TIER_I7 plugin has an entry with constituent_features, mapping_confidence, ambiguous_reason
    - plugins with >5 features or cross-cutting logic are flagged ambiguous (direct IC measurement candidate)
    - committed
  </acceptance_criteria>
  <output_gate>i7-feature-mapping.json committed with an entry for every active TIER_I7 plugin; ambiguous mappings flagged as direct-IC-measurement candidates</output_gate>
</task>

</tasks>
</output>
