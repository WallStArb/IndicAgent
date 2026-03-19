# Signal Confidence Audit Trail & Automated Gate Optimization

**Status:** Design Spec
**Created:** 2026-03-19
**Author:** Claude + User
**Milestone:** v2.0 — Signal Integrity & ML Foundation

---

## Executive Summary

Add full observability to the signal confidence transformation pipeline and automate gate optimization using AI-powered analysis with shadow mode validation.

**Problem:** Signals are being suppressed to 0% confidence by multiple quality gates (Hurst, entropy, KS drift, TOD, isotonic calibration), but we cannot see which gate(s) crushed the signal or whether the suppression is statistically justified.

**Solution:** (1) Audit trail tracks every confidence transformation, (2) Counterfactual analysis measures opportunity cost of suppression, (3) AI analyzes gate effectiveness nightly, (4) Shadow mode validates changes before production deployment.

**Renaissance principles applied:**
- Never drop data — every suppressed signal is a labeled training sample
- Let the system run — automated analysis, no manual reviews
- Earn the right — statistical proof (p < 0.05, n ≥ 30) before any change
- Segment relentlessly — gates work differently in different regimes

---

## Problem Statement

### Current State

Users are seeing signals in the UX like:
```
SHORT  Pattern  14:43:05+5.3s
0% confidence
```

These 0% confidence signals exist because the signal pipeline applies multiple quality multipliers:
```
Plugin (0.85) → Hurst×Entropy (×0.12) → Drift penalty (×0.70) → TOD (×0.80) → Calibration (→0.0)
```

**We cannot see:**
1. Which gate(s) suppressed the signal
2. Why each gate applied its multiplier
3. Whether the suppression was correct (would the signal have won if allowed?)
4. Which gates are suppressing winners vs filtering losers

### Impact

- **UX confusion:** Users see 0% signals with no explanation
- **Blind spots:** We don't know if gates are working or broken
- **Missed opportunities:** Suppressing winning signals without knowing it
- **No feedback loop:** Gate thresholds are static, never validated

---

## Proposed Solution

### Component 1: Confidence Audit Trail

Track every confidence transformation with full diagnostic information.

**Data structure** (`confidence_audit` JSONB column in `signal_ledger`):

```json
{
  "initial_confidence": 0.85,
  "final_confidence": 0.0,
  "suppressed": true,
  "transformations": [
    {
      "gate": "hurst_entropy_quality",
      "before": 0.85,
      "after": 0.102,
      "multiplier": 0.12,
      "inputs": {"hurst_trend_quality": 0.12, "entropy_quality": 0.85},
      "reason": "min(0.12, 0.85) = 0.12"
    },
    {
      "gate": "ks_drift_penalty",
      "before": 0.102,
      "after": 0.071,
      "multiplier": 0.70,
      "inputs": {"drift_severity": "critical", "ks_statistic": 0.42},
      "reason": "KS drift critical threshold"
    },
    {
      "gate": "tod_multiplier",
      "before": 0.071,
      "after": 0.057,
      "multiplier": 0.80,
      "inputs": {"regime": "trend", "timeframe": "1m", "hour_et": 14},
      "reason": "TOD cell (trend,1m,14) = 0.8"
    },
    {
      "gate": "isotonic_calibration",
      "before": 0.057,
      "after": 0.0,
      "multiplier": null,
      "inputs": {"plugin": "trad_MeanReversion", "timeframe": "1m", "raw": 0.057},
      "reason": "calibrated_below_threshold",
      "curve_points": [[0.0, 0.0], [0.1, 0.02], [0.057, 0.0]]
    }
  ]
}
```

### Component 2: Counterfactual Analysis

Track what would have happened if suppressed signals were allowed to run.

**New table** `signal_counterfactuals`:

