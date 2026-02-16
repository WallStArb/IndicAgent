# Claude Skills Design — IndicAgent Project Skills

**Date:** 2026-02-15
**Status:** Approved

## Skills

### 1. `add-plugin` — Process orchestrator for new intelligence plugins
- Rigid gate-by-gate: design → plan → implement → test → register → wire → docs
- References superpowers skills for generic phases (brainstorming, writing-plans, TDD)
- Embeds IndicAgent-specific gates: tier directory, plugin list, registration, doc sync
- Final gate: audit registry count, update 4 doc files, commit

### 2. `plugin-reference` — Protocol & interface reference
- IndicatorPlugin / PatternPlugin protocols from `src/intelligence/plugins.py`
- Tier → directory → plugin list mapping table
- `frames` dict structure, registration pattern, test conventions
- Example plugin skeleton

### 3. `wire-pipeline` — Dashboard & pipeline integration checklist
- 7-step rigid checklist for wiring new tiers
- Embeds gotchas: 3 demo-data sites, SymbolData interface, SSE parsing pattern
- Verify gates: `next build` + `pytest`

## Location
All in `.claude/skills/` within the repo (project-specific).
