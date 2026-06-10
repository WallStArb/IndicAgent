# Phase 120: Shadow Mode Validation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-10
**Phase:** 120-shadow-mode-validation
**Areas discussed:** Architecture, was_selected semantics, calibration metric, promotion criteria, notification

---

## Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| New script, BOTH must pass | `shadow_validator.py` (weekly) + `shadow_auditor.py` (30-min demotion-only) | ✓ |
| Extend shadow_auditor.py | Add new criteria directly to existing 30-min script | |
| New script, replaces bootstrap | Phase 120 criteria entirely replace bootstrap_ci_lower gate | |

**User's choice:** "Think like Renaissance Technologies senior engineers. Apply first-principles rigor, SoC, DAG topology, eliminate complexity."

**Notes:** User delegated architectural decision to Claude with Renaissance principles as the constraint. Selected "new separate service" based on SoC: promotion (weekly, statistical graduation) and demotion (30-min, ongoing health monitoring) are orthogonal concerns with different cadences. Conflating them violates SRP and creates unnecessary coupling.

---

## was_selected Semantics

| Option | Description | Selected |
|--------|-------------|----------|
| activated_at IS NOT NULL | Signal progressed from pending to active state | |
| shadow_outcome = 'selected' | Use shadow_outcome column explicitly | |
| was_selected boolean (existing) | Already a column on signal_ledger | ✓ |

**User's choice:** Delegated to Claude with Renaissance principles.

**Notes:** Schema check revealed `was_selected` is already a boolean column on `signal_ledger`. No inference from other columns needed. This eliminates the ambiguity entirely — use the existing column directly.

---

## Calibration Metric

**Decision (Claude's discretion):** `CORR(cis_score, was_selected::int)`.

**Notes:** No `confidence` column exists in `signal_ledger`. `cis_score` is the aggregator's composite intelligence score — the correct variable to correlate with `was_selected` since it measures whether the scoring system accurately predicts which signals get selected. Root cause doc's pseudocode used generic "confidence" but the actual column is `cis_score`.

---

## Claude's Discretion

All major design decisions were delegated with Renaissance/first-principles as the constraint:

- **Separate weekly service vs extend auditor** — chose new service for SoC
- **shadow_auditor.py becomes demotion-only** — removes promotion path from 30-min script to eliminate race condition
- **signal_ledger_shadow as DB view (migration 120)** — `signal_ledger_full WHERE is_shadow=true` (clean nameable interface)
- **Sampling window = all-time from shadow_tracking_start_ts** — maximize N, avoid arbitrary rolling window cutoffs
- **binomtest (scipy >= 1.7 API)** vs deprecated `binom_test`
- **Notification via topic_alert_requests (CRITICAL)** — reuse AlertMonitor infrastructure
- **Grafana table panel** — per-setup status table + N accumulation time-series

---

## Deferred Ideas

- **Extrinsic composite confidence layer** — ctf_score + hmm_regime_weight + zone_friction + exhaustion_guard as calibrated multiplier at aggregator layer. Root cause doc Phase 4.1. Own phase after Phase 121.
- **Per-setup threshold tuning** — empirical derivation of `_MIN_*` threshold values from Phase 120 shadow data. Phase 121 scope.
