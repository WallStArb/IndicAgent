# Documentation Strategy & Restructuring Design

**Date:** 2026-02-17
**Status:** Approved - Ready for Implementation
**Context:** Addressing stale, duplicated, and incomplete documentation with industry-standard structure

---

## Problem Statement

Current documentation issues:
1. **No single source of truth** — Status/version info duplicated across README.md, CLAUDE.md, docs/current-status-and-priorities.md
2. **Information is outdated** — docs/README.md shows v4.0.0 with "22 plugins" while CLAUDE.md shows v4.2.0 with "38 plugins"
3. **Too much duplication** — Architecture concepts explained in multiple places
4. **Incomplete coverage** — Features exist in code without corresponding docs
5. **Poor navigation** — Hard to find "what should I read for X?"
6. **Archive confusion** — Both `_archive/` and `plans/archive/` directories exist

## Design Goals

1. **Single source of truth** — STATUS.md as canonical reference for current state
2. **Multi-audience support** — Serve external developers, future self, and AI assistants
3. **Industry-standard structure** — Based on proven patterns (Kubernetes, React, Next.js, PostgreSQL)
4. **Clear information hierarchy** — getting-started → guides → concepts → reference
5. **Hybrid migration** — New structure for living docs, existing structure becomes archive
6. **Maintainable** — Clear workflows for keeping docs up-to-date

---

## Chosen Approach: Industry-Standard OSS Structure

Based on patterns from Kubernetes, React, Next.js, PostgreSQL:

**Key characteristics:**
- Clear separation: tutorials → task-guides → concepts → API reference
- Role-based entry points (quickstart, contributing, CLAUDE.md)
- STATUS.md as single source of truth
- Every directory has navigation README.md
- Archive is read-only historical reference

**Why this approach?**
- Proven at scale (Kubernetes, PostgreSQL use this pattern)
- Multi-audience friendly (external devs, solo maintainer, AI assistants)
- Scales well as project grows
- AI-parseable with predictable paths

---

## Complete Directory Structure

```
docs/
├── README.md                          # Hub: "Start here for [your role]"
├── STATUS.md                          # ★ SINGLE SOURCE OF TRUTH ★
│
├── getting-started/                   # Onboarding & tutorials
│   ├── README.md                      # Navigation for this section
│   ├── quickstart.md                  # 5-min: clone → run → see dashboard
│   ├── installation.md                # Full setup: IBKR, Redis, TimescaleDB, Ollama
│   ├── first-plugin.md                # Tutorial: write a simple indicator
│   └── architecture-overview.md       # 10,000-foot view of the system
│
├── guides/                            # Task-oriented how-tos
│   ├── README.md
│   ├── adding-plugins.md              # Step-by-step plugin development
│   ├── running-services.md            # systemd, docker, health checks
│   ├── monitoring-debugging.md        # Logs, metrics, troubleshooting
│   ├── dashboard-development.md       # Frontend setup and development
│   ├── testing.md                     # Writing and running tests
│   └── database-management.md         # TimescaleDB, migrations, backups
│
├── concepts/                          # Deep architectural understanding
│   ├── README.md
│   ├── intelligence-tiers.md          # I1-I8 framework explained
│   ├── plugin-architecture.md         # Plugin system, DAG, registry
│   ├── data-pipeline.md               # Hot/warm/cold, Redis streams
│   ├── incremental-computation.md     # State-based calculations (141x boost)
│   ├── signal-lifecycle.md            # I7 trading signals, aggregation
│   └── regime-classification.md       # Context-aware intelligence
│
├── reference/                         # API & technical specifications
│   ├── README.md
│   ├── api/
│   │   ├── rest-endpoints.md          # FastAPI routes
│   │   ├── sse-protocol.md            # Real-time SSE streams
│   │   └── websocket-protocol.md      # Alternative WebSocket API
│   ├── plugins/
│   │   ├── overview.md                # Plugin protocol & registration
│   │   ├── i1-indicators.md           # All 16 indicator plugins
│   │   ├── i3-structure.md            # 3 structure plugins
│   │   ├── i4-context.md              # 3 context plugins
│   │   ├── i5-patterns.md             # 4 pattern plugins
│   │   ├── i6-smart-money.md          # 6 SMC plugins
│   │   └── i7-trading.md              # 5 trading setup plugins
│   ├── services/
│   │   ├── overview.md                # Service architecture
│   │   ├── hf-tws-daemon.md          # IBKR data collection
│   │   ├── indicator-processor.md     # Indicator calculation
│   │   ├── timeframe-builder.md       # Multi-timeframe aggregation
│   │   ├── intelligence-processor.md  # Pattern/structure/context
│   │   └── coordination.md            # Service orchestration
│   ├── schemas/
│   │   ├── stream-schemas.md          # Redis stream formats
│   │   └── database-schemas.md        # TimescaleDB tables
│   ├── configuration.md               # Settings, env vars, contracts
│   └── cli-commands.md                # Common commands reference
│
├── roadmap/
│   ├── MASTER_ROADMAP.md              # ★ WHAT'S NEXT (already exists)
│   └── decisions/                     # ADRs (Architecture Decision Records)
│       └── template.md
│
├── contributing/
│   ├── CONTRIBUTING.md                # How to contribute
│   ├── code-standards.md              # Linting, formatting, naming
│   ├── testing-standards.md           # Test patterns, coverage
│   ├── documentation-standards.md     # How to write docs (moved from top level)
│   └── release-process.md             # Versioning, changelogs
│
├── for-ai-assistants/
│   └── CLAUDE.md                      # AI-specific context (moved from root)
│
└── _archive/                          # Historical reference (read-only)
    ├── README.md                      # "This is archived, see STATUS.md"
    ├── planning/                      # Old strategic docs (Aug 2025)
    ├── designs/                       # Completed design docs
    └── reference/                     # Old reference material
```

