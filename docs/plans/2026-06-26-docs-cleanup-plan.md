# Docs Cleanup Plan — Renaissance-Grade Reduction

**Date:** 2026-06-26  
**Scope:** docs/plans directory cleanup  
**Goal:** Reduce 81 active plan docs to <15 truly current documents  
**Philosophy:** Keep what informs current work, archive what's historical, delete what's superseded

---

## Executive Summary

The `docs/plans/` directory contains **81 active documents** (plus 49 already archived). Many are **v2.x-specific** (I1-I7 signal pipeline), **cancelled-phase plans**, or **superseded design docs** that no longer reflect the v3.0 AlphaEngine architecture.

This cleanup applies Renaissance ruthlessness: **if it doesn't inform current v3.0 work, it doesn't belong in the active planning directory.**

---

## Category A: DELETE (Superseded by v3.0) — 37 docs

### V2.x Signal Pipeline (I1-I7 Archived)

**Rationale:** All v2.x intelligence pipeline components (I1-I7, plugin system, signal lifecycle) are **archived** in v3.0. These docs describe a system that no longer exists.

**Delete immediately:**

```
docs/plans/2026-06-02-intelligence-pipeline-signal-integrity.md
docs/plans/2026-06-03-intelligence-platform-strategic-review.md
docs/plans/2026-06-04-signal-confidence-pipeline-hardening-plan.md
docs/plans/2026-06-04-signals-screen-renaissance-plan.md
docs/plans/2026-06-05-signal-trade-card-plan.md
docs/plans/2026-06-05-stop-target-hardening.md
docs/plans/2026-06-06-backfill-signal-integrity-plan.md
docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md
docs/plans/2026-06-07-trade-framing-architecture-analysis.md
docs/plans/2026-06-09-signal-refactor-deferred-todo.md
docs/plans/2026-06-11-signal-replay-architecture-plan.md
docs/plans/2026-06-12-i2-persistence-design.md
docs/plans/2026-06-13-i7-onset-detection-design.md
docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md
docs/plans/2026-06-14-phase-126-signal-universe-hardening.md
docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md
docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md
docs/plans/2026-06-17-phases-131-133-signal-corpus-integrity.md
docs/plans/2026-06-20-i7-alpha-scorer-transition.md
docs/plans/2026-06-25-alphaengine-phase-d-prerequisites.md
```

**Why delete not archive:** These are implementation docs for a dead system. v3.0 architecture is documented in `docs/intelligence/intelligence-alphaengine.md`. Keeping these creates confusion about what's current.

---

### Cancelled Phase Plans

**Rationale:** Phase 133 was **cancelled**, Phase 135 was **DEFERRED indefinitely**. No reason to keep their planning docs active.

```
docs/plans/135-REVIEWS.md  # Phase 135 cancelled
```

---

## Category B: MOVE TO docs/plans/archive/ (Historical Reference) — 28 docs

### V2.x Foundation Docs (Worth Preserving)

**Rationale:** These contain design reasoning that informs v3.0, even if the implementation changed. Keep for historical context.

```
docs/plans/2026-06-03-sse-broadcaster-hardening.md
docs/plans/2026-06-05-pending-ttl-expiry-fix.md
docs/plans/2026-06-06-glossary-enforcement-plan.md
docs/plans/2026-06-13-parameter-store-full-plugin-migration.md
docs/plans/2026-06-14-phase-126-pipeline-annotation-layer.md
docs/plans/2026-06-17-simplify-skipped-four.md
docs/plans/2026-06-18-cleanup-a-through-e.md
docs/plans/2026-06-18-post-reboot-repair-design.md
docs/plans/2026-06-18-timeframe-propagation-fix.md
docs/plans/2026-06-19-hmm-garch-kalman-apr-migration.md
docs/plans/2026-06-19-replay-optimization-design.md
docs/plans/2026-06-23-feature-factory-single-path-refactor.md
docs/plans/2026-06-24-feature-cache-batch-fix-design.md
docs/plans/2026-06-24-feature-factory-batch-integrity.md
```

### Phase 127 Logs (Historical)

**Rationale:** Phase 127 calibration/validation logs. Worth preserving for "what we tried and why."

