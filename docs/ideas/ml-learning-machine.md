# MLAgent — Renaissance-Style Learning Machine

**Status:** design
**Priority:** high
**Milestone:** v1.8+
**Last Updated:** 2026-03-10

---

## Philosophy

This isn't a model — it's a **learning machine**. Three compounding layers:

```
Layer 1: Discovery         — what does the data actually say?
Layer 2: Scoring           — real-time signal quality prediction
Layer 3: Feedback Loop     — outcomes improve the next prediction
```

Each layer is independently valuable and ships incrementally. The system never stops learning — drift detection triggers retraining, shadow mode gates promotion, every outcome makes the next prediction better.

**Renaissance principles applied:**
- Segment relentlessly — per-regime × per-setup × per-TF sub-models beat a global model
- Shadow mode before production — no model acts on signals until p < 0.05
- Drift detection is non-negotiable — KS + CUSUM, auto-retrain on drift
- IC over accuracy — information coefficient per feature against outcomes, not just win rate
- Data quality gates model quality — fix CIS backfill and constituent_contributions first
- The feedback loop IS the edge — outcomes → retrain → better predictions → compounds

**What it replaces over time:** hand-tuned CIS weights → IC-derived weights → full ensemble. CIS doesn't die, it becomes the interpretable linear component of a two-stage filter.

**What it never does:** override risk management (AegisAgent), trade autonomously (TradeAgent). MLAgent is signal intelligence only.

---

## Architecture: MLAgent Microservice

Separate `ml_scoring_service` that fits the existing service pattern. Three internal subsystems: Discovery Engine (offline), Ensemble Trainer (offline), Scoring Service (online).

```
intelligence_features + signal_ledger outcomes
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ MLAgent Microservice                                │
│                                                     │
│  ┌──────────────────┐    ┌────────────────────────┐ │
│  │ Discovery Engine  │    │ Ensemble Trainer       │ │
│  │ (weekly offline)  │    │ (offline, on drift)    │ │
│  │                   │    │                        │ │
│  │ IC per feature    │    │ XGBoost/LightGBM       │ │
│  │ Regime-cond. IC   │───▶│ Segmented ensemble     │ │
│  │ Cross-asset lags  │    │ Shadow mode gate       │ │
│  │ feature_ic_scores │    │ p < 0.05 promotion     │ │
│  └──────────────────┘    └────────────────────────┘ │
│                                    │                 │
│                                    ▼                 │
│                         ┌─────────────────────┐     │
│                         │ Scoring Service      │     │
│                         │ (real-time online)   │     │
│                         │                      │     │
│                         │ reads signals:* SSE  │     │
│                         │ runs ensemble infer  │     │
│                         │ win_prob, pnl_r,     │     │
│                         │ confidence_band      │     │
│                         │ writes signal_ledger │     │
│                         └─────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

---

## Phasing

### Phase 1 — Discovery Engine + Adaptive CIS
*Buildable now — no large outcome volume required*

- Weekly offline job reads `intelligence_features` + `signal_ledger` outcomes
- Computes IC (information coefficient) per I1-I7 feature vs outcome (pnl_r, win/loss)
- Regime-conditional IC — which features predict outcomes in HMM regime 0/1/2 separately
- Cross-asset lagged correlations — does ES feature N bars ago predict NQ signal outcomes?
- **Output:** feature rankings → `feature_ic_scores` table
- **Adaptive CIS:** weights auto-updated from IC scores at service startup. CIS becomes a trained linear model, no hand-tuning. Updated weekly.

**Two-stage filter (replaces static CIS):**
```
Stage 1: Adaptive CIS (linear, fast, interpretable)
         — IC-derived weights, runs inline in signal_generator
         — gates obvious noise cheaply

Stage 2: ML Ensemble (non-linear, regime-conditional)  [Phase 2]
         — scores what passes Stage 1
         — win_prob, expected_pnl_r, confidence_band