```sql
CREATE TABLE signal_counterfactuals (
    signal_id UUID PRIMARY KEY REFERENCES signal_ledger(signal_id),
    counterfactual_confidence FLOAT NOT NULL,
    gates_skipped TEXT[] NOT NULL,
    would_have_activated BOOLEAN,
    projected_mfe FLOAT,
    projected_mae FLOAT,
    actual_outcome TEXT,
    counterfactual_outcome TEXT,
    opportunity_cost_r FLOAT,
    gate_chain_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Nightly batch process** (`scripts/analyze_counterfactuals.py`):
1. Select all suppressed signals from yesterday
2. Replay market data to simulate outcome
3. Calculate opportunity cost (R missed)
4. Insert to `signal_counterfactuals`

### Component 3: AI-Powered Gate Optimization

Automated nightly analysis using LLM (OpenRouter free models → Ollama fallback).

**Process flow:**

```
Nightly (2am ET): Counterfactual analysis runs
         ↓
Nightly (3am ET): AI analyzes gate effectiveness
         ↓
If significant finding (p < 0.05, n ≥ 30):
         ↓
Create shadow configuration (14-day validation)
         ↓
After 14 days: Statistical comparison
         ↓
If shadow outperforms production (p < 0.05):
    Deploy to production (30-day monitoring)
Else:
    Reject, log rationale
```

**LLM system prompt** (`GATE_ANALYST_SYSTEM`):

```
You are a quantitative trading systems analyst at Renaissance Capital.
You analyze signal gate effectiveness and recommend adjustments.

RENAISSANCE PRINCIPLES:
1. Never drop data — every suppressed signal is a labeled training sample
2. Let the system run — trust statistical evidence over intuition
3. Earn the right — no change without p < 0.05 significance, n ≥ 30
4. Segment relentlessly — gates work differently in different regimes

ANALYSIS FRAMEWORK:
For each gate, calculate:
- Suppression rate: % of signals suppressed
- Counterfactual win rate: Would suppressed signals have won?
- Opportunity cost: Avg R-missed
- Statistical significance: p-value vs 40% baseline

RECOMMENDATION CRITERIA:
- LOOSEN: counterfactual_win_rate > 40%, p < 0.05, n ≥ 30
- TIGHTEN: active_win_rate < 35%, p < 0.05, n ≥ 50
- KEEP: no statistical evidence

