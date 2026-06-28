# Phase 098: DSPy Offline Prompt Optimizer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-02
**Phase:** 098-dspy-offline-prompt-optimizer
**Areas discussed:** DSPy optimizer design, prompt_versions table design, Data gate + run schedule, A/B comparison report + promotion gate

---

## DSPy Optimizer Design

| Option | Description | Selected |
|--------|-------------|----------|
| BootstrapFewShot | Selects labeled examples as few-shot demos. Fast, deterministic, works well with local models. | ✓ |
| MIPROv2 | Bayesian instruction + few-shot optimization. Requires meta-LLM calls during optimization. | |
| COPRO | Coordinates prompts across a pipeline. Overkill for single-agent optimization. | |

**Optimizer choice:** BootstrapFewShot
**Notes:** User deferred to first-principles reasoning. Key rationale: MIPROv2 makes LLM calls during optimization on the same local Ollama model used in production — circular cost. BootstrapFewShot is deterministic, fast, interpretable, and composes cleanly with PROMPT_REGISTRY.

| Option | Description | Selected |
|--------|-------------|----------|
| parse_success rate | Binary, directly attributable to prompt quality. Clean SoC signal. | ✓ |
| Win rate | Confounded by market conditions, regime, full pipeline — not attributable to prompt. | |
| Composite: parse_success + pnl_r | More ambitious, harder to attribute improvements. | |

**Training signal:** `parse_success`
**Notes:** User deferred to first-principles reasoning. parse_success is the only signal cleanly attributable to prompt quality. win rate and pnl_r depend on market conditions outside the prompt's control.

| Option | Description | Selected |
|--------|-------------|----------|
| Per-agent independently | Each agent compiled independently. Ineligible agents skipped. No cross-agent coupling. | ✓ |
| Single batch, all agents | One DSPy program across all agents. Violates SoC. | |

**Run scope:** Per-agent independently

| Option | Description | Selected |
|--------|-------------|----------|
| Read from PROMPT_REGISTRY, write to DB | Optimizer reads ACTIVE_VERSION template, writes compiled variant to prompt_versions JSONB. No file changes. | ✓ |
| Write compiled prompts back to prompt files | Modifies Python prompt files from batch job. Creates git conflicts, breaks reproducibility. | |

**Interface pattern:** Read from PROMPT_REGISTRY, write to DB

---

## prompt_versions Table Design

| Option | Description | Selected |
|--------|-------------|----------|
| agent_id + version_tag + compiled_prompt JSONB + metadata | Transparent, queryable, inspectable. Status column enables A/B routing via DB field flip. | ✓ |
| Full DSPy program as binary blob | Black box — not queryable or inspectable. Tightly coupled to DSPy version. | |

**Schema choice:** JSONB with status enum (candidate/active/retired)
**Notes:** User deferred to first-principles reasoning. JSONB keeps compiled program transparent and queryable. Status field enables routing changes without application code changes.

| Option | Description | Selected |
|--------|-------------|----------|
| Load at startup, cache in memory | DAG Invariant 3: no DB in live path. Same pattern as contracts, calibration curves. | ✓ |
| Read from DB on every LLM call | Adds DB round-trip to hot path. Violates invariant. | |

**Inference-time loading:** Startup only, cached in memory

---

## Data Gate + Run Schedule

| Option | Description | Selected |
|--------|-------------|----------|
| Skip ineligible agents, optimize eligible | Per-agent gate. Independent agents, no blocking. Log skipped agents with row counts. | ✓ |
| Abort if any agent below threshold | All-or-nothing. One low-volume agent blocks all optimization. | |

**Data gate behavior:** Skip ineligible, optimize eligible
**Notes:** Per-agent independence is the same principle as plugin independence in the I1–I7 pipeline.

| Option | Description | Selected |
|--------|-------------|----------|
| Weekly (Monday 2am ET) | Matches ML batch cadence. Enough time for trade lifecycle to settle. | ✓ |
| Nightly | Too frequent — would hit data gate most nights, producing redundant skipped runs. | |
| Monthly | Too slow for prompt drift correction. | |

**Schedule:** Weekly, Monday 02:00 ET

---

## A/B Comparison Report + Promotion Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-promote with regime-balance guard | Criteria: +2pp parse_success, n>=100, >=20 examples per regime type. Extend window 7 days if regime balance not met. | ✓ |
| Manual CLI command after reviewing report | Human reviews data first. Slower, introduces bias and delay. | |

**Promotion mechanism:** Auto-promote after 7 days with regime-balance guard
**Notes:** User deferred to first-principles reasoning. If criteria can be stated precisely enough to review manually, they can be automated. Regime balance guard prevents confounded single-regime promotions.

| Option | Description | Selected |
|--------|-------------|----------|
| Flat file in logs/ + structlog event | Same pattern as ml_training_agent. Source data already queryable in llm_calls. | ✓ |
| New DB table (ab_comparison_results) | Redundant copy of data already in llm_calls. Adds maintenance overhead. | |

**Report format:** `logs/dspy_optimizer_report_{date}.json` + structlog summary

---

## Claude's Discretion

- DSPy `Signature` field naming conventions for this domain
- Internal retry/timeout handling if Ollama is unavailable during optimization
- Exact JSONB structure of `compiled_prompt` field
- Whether to use the production Ollama model or a separate optimization model

## Deferred Ideas

- Cross-agent joint optimization (COPRO) — violates SoC, future phase only if parse failures persist
- Hot-swap prompts without service restart — requires Kafka topic for prompt updates (MEDIUM-02 from architecture review)
- Prompt optimization for non-LLM plugins — not applicable