```

### Phase 2 — Segmented Ensemble + Scoring Service
*Needs ~60-90 days outcome volume at 5m+ (likely already achievable via backfill replay)*

- Offline trainer: XGBoost/LightGBM
- Segmented: per HMM regime (0/1/2) × per setup-type × per timeframe
- Meta-model combines sub-model outputs
- **Shadow mode:** every new model predicts without acting, promoted only at p < 0.05
- **Drift detection:** KS test on feature distributions + CUSUM on model performance → triggers retraining
- `ml_scoring_service` systemd unit: reads `signals:*` stream, runs inference, writes scores back to `signal_ledger`
- **Rerunability:** `backfill_ml_scores(model_version, date_range)` — rescore any historical window; `intelligence_features` is source of truth

### Phase 3 — Dashboard + Autonomous Loop
*After Phase 2 proven in shadow mode*

- Dashboard panels: feature IC rankings, model calibration by regime/setup/TF, discovery reports as insight cards
- Drift detection → auto-retrain → shadow mode → auto-promote (no human required)
- CIS deprecated once ensemble dominates (or kept as interpretable sanity check)

---

## Data Architecture

### New Tables

```sql
-- Versioned model artifacts
ml_models (
  model_id        UUID PRIMARY KEY,
  version         TEXT,          -- e.g. "v1.0.0"
  segment         TEXT,          -- "regime_0:GapAnalysis:5m" or "global"
  status          TEXT,          -- "shadow" | "production" | "retired"
  trained_at      TIMESTAMPTZ,
  training_n      INT,           -- sample count
  p_value         FLOAT,         -- significance of win rate vs baseline
  win_rate        FLOAT,
  avg_pnl_r       FLOAT,
  artifact_path   TEXT           -- serialized model file path
)

-- Per-signal ML scores
ml_signal_scores (
  signal_id       UUID REFERENCES signal_ledger(signal_id),
  model_id        UUID REFERENCES ml_models(model_id),
  win_prob        FLOAT,         -- 0..1
  expected_pnl_r  FLOAT,
  confidence_band FLOAT,         -- width of 90% CI
  scored_at       TIMESTAMPTZ,
  PRIMARY KEY (signal_id, model_id)
)

-- IC per feature (drives adaptive CIS weights)
feature_ic_scores (
  feature_name    TEXT,
  regime          INT,           -- NULL = global, 0/1/2 = regime-specific
  ic              FLOAT,         -- information coefficient vs pnl_r
  n               INT,
  updated_at      TIMESTAMPTZ,
  PRIMARY KEY (feature_name, regime)
)

-- Weekly discovery run metadata
ml_discovery_runs (
  run_id          UUID PRIMARY KEY,
  ran_at          TIMESTAMPTZ,
  top_features    JSONB,         -- ranked by IC
  cross_asset     JSONB,         -- notable lagged correlations
  regime_findings JSONB,         -- regime-conditional insights
  summary_text    TEXT           -- LLM-generated human summary (optional)
)
```

### signal_ledger additions
```sql
ml_win_prob       FLOAT,         -- NULL until Phase 2 live
ml_expected_pnl_r FLOAT,
ml_model_version  TEXT
```

### Source of truth
`intelligence_features` hypertable — rerunability always re-reads features from here, never from cached state.

---

## Prerequisites (must ship before Phase 1)

1. **CIS backfill fix** — `aggregate()` must receive `features=` kwarg; NULL CIS poisons training data
2. **constituent_contributions** — which plugins drove the CIS score; required for IC analysis
3. **Signal replay verification** — confirm `pipeline_reset.py` generates signal_ledger rows with valid outcomes for historical bars

---

## Open Questions

- Does Phase 2 backfill replay generate enough labeled signals? Run `pipeline_reset.py` on 90-day window and count `signal_ledger` rows with non-null outcomes.
- Model artifact storage: filesystem path (simple) vs TimescaleDB blob (queryable)? Filesystem + path reference in `ml_models` is simplest.
- IC analysis library: `scipy.stats.pearsonr` sufficient for Phase 1, or use `sklearn` from the start?
- CIS weight update cadence: weekly with discovery run, or continuous via lightweight online learning?
- Cross-asset correlation: symmetric (ES↔NQ) or directional with lag (ES at t-2 → NQ at t)?

---

## Related

- `docs/ideas/renaissance-gap-analysis.md` — T1 signal quality items are feature engineering for Phase 1
- `docs/ideas/renaissance-i7-i8-refinement.md` — 105 ideas, many feed as features into the ensemble
- `docs/ideas/i6-confluence-expansion.md` — cross-asset features feed directly into IC analysis
- `docs/ideas/renaissance-framing.md` — philosophical framing
- `docs/plans/2026-03-07-i7-i8-renaissance-refinement-design.md` — prior refinement design