OUTPUT: JSON with gate_name, recommendation, new_threshold, rationale, evidence.
```

### Component 4: Shadow Mode Validation

Validate gate changes in parallel before production deployment.

**New table** `gate_shadow_configurations`:

```sql
CREATE TABLE gate_shadow_configurations (
    config_id SERIAL PRIMARY KEY,
    gate_name TEXT NOT NULL,
    production_thresholds JSONB NOT NULL,
    shadow_thresholds JSONB NOT NULL,
    proposed_by TEXT,
    llm_analysis JSONB,
    status TEXT,
    validation_start_date TIMESTAMPTZ,
    validation_end_date TIMESTAMPTZ,
    shadow_metrics JSONB,
    production_metrics JSONB,
    statistical_test JSONB,
    decision JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Shadow lane service** (`shadow_lane_service.py`):
- Subscribes to same `intelligence:SYMBOL:TF` streams
- Applies shadow thresholds instead of production
- Writes to `signal_shadow_ledger` (not shown to users)
- Runs alongside production for 14-day validation

---

## Architecture

### Data Flow

```
┌─────────────────┐
│  Plugin fires   │ confidence=0.85
└────────┬────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  aggregator._build_all_ranked()                             │
│  - Build confidence_audit dict                              │
│  - Track every transformation                               │
└────────┬────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  signal_generator_service                                   │
│  - Write signal_ledger (with confidence_audit)              │
│  - If suppressed (<5%): mark for counterfactual analysis    │
└────────┬────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  Nightly 2am: analyze_counterfactuals.py                    │
│  - Replay suppressed signals                                │
│  - Simulate outcomes                                        │
│  - Insert signal_counterfactuals                            │
└────────┬────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  Nightly 3am: auto_gate_optimizer.py                        │
│  - Load gate effectiveness report                           │
│  - Call LLM for analysis (OpenRouter → Ollama fallback)     │
│  - Create shadow configurations if significant              │
└────────┬────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  shadow_lane_service (continuous)                           │
│  - Run shadow lane in parallel                              │
│  - Validate after 14 days                                   │
│  - Auto-deploy if significant improvement                   │
└────────┬────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│  UX Signal Card                                             │
│  - Show confidence %                                         │
│  - Hover/click → Audit trail modal                          │
│  - Show "Would have hit T1 (+1.2R)" if counterfactual wins  │
└─────────────────────────────────────────────────────────────┘
```

### Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         Signal Pipeline                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────┐    ┌──────────────┐    ┌─────────────────────────┐ │
│  │ Plugins │───→│  Aggregator  │───→│  signal_ledger         │ │
│  │         │    │              │    │  + confidence_audit    │ │
│  └─────────┘    └──────────────┘    └─────────────────────────┘ │
│                                              ↓                   │
│                              ┌──────────────────────────────────┤
│                              │     Nightly Batch Jobs          │
│                              ├──────────────────────────────────┤
│                              │ 1. analyze_counterfactuals.py   │
│                              │    (2am ET)                     │
│                              │    - Replay suppressed          │
│                              │    - Simulate outcomes          │
│                              │    - Insert counterfactuals     │
│                              │                                │
│                              │ 2. auto_gate_optimizer.py      │
│                              │    (3am ET)                     │
│                              │    - LLM analysis               │
│                              │    - Create shadows             │
│                              │    - Validate & deploy          │
│                              └──────────────────────────────────┘
│                                              ↓                   │
│                              ┌──────────────────────────────────┐
│                              │  Shadow Lane Service            │
│                              │  (parallel to production)       │
│                              │  - Tests gate changes           │
│                              │  - Validates for 14 days        │
│                              └──────────────────────────────────┘
│                                              ↓                   │
│                              ┌──────────────────────────────────┐
│                              │  Dashboard / UX                 │
│                              │  - Audit trail on hover          │
│                              │  - Counterfactual outcomes       │
│                              │  - Gate effectiveness reports    │
│                              └──────────────────────────────────┘
└──────────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase A: Confidence Audit Trail (1-2 days)

**Tasks:**

1. **Add `confidence_audit` field to `LedgerEntry`**
   ```python
   # src/intelligence/trading/signal_ledger.py
   @dataclass
   class LedgerEntry:
       # ... existing fields ...
       confidence_audit: dict | None = None
   ```

2. **Build audit dict in `_build_all_ranked()`**
   ```python
   # src/intelligence/trading/aggregator.py
   def _build_all_ranked(fired, ...) -> list[dict]:
       # Existing logic...
       for sig in with_ranks:
           audit = {"initial_confidence": initial, "transformations": []}
           # Track each transformation...
           sig["confidence_audit"] = audit
   ```

3. **Database migration**
   ```sql
   ALTER TABLE signal_ledger ADD COLUMN confidence_audit jsonb;
   CREATE INDEX ON signal_ledger USING GIN (confidence_audit);
   ```

4. **Update `insert_signals_with_features()`** to include `confidence_audit`

5. **UX: Add hover modal** for audit trail display

**Success criteria:**
- Every signal has `confidence_audit` populated
- UX shows audit trail on hover
- Can trace why any signal is 0%

---

### Phase B: Counterfactual Analysis (2-3 days)

**Tasks:**

1. **Create `signal_counterfactuals` table**
   ```sql
   CREATE TABLE signal_counterfactuals (
       signal_id UUID PRIMARY KEY REFERENCES signal_ledger(signal_id),
       counterfactual_confidence FLOAT NOT NULL,
       gates_skipped TEXT[] NOT NULL,
       would_have_activated BOOLEAN,
       projected_mfe FLOAT,
       projected_mae FLOAT,
       actual_outcome TEXT,
       counterfactual_outcome TEXT,
       opportunity_cost_r FLOAT,
       gate_chain_json JSONB,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );
   ```

2. **Create `scripts/analyze_counterfactuals.py`**
   - Select suppressed signals from yesterday
   - Replay market data (use `intelligence_features` for OHLCV)
   - Check if entry zone would be touched
   - Simulate MFE/MAE if activated
   - Calculate opportunity cost
   - Insert to `signal_counterfactuals`

3. **Add cron job**
   ```bash
   # /etc/cron.d/indicagent
   0 2 * * * indicagent cd /home/bg/dev/indicagent && .venv/bin/python scripts/analyze_counterfactuals.py
   ```

4. **UX: Show counterfactual outcomes** on suppressed signals
   - "Would have hit T1 (+1.2R)" if counterfactual won
   - "Would have stopped at entry (-0.5R)" if lost

**Success criteria:**
- All suppressed signals have counterfactual outcomes tracked
- Can query: "Which gates are suppressing the most winners?"
- Opportunity cost quantified per gate

---

### Phase C: AI Gate Optimization (2-3 days)

**Tasks:**

1. **Create `scripts/auto_gate_optimizer.py`**
   - Load gate effectiveness report (from counterfactuals)
   - Call LLM with analysis prompt
   - Parse recommendations
   - Create shadow configurations for significant findings

2. **Create `GATE_ANALYST_SYSTEM` prompt** in `src/ai/prompts.py`

3. **Add LLM client integration** (reuse `llm_providers.py` chain)

4. **Create `gate_shadow_configurations` table**
   ```sql
   CREATE TABLE gate_shadow_configurations (
       config_id SERIAL PRIMARY KEY,
       gate_name TEXT NOT NULL,
       production_thresholds JSONB NOT NULL,
       shadow_thresholds JSONB NOT NULL,
       proposed_by TEXT,
       llm_analysis JSONB,
       status TEXT,
       validation_start_date TIMESTAMPTZ,
       validation_end_date TIMESTAMPTZ,
       shadow_metrics JSONB,
       production_metrics JSONB,
       statistical_test JSONB,
       decision JSONB,
       created_at TIMESTAMPTZ DEFAULT NOW()
   );
   ```

5. **Add cron job**
   ```bash
   0 3 * * * indicagent cd /home/bg/dev/indicagent && .venv/bin/python scripts/auto_gate_optimizer.py
   ```

**Success criteria:**
- LLM generates recommendations nightly
- Significant findings (p < 0.05) create shadow configs
- Can track: "How many gates are being tested?"

---

### Phase D: Shadow Mode Service (2-3 days)

**Tasks:**

1. **Create `shadow_lane_service.py`**
   - Subscribe to `intelligence:SYMBOL:TF` streams
   - Apply shadow thresholds from `gate_shadow_configurations`
   - Write to `signal_shadow_ledger` table
   - Track shadow lane metrics

2. **Create `signal_shadow_ledger` table**
   ```sql
   CREATE TABLE signal_shadow_ledger (
       -- Same schema as signal_ledger
       -- Plus: shadow_config_id INTEGER REFERENCES gate_shadow_configurations(config_id)
   );
   ```

3. **Add validation logic** to `auto_gate_optimizer.py`
   - After 14 days, compare shadow vs production
   - Statistical test (t-test for proportions)
   - Deploy if significant improvement, reject otherwise

4. **Add rollback monitoring**
   - 30-day monitoring after deploy
   - Auto-rollback if degrades > 3%

5. **Systemd service**
   ```bash
   sudo systemctl enable indicagent-shadow-lane
   ```

**Success criteria:**
- Shadow lane runs in parallel
- Gate changes validated before production
- Automatic rollback if degrades

---

### Phase E: Dashboard & Reporting (1-2 days)

**Tasks:**

1. **Add gate effectiveness report** to dashboard
   - Show: suppression rate, counterfactual win rate, opportunity cost
   - Per gate, per regime, per timeframe

2. **Add active shadow configurations** view
   - Show: gate being tested, days remaining, preliminary results

3. **Add gate change history** view
   - Show: all changes, rationale, outcomes

4. **Alerts**
   - Slack/email on significant gate deployments
   - Alerts on rollback events

**Success criteria:**
- Full visibility into gate optimization loop
- Can audit every automatic change

---

## Success Criteria

### Technical

- [ ] Every signal has complete `confidence_audit` trail
- [ ] Counterfactual analysis runs nightly without errors
- [ ] AI generates at least 1 recommendation/week (when data warrants)
- [ ] Shadow lane runs with < 5% performance overhead
- [ ] Gate changes deployed only after statistical validation (p < 0.05)
- [ ] Rollback triggers work correctly

### Business

- [ ] Can answer: "Why is this signal 0%?" (audit trail)
- [ ] Can answer: "Which gates are suppressing winners?" (counterfactuals)
- [ ] Can answer: "What is the opportunity cost of gate X?" (opportunity_cost_r)
- [ ] Gate thresholds improve over time (measured by win rate lift)
- [ ] Zero manual intervention required (fully automated)

### Renaissance Principles

- [ ] **Never drop data**: Every suppressed signal tracked, analyzed
- [ ] **Let the system run**: Fully automated, no manual reviews
- [ ] **Earn the right**: Statistical proof before every change
- [ ] **Segment relentlessly**: Regime-specific gate recommendations

---

## Open Questions

1. **Counterfactual simulation approach** — Should we use full trade simulation (stops, targets) or simplified MFE/MAE? Simplified is easier but less accurate. **Recommendation:** Start with MFE/MAE, upgrade to full simulation if needed.

2. **Shadow lane scope** — Run shadow for ALL signals or only affected symbols/timeframes? Running for all is simpler but more compute. **Recommendation:** Run for all, overhead is negligible.

3. **Gate change granularity** — Should AI recommend regime-specific changes (e.g., "Hurst threshold = 0.3 in ranging, 0.15 in trending")? More complex but more accurate. **Recommendation:** Start with global thresholds, add regime segmentation if LLM recommends it.

4. **LLM provider priority** — OpenRouter free models first, Ollama fallback? Or Ollama first for privacy? **Recommendation:** OpenRouter first (better models), Ollama fallback (reliability).

5. **Alert thresholds** — When should we alert humans? On every deploy? Only on rollbacks? **Recommendation:** Alert on all deployments and rollbacks, silent for shadow config creation.

---

## Dependencies

**Blocking:**
- None (can start immediately)

**Requires coordination:**
- Database migrations (need DB access)
- Systemd service creation (need sudo)
- Cron job setup (need sudo)

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM generates bad recommendations | Deploy broken gates | Require statistical validation (p < 0.05) before deploy |
| Shadow lane has bugs | Bad data used for validation | Start shadow in read-only mode, validate outputs before trusting |
| Counterfactual simulation is wrong | Incorrect opportunity cost | Cross-check with live outcomes, tune simulation logic |
| Gate changes make things worse | System degrades | 30-day monitoring with auto-rollback |
| Too many shadow configs | Compute overhead | Limit max 3 active shadows per gate |

---

## Timeline

**Total: 10-13 days**

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| A: Audit Trail | 1-2 days | None |
| B: Counterfactual Analysis | 2-3 days | A |
| C: AI Gate Optimization | 2-3 days | B |
| D: Shadow Mode Service | 2-3 days | C |
| E: Dashboard & Reporting | 1-2 days | D |

**Suggested sequencing:** A → B → C → (D || E) (D and E can run in parallel)

---

## Next Steps

1. **Review this spec** — Confirm architecture, timeline, success criteria
2. **Invoke writing-plans skill** — Create detailed TDD implementation plan
3. **Execute Phase A** — Audit trail (quick win, immediate value)
4. **Evaluate after Phase B** — Check if counterfactual analysis is useful before committing to C/D/E

---

**Appendix: Sample LLM Analysis**

```json
{
  "gate": "hurst_entropy_quality",
  "current_threshold": {"hurst_min": 0.3, "entropy_min": 0.5},
  "recommendation": "LOOSEN",
  "new_threshold": {"hurst_min": 0.2, "entropy_min": 0.4},
  "rationale": "Gate is suppressing winners in trending regimes. Counterfactual win rate (44%) is significantly higher than baseline (40%, p=0.003). Regime analysis shows the gate works well in ranging markets (31% win rate) but is too aggressive in trending (52% win rate). Recommend: segment by HMM regime — apply current thresholds in ranging, relaxed thresholds in trending.",
  "evidence_stats": {
    "opportunity_cost_per_signal_r": 0.82,
    "total_missed_r": 280,
    "suppression_rate": 0.28,
    "counterfactual_win_rate": 0.44,
    "active_win_rate": 0.41,
    "p_value": 0.003,
    "sample_size": 342
  },
  "regime_breakdown": {
    "trending": {"suppressed_win_rate": 0.52, "n": 180, "recommendation": "LOOSEN"},
    "ranging": {"suppressed_win_rate": 0.31, "n": 162, "recommendation": "KEEP"}
  },
  "shadow_validation_plan": {
    "duration_days": 14,
    "success_criteria": "shadow_win_rate > production_win_rate by 5% (p < 0.05)",
    "rollback_trigger": "production_degrades_by > 3%"
  }
}
```
