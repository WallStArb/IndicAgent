# Phase 107: Infrastructure Hygiene — Renaissance Delta Analysis

**Date:** 2026-05-25
**Original Scope:** 4 criteria (HYGIENE-01 through HYGIENE-04 from ROADMAP.md)
**Renaissance Scope:** 6 criteria (HYGIENE-01 through HYGIENE-06) — redesigned

## What Changed: Original vs Renaissance

### Original Scope (ROADMAP.md)

**Goal:** Audit and close accumulated DB and observability debt before AI platform work begins.

**Original 4 Criteria:**
1. **HYGIENE-01:** Dead DB table audit + cleanup via migration
2. **HYGIENE-02:** Shadow graduation blockers documented + at least one unblocked
3. **HYGIENE-03:** Shadow registry bootstrap CI manual spot-check
4. **HYGIENE-04:** Metrics naming correctness (ruff check)

---

### Renaissance Scope (REQUIREMENTS.md)

**Goal:** Same — but with Renaissance principles: measurements over opinions, root causes over symptoms, physics over process.

**Renaissance 6 Criteria:**

| # | Name | Original | Renaissance Delta |
|---|------|----------|-------------------|
| **HYGIENE-01** | Hot Path Observability | ~~Dead DB tables~~ | **NEW** — Span coverage + tier latency histograms |
| **HYGIENE-02** | Metric Type Correctness | Metrics naming | **EXPANDED** — Added enforcement, shadow metrics fix, label consistency |
| **HYGIENE-03** | Silent Data Loss | ~~Shadow blockers~~ | **NEW** — Queue drops, flush failures, offset correctness |
| **HYGIENE-04** | DAG Topology | ~~Bootstrap CI~~ | **NEW** — Service completeness, dependency correctness |
| **HYGIENE-05** | Dead Code Elimination | ~~N/A~~ | **NEW** — Dead imports, Settings fields, TEMPLATE fixes |
| **HYGIENE-06** | Shadow Registry Integrity | ~~N/A~~ | **NEW** — Query filters, swarm agent skip, graduation resolution |

---

## What Got Deleted (and Why)

### ❌ **Original HYGIENE-01: Dead DB table audit**

**Renaissance reasoning:** *"Why do we have dead tables? Because we create them without a lifecycle policy. Fix the process, not the symptom."*

**Better approach:** Add to Phase 094 (LiteLLM) as infrastructure hygiene requirement:
```python
# ALL new tables must declare:
TABLE_SPEC = {
    "retention_period": "90 days",
    "owner": "service_name",
    "downstream_consumers": ["consumer1", "consumer2"],
    "cleanup_trigger": "partitioning + retention policy",
}
```

**Verdict:** Delete from Phase 107, move to infrastructure process documentation.

---

### ❌ **Original HYGIENE-02: Shadow graduation blockers**

**Renaissance reasoning:** *"Manual documentation is a band-aid. Fix the governance queries so shadows don't need manual unblocking."*

**Better approach:** This is covered in **HYGIENE-06** (Shadow Registry Integrity) — fix the root cause (query contamination) and blockers won't accumulate.

**Verdict:** Subsumed into HYGIENE-06.

---

### ❌ **Original HYGIENE-03: Bootstrap CI manual spot-check**

**Renaissance reasoning:** *"Manual spot-checks are not scalable. Automate the verification."*

**Better approach:** This is covered in **HYGIENE-06** (Shadow Registry Integrity) — but expanded to include automated CI gate plus one-time manual validation.

**Verdict:** Subsumed into HYGIENE-06 as verification step #3.

---

## What Got Added (and Why)

### ✅ **NEW HYGIENE-01: Hot Path Observability Coverage**

**Rationale:** Critical paths are dark today. Finding #13 from architectural audit: *All 37 services have zero OTel span coverage*.

**Business impact:** When DSPy prompt optimization causes regressions in v2.8, we'll have no traces to diagnose it.

**Renaissance principle:** *Instrumentation is physics — you cannot optimize what you don't measure.*

---

### ✅ **EXPANDED HYGIENE-02: Metric Type Correctness**

**Original:** "ruff check passes on all metric call sites"

**Renaissance expansion:**
- Added shadow metrics fix (5 metrics wrong type)
- Added label consistency (agent vs agent_id split)
- Added automated enforcement (import-time assertion)
- Added verification query

**Business impact:** Shadow governance dashboard shows 500% win rates because up_down_counter accumulates. We can't trust our measurements.

**Renaissance principle:** *Measurement integrity is as important as measurement itself.*

---

### ✅ **NEW HYGIENE-03: Silent Data Loss Elimination**

**Rationale:** Finding #5 from architectural audit: *Intelligence topic drops silently on QueueFull*. Finding HF-4: *FeatureWriter ghost-run on DB failure*.

**Business impact:** 6.25% data loss at 160/min = trading on 93.75% of signal. Alpha leakage.

**Renaissance principle:** *Silent failures are the most expensive — you pay the cost without knowing it.*

---

### ✅ **NEW HYGIENE-04: DAG Topology Correctness**

**Rationale:** Finding #17, #18, #20 from architectural audit: *wrong systemd dependencies, 11 services missing from DAG, cyclic dependencies*.

**Business impact:** ML batch service failures invisible to auditor. If ml-orchestrator fails at 3am, we train models on stale data for 6 hours.

