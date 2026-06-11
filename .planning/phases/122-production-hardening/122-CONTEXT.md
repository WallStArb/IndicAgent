# Phase 122: Production Hardening - Context

**Gathered:** 2026-06-11
**Status:** Absorbed into Phase 121 — number recycled

<domain>
## Phase Boundary

Phase 122 as originally scoped is absorbed into Phase 121 Wave 2. The number 122 is recycled for future use.

**Original scope (from roadmap):**
- FeatureParityAuditor running continuously (5min timer)
- ConfidenceCalibrationMonitor running continuously (5min timer)
- ShadowAuditor running continuously (15min timer)
- All 30 setups empirically validated
- ServiceAuditor unified alerting to Telegram/Discord

**Disposition of each item:**

| Item | Status | Decision |
|------|--------|----------|
| FeatureParityAuditor | Already deployed (5-min timer) | No work needed |
| ConfidenceCalibrationMonitor | Already deployed (30-min timer) | Fold timer adjustment into 121-02 if desired |
| ShadowAuditor | Already deployed (30-min timer active) | Fold timer adjustment into 121-02 if desired |
| All 30 setups validated | Phase 121 Wave 2 report produces per-setup PASS/FAIL verdicts | Covered by 121-02 |
| ServiceAuditor unified alerting (SC5) | Obsolete — monitors emit OTel; oneshot contract covers failures; Alertmanager is the unified path | Drop entirely |

</domain>

<decisions>
## Implementation Decisions

### D-01: Phase 122 Absorbed Into Phase 121

All remaining Phase 122 work folds into Phase 121 Wave 2 (121-02-PLAN.md):
- The 30-setup validation gate is already captured in 121-02 as per-setup PASS/FAIL verdicts
- Timer interval changes (calibration 30min→5min, shadow 30min→15min) are optional 2-line systemd edits — add to 121-02 if desired
- ROADMAP.md + STATE.md v2.9 close-out happens at the end of 121-02

### D-02: SC5 (ServiceAuditor Unified Alerting) Dropped

SC5 was written before the monitors existed. The monitors were built with OTel-first alerting — the correct architecture. The unified alert path already exists via Alertmanager. Adding ServiceAuditor as an alert aggregator would have been a god-class violation. SC5 is obsolete and dropped entirely.

### D-03: Phase 122 Number Recycled

v2.9 milestone becomes Phases 117-121 (5 phases, not 6). Phase 122 is available for the next milestone.

</decisions>

<canonical_refs>
## Canonical References

### Prior Phase
- `.planning/phases/121-lifecycle-replay-validation/121-CONTEXT.md` — D-01 through D-06 decisions; 121-02-PLAN.md already contains the per-setup verdict logic
- `.planning/phases/121-lifecycle-replay-validation/121-02-PLAN.md` — Wave 2 plan; add timer adjustments and v2.9 close-out tasks here

### RCA Doc (authoritative scope definition)
- `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md` — Phase 6 (v2.9 Phase 122) defined as "FeatureParityAuditor + ConfidenceCalibrationMonitor + SignalProbeAuditor running continuously. All 30 setups validated." All three monitors marked DONE as of Phase 120.

</canonical_refs>

<code_context>
## Existing Code Insights

### Already Deployed
- `services/feature_parity_auditor.py` — 5-min timer, OTel metrics, oneshot contract, DONE
- `services/confidence_calibration_monitor.py` — 30-min timer, OTel metrics, oneshot contract, DONE
- `services/shadow_auditor.py` — 30-min timer, demotion-only (SoC split from shadow_validator), DONE
- All three have `/etc/systemd/system/` timer units installed and active

### Timer Adjustments (if desired — fold into 121-02)
- `indicagent-confidence-calibration-monitor.timer` — change `OnUnitActiveSec=30min` to `5min`
- `indicagent-shadow-auditor.timer` — change `OnUnitActiveSec=30min` to `15min`

</code_context>

<specifics>
No specific implementation requirements — Phase 122 scope fully resolved by absorption.
</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. Phase 122 number available for next milestone use.
</deferred>

---

*Phase: 122-Production-Hardening*
*Context gathered: 2026-06-11*
*Decision: Absorbed into Phase 121 — number recycled*
