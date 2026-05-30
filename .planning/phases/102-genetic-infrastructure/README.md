# Phase 102: Genetic Infrastructure

**Milestone:** v2.8 Evolvable AI Foundation
**Status:** Planned
**Timeline:** ~1-2 weeks
**Plans:** 5 plans

## Goal

Build the genome data model, gene bank, frozen archive, and decomposition
algorithms that make agents traceable and reusable across generations.

## Plans

1. **Plan 01:** AgentGenome — core data model and provenance enforcement
2. **Plan 02:** Frozen archive — TimescaleDB hypertable for genome storage
3. **Plan 03:** Gene bank extraction — best chromosome segment catalog
4. **Plan 04:** Decomposition algorithms — chromosome extraction from failed agents
5. **Plan 05:** Resurrection evaluation — test archived genomes against new data

## Plan 01 Detail: AgentGenome Foundation

Extracted from 095-07 planning. This is the prerequisite for everything else
in phases 102 and 103.

### Chromosome Schema

Per eAI research (`docs/ideas/ai-03-evolvable-ai-agents.md`), six independently
heritable and mutable chromosomes:

| Chromosome | What it encodes | Typical mutations |
|---|---|---|
| `system_prompt` | Chain-of-thought strategy, reasoning instructions, persona | Reword CoT, add/remove reasoning steps, shift analytical frame |
| `model_adapter` | Fine-tuned LoRA adapter weights for task specialization | Blend two adapter weight sets, fine-tune on different outcome subsets |
| `config_params` | Thresholds, timeframe weights, signal filters, scoring weights | Nudge confidence threshold ±5%, swap timeframe priority, adjust lookback |
| `tool_set` | Which data sources, APIs, analysis tools the agent can call | Add data feed, remove underperforming indicator, reorder tool calls |
| `guardrails` | Constraints on what the agent can/cannot do | Tighten regime filter, add volatility guard, relax false-positive screen |
| `logic` | Entire analysis approaches, plugin implementations | LLM writes new variant of analysis function |

### AgentGenome Dataclass

```python
@dataclass(frozen=True)
class AgentGenome:
    genome_id: str          # SHA256 of all chromosome hashes — deterministic, forgery-proof
    agent_id: str           # Links to shadow_registry
    parent_ids: list[str]   # Empty list = generation 0; enables full ancestry chain
    generation: int         # Distance from generation 0
    chromosome_hashes: dict[str, str]  # {chromosome_name: sha256_hash}
    created_at: datetime
```

Genome hash is computed as `SHA256(sorted(chromosome_hashes.values()))` — deterministic
regardless of dict ordering. Frozen dataclass prevents post-construction tampering.

### DB Migration

`production/migrations/110_genome_tracking.sql`:
- New hypertable `agent_genomes` (genome_id, agent_id, parent_ids, generation, chromosomes JSONB)
- Add `genome_id` column to `llm_calls` — links every LLM call to the genome that made it
- Index on `(agent_id, generation)` for lineage queries

### Storage Layout

```
agents/
  active/     # JSON genome files for live agents
  shadow/     # JSON genome files for shadow agents
  demoted/    # Soft-death preserved genomes (not deleted on demotion)
```

### Provenance Enforcement

No agent registered without a known genome_id. Registration checks:
- `genome_id` present and matches computed hash
- `parent_ids` either empty (gen 0) or all exist in `agent_genomes` table
- Unknown ancestry is a hard rejection

## Plans 02-05 Detail

**Frozen archive (Plan 02):** `agent_genomes` hypertable stores all genomes ever
created — active, shadow, and demoted. Compression after 30 days. Retention: permanent
(genomes are small; lineage is the irreplaceable asset).

**Gene bank extraction (Plan 03):** For each demoted agent, extract the highest-scoring
chromosome segments (ranked by contribution to composite fitness). Store in `gene_bank`
table as independently reusable segments. Phase 103 recombination operators draw from here.

**Decomposition (Plan 04):** Algorithm to attribute fitness delta to specific chromosome
changes across parent-child pairs. Uses the llm_calls genome_id link to correlate
chromosome variants with outcome distributions.

**Resurrection evaluation (Plan 05):** Test archived genomes against recent market data
(out-of-sample from their demotion period). If a previously-demoted genome shows revived
fitness, it becomes eligible for re-promotion without full re-incubation.

## Documentation

eAI research: `docs/ideas/ai-03-evolvable-ai-agents.md`
ROADMAP: `.planning/ROADMAP.md`
