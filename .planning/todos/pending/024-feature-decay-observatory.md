# 024 — Feature Decay Observatory (Superset Dashboard)

**Priority:** Low — pure read layer; research quality-of-life.
**Prerequisite:** 009 (Feature Vector Lifecycle) demotion logic must be wired first so
`is_decaying` and `feature_ic_stats` have meaningful time-series data.

## What

A Superset dashboard over `feature_ic_stats` and `feature_ic_scores` that answers two
permanent research questions: "Which features are losing IC, and which are crowding?"
No new computation — pure visualization of existing data.

## Why

Without a visual layer, detecting feature decay requires ad-hoc SQL queries. At 54+ features
across 4 TFs and multiple regimes, the combinatorial space is too large to monitor manually.
Silent decay is a compounding risk — a feature that lost its edge 6 months ago still dilutes
the ensemble if 009's demotion logic never fires.

## Scope

### Charts

1. **IC Sharpe heatmap** — feature × regime × TF; cell color = current rolling IC Sharpe;
   red = below decay threshold; green = passing; grey = insufficient data
2. **IC trend lines** — per-feature time series of rolling IC Sharpe (30d window);
   one panel per TF; togglable by regime
3. **Decay event log** — table of `is_decaying=true` transitions from `feature_ic_stats`
   with `decay_detected_at`, `recovery_eligible_at`, current status
4. **Correlation crowding** — scatter of pairwise |correlation| vs IC Sharpe delta;
   features in the top-right quadrant (high correlation, IC declining) are crowding candidates
5. **Feature active count** — time series of `feature_active_count` / `feature_decaying_count`
   metrics (from 009's OTel metrics); shows fleet health over time

### Filters

- Regime (bull/bear/sideways/volatile/neutral)
- Timeframe (5m/15m/1h/1d)
- Feature name (multi-select)
- Date range

## Files

| Artifact | Notes |
|----------|-------|
| Superset dashboard JSON | Export and commit to `production/superset/` |
| SQL queries | Commit as named datasets in Superset; also save to `docs/analysis/feature-decay-queries.sql` |

## Success Criteria

- Dashboard loads in < 3s for 12-month date range
- IC Sharpe heatmap correctly flags `is_decaying=true` features in red
- Correlation crowding scatter matches ad-hoc SQL verification for 3 spot-checked features
