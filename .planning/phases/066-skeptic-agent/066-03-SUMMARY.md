---
phase: 066-skeptic-agent
plan: 03
subsystem: swarm
tags: [validation, statistics, shadow-recording, signal-ledger]

# Dependency graph
requires:
  - phase: 066-01
    provides: alpha_multiplier_shadow table (ShadowRecorder writes here)
  - phase: 066-02
    provides: All 3 agents recording predictions to alpha_multiplier_shadow
provides:
  - scripts/compute_skeptic_baseline.py: per-segment historical failure rates from signal_ledger
  - scripts/validate_skeptic.py: Pearson correlation + graduation gate (rho>=0.3, p<0.05, N>=30)
affects: []

# Tech tracking
tech-stack:
  - asyncpg (DB queries)
  - scipy.stats.pearsonr (Pearson correlation)
  - pandas (segment aggregation)

# Summary
Delivered two validation scripts implementing the Renaissance "earn the right through proof" gate for swarm agents.

**compute_skeptic_baseline.py** (D-12): Queries signal_ledger historical outcomes grouped by (hmm_regime, tf, regime_type_at_fire, plugin), computes per-segment failure_rate and win_rate. Provides the naive baseline the LLM must beat.

**validate_skeptic.py** (D-13, D-14): JOINs alpha_multiplier_shadow with signal_ledger on signal_id, extracts failure_probability from features JSONB, computes Pearson rho per (tf, hmm_regime) segment. Graduation gate: rho >= 0.3 AND p < 0.05 AND N >= 30 per segment; global gate rho >= 0.2. Exit code 0 = PASS, 1 = FAIL (CI-compatible). Both scripts verified: --help displays, ruff clean, imports resolve.

Note: validate_skeptic.py was later refactored in Phase 72 (plan 72-05) into a thin CLI wrapper over graduation.py, which absorbed the core statistical logic into the shared module.
