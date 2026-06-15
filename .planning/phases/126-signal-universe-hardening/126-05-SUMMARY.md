---
phase: "126"
plan: "05"
subsystem: "signal-universe"
tags: ["signal-quality", "ic-audit", "bootstrap-ci", "shadow-only", "detection-verifiability", "anti-signal"]
dependency_graph:
  requires: ["126-02"]
  provides: ["ic-league-table", "detection-verifiability", "anti-signal-demotions"]
  affects: ["signal_ledger", "intelligence_features", "shadow_registry"]
tech_stack:
  added: []
  patterns:
    - "bootstrap 95% CI on hit_rate (10,000 resamples, numpy)"
    - "Pearson IC with two-sided t-stat (n-2 dof)"
    - "intelligence_features JSONB join for detection-condition verifiability"
    - "APR-backed audit thresholds (migration 135)"
key_files:
  created:
    - "production/scripts/signal_quality_audit.py"
    - "production/migrations/135_phase126_signal_audit.sql"
    - "docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md"
  modified:
    - "src/intelligence/trading/choch_reversal.py"
    - "src/intelligence/trading/fvg_fill.py"
    - "src/intelligence/trading/liquidity_sweep_reclaim.py"
    - "src/intelligence/trading/supply_demand_setup.py"
    - "src/intelligence/trading/trend_following.py"
decisions:
  - "All 12 corpus-qualified plugins (>=30 outcomes) are ANTI-SIGNAL - hit_rate CI upper peaks at 0.305 (CVDDivergence), far below the 0.45 floor; statistical validation must be re-run on Phase 127 clean replay data"
  - "Layer 2 (detection verifiability) produced zero rows - all 12 plugins are ANTI-SIGNAL and Layer 2 only runs for VALIDATED/NOISE CANDIDATE survivors; feature field mapping defined for future replay corpus"
  - "5 plugins received shadow_only=True field additions: CHoCHReversal, LiquiditySweepReclaim, SupplyDemandSetup, TrendFollowing (missing field), FVGFill (had comment only)"
  - "7 plugins were already shadow_only=True (pre-existing); IC audit independently confirms all 7 dispositions"
  - "Migration 135 seeds 6 APR keys: threshold.signal_audit.* (ic_validated_floor, ic_anti_signal_ceiling, hit_rate floors, verifiability floors)"
metrics:
  duration_minutes: 75
  completed_date: "2026-06-15"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 8
  tests_added: 0
---

# Phase 126 Plan 05: Signal Quality Audit - IC League Table + Detection Verifiability Summary

Two-layer signal quality audit: statistical IC validation (Layer 1) and detection-condition verifiability (Layer 2) for all I7 plugins with >= 30 corpus outcomes; 5 ANTI-SIGNAL plugins demoted to shadow_only=True with documented rationale.

## What Was Built

### Task 1 & 2: signal_quality_audit.py - Two-Layer Audit Script

Created `production/scripts/signal_quality_audit.py` implementing both audit layers in a single runnable script:

**Layer 1 - Statistical IC table:**
- Queries signal_ledger JOIN signal_outcomes for plugins with >= 30 non-null pnl_r outcomes
- Computes: hit_rate, IC = Pearson corr(raw_confidence, pnl_r), bootstrap 95% CI on hit_rate (10,000 resamples, numpy), IC t-stat (n-2 dof), avg_pnl_r, equity/forex segment breakdown
- Reads D-13 thresholds from APR (threshold.signal_audit.* keys)
- Assigns VALIDATED / NOISE CANDIDATE / ANTI-SIGNAL per D-13 verdict logic

**Layer 2 - Detection verifiability:**
- Samples 50 signals per VALIDATED/NOISE CANDIDATE plugin, joins to intelligence_features
- Checks primary detection-condition field presence across all JSONB columns (technical_indicators, pattern_detections, smc, etc.)
- Computes fields_populated_rate, assigns VERIFIABLE / PARTIAL / UNVERIFIABLE per APR thresholds
- `_PLUGIN_DETECTION_FIELDS` dict maps 12 plugins to their primary detection-condition fields