```
docs/plans/phase-127-calibration-retrain-log.md
docs/plans/phase-127-replay-log.md
docs/plans/phase-127-validation-report.md
```

### V2.x Foundation → Archive (Already Superseded)

**Rationale:** These were moved from `docs/plans/` → `docs/plans/archive/` between 2026-02 and 2026-05. Verify they're already archived and delete duplicates from root.

```
docs/plans/archive/2026-02-12-robinhood-scaling-patterns.md
docs/plans/archive/2026-02-13-robinhood-architecture-comparison.md
docs/plans/archive/2026-02-13-smart-money-plugins-design.md
docs/plans/archive/2026-02-14-bocpd-changepoint-design.md
docs/plans/archive/2026-02-15-hmm-regime-design.md
docs/plans/archive/2026-02-16-i7-signals-ai-experts-design.md
docs/plans/archive/2026-02-17-signal-aggregation-design.md
docs/plans/archive/2026-02-19-i8-ai-narrative-design.md
docs/plans/archive/2026-02-19-kalman-trend-design.md
docs/plans/archive/2026-02-21-data-layer-redesign.md
docs/plans/archive/2026-02-22-liquidity-pools-supply-demand-design.md
docs/plans/archive/2026-02-25-momentum-acceleration-analysis.md
docs/plans/archive/2026-02-27-composite-intelligence-score-design.md
docs/plans/archive/2026-03-02-momentum-acceleration-design.md
docs/plans/archive/2026-03-03-signal-lifecycle-redesign.md
docs/plans/archive/2026-03-04-cis-universal-ensemble-design.md
docs/plans/archive/2026-03-06-pipeline-reset-design.md
docs/plans/archive/2026-03-07-i7-i8-renaissance-refinement-design.md
docs/plans/archive/2026-03-11-signal-drift-detection-design.md
docs/plans/archive/2026-03-13-equity-expansion-design.md
docs/plans/archive/2026-03-13-equity-expansion-renaissance.md
docs/plans/archive/2026-03-14-distribagent-design.md
docs/plans/archive/2026-03-14-market-entry-dual-track-design.md
docs/plans/archive/2026-03-16-signal-intelligence-design.md
docs/plans/archive/2026-03-17-automated-roll-detection-design.md
docs/plans/archive/2026-03-19-db-institutional-audit-design.md
docs/plans/archive/2026-03-19-signal-pipeline-dag-refactor-and-renaissance-observability.md
docs/plans/archive/2026-03-21-data-layer-renaissance-refactor-design.md
docs/plans/archive/2026-03-21-renaissance-pipeline-refactor-design.md
docs/plans/archive/2026-03-22-phase-46-gap-vix-cross-asset-to-i4.md
docs/plans/archive/2026-03-24-canonical-bar-normalization-design.md
docs/plans/archive/2026-03-24-intelligence-dual-path-poc.md
docs/plans/archive/2026-03-25-agentic-topology-alignment.md
docs/plans/archive/2026-03-25-architectural-vision-agentic-dags.md
docs/plans/archive/2026-03-25-dual-write-parity-audit.md
docs/plans/archive/2026-03-25-market-aggregator-agent-refactor.md
docs/plans/archive/2026-03-25-parity-auditor-agent.md
docs/plans/archive/2026-03-25-pipeline-audit-design.md
docs/plans/archive/2026-03-25-renaissance-integrity-and-usage-audit.md
docs/plans/archive/2026-03-25-tiered-compute-agent-decompostion.md
docs/plans/archive/2026-03-26-data-layer-dag-design.md
docs/plans/archive/2026-03-28-multi-provider-data-architecture.md
docs/plans/archive/2026-03-29-intelligence-agent-unified-pipeline-design.md
docs/plans/archive/2026-04-01-bar-aggregator-fault-tolerance-design.md
docs/plans/archive/2026-04-01-pipeline-parallelization-design.md
docs/plans/archive/2026-04-02-contract-lifecycle-automation-design.md
docs/plans/archive/2026-04-02-pipeline-parallelization-renaissance-completion-design.md
docs/plans/archive/2026-04-03-service-auditor-design.md
docs/plans/archive/2026-04-05-ofi-divergence-redesign-design.md
docs/plans/archive/2026-04-05-signal-metrics-redesign.md
docs/plans/archive/2026-04-06-signal-auditor-design.md
docs/plans/archive/2026-04-07-refactoring-analysis.md
docs/plans/archive/2026-04-10-pipeline-health-audit.md
docs/plans/archive/2026-04-10-pipeline-health-fixes-design.md
docs/plans/archive/2026-04-10-pipeline-health-fixes-plan.md
docs/plans/archive/2026-04-11-pipeline-hardening-design.md
docs/plans/archive/2026-04-12-observability-automation-design.md
docs/plans/archive/2026-04-13-basewriter-renaissance-refactor-design.md
docs/plans/archive/2026-04-14-base-agent-infrastructure-alignment-design.md
docs/plans/archive/2026-04-20-ingestion-edge-hardening.md
docs/plans/archive/2026-04-21-data-quality-loop-hardening.md
docs/plans/archive/2026-04-24-signal-transform-log-design.md
docs/plans/archive/2026-04-26-ai-llm-layer-design.md
docs/plans/archive/2026-04-28-otel-observability-unification-design.md
docs/plans/archive/2026-04-28-shadow-governance-design.md
docs/plans/archive/2026-05-02-unified-intelligence-design.md
docs/plans/archive/2026-05-03-ib-gateway-linux-design.md
docs/plans/archive/2026-05-03-phase-79-implementation-plan.md
docs/plans/archive/2026-05-03-phase-79-signal-quality-fix-design.md
docs/plans/archive/2026-05-04-structural-zone-engine-design.md
docs/plans/archive/2026-05-04-structural-zone-engine-plan.md
docs/plans/archive/2026-05-04-zone-engine-codex-review.md
docs/plans/archive/2026-05-04-zone-engine-reviews.md
docs/plans/archive/2026-05-05-codebase-cleanup-design.md
docs/plans/archive/2026-05-05-swarm-intelligence-design.md
docs/plans/archive/2026-05-08-signal-lifecycle-hardening-design.md
docs/plans/archive/2026-05-14-env-cleanup-design.md
docs/plans/archive/2026-05-14-env-cleanup.md
docs/plans/archive/2026-05-14-signal-quality-hardening-design.md
docs/plans/archive/2026-05-14-signal-quality-hardening-plan.md
docs/plans/archive/2026-05-15-observability-hardening-design.md
docs/plans/archive/2026-05-17-llm-inference-hardening-design.md
docs/plans/archive/2026-05-17-llm-inference-hardening.md
docs/plans/archive/2026-05-19-cis-stf-mtf-per-bar-design.md
docs/plans/archive/2026-05-19-cis-stf-mtf-reviews.md
docs/plans/archive/2026-05-19-instrument-registry-hardening-design.md
docs/plans/archive/2026-05-20-agent-platform-redesign.md
docs/plans/archive/2026-05-20-phase1-litellm.md
docs/plans/archive/2026-05-20-phase2-instructor.md
docs/plans/archive/2026-05-20-phase3-pydantic-ai.md
docs/plans/archive/2026-05-20-phase4-agent-registry.md
docs/plans/archive/2026-05-20-phase5-zep-memory.md
docs/plans/archive/2026-05-20-phase6-dspy-optimizer.md
docs/plans/archive/2026-05-20-phase7-guardrails.md
docs/plans/archive/2026-05-21-plugin-infrastructure-design.md
docs/plans/archive/2026-05-21-plugin-infrastructure-REVIEWS.md
docs/plans/archive/2026-05-21-plugin-state-migration-fix.md
docs/plans/archive/2026-05-22-plugin-infrastructure-hardening-design.md
docs/plans/archive/2026-05-22-plugin-infrastructure-hardening.md
docs/plans/archive/2026-05-22-project-cleanup-restructure.md
docs/plans/archive/2026-05-23-architecture-audit-design.md
docs/plans/archive/2026-05-23-signal-ledger-definition-fields.md
docs/plans/archive/2026-05-23-signal-ledger-definition-fields-plan.md
docs/plans/archive/2026-05-24-fix-a-intelligence-features-toast.md
docs/plans/archive/2026-05-24-fix-b-signal-ledger-split.md
docs/plans/archive/2026-05-24-storage-root-cause-fix.md
docs/plans/archive/2026-05-26-pipeline-issues-fixes-applied.md
docs/plans/archive/2026-05-26-pipeline-issues-root-cause-analysis.md
docs/plans/archive/2026-05-26-roll-compute-simplification.md
docs/plans/archive/2026-05-27-signal-lifecycle-architecture.md
docs/plans/archive/2026-05-28-config-foundation-and-alerting-system.md
docs/plans/archive/2026-05-28-config-foundation-and-alerting-system-REVIEWS.md
docs/plans/archive/2026-05-29-concepts-library-design.md
docs/plans/archive/2026-05-29-concepts-library-plan.md
docs/plans/archive/2026-05-30-phase-111-naming-alignment.md
docs/plans/archive/2026-05-30-renaissance-naming-system-design.md
docs/plans/archive/2026-06-02-agent-memory-design.md
docs/plans/archive/2026-06-03-lifecycle-replay-repair.md
docs/plans/archive/2026-06-03-lifecycle-replay-reviews.md
docs/plans/archive/2026-06-04-signal-confidence-pipeline-hardening.md
docs/plans/archive/2026-06-04-signals-screen-renaissance-redesign.md
docs/plans/archive/2026-06-05-pending-ttl-expiry-fix-design.md
docs/plans/archive/2026-06-05-signal-trade-card-design.md
docs/plans/archive/2026-06-05-sr-consensus.md
docs/plans/archive/2026-06-06-backfill-signal-integrity.md
docs/plans/archive/2026-06-06-glossary-enforcement.md
docs/plans/archive/2026-06-07-backfill-monitoring.md
docs/plans/archive/2026-06-07-signal-cleanup-regeneration-plan.md
docs/plans/archive/2026-06-08-confidence-intrinsic-cleanup.md
```

