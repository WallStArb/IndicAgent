# Documentation Refactoring — Design

**Date:** 2026-03-01
**Status:** Approved
**Scope:** Comprehensive audit and update of stale documentation across README.md, docs/STATUS.md, and docs/architecture/*

## Problem

Multiple documentation files contain stale information:
- Version numbers (4.1.0 vs 5.6.0)
- Plugin counts (31, 62 vs 63)
- Test counts (123, 781 vs 803)
- Contract lists (missing FX/crypto, contains removed contracts)
- LLM providers (missing ZAI/GLM-5)
- Phase completion status (missing Phases 8-9)
- Incomplete plugin lists (only showing subset)

This causes confusion for anyone reading the docs and reduces trust in documentation accuracy.

## Design

### Files to Update

| File | Priority | Stale Issues Summary |
|------|------------|---------------------|
| `README.md` | High | Version, stats, contracts, LLM providers, phase count |
| `docs/STATUS.md` | High | Version, test count, plugin count, LLM providers, Phase 8-9 status, typos |
| `docs/architecture/intelligence-bus.md` | Medium | Version, LLM providers |
| `docs/concepts/intelligence-tiers.md` | Medium | Version, test count, plugin count, I8 (add ZAI) |
| `docs/architecture/plugin-registry-and-dag-execution.md` | Medium | Version, plugin count, test count, incomplete plugin list, LLM providers |

**Total:** ~32 bite-sized tasks across 5 docs

### Approach: Single Comprehensive Plan

Create one detailed implementation plan with all ~32 tasks grouped by file. Execute in sequence with checkpoints after each major doc is complete.

**Rationale:**
- Efficient context reuse (only read each doc once)
- Consistent style and version numbers across all docs
- Can batch commits per file
- Easy to track overall progress

### Task Organization

- Group tasks by file (all README.md tasks together, then STATUS.md tasks, etc.)
- Each task is a specific update (one line or section)
- Verify counts using actual codebase before updating

### Version Strategy

- Current version: `5.6.0` (from CLAUDE.md line 3)
- Current date: `2026-03-01`
- Update all docs to match

### Verification Steps

**Before updating each count, verify:**

```bash
# Plugin count
grep -c "register_" src/intelligence/register_plugins.py

# Test count
pytest tests/unit/ --co -q | grep "test session"

# Contract count
.venv/bin/python -c "from src.config.settings import get_active_contracts; print(len(get_active_contracts()))"

# LLM providers
ls src/intelligence/llm_providers.py | grep -c "Provider"
```

**For count verification failures:**
- If grep fails or returns unexpected value, log warning and skip update
- Commit with message: "docs: update X count (Y→Z) - verification failed, skipping"

### Error Handling

**For version updates:**
- Verify version in CLAUDE.md (source of truth) first
- If CLAUDE.md doesn't match expected, note in commit

**For contract list updates:**
- Cross-reference with `src/config/settings.py` `get_active_contracts()` output
- Ensure all contracts in settings are documented
- Remove any not in settings

**For LLM provider updates:**
- Cross-reference with `src/intelligence/llm_providers.py`
- Ensure all provider classes listed (ZAIProvider, OpenRouterProvider, OllamaProvider)

### Specific Updates by File

**README.md:**
1. Version 5.6.0, date 2026-03-01
2. 63 plugins (not 62)
3. 803 tests (not 784)
4. 24 contracts (not 23)
5. Remove BZ, NG, SR1, BTC from contract list
6. Add EURUSD, GBPUSD, USDJPY, USDCHF, ETHUSD, SOLUSD
7. Add ZAI (GLM-5) to LLM providers section
8. Update I8 section to mention ZAI as primary
9. "All 10 phases complete" (not 9)
10. Update AI narrative service description to mention ZAI

**docs/STATUS.md:**
1. Version 5.6.0, date 2026-03-01
2. 803 tests (not 781)
3. 63 plugins (not 62)
4. Phases 0-9 complete (not 0-7)
5. Add ZAI to LLM providers
6. Mark Phases 8-9 as complete
7. Fix typo "indicagent-signal-tracker" → "indicagent-signal-tracker"

**docs/architecture/intelligence-bus.md:**
1. Version 5.6.0, last updated 2026-03-01
2. Add ZAI to LLM providers section

**docs/concepts/intelligence-tiers.md:**
1. Version 5.6.0, last updated 2026-03-01
2. 63 plugins (not 62)
3. 803 tests (not 781)
4. I8 section: Add ZAI (GLM-5) as primary
5. Update "OpenRouter available" to "OpenRouter + ZAI available"

**docs/architecture/plugin-registry-and-dag-execution.md:**
1. Version 5.6.0, last updated 2026-03-01
2. 63 plugins (not 31)
3. 803 tests (not 123)
4. Update I1 indicator list from 16 to 23 (add missing indicators)
5. Add ZAI to LLM providers section
6. Update "OpenRouter for cloud LLM" to "OpenRouter + ZAI for cloud LLM"

### Summary

**Files:** 5
**Tasks:** ~32
**Estimated time:** 1-2 hours
**Risk:** Low - straightforward string replacements with verification

**Key deliverable:** All documentation reflects v5.6.0, v1.0 shipped, 63 plugins, 803 tests, 24 contracts, ZAI LLM provider included.