**Migration 135:** Seeds 6 APR keys for audit thresholds:
- `threshold.signal_audit.ic_validated_floor` = 0.02
- `threshold.signal_audit.ic_anti_signal_ceiling` = -0.02
- `threshold.signal_audit.hit_rate_validated_floor` = 0.45
- `threshold.signal_audit.hit_rate_anti_signal_ceiling` = 0.45
- `threshold.signal_audit.verifiable_population_floor` = 0.90
- `threshold.signal_audit.partial_population_floor` = 0.50

**Usage:** `--layer 1`, `--layer 2`, `--layer all` (default). Exits 0 on success.

### Task 3: Audit Results + shadow_only Demotions

**Audit findings (Layer 1):**

All 12 corpus-qualified plugins are ANTI-SIGNAL. Hit rates range from 0.09 to 0.30 - none approaching the 0.45 floor. This is a corpus-contamination finding: the existing signal_ledger was generated before Phase 126 Root Crime fixes. Key stats:

| Plugin | N | IC | CI upper | Verdict |
|--------|---|----|----------|---------|
| trad_CVDDivergence | 84,409 | -0.055 | 0.305 | ANTI-SIGNAL |
| trad_SupplyDemandSetup | 8,433 | -0.020 | 0.175 | ANTI-SIGNAL |
| trad_CHoCHReversal | 38,393 | -0.014 | 0.221 | ANTI-SIGNAL |
| trad_LiquiditySweepReclaim | 78,683 | -0.011 | 0.213 | ANTI-SIGNAL |
| trad_DivergenceStack | 149,873 | -0.011 | 0.222 | ANTI-SIGNAL |
| trad_GapAnalysisSetup | 147,238 | -0.001 | 0.154 | ANTI-SIGNAL |
| trad_OFIContinuation | 48,528 | -0.001 | 0.136 | ANTI-SIGNAL |
| trad_FVGFill | 37,664 | +0.001 | 0.126 | ANTI-SIGNAL |
| trad_AnchoredVWAPReversion | 84,932 | +0.004 | 0.093 | ANTI-SIGNAL |
| trad_PatternCompletion | 77,714 | +0.008 | 0.143 | ANTI-SIGNAL |
| trad_TrendFollowing | 2,393 | +0.023 | 0.250 | ANTI-SIGNAL |
| trad_SqueezeExpansion | 6,803 | +0.032 | 0.124 | ANTI-SIGNAL |

Layer 2 produced zero rows (all Layer 1 qualifiers are ANTI-SIGNAL; Layer 2 only audits VALIDATED/NOISE CANDIDATE survivors). The `_PLUGIN_DETECTION_FIELDS` mapping is defined and ready for the Phase 127 clean replay corpus.

**shadow_only dispositions applied:**
5 plugins added `shadow_only: bool = True` with rationale comment:
- `choch_reversal.py` - IC=-0.014, hit_rate CI upper=0.221
- `liquidity_sweep_reclaim.py` - IC=-0.011, hit_rate CI upper=0.213
- `supply_demand_setup.py` - IC=-0.020, hit_rate CI upper=0.175
- `trend_following.py` - IC=+0.023, hit_rate CI upper=0.250 (below floor)
- `fvg_fill.py` - Wave 2 entry-timing defect + IC=+0.001, hit_rate CI upper=0.126

7 plugins were already shadow_only=True (pre-existing); audit independently confirms all 7.

**D-12 enforced:** No plugin removed from TIER_I7. All 36 non-aggregator I7 plugins remain in the list.

## Deviations from Plan

None - plan executed as written.

## Commits

| Hash | Description |
|------|-------------|
| e4cd3fd1 | feat(126-05): add signal_quality_audit.py with two-layer IC + verifiability audit |
| dacaf5e9 | feat(126-05): apply shadow_only demotions + produce IC audit results doc |

## Self-Check: PASSED