---

## Category C: KEEP (Active v3.0 Work) — 16 docs

### Current Architecture & Design

**Rationale:** These are the **canonical v3.0 architecture documents**. They describe the live system.

```
docs/plans/2026-06-18-controlled-vocabulary-system.md       # APR design
docs/plans/2026-06-20-alphaengine-architecture.md          # v3.0 canonical spec
docs/plans/2026-06-20-alphaengine-ic-spec.md               # IC methodology
docs/plans/2026-06-20-analogengine-design.md                # Future: pgvector search
docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md         # alpha_events table spec
docs/plans/2026-06-26-renaissance-optimization-roadmap.md  # This doc: IC engine + beyond
```

### HMM Improvement (Completed 2026-06-25)

**Rationale:** HMM improvements are **shipped to main** (b562a718). Keep for reference on what changed and why.

```
docs/plans/2026-06-19-hmm-garch-kalman-apr-migration.md     # HMM → APR migration
```

### Feature Factory v3.0 (Active)

**Rationale:** Feature Factory is the **core v3.0 primitive**. Keep all current design docs.

```
docs/plans/2026-06-23-feature-factory-single-path-refactor.md
docs/plans/2026-06-24-feature-cache-batch-fix-design.md
docs/plans/2026-06-24-feature-factory-batch-integrity.md
```

