# Phase 107 Discussion Log

**Date:** 2026-05-25
**Workflow:** `/gsd-discuss-phase 107`
**Result:** Context updated with execution strategy decisions

---

## Areas Discussed

### Wave Sequencing
**Question:** Should waves execute serially or in parallel?

**Options presented:**
- Option A: Wave 1 first, then Wave 2 + Wave 3 in parallel
- Option B: All waves serial with verification gates

**User selection:** Option B (serial waves)
**Rationale:** Wave 1 changes are high-risk (BaseAgent lifecycle, DatabaseManager pools). Parallel waves make rollback hell if Wave 2 reveals a Wave 1 bug. Serial waves with checkpoints prioritize debuggability over speed.

**Decision captured:** D-01 — Serial wave execution with verification gates

---

### Dependencies
**Question:** Are there dependencies between the 9 criteria that affect execution order?

**Options presented:**
- Option A: Hard dependencies serialized, parallelize where safe
- Option B: All criteria serialized (no parallelization)

**User selection:** Option A with refinement
**Rationale:** Hard deps are real (HYGIENE-07→01, HYGIENE-08→03). Within-wave parallelization allowed (HYGIENE-09 with 07/08 in Wave 1). Serial waves make most parallelization moot anyway.

**Decision captured:** D-02, D-03 — Hard deps serialized, within-wave parallelization allowed

---

### Scope Validation
**Question:** Are all 9 criteria the right set? Should any be deleted/deferred?

**Options presented:**
- Option A: Keep all 9 criteria
- Option B: Tighten to 7 criteria, defer HYGIENE-05 (dead code) to post-v2.8

**User selection:** Option A (keep all 9)
**Rationale:** Dead code deletion is low-risk (git revert is trivial) and high-value (cognitive clarity during complex AI platform changes). Having ShadowRecorder, GuardrailsValidator, and 8 dead Settings fields around means developers constantly second-guess "Is this used?"

**Decision captured:** D-04 — Keep all 9 criteria; HYGIENE-09 is P1 not P3

---

### Automation Approach
**Question:** Should success criteria be enforced via automated checks or manual verification?

**Options presented:**
- Option A: CI gates + runtime queries with PagerDuty alerting
- Option B: CI gates + runtime queries with Grafana visibility (no PagerDuty)

**User selection:** Option B after refinement
**Rationale:** PagerDuty is premature for development/research system. CI gates for static checks + runtime queries with Grafana panels is correct tier. "Zero tolerance for silent failures" means detecting failures automatically (automated checks), not necessarily responding to them automatically in production (PagerDuty).

**Decision captured:** D-06, D-07, D-08 — CI gates + Grafana visibility + manual spot-checks

---

## Deferred Ideas

### Reviewed Todos (not folded)
- 013-earnings-provider-lane.md (0.6) — Future qualitative provider phase
- 014-macro-event-provider-lane.md (0.6) — Future qualitative provider phase
- 015-qualitative-shadow-evaluation.md (0.6) — Belongs with qualitative provider work
- 017-unified-intelligence-layer-modularization.md (0.4) — Architecture evolution, not infrastructure hygiene
- 005-bi-analytics-layer-apache-superset.md (0.2) — Tooling addition, not infrastructure debt

### Other Deferred
- Kafka topic lifecycle management (process fix, not Phase 107)
- Test infrastructure health (design debt, not Phase 107)
- Documentation audit (automate instead)
- Health monitor standardization (too low priority)

---

## Key Decisions Summary

| Decision ID | Decision | Rationale |
|-------------|----------|-----------|
| D-01 | Serial wave execution with verification gates | Wave 1 is high-risk; parallel waves make rollback hell |
| D-02 | Hard dependencies serialized | Can't add flush spans to services lacking teardown; can't fix data loss in services with broken DB handling |
| D-03 | Within-wave parallelization allowed | HYGIENE-09 can run with 07/08 in Wave 1 |
| D-04 | Keep all 9 criteria | Dead code deletion is low-risk, high-value for cognitive clarity during AI platform work |
| D-05 | HYGIENE-09 is P1 not P3 | Fleet-wide dashboards broken today; can't observe system-wide behavior during v2.8 rollout |
| D-06 | CI gates for static checks | Fail fast during development; block PR merge if violations |
| D-07 | Runtime queries with Grafana visibility | Detect failures automatically; Grafana sufficient for dev/research (no PagerDuty) |
| D-08 | Manual spot-checks for automation validation | One-time validation that automation itself is correct |

---

## Renaissance Principles Applied

- Zero tolerance for silent failures — data loss = alpha leakage
- Instrumentation before optimization — measure before fixing
- Every component must earn its keep — justify with measurements
- Simplicity over complexity — smallest fix that solves the problem
- Technical debt is quantifiable — verification queries return binary TRUE/FALSE

---

## Next Steps

1. `/gsd:plan-phase 107` — Create detailed plans with verification loops
2. Planner MUST read:
   - `.planning/phases/107-infrastructure-hygiene/CONTEXT.md` (this file)
   - `docs/ideas/architectural-weakness-assessment.md` (source of truth)
   - `.planning/phases/phase-106/106-04-SUMMARY.md` (what was just delivered)
3. Execute plans in wave order: Wave 1 → verify → Wave 2 → verify → Wave 3 → verify
4. After each wave: Run success SQL query; only proceed if TRUE

---

**Discussion completed:** 2026-05-25
**Context updated:** `.planning/phases/107-infrastructure-hygiene/107-CONTEXT.md`