**Principles:**
1. Every directory has README.md for navigation
2. STATUS.md is the anchor for current state
3. Clear boundaries: getting-started (learn) → guides (do) → concepts (understand) → reference (lookup)
4. AI-friendly with predictable paths
5. Archive is read-only but preserved

---

## STATUS.md Schema (Single Source of Truth)

**Purpose:** Canonical reference for "what's true right now." All other docs link here instead of duplicating version numbers, plugin counts, etc.

**Key sections:**

### 1. Header
```markdown
# IndicAgent Platform Status

> **Last Updated:** [Auto-generated timestamp]
> **Version:** 4.2.0
> **Phase:** I7 Phase 1.5 Complete
```

### 2. Current State Summary
High-level overview: infrastructure status, pipeline status, test coverage, data collection

### 3. System Health
Table of all services with:
- Component name
- Status (RUNNING/STOPPED/ERROR)
- Version
- Health endpoint

### 4. Intelligence Tiers
Table showing:
- Tier (I1-I8)
- Name
- Plugin count
- Status (COMPLETE/IN_PROGRESS/NOT_STARTED)
- Link to detailed docs

**Total Plugins:** 38 registered

### 5. Data Infrastructure
- Hot/Warm/Cold tier architecture
- Stream key conventions
- Database schemas reference

### 6. Instrumentation
- Active contracts (14 futures)
- Timeframes
- Collection status

### 7. Development Environment
- Python version, key dependencies
- Infrastructure requirements
- Local LLM models

### 8. Next Steps
Link to MASTER_ROADMAP.md with immediate priority

### 9. Recent Changes
Last 3-5 version updates (not exhaustive changelog):
```markdown
### 2026-02-17 (v4.2.0)
- COMPLETE I7 Phase 1.5: Signal aggregation components
- ADD 45 new tests
- UPDATE Consolidated planning docs into MASTER_ROADMAP.md
```

**Design notes:**
- No emojis (per CLAUDE.md standards)
- Text indicators: COMPLETE/IN_PROGRESS/NOT_STARTED/RUNNING/STOPPED/ERROR
- Links to detailed docs in every section
- Version + timestamp always at top
- Recent changes are summaries, not exhaustive

---

## Entry Points & Navigation

### docs/README.md (Router for All Audiences)