**Renaissance principle:** *System topology is physics. Get it wrong and the universe punishes you.*

---

### ✅ **NEW HYGIENE-05: Dead Code Elimination**

**Rationale:** Finding #4 from architectural audit: *Dead AI foundations (ShadowRecorder, GuardrailsValidator, TEMPLATE bug)*.

**Business impact:** Every wrong pattern in TEMPLATE is copied 10 times. We had 4 services bypassing DatabaseManager because the pattern existed.

**Renaissance principle:** *Code surface area = cognitive load. Minimize both.*

---

### ✅ **NEW HYGIENE-06: Shadow Registry Integrity**

**Rationale:** Finding #22, #23 from architectural audit: *Shadow promotion/demption trains on shadow signals, swarm agent governance broken*.

**Business impact:** Shadow signals contaminate promotion statistics → we optimize for wrong objective function → promote bad plugins.

**Renaissance principle:** *Experimental integrity is sacred. Control groups must remain independent.*

---

## What Got Reordered (Wave Structure)

### **Wave 1: Instrumentation First** (Blocker for everything else)
- HYGIENE-01: Spans on hot path
- HYGIENE-02: Metric type correctness

**Why:** *"You can't fix what you can't see. Measure first, optimize second."*

### **Wave 2: Silent Failure Elimination** (Blocker for AI platform)
- HYGIENE-03: No silent data loss
- HYGIENE-04: DAG correctness

**Why:** *"Data loss is alpha leakage. Zero tolerance."*

### **Wave 3: Complexity Reduction** (Efficiency)
- HYGIENE-05: Dead code elimination
- HYGIENE-06: Shadow registry integrity

**Why:** *"Every line of code is a liability. Minimize surface area."*

---

## Quantified Delta: Before vs After Renaissance Redesign

| Aspect | Original Scope | Renaissance Scope | Delta |
|--------|----------------|-------------------|-------|
| **Criteria count** | 4 | 6 | +2 (more comprehensive) |
| **Measurement-driven** | 1/4 (25%) | 6/6 (100%) | +75% (all quantified) |
| **Root cause fixes** | 0/4 (0%) | 6/6 (100%) | +100% (all address root causes) |
| **Automated enforcement** | 1/4 (25%) | 6/6 (100%) | +75% (CI gates, pre-commit hooks) |
| **Business impact** | Implicit | Explicit (alpha leakage, PnL impact) | +100% (quantified) |
| **Verification queries** | 0 | 7 (one per HYGIENE + overall) | +7 (automated validation) |
| **Success score** | None | Formula with 7 metrics | +100% (quantified success) |

---

## What Stayed the Same (Core Principles)

### **Unchanged Principles:**
1. ✅ **Infrastructure hygiene before AI platform** — both agree this must block v2.8
2. ✅ **Measurement-driven** — Renaissance expanded this, didn't replace it
3. ✅ **Root cause focus** — Renaissance made this explicit (process fixes, not symptoms)
4. ✅ **Zero tolerance for silent failures** — Renaissance made this quantified

### **Unchanged Goal:**
*"Audit and close accumulated DB and observability debt before AI platform work begins."*

**Renaissance interpretation:** Same goal — but "audit" means "measure with quantified before/after" and "close debt" means "fix root causes with automated enforcement."

---

## Jim Simons' Review of Delta

### **What he'd approve:**
✅ **Measurement-driven** — every criterion has quantified before/after
✅ **Root cause fixes** — pre-commit hooks, CI gates, process changes
✅ **Business impact quantified** — alpha leakage, PnL at risk, data loss rates
✅ **Physics over process** — DAG topology is physics, silent failures are expensive
✅ **Smallest fix that works** — no grand refactors, targeted fixes with high leverage

### **What he'd challenge:**
❓ **"Is 6 criteria too many?"** — Maybe. Consider rolling HYGIENE-05 into Wave 3 if timeline pressure.
❓ **"Where's the ongoing monitoring?"** — Good point. Add HYGIENE-07 for infrastructure health dashboard (deferred to v2.9).
❓ **"What's the control experiment?"** — For HYGIENE-06 (shadow governance), add A/B test: compare promotion accuracy before/after query fix.

### **Final verdict:**
*"This is how Renaissance does infrastructure. Measure everything. Fix root causes. Never tolerate silent failures. When you add 10 AI agents in v2.8, you'll do it on a foundation that's engineered like physics — not held together by duct tape and hope."*

---

## Next Steps

1. **Review REQUIREMENTS.md** — validate Renaissance approach aligns with project goals
2. **Run baseline measurements** — capture "before" state for all 7 metrics
3. **Plan execution waves** — Wave 1 (instrumentation) → Wave 2 (silent failures) → Wave 3 (complexity)
4. **Execute Phase 107** — follow Renaissance-style success criteria
5. **Verify with queries** — run verification queries after each wave
6. **Compute Phase 107 Success Score** — must be ≥ 95% to unblock v2.8
7. **Gate v2.8 AI platform** — no AI platform work until Phase 107 complete

**Bottom line:** Renaissance redesign transforms Phase 107 from a tactical "cleanup task" into a strategic "infrastructure hygiene foundation" that quantifies every fix, addresses root causes, and provides measurable guarantees for v2.8 AI platform work.
