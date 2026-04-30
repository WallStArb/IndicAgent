# Phase 78: I8 Alpha Feedback Loop - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 78-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-30
**Phase:** 78-I8 Alpha Feedback Loop
**Areas discussed:** Shadow data architecture, AIContext API design, Agent authoring pattern, Phase scope, TierContext coverage

---

## Shadow Data Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Complete Phase 73 migration first | Migrate swarm → LineageRecorder → signal_lineage as part of Phase 78. Retire alpha_multiplier_shadow + signal_transform_log for swarm. One data path, shadow_registry for state, signal_lineage for outcomes. | ✓ |
| Build on existing dual-write | Don't migrate yet. Graduate swarm using signal_transform_log (already populated). Faster, but leaves dual-write debt alive. | |
| Full unification — shadow_registry only | Make shadow_registry the single source for both I7 and swarm, remove signal_transform_log from graduation path entirely. | |

**User's choice:** Complete Phase 73 migration first  
**Notes:** User framing — "design like Renaissance would. Ask yourself how would a senior engineer/quant at Renaissance think about this? What would Jim Simons demand? I am happy with whatever is the most institutional design that will be easy to build on. Prefer not to rebuild and leave tech debt." Claude determined: complete migration is the Renaissance call. Dual-write debt is exactly the kind of hidden failure mode that causes "works in testing, wrong in production."

---

## AIContext API Design

| Option | Description | Selected |
|--------|-------------|----------|
| Expand typed tier models | Add missing fields to existing TierContext subclasses, add I2Context/I3Context/I5Context. | |
| dict escape hatch (Plan 05 as-is) | Add full_features: dict[str, Any] alongside existing typed models. Quick, fragile. | |
| Use schemas.py types directly | AIContext.i1: I1Indicators \| None, etc. AIContextCache.build() maps event.i1 → ctx.i1 directly. Zero duplication. D-36 allows this import. | ✓ |

**User's choice:** "Design like Renaissance would" (applied to all questions consistently)  
**Notes:** User consistently applied Renaissance/institutional framing. Claude's determination: use schemas.py types directly eliminates all drift risk. schemas.py already has complete typed models (I1Indicators=53 fields, I4Context=112 fields, etc.) and D-36 (Phase 73) explicitly permits the import. No `dict[str, Any]` in critical paths — ever.

---

## TierContext Coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Only fields agents use in Phase 78 | Pragmatic — expand to cover skeptic_v2 prompt needs only. | |
| Full coverage — every pipeline field | Map ALL fields from I1-I7 into typed models. Complete, future-proof. | ✓ |
| Just I4 + I6 (skeptic needs them most) | Fast, but typed context story is incomplete. | |

**User's choice:** Full coverage — "design like Renaissance would, institutionally sound that we can expand as we grow"  
**Notes:** The institutional approach maps all pipeline fields once. Null-safe (all Optional). Zero drift because schemas.py IS the source of truth and AIContext imports it directly. This is achieved for free since we're using schemas.py types directly.

---

## Phase Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Expand Phase 78 to include migration | Add Phase 73 lineage completion to Phase 78. Total ~8-9 plans. Ship it once, done. | ✓ |
| Split into Phase 78 + Phase 79 | Phase 78 does typed context + agent pattern; Phase 79 does lineage migration. | |
| Phase 78 as planned, file todo | Execute 7 plans as-is. Capture lineage migration as new todo. | |

**User's choice:** Expand Phase 78 to include migration  
**Notes:** The 7 existing plans can absorb the expanded scope — Plans 01, 02, 03, and 05 receive additional tasks. No 8th plan needed. This was confirmed after codebase analysis.

---

## Graduation Auditor Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Unified eventually, two auditors now | Phase 78 keeps _graduation_loop in swarm service; ShadowAuditorAgent stays I7 only. Future phase unifies. | ✓ |
| Unify now — ShadowAuditorAgent handles both | Extend ShadowAuditorAgent to component_type='swarm_agent'. More Phase 78 scope. | |

**User's choice:** Claude's discretion  
**Notes:** Claude determined: two auditors now (different eval logic — Spearman vs bootstrap CI; different cadence — 15min vs 30min). The schema (shadow_registry) is already unified. Unified auditor service is Phase 79+ work. This is consistent with Renaissance principle: prove both paths work independently before merging.

---

## Agent Authoring Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| CLAUDE.md entry + template file | CLAUDE.md section + TEMPLATE_agent.py + AUTHORING.md protocol doc. | ✓ |
| CLAUDE.md only | Concise CLAUDE.md section, skeptic_agent.py is the canonical example. | |
| Self-documenting code | No docs — read skeptic_agent.py. | |

**User's choice:** Claude's discretion (Renaissance framing applied)  
**Notes:** Claude determined: CLAUDE.md + TEMPLATE_agent.py + AUTHORING.md. Institutional code requires protocol documentation. A new team member should be able to add an agent without reading source code.

---

## Claude's Discretion

- **Graduation auditor split**: Two separate auditors (swarm _graduation_loop vs ShadowAuditorAgent) for Phase 78; unification deferred to Phase 79+
- **Agent authoring format**: CLAUDE.md section + TEMPLATE_agent.py + AUTHORING.md (three-layer documentation)
- **AIContext import boundary**: Use schemas.py types directly, delete sparse TierContext subclasses

## Deferred Ideas

- Unified ShadowAuditorAgent (swarm + I7) → Phase 79+
- `risk` agent group population → future phase when risk agents are designed
- FeatureValidationService → todo 008, separate phase
- Dashboard I3/I5/I6 field gaps → todo 003
- Apache Superset BI layer → todo 005
- validate_alpha re-run for DerivOsc/AC Osc → todo 006, data-gated ~May 10
- Extract swarm shared utilities → todo 007, triggered at 4th agent
