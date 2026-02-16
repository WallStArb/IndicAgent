# Documentation Audit

**Version:** 1.1.0  
**Last Updated:** 2026-02-13  
**Status:** Post-audit fixes applied; docs folder date pass complete

## Summary

Cross-check of README, CLAUDE.md, and key docs against the codebase. Overall the docs are **up to date** with version 2.8.0, I3+I4+I5 complete, 22 plugins, 110 unit tests, and current services. A few inconsistencies were found and fixed.

## What Was Aligned

- **README.md** – 2.8.0, 2026-02-12, 22 plugins, I3/I4/I5, 110 tests, intelligence_processor_service, config paths, project structure.
- **CLAUDE.md** – Same version/status; plugin counts; service list; I1–I8 tier status; dead code ~6,100 lines; test count 110.
- **docs/README.md** – 4.0.0, points to current-status-and-priorities.
- **docs/development-roadmap.md** – Redirects to current-status-and-priorities; quick summary matches.
- **docs/current-status-and-priorities.md** – Matches README/CLAUDE status and priorities.
- **docs/architecture/intelligence-tiers.md** – 3.0.0, I1–I5 complete, 22 plugins.
- **Unit test count** – `pytest tests/unit/ --collect-only -q` reports 110 tests.

## Fixes Applied (2026-02-12)

1. **CLAUDE.md – API references**  
   Replaced "SocketIO: https://socket.io/docs/v4/" with a short note that SSE (`src/api/routes/sse.py`) is the primary real-time API and Socket.IO on port 8001 is optional.

2. **services/README.md – Development mode**  
   Corrected service name and added config: `indicator_processor_service.py` -> `indicators_processor_service.py --config config/indicator_processor_service.json`.

3. **dashboard/README.md**  
   - Features: "WebSocket Integration" -> "Real-time updates: SSE or Socket.IO (env-configurable)".  
   - Features: "WebSocket API" -> "API: Backend health, indicators, market data, and SSE/Socket.IO real-time endpoints".  
   - Features: "Pattern Detection: Ready for MACD divergence (next phase)" -> "Pattern Detection: I5 plugins (RSI divergence, Bollinger squeeze, volume divergence, confluence) with structure/context panels".  
   - Data Sources: clarified backend stream consumption and real-time API (SSE vs Socket.IO).

4. **docs/development-roadmap.md**  
   Typo: "** Continue" -> "**Continue".

## Notes (No Change)

- **Config files** – Docs reference `config/indicator_processor_service.json`, `config/intelligence_processor.json`, etc. These may live in `config/` as untracked or repo-specific; path convention in docs is correct.
- **services/README.md** – Diagram and table do not list `intelligence_processor_service` or `coordination_parallel_service`. They are described in the root README; adding them to the services diagram could be a follow-up.
- **dashboard/DASHBOARD_README.md** – Still describes WebSocket and "MACD divergence (current development)". Consider updating to match dashboard/README.md (SSE/Socket.IO, I5 patterns) if that file remains in use.
- **.cursorrules** – Project rules (no version/date); no conflict with CLAUDE.md.

## Additional Improvements (2026-02-12)

- **dashboard/DASHBOARD_README.md** – Rewritten to current state: version/date header, I3/I4/I5 panels, SSE/Socket.IO, price hero/indicator grid/pattern/structure/context layout. Removed reference to non-existent `start_dashboard_system.py`.
- **production/README.md** – Version 2.3.0, date 2026-02-12; added pointer to root README and services/README for full service list; removed duplicate version block in Runtime section.
- **services/README.md** – Added note that intelligence-processor and coordination_parallel_service are part of the platform with link to root README.
- **docs/README.md** – Added "Maintenance" section with link to documentation-audit.md.
- **docs/documentation-standards.md** – Added documentation-audit.md to directory structure list.

## Optional Next Steps Completed (2026-02-12)

**Architecture docs:**
- **layered-architecture.md** – Service names corrected to `indicators_processor_service.py` and `indicators_enhanced_service.py`; "13+" changed to "12" indicator plugins.
- **plugin-registry-and-dag-execution.md** – Removed emoji from section header (per documentation standards).
- **stream-schemas.md** – Added one-line note: "I1-I5 schemas are in production use; I6-I8 are defined for future tiers."
- **comprehensive-intelligence-architecture.md** – Corrected indicator service filename and pipeline diagram (indicators_enhanced_service / intelligence_processor_service).
- **intelligence-tiers.md** – Data foundation service name updated to indicators_processor_service and indicators_enhanced_service.