```markdown
# IndicAgent Intelligence Platform Documentation

**Current Version:** See [STATUS.md](STATUS.md)
**Last Updated:** [Auto-generated]

---

## Start Here

Choose your path based on what you need:

### New to IndicAgent?
→ [Quick Start](getting-started/quickstart.md) — Get running in 5 minutes
→ [Architecture Overview](getting-started/architecture-overview.md) — Understand the system

### Working on the platform?
→ [STATUS.md](STATUS.md) — Current state, versions, health
→ [Guides](guides/) — How to add plugins, run services, debug
→ [MASTER_ROADMAP.md](roadmap/MASTER_ROADMAP.md) — What's next

### Understanding the architecture?
→ [Intelligence Tiers](concepts/intelligence-tiers.md) — I1-I8 framework
→ [Plugin Architecture](concepts/plugin-architecture.md) — How plugins work
→ [Data Pipeline](concepts/data-pipeline.md) — Hot/warm/cold data flow

### Looking up specifics?
→ [Plugin Reference](reference/plugins/) — All 38 plugins documented
→ [API Reference](reference/api/) — REST endpoints, SSE protocol
→ [Stream Schemas](reference/schemas/stream-schemas.md) — Redis data formats

### Contributing?
→ [CONTRIBUTING.md](contributing/CONTRIBUTING.md) — How to contribute
→ [Code Standards](contributing/code-standards.md) — Linting, naming, testing

### AI Assistant?
→ [CLAUDE.md](for-ai-assistants/CLAUDE.md) — Project conventions and context

---

## Directory Structure

[Tree view of docs/ structure]

---

## Quick Links

**Development:**
- [Adding Plugins](guides/adding-plugins.md)
- [Running Services](guides/running-services.md)
- [Testing](guides/testing.md)

**Architecture:**
- [Intelligence Tiers](concepts/intelligence-tiers.md)
- [Plugin System](concepts/plugin-architecture.md)
- [Data Pipeline](concepts/data-pipeline.md)

**Reference:**
- [All Plugins](reference/plugins/overview.md)
- [API Endpoints](reference/api/rest-endpoints.md)
- [Configuration](reference/configuration.md)
```

**Key features:**
- Role-based entry (new user vs contributor vs AI)
- STATUS.md prominent for active development
- Quick links to common tasks
- No duplication (everything links to authoritative docs)

### Root README.md (Project Introduction)

Stays at project root, focused on:
- Project introduction
- Quick start commands
- Link to full documentation
- Key features list
- Architecture summary link
- Contributing link

**Purpose:** GitHub landing page. Detailed docs live in `docs/`.

---

## Content Migration Plan

### Phase 1: Create New Structure (No Deletions)

**New files to create:**
```bash
docs/STATUS.md                           # NEW - consolidate current-status-and-priorities.md
docs/getting-started/quickstart.md       # NEW
docs/getting-started/first-plugin.md     # NEW
docs/guides/adding-plugins.md            # NEW - consolidate from planning/
docs/concepts/signal-lifecycle.md        # NEW (I7 concepts)
docs/reference/plugins/overview.md       # NEW navigation
docs/reference/services/overview.md      # Enhance from services/README.md
docs/for-ai-assistants/CLAUDE.md         # MOVE from root
```

### Phase 2: Migrate Existing Valuable Content

| Current Location | New Location | Action |
|-----------------|--------------|--------|
| `docs/current-status-and-priorities.md` | `docs/STATUS.md` | Refactor into new schema |
| `docs/architecture/intelligence-tiers.md` | `docs/concepts/intelligence-tiers.md` | Move + enhance |
| `docs/architecture/plugin-registry-and-dag-execution.md` | `docs/concepts/plugin-architecture.md` | Move |
| `docs/architecture/stream-schemas.md` | `docs/reference/schemas/stream-schemas.md` | Move |
| `docs/architecture/layered-architecture.md` | `docs/concepts/data-pipeline.md` | Merge content |
| `docs/documentation-standards.md` | `docs/contributing/documentation-standards.md` | Move |
| `docs/setup-new-machine.md` | `docs/getting-started/installation.md` | Enhance + move |
| `CLAUDE.md` (root) | `docs/for-ai-assistants/CLAUDE.md` | Move |
| `docs/roadmap/MASTER_ROADMAP.md` | Keep in place | Already correct location |

### Phase 3: Archive Old Structure

```bash
# Move to _archive/ (after migration complete)
docs/_archive/planning/          # Keep Aug 2025 strategic docs
docs/_archive/designs/           # Move completed design docs from plans/archive/
docs/_archive/reference/         # Old architecture docs not migrated
docs/_archive/README.md          # Add notice: "This is archived, see STATUS.md"
```

**Archive directory structure:**
```
docs/_archive/
├── README.md                    # "Historical docs - see STATUS.md for current"
├── planning/                    # Aug 2025 strategic planning docs
├── designs/                     # Completed feature designs
└── reference/                   # Old architecture/reference docs
```

### Phase 4: Update Cross-References

1. Update all internal links in migrated docs
2. Add deprecation notices to old files before archiving
3. Update CLAUDE.md references in root README.md
4. Update docs/README.md to point to new structure
5. Search codebase for hardcoded doc paths and update