---

## After Cleanup: 16 Active Docs

**Goal:** From 81 active docs → 16 active docs (80% reduction)

**Active docs structure:**
```
docs/plans/
├── 2026-06-18-controlled-vocabulary-system.md          # APR
├── 2026-06-19-hmm-garch-kalman-apr-migration.md         # HMM (shipped)
├── 2026-06-20-alphaengine-architecture.md                # v3.0 canonical
├── 2026-06-20-alphaengine-ic-spec.md                     # IC methodology
├── 2026-06-20-analogengine-design.md                    # Future work
├── 2026-06-23-feature-factory-single-path-refactor.md  # Feature Factory
├── 2026-06-24-feature-cache-batch-fix-design.md         # Feature Factory
├── 2026-06-24-feature-factory-batch-integrity.md       # Feature Factory
├── 2026-06-25-v30-alpha-lifecycle-schema.md             # alpha_events schema
├── 2026-06-26-renaissance-optimization-roadmap.md       # IC engine + beyond
└── archive/                                             # 65+ historical docs
    ├── 2026-02-... (early v2.x design)
    ├── 2026-03-... (v2.x implementation)
    ├── 2026-04-... (v2.x hardening)
    ├── 2026-05-... (v2.x foundation)
    ├── 2026-06-... (v2.x → v3.0 transition)
    └── phase-127-* (historical calibration logs)
```

