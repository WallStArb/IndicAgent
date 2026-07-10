---
**Created:** 2026-07-01
**Area:** intelligence
**Type:** new_feature
**Priority:** P2
**Effort:** 1-2 days (design + one monitor check, reusing IntegrityMonitor shared infra from Phase 149A)
**Benefit:** Closes a monitoring blind spot — no existing or planned monitor detects regime-*model* methodology bugs (only feature-*distribution* drift)
**Risk:** low (observability only)
**Gate:** Phase 149A (`indicagent-integrity-monitor` service + shared BaseMonitor infra) shipped
---


**Status (moved to deferred/, 2026-07-10):** Depends on the IntegrityMonitor shared infra (Phase 151), which has not shipped yet -- nothing to reuse until then. Revive once Phase 151 ships.

# 036 — Regime Model Integrity Monitor (gap in IntegrityMonitor coverage)

## Problem

Reviewed the full v3.1-v4.1 roadmap plus `docs/plans/2026-06-27-health-guardian-design.md`
(archived 2026-07-02, source for Phases 149A/149B/150 — superseded by
`docs/research/intel-14-integrity-monitor.md`, which found this consolidation had dropped real
content from its own predecessors; `DistributionDriftMonitor` kept unchanged, consult intel-14
for the current design) against todo 034 (HMM non-causal fit contaminating causal decode, found
2026-07-01). None of the three planned IntegrityMonitor modules would have caught the 034 class
of bug, and nothing else in the roadmap is designed to catch its recurrence:

- **DistributionDriftMonitor (149A)** watches `feature_vectors` column *distributions* (KS + chi-squared + Wasserstein) for input data corruption. It explicitly treats regime as a *conditioning variable* to avoid false alerts across regime transitions — it does not evaluate whether the regime *labels themselves* were produced by a methodologically sound (causal) fit.
- **ICLifecycleMonitor (149B)** watches feature-level IC decay. It would see downstream symptoms (IC quietly degrading) but has no way to attribute that to a regime-model fitting bug specifically — it would look identical to genuine alpha decay.
- **EnsembleHealthMonitor (150)** watches ensemble-level IC/conviction/coverage gates. Same blind spot — a systematically biased regime label set could pass all three gates if the bias is stable enough not to trip drift/decay thresholds.

This is a distinct failure mode from anything the health-guardian design addresses: it's about whether the *model that assigns regime labels* was trained without look-ahead, not whether the *data feeding that model* or the *downstream IC* look healthy.

## Proposed scope

Add a fourth monitor module to the same `indicagent-integrity-monitor` service (reusing `BaseMonitor`, the shared recovery state machine, and the `integrity_monitor` hypertable — this is exactly the kind of module the Phase 149A architecture was designed to make cheap to add):

**RegimeModelIntegrityMonitor** — periodic check (e.g. weekly, piggybacked on the HMM refit cadence from todo 034's Option A):
1. Confirms the HMM refit fit window respects the causal boundary (fit data ends at or before the refit date; no bars after the refit date were used in `model.fit()`). A simple assertion against `regime_writer`'s own refit bookkeeping, not a statistical test.
2. Seed-stability check (bundled in todo 034's "secondary finding") — fit with 3-5 seeds per refit, compare log-likelihood spread and label agreement; alert if a refit's chosen seed produces label sets that disagree materially from the other seeds (brittle fit).
3. Emits `integrity_regime_model_causal_violation_total` (should always be 0 — a canary, not a tunable threshold) and `integrity_regime_model_seed_stability_score`.

## Why P2, not P0

Todo 034 is the P0 fix — this todo is the monitor that prevents this class of bug from silently recurring after 034 lands. It only becomes actionable once 149A's shared monitor infrastructure exists (no point building a bespoke standalone service for one more check).

## Depends on

- Todo 034 (merged with todo 026 P4a, 2026-07-01) — defines what "causal" means operationally for this monitor to check against, and whether a fix is even warranted (see that todo's validation gate before assuming this monitor has something to check).
- Phase 149A shipped (`BaseMonitor`, `integrity_monitor` table, service skeleton).
