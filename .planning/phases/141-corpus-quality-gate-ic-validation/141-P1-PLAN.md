---
plan: 141-P1
phase: "141"
title: "IC Validation Analysis"
wave: 1
depends_on: [141-P0]
files_modified:
  - docs/analysis/ic-validation-report-58sym.md
autonomous: true
must_haves:
  goal: "IC validation report written from V1-corrected corpus; gate assessment determines whether Phase 142 shadow mode proceeds"
  truths:
    - "docs/analysis/ic-validation-report-58sym.md exists and is committed"
    - "Report contains top-30 features ranked by |ic_sharpe_hac| from feature_ic_scores WHERE is_pooled=true AND symbol='POOLED' AND regime != '_pooled'"
    - "Report contains NULL-rate section: counts cells with ic_sharpe_hac IS NULL per TF — 1d absence is expected and documented"
    - "Report contains per-TF IC breakdown with cells_with_sharpe, pass_sharpe_05 (|ic_sharpe_hac|>0.5), ci_lower_positive counts"
    - "Report contains per-regime IC breakdown across all 9 cross-sectional labels ({low,mid,high}_{bull,neutral,bear})"
    - "Report contains demotion candidates: features with max_abs_ic=0 across all regimes (zero-IC features)"
    - "Report contains V2 cost calibration constants: ic_x_return_scale per (tf, regime)"
    - "Gate assessment explicitly states PASS or FAIL with exact counts: '5m: N features |ic_sharpe_hac|>0.5 with ic_ci_lower>0'"
    - "Criterion for PASS: ≥1 feature per (tf, regime) with |ic_sharpe_hac|>0.5 AND ic_ci_lower>0 across at least 5m and 1h TFs"
---

<objective>
Run the Phase 141 IC validation analysis on the V1-corrected corpus. Read existing
feature_ic_scores (cross-sectional rows), produce a ranked validation report, and
determine whether the Phase 141 gate passes.

No new services are written. This plan is query-only: read feature_ic_scores →
summarize → write report → gate assessment.

Key invariant: all queries filter WHERE return_type = 'executable_open_to_open'
at the forward_returns join level. The IC engine already enforces this; the V2
calibration constant query must enforce it explicitly.

Key invariant: 1d has almost no ic_sharpe_hac values (insufficient bars for the
60K subsampled-bar minimum). Do not report 1d IC Sharpe as a signal-bearing result
and do not let 1d NULL rate influence the gate assessment.
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

    Step 8 — Gate assessment (PASS/FAIL computation):
      PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
        SELECT tf, regime,
          COUNT(CASE WHEN ABS(ic_sharpe_hac) > 0.5 AND ic_ci_lower > 0 THEN 1 END) AS gate_pass_features
        FROM feature_ic_scores
        WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
          AND tf IN ('5m', '1h')
        GROUP BY tf, regime
        ORDER BY tf, regime;
      "
      PASS criterion: at least 1 feature per (tf, regime) with gate_pass_features >= 1 across
      both 5m and 1h. If ANY (tf, regime) cell has gate_pass_features = 0 for 5m or 1h: FAIL.
      Record specific counts.
  </action>
  <output_gate>All 7 query outputs captured; NULL rate by TF recorded; gate_pass_features matrix computed for 5m and 1h across all 9 regimes</output_gate>
</task>

<task id="P1-T2" type="execute">
  <title>Write IC Validation Report</title>
  <wave>2</wave>
  <read_first>
    - docs/plans/2026-06-28-validity-fixes-and-phase-141.md — Step 7.6 report template
  </read_first>
  <action>
    Write docs/analysis/ic-validation-report-58sym.md following the template at Step 7.6.

    Required sections (in order):
    1. Header with date, corpus description, IC score counts
    2. Executive Summary (2-3 sentences: which TFs have usable IC, top features, gate result)
    3. NULL Rate by TF — paste Step 2 output from T1; note 1d is expected near-zero
    4. Top Features by IC Sharpe (cross-sectional, all regimes) — paste Step 3 output
    5. IC by Timeframe — paste Step 4 output; include note "1d has insufficient data for IC Sharpe (< 5,040 bars vs 60,000 minimum). Do not use 1d IC Sharpe as a decision input."
    6. IC by Regime — paste Step 5 output; note any absent regime labels
    7. Demotion Candidates (todo 015) — paste Step 6 output; note "Phase 141 identifies candidates; Phase 143 implements demotion"
    8. V2 Cost Calibration Constants — paste Step 7 output with explanation of ic_x_return_scale units
    9. Phase 141 Gate Assessment — paste Step 8 output; state PASS or FAIL explicitly:
       "Gate PASS: [N] features across 5m and 1h with |ic_sharpe_hac|>0.5 and ic_ci_lower>0" or
       "Gate FAIL: [describe which (tf, regime) cells have zero qualifying features]"
    10. Next Steps (Phase 142, V2, todo 015, todo 026 P1a as specified in planning doc)

    Commit:
      git add docs/analysis/ic-validation-report-58sym.md
      git commit -m "docs(analysis): Phase 141 IC validation report — 58-symbol V1-corrected corpus"
  </action>
  <output_gate>docs/analysis/ic-validation-report-58sym.md exists and is committed; report contains all 10 sections; gate assessment section explicitly states PASS or FAIL with specific feature counts</output_gate>
</task>

</tasks>
