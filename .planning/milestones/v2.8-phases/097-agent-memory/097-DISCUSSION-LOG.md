# Phase 097: Agent Memory - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-02
**Phase:** 097-agent-memory
**Areas discussed:** Technology selection, memory tier taxonomy, schema structure, Renaissance rigor constraints

---

## Technology Selection: Zep vs pgvector

| Option | Description | Selected |
|--------|-------------|----------|
| Zep | Managed episodic memory service — built-in session scoping, MMR reranking, automatic summarization. Adds a Docker container and network hop. 50ms p95 latency budget was tight for a remote service. | |
| pgvector | Already live in TimescaleDB (v0.8.2, HNSW support). Zero new infrastructure. Sub-5ms recall latency for filtered vector queries. Schema owned by us — full observability. Fits Renaissance "instrument everything" principle. | ✓ |

**Rationale for pgvector:** Phase 097's stated recall pattern — filter by `(regime, symbol, setup_type)` then rank by vector similarity — is pgvector's core use case. Zep's managed session summarization and higher-level SDK add no value for this access pattern. The latency win is substantial.

**Embedding model:** TBD — requires a dedicated embedding model (chat models do not produce embeddings). Options: `nomic-embed-text` via Ollama, `sentence-transformers` locally. To be decided in CONTEXT.md phase.

---

## Memory Tier Taxonomy

Eight tiers identified and agreed upon:

| Tier | Name | Description |
|------|------|-------------|
| 1 | Episodic recall | Retrieve N similar past setups as few-shot prompt context at `_compute()` time. Keyed by `(regime, symbol, setup_type)` + vector similarity on setup embedding. |
| 2 | Outcome-driven self-correction | Agents see their own historical prediction accuracy on similar conditions. Skeptic's calibrated failure_probability vs actual failure rate on matching setup cohort. |
| 3 | Cross-agent disagreement | Store episodes of strong inter-agent conflict (skeptic vs counterfactual). Surface as signal: "last 5 times agents disagreed this much on this setup type, 4 failed." |
| 4 | Narrative continuity | Narrative agent recalls past narratives for same symbol/regime — produces temporally coherent text rather than cold-start generation each bar. |
| 5 | Regime transition memory | Markov state machine over regime labels. "ES entered trending_up 4 bars ago; median duration is 23 bars; last 6 transitions, signal win rate was 71%." |
| 6 | Cross-symbol relational | "When ZN shows range compression while ES is in trending_up, ES pullback signals have 68% win rate vs 51% baseline." Multi-symbol state keyed episodes. |
| 7 | Operator annotations | Human-written notes attached to symbol/regime/timeframe with expiry. Structurally isolated from quant pipeline via `contaminates_quant` flag. |
| 8 | Confidence drift detection | SPC-style rolling stats (EWMA/CUSUM) over per-agent confidence distributions. Distributional shift detection via KS test, not just mean comparison. |

---

## Schema Structure Approaches

| Option | Description | Selected |
|--------|-------------|----------|
| A: Unified hypertable + 3 satellites | One `memory_episodes` hypertable (HNSW index) for tiers 1-4, 6. Three satellites for structured tiers 5, 7, 8. `memory_episodes_labeled` implemented as application-enforced view. | Rejected — view-based gate is a convention, not a structural guarantee. |
| B: Raw/labeled split + offline promotion | `memory_episodes_raw` (write-only from live pipeline) + `memory_episodes_labeled` (physical table, populated by background job on outcome resolution) + `memory_calibration_promoted` (offline-validated stats, the only table agents read for calibration). Three satellite tables unchanged. | ✓ |
| C: Kind-per-table | Eight tables, one per tier, separate HNSW indexes per kind. | Rejected — fragmented interface, duplicated regime epoch and lineage columns, no shared recall abstraction. |

**Why B over A:** The council (in Renaissance frame) rejected A on the grounds that view-based gates are conventions that break. The failure mode — accidentally querying unlabeled episodes and injecting noise as signal into live agent decisions — is silent and catastrophic. Physical table separation is a structural guarantee. Application code cannot accidentally bypass it.

**Why B requires offline promotion (not in original B framing):** Agents should never compute calibration statistics on-the-fly from raw episode queries. That is an online inference path over a live, growing dataset with no stability guarantees. Stats must be computed offline, validated (CI bounds, sample size gates, regime epoch filtering, selection bias correction), and promoted to `memory_calibration_promoted` before agents are permitted to read them.

