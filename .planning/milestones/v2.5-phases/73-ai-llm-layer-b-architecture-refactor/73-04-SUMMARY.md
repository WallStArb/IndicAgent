---
phase: 73-ai-llm-layer-b-architecture-refactor
plan: 04
status: completed
commit: edf3bd33
subsystem: ai-agent-directory-structure
tags: [module-move, BaseAIAgent-rebase, narrative-tf-gate, mandate-structure]

dependency_graph:
  requires: [73-02]
  provides: [D-23, D-24, D-25, D-26, D-27, D-34, D-35]
  affects: [alpha-agents, narrative-agent, ai-infrastructure]

tech_stack:
  added: []
  patterns:
    - Mandate-based AI agent directory structure (alpha/, narrative/, risk/)
    - BaseAIAgent rebase replacing SwarmBaseAgent
    - AgentOutput replacing AgentResult in all alpha + narrative agents
    - Narrative TF gate via _NARRATIVE_TFS frozenset

key_files:
  created:
    - path: src/intelligence/ai/alpha/skeptic_agent.py
      purpose: SkepticAgentComputeAgent extending BaseAIAgent, AgentOutput return (D-23, D-34)
    - path: src/intelligence/ai/alpha/skeptic_prompts.py
      purpose: Prompt file moved from swarm/agents/
    - path: src/intelligence/ai/alpha/correlation_agent.py
      purpose: CorrelationAgentComputeAgent extending BaseAIAgent (D-24, D-34)
    - path: src/intelligence/ai/alpha/correlation_prompts.py
      purpose: Prompt file moved from swarm/agents/
    - path: src/intelligence/ai/alpha/volume_agent.py
      purpose: VolumeAgentComputeAgent extending BaseAIAgent (D-25, D-34)
    - path: src/intelligence/ai/alpha/volume_prompts.py
      purpose: Prompt file moved from swarm/agents/
    - path: src/intelligence/ai/narrative/narrative_agent.py
      purpose: NarrativeComputeAgent with _NARRATIVE_TFS TF gate (D-26, D-35)
    - path: src/intelligence/ai/narrative/prompts.py
      purpose: Narrative prompt moved from intelligence/narrative/
    - path: src/intelligence/ai/narrative/parsers.py
      purpose: Narrative parser moved from intelligence/narrative/
    - path: src/intelligence/ai/risk/__init__.py
      purpose: Risk group placeholder (D-27)
---

## What Was Delivered

Moved 3 alpha agents + 3 prompt files from `src/intelligence/swarm/agents/` to `src/intelligence/ai/alpha/`. Moved narrative module from `src/intelligence/narrative/` to `src/intelligence/ai/narrative/`. Rebased all 4 agents onto `BaseAIAgent` (replacing `SwarmBaseAgent`) and migrated return types from `AgentResult` to `AgentOutput`. Added narrative TF gate rejecting non-standard timeframes before any LLM call. Created risk group placeholder.

Old files preserved in place — Plan 05 updated the services that import them.

## Decisions Closed

- D-23/D-24/D-25: Alpha agent module paths confirmed as `src/intelligence/ai/alpha/`
- D-26: Narrative module path confirmed as `src/intelligence/ai/narrative/`
- D-27: Risk placeholder created at `src/intelligence/ai/risk/__init__.py`
- D-34: All agents extend `BaseAIAgent` — `SwarmBaseAgent` eliminated from new files
- D-35: `_NARRATIVE_TFS = frozenset({"5m", "15m", "1h", "4h", "1d"})` — TF gate hard-rejects before LLM call