**Intelligence docs:**
- **ai-intelligence-architecture.md** – Executive summary now states "I1-I5 are operational (22 plugins); this doc focuses on planned I6-I8."
- **market-intelligence-strategy.md** – Version 2.2.0, date 2026-02-12, status updated to "I1-I5 operational; doc guides I6-I8 evolution."
- **ai-intelligence-resources.md** – Version 2.2.0, date 2026-02-12, status note added for I1-I5 operational.

**Planning:**
- **planning/readme.md** – Standard version/date header; prominent note that planning docs are strategic/historical (Aug 2025) and that current runbooks are in Current Status & Priorities and CLAUDE.md.
- **planning/hybrid-intelligence-implementation.md** – Service names in table and code comment updated to indicators_processor_service / indicators_enhanced_service / intelligence_processor_service.
- **planning/enhanced-intelligence-architecture.md** – Service names and "Current Limitations" updated to reflect intelligence_processor_service (I3/I4/I5) and correct indicator service filenames.

## Final sweep: out-of-date info (2026-02-12)

**Enhanced-intelligence-architecture:** Version 3.2.0, date 2026-02-12; "13+" → "12" indicator plugins; removed executor.py/shadow_runner.py/join.py from component list and added "(Removed)" note.

**Stream-schemas:** features.v1 description "13+" → "12 indicator plugins".

**Intelligence-value-add-progression:** Version 1.1.0, date 2026-02-12; "Current Reality Assessment" updated to I1-I5 operational (22 plugins); "13+" → "12"; "11+ plugins" → "22 registered plugins"; I2-I8 section replaced with accurate I2-I5 list and "I6-I8 Not Yet Implemented".

**Dates/status:** ai-agent-stack-map (2026-02-12, I1-I5 operational); intelligence-concepts-and-ideas (2026-02-12, I1-I5 operational); platform-expansion-strategy (2026-02-12, Current Focus line updated); robinhood-inspired-enhancements (2026-02-12, status "Reference"); research-ideas (2026-02-12).

**Indicator counts:** dashboard/DASHBOARD_README and dashboard/README "13+" → "12 indicator plugins"; root README "Technical Indicators (13+)" → "Technical Indicators (12 plugins)".

## Content review of changed files (2026-02-13)

Reviewed the six docs that had date-only updates for conflicts with current state. Fixes applied:

- **planning/hybrid-intelligence-implementation.md** — Clarified that I3/I4/I5 run in `intelligence_processor_service.py` (no separate pattern_detection_service).
- **planning/service-plugin-integration-plan.md** — Updated "Current State": integration complete, 22 plugins, removed outdated "two systems requiring bridge" and checkmark.
- **configuration/market-data-intelligence-configuration.md** — Note that contract symbols (ESU5, NQU5) are examples; use symbol_config or auto-discovery for current front-month.
- **planning/ideas/ai-agents-innovative-concepts-and-ideas.md** — Status clarified: I1-I5 implemented (22 plugins); doc describes future I8 concepts.
- **planning/ideas/ai-architecture-gaps-analysis.md** — Status clarified: I1-I5 operational; analysis focuses on gaps for future I8/agent runtime.
- **architecture-comparison-robinhood.md** — Note that implementation details may have evolved (see src/core); removed emojis from convergence table per documentation standards.

## Docs folder date pass (2026-02-13)

Updated **Last Updated** to 2026-02-13 for any non-archive doc that still had 2025: `planning/hybrid-intelligence-implementation.md`, `planning/ideas/ai-agents-innovative-concepts-and-ideas.md`, `planning/ideas/ai-architecture-gaps-analysis.md`, `configuration/market-data-intelligence-configuration.md`, `architecture-comparison-robinhood.md`. Added **Last Updated** to `planning/service-plugin-integration-plan.md`. Archive docs (`_archive/`, `planning/_archive/`) left with historical dates.

## Recommendation

- Re-run this audit after major releases or when adding new services.  
- Keep version/date in README and CLAUDE.md in sync when changing status.