---

## Execution Plan

### Step 1: Delete Category A (37 files)

```bash
cd /home/bg/dev/indicagent/docs/plans

# Delete v2.x signal pipeline docs (21 files)
rm 2026-06-02-intelligence-pipeline-signal-integrity.md
rm 2026-06-03-intelligence-platform-strategic-review.md
rm 2026-06-04-signal-confidence-pipeline-hardening-plan.md
rm 2026-06-04-signals-screen-renaissance-plan.md
rm 2026-06-05-signal-trade-card-plan.md
rm 2026-06-05-stop-target-hardening.md
rm 2026-06-06-backfill-signal-integrity-plan.md
rm 2026-06-07-signal-quality-crisis-root-cause-analysis.md
rm 2026-06-07-trade-framing-architecture-analysis.md
rm 2026-06-09-signal-refactor-deferred-todo.md
rm 2026-06-11-signal-replay-architecture-plan.md
rm 2026-06-12-i2-persistence-design.md
rm 2026-06-13-i7-onset-detection-design.md
rm 2026-06-14-phase-126-signal-quality-audit-results.md
rm 2026-06-14-phase-126-signal-universe-hardening.md
rm 2026-06-14-phase-126-usdjpy-diagnostic.md
rm 2026-06-14-v2.10-signal-architecture-refactor.md
rm 2026-06-17-phases-131-133-signal-corpus-integrity.md
rm 2026-06-20-i7-alpha-scorer-transition.md
rm 2026-06-25-alphaengine-phase-d-prerequisites.md

# Delete cancelled phase docs (1 file)
rm 135-REVIEWS.md
```

### Step 2: Archive Category B (16 files)

```bash
# Move v2.x foundation docs to archive
mv 2026-06-03-sse-broadcaster-hardening.md archive/
mv 2026-06-05-pending-ttl-expiry-fix.md archive/
mv 2026-06-06-glossary-enforcement-plan.md archive/
mv 2026-06-13-parameter-store-full-plugin-migration.md archive/
mv 2026-06-14-phase-126-pipeline-annotation-layer.md archive/
mv 2026-06-17-simplify-skipped-four.md archive/
mv 2026-06-18-cleanup-a-through-e.md archive/
mv 2026-06-18-post-reboot-repair-design.md archive/
mv 2026-06-18-timeframe-propagation-fix.md archive/
mv 2026-06-19-replay-optimization-design.md archive/
mv 2026-06-23-feature-factory-single-path-refactor.md archive/
mv 2026-06-24-feature-cache-batch-fix-design.md archive/
mv 2026-06-24-feature-factory-batch-integrity.md archive/

# Move Phase 127 logs to archive
mv phase-127-calibration-retrain-log.md archive/
mv phase-127-replay-log.md archive/
mv phase-127-validation-report.md archive/
```

### Step 3: Verify Active Doc Count

```bash
# Should show ~16 active docs
ls -1 docs/plans/*.md | wc -l

# Should show ~65 archived docs
ls -1 docs/plans/archive/*.md | wc -l
```

---

## What Jim Simons Would Demand

> "You have 81 planning documents for a system that doesn't exist. The v2.x pipeline is archived. Why are its design docs still in the active directory?"
> 
> "Every document in `docs/plans/` should describe either the current system or the next 6 months of work. Anything else is archive material."
> 
> "Decision fatigue kills organizations. When you have 80 plans, you have no plans. Reduce to the essential. Archive the rest."

**The Renaissance standard:** **10-15 active planning docs maximum.** Anything more dilutes focus and creates confusion about what's current.

---

## Expected Outcome

**Before cleanup:** 81 active docs + 49 archived = 130 total planning docs  
**After cleanup:** 16 active docs + 65 archived = 81 total planning docs

**Benefits:**
1. **Clarity:** New developers see only current v3.0 architecture
2. **Focus:** Active planning directory reflects next work, not historical baggage
3. **Maintainability:** No confusion about which docs describe the live system
4. **Searchability:** Active directory searches return relevant v3.0 results only

**Historical preservation:** All deleted/archived docs remain in `docs/plans/archive/` for reference. Nothing is lost—just moved out of the critical path.
