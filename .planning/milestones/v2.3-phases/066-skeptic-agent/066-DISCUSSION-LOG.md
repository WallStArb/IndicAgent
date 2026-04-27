# Phase 66: SkepticAgent - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-24
**Phase:** 066-skeptic-agent
**Areas discussed:** LLM Prompt Design, Failure Probability Mapping, Trigger & Orchestration, Validation Framework

---

## LLM Prompt Design

| Option | Description | Selected |
|--------|-------------|----------|
| Full context dump | Send full SwarmContext as structured JSON. Higher token cost but richer reasoning. | ✓ |
| Curated feature subset | Only features that prior analysis correlated with failure. Cheaper, faster. | |
| Natural language summary | Human-readable market narrative string. Cheaper tokens but less precise. | |

**User's choice:** Full context dump
**Notes:** "The whole point is to use LLMs to distill more intelligence and find things deterministic logic missed."

| Option | Description | Selected |
|--------|-------------|----------|
| Structured JSON | failure_probability, confidence, risk_factors, reasoning. Parseable, auditable. | ✓ |
| Single scalar only | Just failure probability. Minimal but no interpretability. | |
| Free text + parse | Free text reasoning, extract probability via regex. Flexible but fragile. | |

**User's choice:** Structured JSON

| Option | Description | Selected |
|--------|-------------|----------|
| Prompt versioning in code | prompt_registry.py with version ID, tracked in features JSONB. | ✓ |
| Database-stored prompts | Load dynamically from DB. Flexible but adds hot-path DB dependency. | |
| No versioning | Hard-code prompt. Simplest but no A/B testing. | |

**User's choice:** Prompt versioning in code

---

## Failure Probability Mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Linear: 1.0 - failure_prob | Simple, interpretable. Shadow-track raw values for optimization. | ✓ |
| Penalty-only threshold | Only penalize high failure_prob, ignore low. Conservative. | |
| Bidirectional [0.5, 1.5] | Let Skeptic both boost and penalize. | |

**User's choice:** Start linear, let data determine optimal mapping. Transfer function as separable concern.
**Notes:** Confidence-weighted: `final_mult = (1.0 - failure_prob) * llm_confidence`. User emphasized: "never overwrite data, every adjustment is separate auditable column." Follows CIS attribution pattern.

---

## Trigger & Orchestration

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone Kafka consumer | Consume intelligence.i7.signals. Event-driven, independent failure domain. | ✓ |
| Timer + DB reader | Poll signal_ledger every 30-60s. Simplest but higher latency. | |
| In-process async | Run inside pipeline. Lowest latency but crash coupling. | |

**User's choice:** Standalone Kafka consumer
**Notes:** User clarified that Kafka IS the inter-service transport in the DAG (the "Kafka as sink" principle applies only to I1→I7 in-process computation, not inter-service communication). Event-driven for low latency. Production impact from day one.

TF filter: 5m+ only (~50-100 signals/day, manageable LLM cost).

User initially challenged the Kafka approach, then confirmed it after clarifying the architecture principle.

---

## Validation Framework

| Option | Description | Selected |
|--------|-------------|----------|
| Per-segment failure rate baseline | Historical failure rate per (regime, tf, setup) from signal_ledger. | ✓ |
| Global average failure rate | Simple overall rate. Easier but masks segment-level value. | |

**User's choice:** Per-segment failure rate baseline

| Option | Description | Selected |
|--------|-------------|----------|
| Correlation + segment analysis | Pearson(skeptic_failure_prob, actual_outcome) per segment. Full breakdown. | ✓ |
| Binary accuracy | What % of time did failure_prob > 0.5 predict failure? Simple but ignores calibration. | |

**User's choice:** Correlation + segment analysis

| Option | Description | Selected |
|--------|-------------|----------|
| Per-segment stats gate | ρ ≥ 0.3 AND p < 0.05 AND N ≥ 30 per segment. Individual promotion. | ✓ |
| Manual review | Look at report and decide. | |

**User's choice:** Per-segment stats gate

---

## Claude's Discretion

- Exact prompt wording and system message
- Signal_ledger migration column names
- Systemd unit configuration details
- Naive baseline script implementation

## Deferred Ideas

- Deterministic heuristic scorer (Path A) — future phase
- Dashboard UI for skeptic accuracy — future phase
- Additional swarm agents — blocked on SkepticAgent validation
- Prompt A/B testing infrastructure — single version first
