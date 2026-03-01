# Phase 01: Code Quality Sprint - Context

**Generated:** 2026-03-01

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-03-01)

**Core value:** Production-grade code with zero blocking defects

**Current focus:** v1.0 code quality sprint — resolve all scanner findings across I1-I7 plugins and reduce technical debt

---

## Problem Space

Code quality issues have been identified through multiple scans:
- ruff lint: 206 issues (E501, E741, PLR errors, magic numbers, elif misuse, etc.)
- Code complexity: O(N³) in head_shoulders.py, O(N²) in 8 pattern files
- Correctness bugs: plugin state isolation (62 plugins), missing xgroup recovery, unconditional signal rewind
- Performance issues: sequential warmup reads (14,400+ Redis calls), sequential plugin execution
- Code duplication: 30+ duplicate patterns across 5+ services
- Configuration: empty symbols list, hardcoded contract expirations

---

## User Stories

**Primary goal:** Fix all critical and high-priority code quality issues to bring codebase to production-grade standards.

**User personas:**
- Platform engineer: Needs actionable technical descriptions with clear success criteria
- Platform operator: Focuses on service health and configuration correctness
- Code reviewer: Wants clear code impact assessment and test coverage validation

---

## Constraints

| Type | Constraint |
|-------|-----------|
| Stack | Python 3.13, FastAPI, TimescaleDB, asyncpg, DragonflyDB — no stack changes for this milestone |
| Timeline | No fixed deadline — quality improvements delivered incrementally |
| Testing | 796 unit tests passing, 0 ruff errors target |
| Performance | Focus on correctness first, then optimize hot paths |
| Dependencies | No new external dependencies |

---

## Requirements

See: `.planning/REQUIREMENTS.md` (updated 2026-03-01) for full scope.