---

## Maintenance Workflow

### 1. STATUS.md Updates (After Every Release)

**When:** After completing any phase, feature, or version bump

**Process:**
```bash
1. Update version number at top
2. Update intelligence tiers table (plugin counts, status)
3. Update system health table (service versions)
4. Add entry to "Recent Changes" section (top 3-5 only)
5. Update "Next Steps" if priorities changed
6. Commit: "docs: update STATUS.md to v4.3.0"
```

**Frequency:** Every release (v4.2.0 → v4.3.0)

### 2. CLAUDE.md Updates (Weekly/As Needed)

**When:** After significant sessions, when patterns/conventions change

**Process:**
```bash
1. Use /revise-claude-md skill after major sessions
2. Update plugin counts, service lists
3. Keep CLAUDE.md version synced with STATUS.md
4. Update "Current Development Status" section
5. Commit: "docs: update CLAUDE.md to v4.3.0"
```

**Frequency:** After major features, weekly check

### 3. Plugin Documentation (When Adding Plugins)

**When:** Adding any new plugin

**Process:**
```bash
1. Add plugin details to reference/plugins/iX-*.md
2. Update STATUS.md intelligence tiers table (increment count)
3. Update CLAUDE.md plugin count
4. Optional: Add example to guides/adding-plugins.md
5. Commit with feature: "feat(i7): add VWAP deviation setup plugin"
```

**Frequency:** Every new plugin

### 4. Roadmap Updates (Monthly or After Phase Completion)

**When:** Completing major phases, reprioritizing work

**Process:**
```bash
1. Update MASTER_ROADMAP.md phase status
2. Move completed phases to "Completed" section
3. Adjust priorities based on learnings
4. Update STATUS.md "Next Steps" link
5. Commit: "docs: update MASTER_ROADMAP.md - I7 Phase 1.5 complete"
```

**Frequency:** Monthly or after major milestones

### 5. Periodic Audits (Quarterly)

**When:** Every 3 months or when docs feel stale

**Process:**
```bash
1. Run /claude-md-improver skill
2. Check STATUS.md vs actual codebase:
   - Plugin counts match registry
   - Service versions match code
   - Health endpoints are correct
3. Verify internal links aren't broken
4. Update outdated examples/screenshots
5. Archive obsolete content
6. Commit: "docs: quarterly audit - fix stale content"
```

**Frequency:** Quarterly (Jan/Apr/Jul/Oct)

### 6. Automated Checks (Future Enhancement)

**When:** Implemented as GitHub Actions

**Potential checks:**
```bash
- STATUS.md version matches pyproject.toml
- Plugin counts match len(registry.indicators) + len(registry.patterns)
- All internal doc links resolve
- Flag docs not updated in 6+ months
- Lint markdown for style consistency
```

**Frequency:** On every commit (CI/CD)

---

## Success Criteria

### Immediate (Week 1)
- [ ] New directory structure created
- [ ] STATUS.md exists as single source of truth
- [ ] docs/README.md routes users by role
- [ ] CLAUDE.md moved to for-ai-assistants/
- [ ] Old structure archived with deprecation notices

### Short-Term (Month 1)
- [ ] All high-value content migrated to new structure
- [ ] Cross-references updated (no broken links)
- [ ] External contributors can onboard via quickstart.md
- [ ] AI assistants (Claude Code) can navigate effectively

### Long-Term (Ongoing)
- [ ] STATUS.md updated after every release
- [ ] Plugin docs updated when adding plugins
- [ ] No duplication of version/status info
- [ ] Quarterly audits catch staleness
- [ ] Zero "where do I find X?" questions

---

## References

**Industry Examples:**
- Kubernetes: https://kubernetes.io/docs/
- React: https://react.dev/
- Next.js: https://nextjs.org/docs
- PostgreSQL: https://www.postgresql.org/docs/

**Current State:**
- docs/documentation-audit.md (v1.1.0, 2026-02-13)
- docs/roadmap/MASTER_ROADMAP.md (v4.2.0, 2026-02-17)
- CLAUDE.md (v4.2.0, 2026-02-17)

---

## Next Steps

1. **Implementation Planning:** Use /writing-plans skill to create task-by-task implementation plan
2. **Execution:** Migrate content incrementally (getting-started first, then guides, etc.)
3. **Validation:** Test navigation with fresh eyes (external dev perspective)
4. **Iteration:** Adjust based on usage feedback

---

**Design Status:** APPROVED - Ready for implementation planning
