# Phase 70: ML Scoring Model — Discussion Log

**Session:** 2026-05-13
**Participants:** Brandon + Claude
**Areas discussed:** Feature Vector Composition, Model Segmentation, Pipeline Integration, TODO-018 Schema Fold

---

## Area 1: Feature Vector Composition

**Q: What should the feature vector include beyond the _shadow dict?**
Options: Shadow only | Shadow + bar context | Shadow + bar + swarm outputs
**Selected:** Shadow + bar context (with swarm augmentation deferred)

**Reasoning:** User initially asked about Option 3 (swarm outputs), asking "is more info better?" Claude applied Renaissance framing: swarm agents only shipped Phase 80 (~8 days ago), so the full training corpus predates them. Including sparse swarm features degrades training quality. Build the pipeline to support swarm augmentation as a later opt-in. User agreed.

**Q: Target variable?**
Options: Binary win/loss | Continuous pnl_r | Multi-class
**Selected:** Binary win/loss — P(win) where win = pnl_r > 0. Aligns with existing confidence_calibrator.py.

---

## Area 2: Model Segmentation

**Q: Model segmentation approach?**
Options: Global + per-regime | Per-plugin-per-TF | Per-timeframe only
**Selected:** Global + per-regime (hmm_regime 0/1/2). Fall back to global when n_regime < 100.

**Q: Walk-forward retraining trigger?**
Options: Nightly + N-gate | N-threshold only | Weekly fixed
**Selected:** Nightly + N-gate — retrain if resolved signal count grew by >= 50. Follows setup_performance_updater.py pattern.

---

## Area 3: Pipeline Integration

**Q: Where does the ML scorer live in the DAG?**
Options: MLScorerMultiplierAgent in swarm | Standalone MLScoringComputeAgent (L8) | Inline in signal_generator_service
**Selected:** MLScorerMultiplierAgent in swarm — extends BaseMultiplierAgent, inference only, shadow_only=True.

**Nuance:** User asked Claude to confirm Renaissance alignment. Claude clarified: Option 1 is correct because inference is cheap (LightGBM, in-memory, sub-ms). Training is a completely separate concern handled by MLTrainingComputeAgent (new L8 service).

**Q: Where does the walk-forward training pipeline run?**
Options: MLTrainingComputeAgent (L8) | Embedded in setup_performance_updater | Manual/research only
**Selected:** MLTrainingComputeAgent — new L8 systemd service.

**Q: How does ml_score integrate with existing confidence and swarm multiplier?**
Options: Additional swarm agent weight | Separate α=0.20 blend coefficient | Replace Sharpe ranker
**Selected:** Additional swarm agent weight — same Σ(w_i × m_i) / Σ(w_i) system as Phase 80 swarm agents.

---

## Area 4: TODO-018 Schema Fold

**Q: Where does ml_score live, and should we implement AI-SEP-01 now?**
Options: Fold TODO-018 into Phase 70 | Add ml_score column to signal_ledger | New signal_ml_score table only
**Selected:** Fold TODO-018 — implement signal_ai_enrichment + intelligence_ai_enrichment, migrate all AI writers.

**Reasoning:** User invoked Renaissance/Jim Simons principle again. Claude confirmed: clean data provenance means quant tables must be immutable after write. Tackling the full separation now is the right call, even though it expands Phase 70's scope. One larger phase beats two phases of migration debt.

---

## Deferred Ideas Captured

- Swarm outputs as ML features (deferred ~90 days of co-located swarm data)
- SHAP attribution in dashboard
- Per-plugin-per-TF segmentation
- Replacing Sharpe ranker with ML
- ML-driven alpha decay monitoring
