---
created: 2026-03-24T10:57:11.838Z
updated: 2026-03-28T00:00:00.000Z
title: Signal quality and pipeline integrity audit
area: intelligence
priority: 5
tier: immediate
files:
  - services/signal_generator_agent.py
  - src/intelligence/pipeline/regime_gate.py
  - src/intelligence/trading/signal_ledger.py
  - src/intelligence/trading/confidence_utils.py
  - src/intelligence/trading/aggregator.py
---

## Problem

Comprehensive signal quality and pipeline integrity issues discovered during investigation:

**I6 Confluence Integration Bug (FIXED in commit 8d9ca3e)**:
- `signal_ledger.confluence_score` was always 0.0 despite I6 computing valid `ctf_score`
- Root cause: Signal generator not extracting I6 data from `frames["features"]["ctf_score"]`
- Impact: I7 plugins not using I6 confluence for confidence weighting (Renaissance violation)

**High-Confidence Signal Rejection Pattern**:
- Top 1% confidence signals (0.43–0.81) showing only 9% selection rate
- Middle confidence (0.07–0.23) showing 25–40% selection rate
- This is backwards — highest confidence should have HIGHEST selection rate
- Possible causes: aggregator `adjusted_rank` calculation bug, TOD multiplier misapplied, performance weight issues

**ML Training Data Gaps**:
- `cis_score` column: NULL for all 11,163 recent signals
- `bucket_scores` column: NULL for all 11,163 recent signals
- `signal_features` table: doesn't exist (planned but never created)
- Shadow dict (`_shadow`) capture status unknown in I7 plugins
- Violates Renaissance: "Never drop data that could contain signal"

**Regime Suppression Aggressiveness**:
- `regime_suppressed` signals: 4,049 with avg confidence 0.168
- May be too aggressive around regime transitions (user wants to loosen)
- Existing todo #001 covers regime gate Renaissance violation
- Need to verify suppression logic matches design intent

**Performance Metrics Validation Needed**:
- `setup_performance` table freshness unknown
- Sample sizes per setup (min 30 for `perf_multiplier` activation)
- Win rate / avg_pnl_r distribution by setup
- Calibration effectiveness (isotonic regression)

## Solution

Comprehensive audit across 6 areas:

### 1. Confluence Integration Validation
- Verify `signal_ledger.confluence_score` now non-zero (fix deployed)
- Check I6 CTF sub-scores flowing (ctf_trend_alignment, ctf_regime_agreement, ctf_fvg_alignment, ctf_ob_alignment)
- Confirm aggregator using confluence in `adjusted_rank` calculation
- Validate I7 plugins consuming I6 data per Renaissance principle

### 2. Signal Quality Assessment
- Confidence distribution analysis (should be bell-shaped, not inverted)
- Selection rate by confidence decile (top decile should have HIGHEST selection rate)
- Confluence vs confidence correlation (higher confluence → higher selection)
- Plugin performance analysis (which plugins over/under-performing)

### 3. Regime Suppression Analysis
- Suppression rate by plugin type (trend vs mean_reversion vs any)
- Suppression patterns around regime transitions (hmm_regime_duration < 5 bars)
- Verify regime_gate logic matches design intent (loosen around shifts?)
- Check for false positives (valid signals suppressed incorrectly)

### 4. ML Training Data Gaps
- Investigate `cis_score` and `bucket_scores` population status
- Audit shadow dict capture in I7 plugins (should have 15 keys per confidence_utils doc)
- Determine if `signal_features` table needs creation
- Assess XGBoost training readiness (30+ days clean signal data requirement)

### 5. Performance Metrics Validation
- Check `setup_performance` table last refresh time
- Verify sample sizes per setup (min 30 threshold)
- Analyze win rate / avg_pnl_r distribution
- Test calibration effectiveness (isotonic regression)

### 6. High-Confidence Rejection Investigation
- Sample top 1% confidence signals — trace why rejected
- Deep dive into `adjusted_rank` calculation (confluence weight + TOD + perf)
- Verify `composite_rank` scoring logic in aggregator
- Search for bugs in winner selection algorithm

**Deliverables**:
- AUDIT_REPORT.md with findings, severity ratings, fix priorities
- SQL queries for ongoing monitoring
- Code fixes for bugs discovered
- Updated CLAUDE.md if patterns found

**Priority**: High — blocks v2.3 ML work and signal reliability
**Estimated effort**: 2-3 hours for full audit + fixes

## Related

- Todo #001: Regime gate violates Renaissance signal data collection
- Commit 8d9ca3e: I6 confluence_score fix (deployed, needs validation)
- Phase 49.1: ML training data infrastructure