---

## Renaissance / Simons Constraints (Non-Negotiable)

Four structural constraints agreed upon by the council before any schema decisions:

**C-01: Non-stationarity — regime epochs**
Markets are non-stationary. Episodes from different distributional periods are not comparable. Schema must carry `regime_epoch` (monotonically incrementing integer, increments on macro distributional shift detection) on every episode. Recall is weighted toward current epoch.

**C-02: Selection bias — n_eligible**
We only store episodes that generated a signal. The denominator (rejected setups) is invisible. Every episode must carry `n_eligible` (total setups evaluated in the same condition window) alongside `n_stored` so calibration stats can correct for the selection bias.

**C-03: No inference below N=30**
Matches existing `setup_performance` gate. `memory_calibration_promoted` must carry `sample_n`, `ci_lower`, `ci_upper`, `p_value`. A strict gate view refuses to surface stats where `sample_n < 30`. Application code must read only through this view — never raw.

**C-04: Feedback loop containment — lineage flag**
If memory influences agent outputs, and those outputs generate new episodes, we have a closed feedback loop. Every episode written under memory-assisted conditions must carry `memory_assisted: bool`. Offline calibration jobs must isolate memory-assisted episodes from training sets and test for feedback amplification separately.

---

## Hybrid Architecture Decision

| Option | Description | Selected |
|--------|-------------|----------|
| pgvector only | Full custom schema for all 8 tiers. Maximum control, zero external dependency. | Rejected — reinvents deduplication, contradiction resolution, graph traversal that maintained libraries provide and will keep improving. |
| Mem0 only | Mem0 as primary memory layer; custom fields in JSONB metadata. | Rejected — cannot structurally satisfy C-01 through C-04 (native columns and physical table separation required). |
| Hybrid | Mem0 for soft-memory tiers (3, 4, 6, 7); custom pgvector for hard-statistical tiers (1, 2, 5, 8). | ✓ |

**Rationale:** Mem0 is an actively maintained library in a fast-moving area. Riding its improvements in retrieval quality, graph traversal, deduplication, and temporal reasoning compounds in our favour without maintenance burden. The Renaissance constraints live entirely in the custom pgvector layer where we need them — Mem0 never touches those tables.

**Embedding model lock:** `nomic-embed-text` via Ollama, used by both Mem0 and the custom schema. Cross-querying is only valid when both sides share the same embedder.

**Tier routing:**
| Tier | Backend |
|------|---------|
| 1 (episodic recall) | Custom pgvector — regime_epoch, n_eligible, raw/labeled/promoted split |
| 2 (self-correction) | Custom pgvector — calibration promoted table, CI bounds |
| 3 (cross-agent disagreement) | Mem0 — fact extraction from agent outputs |
| 4 (narrative continuity) | Mem0 — LLM distillation of narrative facts, deduplication |
| 5 (regime transitions) | Custom pgvector — Markov state, duration distributions |
| 6 (cross-symbol relational) | Mem0 graph layer — instruments as nodes, co-regime states as temporal edges |
| 7 (operator annotations) | Mem0 — natural text-in, scoped retrieval |
| 8 (confidence drift) | Custom pgvector — SPC timeseries, EWMA/CUSUM |

**Unified interface:** `MemoryClient` routes to Mem0 or custom schema by tier. Agents call `MemoryClient.recall()` — they never know which backend.

---

## Final Agreed Architecture

**Episode layer (3 tables):**
- `memory_episodes_raw` — write-only from live pipeline; all signal-time data; outcome fields nullable
- `memory_episodes_labeled` — physical table (not view); populated by background job when `signal_outcomes` resolves; only source for episodic recall by live agents
- `memory_calibration_promoted` — offline-validated stats; gated by N≥30, CI bounds, epoch conditioning; only source for agent calibration reads

**Satellite layer (3 tables):**
- `memory_regime_transitions` — Markov state machine; transition timestamps, duration distributions, conditional win rates
- `memory_annotations` — operator notes; symbol/regime/timeframe scope; `expires_at`; `contaminates_quant` isolation flag
- `memory_calibration_spc` — SPC timeseries; EWMA/CUSUM stats per agent per setup cohort; source data for the offline promotion job

**Total: 6 tables.** No views enforced by convention. No inline stat computation in live agents.
