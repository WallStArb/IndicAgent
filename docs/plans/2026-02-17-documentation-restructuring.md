# Documentation Restructuring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure documentation to industry-standard OSS pattern with STATUS.md as single source of truth, eliminating duplication and staleness.

**Architecture:** Hybrid migration — create new structure (getting-started/, guides/, concepts/, reference/, contributing/) with STATUS.md as canonical state, migrate valuable content from existing docs, archive old structure for historical reference. Multi-audience support via role-based entry points.

**Tech Stack:** Markdown, git, industry patterns from Kubernetes/React/Next.js

**Design Doc:** `docs/plans/2026-02-17-documentation-strategy-design.md`

---

## Phase 1: Create Core Structure (Foundation)

### Task 1: Create Directory Structure

**Files:**
- Create: `docs/getting-started/`
- Create: `docs/guides/`
- Create: `docs/concepts/`
- Create: `docs/reference/api/`
- Create: `docs/reference/plugins/`
- Create: `docs/reference/services/`
- Create: `docs/reference/schemas/`
- Create: `docs/contributing/`
- Create: `docs/for-ai-assistants/`
- Create: `docs/roadmap/decisions/`

**Step 1: Create directory structure**

```bash
mkdir -p docs/getting-started
mkdir -p docs/guides
mkdir -p docs/concepts
mkdir -p docs/reference/{api,plugins,services,schemas}
mkdir -p docs/contributing
mkdir -p docs/for-ai-assistants
mkdir -p docs/roadmap/decisions
```

**Step 2: Verify structure**

Run: `tree docs/ -L 2 -d`
Expected: All new directories listed

**Step 3: Commit**

```bash
git add docs/
git commit -m "docs: create new directory structure for restructuring"
```

---

### Task 2: Create STATUS.md (Single Source of Truth)

**Files:**
- Create: `docs/STATUS.md`

**Step 1: Create STATUS.md**

```bash
touch docs/STATUS.md
```

**Step 2: Write STATUS.md content**

```markdown
# IndicAgent Platform Status

> **Last Updated:** 2026-02-17
> **Version:** 4.2.0
> **Phase:** I7 Phase 1.5 Complete

---

## Current State Summary

**Infrastructure:** Production-ready
**Intelligence Pipeline:** Fully operational (I1 → I7)
**Test Coverage:** 258 tests passing, 0 lint errors
**Data Collection:** Active (ES, NQ, RTY + 11 more contracts)

---

## System Health

| Component | Status | Version | Health Endpoint |
|-----------|--------|---------|-----------------|
| HF TWS Daemon | RUNNING | 2.1.0 | N/A |
| Indicator Processor | RUNNING | 3.2.0 | :9109/health |
| Enhanced Processor | RUNNING | 1.0.0 | :9109/health |
| Timeframe Builder | RUNNING | 2.0.0 | :9110/health |
| Intelligence Processor | RUNNING | 2.5.0 | N/A |
| Backend API | RUNNING | 4.1.0 | :8000/health |
| Dashboard | RUNNING | 1.5.0 | http://localhost:3000 |

---

## Intelligence Tiers

| Tier | Name | Plugins | Status | Details |
|------|------|---------|--------|---------|
| I1 | Technical Indicators | 16 | COMPLETE | [Reference](reference/plugins/i1-indicators.md) |
| I2 | Composite Indicators | — | COMPLETE | Built-in (crossovers, slopes) |
| I3 | Market Structure | 3 | COMPLETE | [Reference](reference/plugins/i3-structure.md) |
| I4 | Context Classification | 3 | COMPLETE | [Reference](reference/plugins/i4-context.md) |
| I5 | Pattern Detection | 4 | COMPLETE | [Reference](reference/plugins/i5-patterns.md) |
| I6 | Smart Money Concepts | 6 | COMPLETE | [Reference](reference/plugins/i6-smart-money.md) |
| I6 | Cross-Timeframe Confluence | 1 | COMPLETE | [Reference](reference/plugins/i6-smart-money.md) |
| I7 | Trading Setups | 5 | PHASE_1_COMPLETE | [Reference](reference/plugins/i7-trading.md) |
| I7 | Signal Aggregation | 4 components | PHASE_1.5_BUILT | Not wired to services |
| I8 | AI Intelligence | 0 | NOT_STARTED | [Roadmap](roadmap/MASTER_ROADMAP.md#phase-9) |

**Total Plugins:** 38 registered

---

## Data Infrastructure

**Hot Tier:** DragonflyDB (Redis protocol) - <1ms latency
**Warm Tier:** Redis Streams - Real-time processing
**Cold Tier:** TimescaleDB - Historical analysis

**Stream Keys:**
- Market data: `market:SYMBOL:TIMEFRAME`
- Indicators: `indicators:SYMBOL:TIMEFRAME`
- Intelligence: `intelligence:SYMBOL:TIMEFRAME`
- Signals: `signals:SYMBOL:TIMEFRAME:aggregated`

See [Stream Schemas](reference/schemas/stream-schemas.md) for details.

---

## Instrumentation

**Active Contracts:** 14 futures
- **Equity Indices:** ES, NQ, RTY
- **Energy:** CL, NG
- **Metals:** GC, SI, HG, PL
- **Rates:** ZN, ZF, ZB, ZT
- **Volatility:** VX

**Timeframes:** 1m, 5m, 15m, 1h, 4h, 1d

---

## Development Environment

**Python:** 3.11+
**Key Dependencies:** pandas 3.0, redis 7.1, FastAPI 0.129, LangGraph 1.0
**Infrastructure:** Docker (TimescaleDB, DragonflyDB, Ollama)
**Frontend:** Next.js 15.5, React 19

**Local LLMs (Ollama):** 5 models available at http://localhost:11434
- **Default:** `qwen3:8b` (5.2 GB, thinking mode)
- See [Intelligence Tiers](concepts/intelligence-tiers.md#i8) for full model list

---

## Next Steps

See [MASTER_ROADMAP.md](roadmap/MASTER_ROADMAP.md) for detailed priorities.

**Immediate Priority:** Phase 1 - Signal Orchestrator Service (critical blocker for ML calibration)

---

## Recent Changes

### 2026-02-17 (v4.2.0)
- COMPLETE I7 Phase 1.5: Signal aggregation components (aggregator, ledger, lifecycle, sizer)
- ADD 45 new tests for signal aggregation
- UPDATE Consolidated planning docs into MASTER_ROADMAP.md
- UPDATE Restructured documentation with STATUS.md as single source of truth

### 2026-02-16 (v4.1.0)
- COMPLETE I7 Phase 1: 5 trading setup plugins
- ADD signal.v1 schema with SSE wiring
- ADD 35 new tests

### 2026-02-15 (v4.0.0)
- COMPLETE I6 Smart Money: BOCPD changepoint + HMM regime classification
- ADD Cross-timeframe confluence plugin

---

**Note:** This is the canonical reference for current state. All other docs link here instead of duplicating version/status info.
```

**Step 3: Verify rendering**

Read the file to check formatting looks correct.

**Step 4: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs: create STATUS.md as single source of truth

- System health table
- Intelligence tiers with plugin counts
- Data infrastructure overview
- Recent changes log
- Links to detailed docs

All other docs will reference this instead of duplicating state."
```

---

### Task 3: Create docs/README.md (Navigation Hub)

**Files:**
- Modify: `docs/README.md`

**Step 1: Back up existing README**

```bash
cp docs/README.md docs/README.md.backup
```

**Step 2: Replace with new navigation-focused content**

```markdown
# IndicAgent Intelligence Platform Documentation

**Current Version:** See [STATUS.md](STATUS.md) for current state
**Last Updated:** 2026-02-17

---

## Start Here

Choose your path based on what you need:

### New to IndicAgent?
**→ [Quick Start](getting-started/quickstart.md)** — Get running in 5 minutes
**→ [Architecture Overview](getting-started/architecture-overview.md)** — Understand the system

### Working on the platform?
**→ [STATUS.md](STATUS.md)** — Current state, versions, health
**→ [Guides](guides/)** — How to add plugins, run services, debug
**→ [MASTER_ROADMAP.md](roadmap/MASTER_ROADMAP.md)** — What's next

### Understanding the architecture?
**→ [Intelligence Tiers](concepts/intelligence-tiers.md)** — I1-I8 framework
**→ [Plugin Architecture](concepts/plugin-architecture.md)** — How plugins work
**→ [Data Pipeline](concepts/data-pipeline.md)** — Hot/warm/cold data flow

### Looking up specifics?
**→ [Plugin Reference](reference/plugins/)** — All 38 plugins documented
**→ [API Reference](reference/api/)** — REST endpoints, SSE protocol
**→ [Stream Schemas](reference/schemas/stream-schemas.md)** — Redis data formats

### Contributing?
**→ [CONTRIBUTING.md](contributing/CONTRIBUTING.md)** — How to contribute
**→ [Code Standards](contributing/code-standards.md)** — Linting, naming, testing

### AI Assistant?
**→ [CLAUDE.md](for-ai-assistants/CLAUDE.md)** — Project conventions and context

---

## Directory Structure

```
docs/
├── STATUS.md              ← Single source of truth
├── getting-started/       ← Tutorials and onboarding
├── guides/                ← Task-oriented how-tos
├── concepts/              ← Deep architectural understanding
├── reference/             ← API & technical specs
├── roadmap/               ← MASTER_ROADMAP.md
├── contributing/          ← For contributors
├── for-ai-assistants/     ← CLAUDE.md
└── _archive/              ← Historical docs (read-only)
```

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

---

## External Links

- [Main Repository README](../README.md)
- [IBKR TWS API Docs](https://interactivebrokers.github.io/tws-api/)
- [TimescaleDB Docs](https://docs.timescale.com/)
- [DragonflyDB Docs](https://www.dragonflydb.io/docs/)
```

**Step 3: Verify links and formatting**

Read the file to ensure markdown renders correctly.

**Step 4: Commit**

```bash
git add docs/README.md docs/README.md.backup
git commit -m "docs: refactor README.md as navigation hub

- Role-based entry points (new user vs contributor vs AI)
- Links to STATUS.md for current state
- Quick links to common tasks
- Backed up old version to README.md.backup"
```

---

## Phase 2: Create Section Navigation READMEs

### Task 4: Create getting-started/README.md

**Files:**
- Create: `docs/getting-started/README.md`

**Step 1: Create file**

```markdown
# Getting Started with IndicAgent

New to the platform? Start here.

---

## Learning Path

**1. Quick Start (5 minutes)**
→ [quickstart.md](quickstart.md) — Clone, run, see dashboard

**2. Full Installation (30 minutes)**
→ [installation.md](installation.md) — IBKR, Redis, TimescaleDB, Ollama setup

**3. First Plugin Tutorial (1 hour)**
→ [first-plugin.md](first-plugin.md) — Write a simple indicator plugin

**4. Architecture Overview (30 minutes)**
→ [architecture-overview.md](architecture-overview.md) — Understand the 10,000-foot view

---

## Next Steps

After completing getting-started:
- **Dive deeper:** [Concepts](../concepts/) for architectural understanding
- **Build something:** [Guides](../guides/) for task-oriented how-tos
- **Look up specifics:** [Reference](../reference/) for API/plugin docs

---

**Back to:** [Documentation Home](../README.md)
```

**Step 2: Commit**

```bash
git add docs/getting-started/README.md
git commit -m "docs: add getting-started navigation README"
```

---

### Task 5: Create guides/README.md

**Files:**
- Create: `docs/guides/README.md`

**Step 1: Create file**

```markdown
# Guides — Task-Oriented How-Tos

Step-by-step guides for common development tasks.

---

## Development

**[Adding Plugins](adding-plugins.md)**
How to create new indicator, pattern, or setup plugins

**[Running Services](running-services.md)**
systemd, docker, health checks, logs

**[Testing](testing.md)**
Writing tests, running test suite, coverage

**[Dashboard Development](dashboard-development.md)**
Frontend setup, component development, SSE integration

---

## Operations

**[Monitoring & Debugging](monitoring-debugging.md)**
Logs, metrics, troubleshooting common issues

**[Database Management](database-management.md)**
TimescaleDB migrations, backups, compression policies

---

## Next Steps

- **Understand concepts:** [Concepts](../concepts/) for deep dives
- **Look up APIs:** [Reference](../reference/) for technical specs
- **Current status:** [STATUS.md](../STATUS.md)

---

**Back to:** [Documentation Home](../README.md)
```

**Step 2: Commit**

```bash
git add docs/guides/README.md
git commit -m "docs: add guides navigation README"
```

---

### Task 6: Create concepts/README.md

**Files:**
- Create: `docs/concepts/README.md`

**Step 1: Create file**

```markdown
# Concepts — Architectural Deep Dives

Understand the architectural decisions and design patterns.

---

## Core Architecture

**[Intelligence Tiers](intelligence-tiers.md)**
I1-I8 progressive intelligence framework

**[Plugin Architecture](plugin-architecture.md)**
Plugin system, DAG execution, registry pattern

**[Data Pipeline](data-pipeline.md)**
Hot/warm/cold data flow, Redis streams, TimescaleDB persistence

---

## Advanced Topics

**[Incremental Computation](incremental-computation.md)**
State-based calculations — 141x performance boost explained

**[Signal Lifecycle](signal-lifecycle.md)**
I7 trading signals, aggregation, P&L tracking

**[Regime Classification](regime-classification.md)**
Context-aware intelligence with HMM, GARCH, Kalman filters

---

## Next Steps

- **Learn by doing:** [Guides](../guides/) for hands-on tasks
- **Look up specifics:** [Reference](../reference/) for API docs
- **See examples:** [Getting Started](../getting-started/) for tutorials

---

**Back to:** [Documentation Home](../README.md)
```

**Step 2: Commit**

```bash
git add docs/concepts/README.md
git commit -m "docs: add concepts navigation README"
```

---

### Task 7: Create reference/README.md

**Files:**
- Create: `docs/reference/README.md`

**Step 1: Create file**

```markdown
# Reference — API & Technical Specifications

Technical reference for APIs, plugins, services, and schemas.

---

## API Documentation

**[REST Endpoints](api/rest-endpoints.md)**
FastAPI routes, request/response formats

**[SSE Protocol](api/sse-protocol.md)**
Real-time Server-Sent Events streams

**[WebSocket Protocol](api/websocket-protocol.md)**
Alternative real-time API (optional)

---

## Plugin Reference

**[Plugin Overview](plugins/overview.md)**
Plugin protocol, registration, lifecycle

**Plugin Directories:**
- [I1: Technical Indicators](plugins/i1-indicators.md) — 16 plugins
- [I3: Market Structure](plugins/i3-structure.md) — 3 plugins
- [I4: Context Classification](plugins/i4-context.md) — 3 plugins
- [I5: Pattern Detection](plugins/i5-patterns.md) — 4 plugins
- [I6: Smart Money Concepts](plugins/i6-smart-money.md) — 7 plugins
- [I7: Trading Setups](plugins/i7-trading.md) — 5 plugins

**Total:** 38 plugins

---

## Service Reference

**[Service Overview](services/overview.md)**
Service architecture, coordination, health checks

**Service Docs:**
- [HF TWS Daemon](services/hf-tws-daemon.md) — IBKR data collection
- [Indicator Processor](services/indicator-processor.md) — I1 calculations
- [Timeframe Builder](services/timeframe-builder.md) — Multi-timeframe aggregation
- [Intelligence Processor](services/intelligence-processor.md) — I3-I7 processing
- [Coordination Service](services/coordination.md) — Service orchestration

---

## Data Schemas

**[Stream Schemas](schemas/stream-schemas.md)**
Redis stream data formats

**[Database Schemas](schemas/database-schemas.md)**
TimescaleDB table definitions

---

## Configuration

**[Configuration Reference](configuration.md)**
Settings.py, environment variables, contract definitions

**[CLI Commands](cli-commands.md)**
Common command reference for development

---

## Next Steps

- **Understand why:** [Concepts](../concepts/) for architectural context
- **Learn how:** [Guides](../guides/) for task-oriented how-tos
- **Check status:** [STATUS.md](../STATUS.md)

---

**Back to:** [Documentation Home](../README.md)
```

**Step 2: Commit**

```bash
git add docs/reference/README.md
git commit -m "docs: add reference navigation README"
```

---

### Task 8: Create contributing/README.md

**Files:**
- Create: `docs/contributing/README.md`

**Step 1: Create file**

```markdown
# Contributing to IndicAgent

Thank you for considering contributing!

---

## Start Here

**[CONTRIBUTING.md](CONTRIBUTING.md)**
How to contribute — workflow, pull requests, issues

---

## Standards & Guidelines

**[Code Standards](code-standards.md)**
Linting, formatting, naming conventions

**[Testing Standards](testing-standards.md)**
Test patterns, coverage requirements

**[Documentation Standards](documentation-standards.md)**
How to write documentation

**[Release Process](release-process.md)**
Versioning, changelogs, releases

---

## Quick Links

- **Current Status:** [STATUS.md](../STATUS.md)
- **Roadmap:** [MASTER_ROADMAP.md](../roadmap/MASTER_ROADMAP.md)
- **Architecture:** [Concepts](../concepts/)

---

**Back to:** [Documentation Home](../README.md)
```

**Step 2: Commit**

```bash
git add docs/contributing/README.md
git commit -m "docs: add contributing navigation README"
```

---

## Phase 3: Migrate Key Content

### Task 9: Move CLAUDE.md to for-ai-assistants/

**Files:**
- Move: `CLAUDE.md` → `docs/for-ai-assistants/CLAUDE.md`

**Step 1: Move file**

```bash
git mv CLAUDE.md docs/for-ai-assistants/CLAUDE.md
```

**Step 2: Verify file moved**

```bash
ls -la docs/for-ai-assistants/CLAUDE.md
cat docs/for-ai-assistants/CLAUDE.md | head -20
```

**Step 3: Commit**

```bash
git commit -m "docs: move CLAUDE.md to for-ai-assistants/

AI-specific context now in dedicated directory.
Root README.md will link to this location."
```

---

### Task 10: Update Root README.md to Link to New CLAUDE.md

**Files:**
- Modify: `README.md`

**Step 1: Find CLAUDE.md references in root README**

```bash
grep -n "CLAUDE.md" README.md
```

**Step 2: Update link**

Change any `CLAUDE.md` references to `docs/for-ai-assistants/CLAUDE.md`

**Step 3: Verify change**

```bash
git diff README.md
```

**Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update root README to link to new CLAUDE.md location"
```

---

### Task 11: Migrate architecture/intelligence-tiers.md to concepts/

**Files:**
- Copy: `docs/architecture/intelligence-tiers.md` → `docs/concepts/intelligence-tiers.md`

**Step 1: Copy file**

```bash
cp docs/architecture/intelligence-tiers.md docs/concepts/intelligence-tiers.md
```

**Step 2: Update STATUS.md references in the file**

Edit `docs/concepts/intelligence-tiers.md`:
- Add note at top: "**Current State:** See [STATUS.md](../STATUS.md) for plugin counts and tier status"
- Remove any hardcoded version numbers/plugin counts

**Step 3: Verify content**

```bash
head -30 docs/concepts/intelligence-tiers.md
```

**Step 4: Commit**

```bash
git add docs/concepts/intelligence-tiers.md
git commit -m "docs: migrate intelligence-tiers.md to concepts/

- Copied from architecture/ to concepts/
- Added STATUS.md reference for current state
- Original file remains in architecture/ for now"
```

---

### Task 12: Migrate architecture/plugin-registry-and-dag-execution.md to concepts/

**Files:**
- Copy: `docs/architecture/plugin-registry-and-dag-execution.md` → `docs/concepts/plugin-architecture.md`

**Step 1: Copy and rename**

```bash
cp docs/architecture/plugin-registry-and-dag-execution.md docs/concepts/plugin-architecture.md
```

**Step 2: Update header and add STATUS.md reference**

Edit `docs/concepts/plugin-architecture.md`:
- Change title to "# Plugin Architecture"
- Add: "**Current Plugin Count:** See [STATUS.md](../STATUS.md)"
- Remove any hardcoded plugin counts

**Step 3: Commit**

```bash
git add docs/concepts/plugin-architecture.md
git commit -m "docs: migrate plugin-registry docs to concepts/plugin-architecture.md

- Renamed for clarity
- Added STATUS.md reference
- Original remains in architecture/ for now"
```

---

### Task 13: Migrate architecture/stream-schemas.md to reference/schemas/

**Files:**
- Move: `docs/architecture/stream-schemas.md` → `docs/reference/schemas/stream-schemas.md`

**Step 1: Move file**

```bash
git mv docs/architecture/stream-schemas.md docs/reference/schemas/stream-schemas.md
```

**Step 2: Update any internal links**

Check if the file references other docs, update paths if needed.

**Step 3: Commit**

```bash
git commit -m "docs: move stream-schemas.md to reference/schemas/

Reference material now in reference/ hierarchy."
```

---

### Task 14: Move documentation-standards.md to contributing/

**Files:**
- Move: `docs/documentation-standards.md` → `docs/contributing/documentation-standards.md`

**Step 1: Move file**

```bash
git mv docs/documentation-standards.md docs/contributing/documentation-standards.md
```

**Step 2: Commit**

```bash
git commit -m "docs: move documentation-standards.md to contributing/

Contributor guidelines now in contributing/ directory."
```

---

## Phase 4: Create Placeholder Stubs

### Task 15: Create getting-started Stubs

**Files:**
- Create: `docs/getting-started/quickstart.md`
- Create: `docs/getting-started/installation.md`
- Create: `docs/getting-started/first-plugin.md`
- Create: `docs/getting-started/architecture-overview.md`

**Step 1: Create quickstart.md stub**

```markdown
# Quick Start

Get IndicAgent running in 5 minutes.

---

## Prerequisites

- Python 3.11+
- Docker Desktop
- Git

---

## Steps

### 1. Clone Repository

\`\`\`bash
git clone https://github.com/yourusername/indicagent.git
cd indicagent
\`\`\`

### 2. Setup Environment

\`\`\`bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
\`\`\`

### 3. Start Infrastructure

\`\`\`bash
docker-compose up -d
\`\`\`

### 4. Start Services

\`\`\`bash
python production/daemons/high_frequency_tws_daemon.py --client-id 35
python services/indicators_processor_service.py --config config/indicator_processor_service.json
\`\`\`

### 5. Start Dashboard

\`\`\`bash
cd dashboard
npm install
npm run dev
\`\`\`

Open http://localhost:3000

---

## Next Steps

- **Full Installation:** [installation.md](installation.md) for detailed setup
- **First Plugin:** [first-plugin.md](first-plugin.md) to write your first plugin
- **Architecture:** [architecture-overview.md](architecture-overview.md) to understand the system

---

**Status:** See [STATUS.md](../STATUS.md) for current versions
```

**Step 2: Create installation.md stub**

```markdown
# Installation Guide

Detailed setup for all components.

---

## Overview

IndicAgent requires:
1. Python 3.11+ environment
2. Docker infrastructure (TimescaleDB, DragonflyDB, Ollama)
3. IBKR TWS or IB Gateway (paper trading)
4. Node.js 18+ for dashboard

---

## Detailed Steps

### 1. Python Environment

[TODO: Expand from setup-new-machine.md]

### 2. Docker Infrastructure

[TODO: Expand from setup-new-machine.md]

### 3. IBKR Setup

[TODO: Add IBKR TWS/Gateway setup instructions]

### 4. Database Schema

[TODO: Add schema creation steps]

### 5. Dashboard Setup

[TODO: Add dashboard setup]

---

## Verification

[TODO: Add health check commands]

---

**Next:** [Quick Start](quickstart.md) | [First Plugin](first-plugin.md)
```

**Step 3: Create first-plugin.md stub**

```markdown
# First Plugin Tutorial

Write a simple indicator plugin.

---

## Goal

Create a custom Simple Moving Average (SMA) plugin to understand the plugin system.

---

## Steps

[TODO: Step-by-step tutorial for creating a basic indicator plugin]

1. Create plugin file
2. Implement IndicatorPlugin protocol
3. Register plugin
4. Write tests
5. Run and verify

---

**Reference:** [Plugin Architecture](../concepts/plugin-architecture.md)
```

**Step 4: Create architecture-overview.md stub**

```markdown
# Architecture Overview

10,000-foot view of IndicAgent.

---

## System Architecture

[TODO: High-level diagram and explanation]

### Intelligence Pipeline

\`\`\`
IBKR TWS → I1 Indicators → I3 Structure → I4 Context →
I5 Patterns → I6 Smart Money → I7 Trading → Redis → Dashboard
\`\`\`

### Data Flow

**Hot Tier:** DragonflyDB (sub-ms)
**Warm Tier:** Redis Streams (real-time)
**Cold Tier:** TimescaleDB (historical)

---

## Core Concepts

[TODO: Brief intro to intelligence tiers, plugins, services]

---

**Deep Dive:** [Concepts](../concepts/) for detailed architecture
```

**Step 5: Commit all stubs**

```bash
git add docs/getting-started/*.md
git commit -m "docs: add getting-started stub documents

- quickstart.md: 5-minute setup
- installation.md: detailed setup (TODO)
- first-plugin.md: tutorial (TODO)
- architecture-overview.md: high-level view (TODO)

Stubs establish structure, content to be filled incrementally."
```

---

### Task 16: Create guides Stubs

**Files:**
- Create: `docs/guides/adding-plugins.md`
- Create: `docs/guides/running-services.md`
- Create: `docs/guides/monitoring-debugging.md`
- Create: `docs/guides/dashboard-development.md`
- Create: `docs/guides/testing.md`
- Create: `docs/guides/database-management.md`

**Step 1: Create adding-plugins.md stub**

```markdown
# Adding Plugins

Step-by-step guide to creating new plugins.

---

## Plugin Types

- **I1: Indicators** — Technical indicators (SMA, RSI, etc.)
- **I3: Structure** — Market structure (swings, S/R, trends)
- **I4: Context** — Regime classification (volatility, trend)
- **I5: Patterns** — Pattern detection (divergence, confluence)
- **I6: Smart Money** — SMC concepts (FVG, order blocks, BOS)
- **I7: Trading** — Setup plugins (signals)

---

## Process

[TODO: Detailed step-by-step for each plugin type]

1. Design plugin (input/output schema)
2. Write tests (TDD)
3. Implement plugin
4. Register in register_plugins.py
5. Add to reference docs
6. Update STATUS.md plugin count

---

**Reference:** [Plugin Architecture](../concepts/plugin-architecture.md)
**Example:** [First Plugin Tutorial](../getting-started/first-plugin.md)
```

**Step 2: Create running-services.md stub**

```markdown
# Running Services

Service management guide.

---

## Production Services

See [STATUS.md](../STATUS.md) for current service list.

### systemd Management

\`\`\`bash
sudo systemctl status indicagent-backend-api
sudo systemctl restart indicagent-hf-tws
journalctl -u indicagent-hf-tws -f
\`\`\`

### Health Checks

\`\`\`bash
curl http://localhost:9109/health  # Indicator Processor
curl http://localhost:9109/metrics # Prometheus metrics
\`\`\`

---

## Development Mode

[TODO: Add development service startup]

---

**Reference:** [Service Reference](../reference/services/overview.md)
```

**Step 3: Create other guide stubs**

```markdown
# monitoring-debugging.md
# Monitoring & Debugging

[TODO: Logs, metrics, troubleshooting]

---

# dashboard-development.md
# Dashboard Development

[TODO: Frontend setup, component dev, SSE integration]

---

# testing.md
# Testing Guide

[TODO: Writing tests, running suite, coverage]

See current test count: [STATUS.md](../STATUS.md)

---

# database-management.md
# Database Management

[TODO: TimescaleDB migrations, backups, compression]
```

**Step 4: Commit**

```bash
git add docs/guides/*.md
git commit -m "docs: add guides stub documents

Establish structure for task-oriented how-tos.
Content to be filled incrementally."
```

---

### Task 17: Create reference Stubs

**Files:**
- Create: `docs/reference/plugins/overview.md`
- Create: `docs/reference/services/overview.md`
- Create: `docs/reference/api/rest-endpoints.md`
- Create: `docs/reference/api/sse-protocol.md`
- Create: `docs/reference/configuration.md`

**Step 1: Create plugins/overview.md**

```markdown
# Plugin Reference Overview

All 38 registered plugins.

---

## Plugin Protocol

[TODO: Explain IndicatorPlugin, PatternPlugin protocols]

## Registration

[TODO: Explain register_plugins.py]

---

## Plugin Directories

- [I1: Technical Indicators](i1-indicators.md) — 16 plugins
- [I3: Market Structure](i3-structure.md) — 3 plugins
- [I4: Context Classification](i4-context.md) — 3 plugins
- [I5: Pattern Detection](i5-patterns.md) — 4 plugins
- [I6: Smart Money Concepts](i6-smart-money.md) — 7 plugins
- [I7: Trading Setups](i7-trading.md) — 5 plugins

**Total:** 38 plugins

See [STATUS.md](../../STATUS.md) for current counts.

---

**Guide:** [Adding Plugins](../../guides/adding-plugins.md)
**Concepts:** [Plugin Architecture](../../concepts/plugin-architecture.md)
```

**Step 2: Create services/overview.md**

```markdown
# Service Reference Overview

Production services architecture.

---

## Services

See [STATUS.md](../../STATUS.md) for current service status.

### Data Collection
- [HF TWS Daemon](hf-tws-daemon.md) — IBKR data collection

### Processing
- [Indicator Processor](indicator-processor.md) — I1 calculations
- [Timeframe Builder](timeframe-builder.md) — Multi-timeframe aggregation
- [Intelligence Processor](intelligence-processor.md) — I3-I7 processing

### Coordination
- [Coordination Service](coordination.md) — Service orchestration

---

**Guide:** [Running Services](../../guides/running-services.md)
```

**Step 3: Create api/rest-endpoints.md stub**

```markdown
# REST API Endpoints

FastAPI backend routes.

---

## Health & Metrics

\`GET /health\` — Service health check
\`GET /metrics\` — Prometheus metrics

---

## Market Data

[TODO: Document market data endpoints]

---

## Indicators

[TODO: Document indicator endpoints]

---

**Guide:** [Dashboard Development](../../guides/dashboard-development.md)
```

**Step 4: Create api/sse-protocol.md stub**

```markdown
# Server-Sent Events Protocol

Real-time streaming API.

---

## Stream Keys

See [Stream Schemas](../schemas/stream-schemas.md) for data formats.

\`\`\`
market:SYMBOL:TIMEFRAME
indicators:SYMBOL:TIMEFRAME
intelligence:SYMBOL:TIMEFRAME
signals:SYMBOL:TIMEFRAME:aggregated
\`\`\`

---

[TODO: Document SSE connection, message format, examples]

---

**Guide:** [Dashboard Development](../../guides/dashboard-development.md)
```

**Step 5: Create configuration.md stub**

```markdown
# Configuration Reference

Settings, environment variables, contracts.

---

## Environment Variables

See [STATUS.md](../STATUS.md) for current environment setup.

\`\`\`bash
INDICAGENT_ENV="development"
DATABASE_URL="postgresql://..."
REDIS_URL="redis://localhost:6379/0"
IBKR_HOST="172.18.176.1"
IBKR_PORT=7497
IBKR_CLIENT_ID=35
\`\`\`

---

## Instrument Configuration

[TODO: Document contract definitions, Settings.py]

---

**Concepts:** [Data Pipeline](../concepts/data-pipeline.md)
```

**Step 6: Commit**

```bash
git add docs/reference/**/*.md
git commit -m "docs: add reference stub documents

Establish structure for API/plugin/service reference.
Content to be filled incrementally."
```

---

## Phase 5: Archive Old Structure

### Task 18: Create Archive README with Notice

**Files:**
- Create: `docs/_archive/README.md`

**Step 1: Create notice**

```markdown
# Archived Documentation

**This directory contains historical documentation for reference only.**

**For current information, see:**
- [STATUS.md](../STATUS.md) — Current state
- [Documentation Home](../README.md) — Navigation

---

## Archive Contents

### planning/
Strategic planning documents from August 2025. Retained for historical context.

### designs/
Completed feature design documents (moved from plans/archive/).

### reference/
Old architecture documentation (superseded by new structure).

---

**Last Updated:** 2026-02-17
**Reason:** Documentation restructuring to industry-standard OSS pattern
```

**Step 2: Commit**

```bash
git add docs/_archive/README.md
git commit -m "docs: add archive README with deprecation notice"
```

---

### Task 19: Move Old Planning Docs to Archive

**Files:**
- Move: `docs/planning/` → `docs/_archive/planning/` (if not already there)

**Step 1: Check if planning/ should be archived**

```bash
ls -la docs/planning/
```

**Step 2: If contains only Aug 2025 strategic docs, move to archive**

```bash
# Only if planning/ contains historical strategic docs
git mv docs/planning docs/_archive/planning
```

**Step 3: Commit**

```bash
git commit -m "docs: archive planning/ directory

Strategic docs from Aug 2025 moved to _archive/ for historical reference.
Current planning lives in roadmap/MASTER_ROADMAP.md."
```

---

### Task 20: Move Completed Design Docs to Archive

**Files:**
- Move: `docs/plans/archive/` → `docs/_archive/designs/`

**Step 1: Move archive subdirectory**

```bash
git mv docs/plans/archive docs/_archive/designs
```

**Step 2: Update any references**

Check if any active docs reference plans/archive/, update to _archive/designs/

**Step 3: Commit**

```bash
git commit -m "docs: move completed design docs to _archive/designs/

Consolidate archives into single _archive/ directory."
```

---

## Phase 6: Create Contributing Docs

### Task 21: Create CONTRIBUTING.md

**Files:**
- Create: `docs/contributing/CONTRIBUTING.md`

**Step 1: Create file**

```markdown
# Contributing to IndicAgent

Thank you for your interest in contributing!

---

## Quick Start

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Follow [Code Standards](code-standards.md)
4. Write tests (see [Testing Standards](testing-standards.md))
5. Submit a pull request

---

## Development Workflow

### Setting Up

See [Installation Guide](../getting-started/installation.md)

### Adding Features

1. **Design first:** Use brainstorming → writing-plans workflow
2. **TDD:** Write tests before implementation
3. **Small commits:** Frequent, focused commits
4. **Documentation:** Update docs with code changes

### Plugin Development

See [Adding Plugins Guide](../guides/adding-plugins.md)

---

## Pull Request Process

1. Update STATUS.md if adding plugins or changing versions
2. Add tests for new functionality
3. Ensure all tests pass: `pytest tests/`
4. Update relevant documentation
5. Use conventional commits: `feat:`, `fix:`, `docs:`, etc.

---

## Code Review

All PRs require review. See [Code Standards](code-standards.md) for what we look for.

---

## Questions?

- **Current Status:** [STATUS.md](../STATUS.md)
- **Roadmap:** [MASTER_ROADMAP.md](../roadmap/MASTER_ROADMAP.md)
- **Architecture:** [Concepts](../concepts/)
```

**Step 2: Commit**

```bash
git add docs/contributing/CONTRIBUTING.md
git commit -m "docs: add CONTRIBUTING.md"
```

---

### Task 22: Create code-standards.md

**Files:**
- Create: `docs/contributing/code-standards.md`

**Step 1: Create file**

```markdown
# Code Standards

Coding conventions for IndicAgent.

---

## Linting & Formatting

\`\`\`bash
ruff check . --fix        # Linting
black .                   # Formatting
mypy src/ --ignore-missing-imports  # Type checking
\`\`\`

**Target:** 0 ruff errors on new code

---

## Naming Conventions

### Files
\`[domain]_[purpose]_[suffix].py\`

Examples:
- \`indicator_processor_service.py\`
- \`signal_aggregation_design.md\`

### Redis Streams
\`domain:SYMBOL:TIMEFRAME:type\`

Examples:
- \`market:ES:5m\`
- \`indicators:NQ:15m\`

### Plugin Names
- I1 indicators: \`ind_*\` (e.g., \`ind_sma\`)
- I3 structure: \`struct_*\`
- I4 context: \`ctx_*\`
- I5 patterns: \`patt_*\`
- I6 smart money: \`smc_*\`
- I7 trading: \`setup_*\`

---

## Code Organization

[TODO: Expand with more conventions from CLAUDE.md]

---

**Reference:** [CLAUDE.md](../for-ai-assistants/CLAUDE.md)
```

**Step 2: Commit**

```bash
git add docs/contributing/code-standards.md
git commit -m "docs: add code-standards.md"
```

---

### Task 23: Create testing-standards.md

**Files:**
- Create: `docs/contributing/testing-standards.md`

**Step 1: Create file**

```markdown
# Testing Standards

Test guidelines for IndicAgent.

---

## Running Tests

\`\`\`bash
pytest tests/unit/ -v                  # Unit tests
pytest tests/integration/ -v           # Integration tests
python tests/run_all_tests.py          # Full suite
python tests/run_all_tests.py --coverage  # With coverage
\`\`\`

**Current:** See [STATUS.md](../STATUS.md) for test count

---

## Test Organization

\`\`\`
tests/
├── unit/           # Fast, isolated tests
├── integration/    # Multi-component tests (requires Redis/PostgreSQL)
└── e2e/            # End-to-end tests
\`\`\`

---

## Writing Tests

### Unit Tests

[TODO: Examples of good unit tests]

### Integration Tests

[TODO: Examples of integration tests]

---

## Coverage Requirements

[TODO: Define coverage thresholds]

---

**Guide:** [Testing](../guides/testing.md)
```

**Step 2: Commit**

```bash
git add docs/contributing/testing-standards.md
git commit -m "docs: add testing-standards.md"
```

---

## Phase 7: Final Touches

### Task 24: Update Root README.md to Point to New Docs

**Files:**
- Modify: `README.md` (root)

**Step 1: Update documentation section**

Replace existing documentation links with:

```markdown
## Documentation

**→ [Full Documentation](docs/README.md)**
**→ [Current Status](docs/STATUS.md)**
**→ [Roadmap](docs/roadmap/MASTER_ROADMAP.md)**
**→ [Quick Start](docs/getting-started/quickstart.md)**

**For AI Assistants:** [CLAUDE.md](docs/for-ai-assistants/CLAUDE.md)
```

**Step 2: Verify changes**

```bash
git diff README.md
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update root README links to new doc structure"
```

---

### Task 25: Add Maintenance Checklist

**Files:**
- Create: `docs/contributing/maintenance-checklist.md`

**Step 1: Create checklist**

```markdown
# Documentation Maintenance Checklist

Keep docs up-to-date with regular maintenance.

---

## After Every Release

- [ ] Update STATUS.md version number
- [ ] Update STATUS.md intelligence tiers table (plugin counts)
- [ ] Update STATUS.md system health table (service versions)
- [ ] Add entry to STATUS.md "Recent Changes"
- [ ] Update CLAUDE.md version (sync with STATUS.md)
- [ ] Update CLAUDE.md plugin count

---

## When Adding Plugins

- [ ] Add plugin to reference/plugins/iX-*.md
- [ ] Update STATUS.md plugin count in intelligence tiers table
- [ ] Update CLAUDE.md plugin count in "Plugin System" section
- [ ] Optional: Add example to guides/adding-plugins.md

---

## When Completing Major Phases

- [ ] Update MASTER_ROADMAP.md phase status
- [ ] Move completed phase to "Completed" section
- [ ] Update STATUS.md "Next Steps" if priorities changed
- [ ] Consider updating architecture docs in concepts/

---

## Quarterly (Every 3 Months)

- [ ] Run STATUS.md audit: plugin counts vs actual codebase
- [ ] Verify service versions in system health table
- [ ] Check for broken internal links
- [ ] Update outdated examples/screenshots
- [ ] Archive obsolete content to _archive/
- [ ] Run /claude-md-improver skill

---

## When Making Doc Changes

- [ ] Update "Last Updated" date in modified files
- [ ] Check cross-references still work
- [ ] Verify markdown renders correctly
- [ ] Commit with "docs:" prefix

---

**Last Review:** 2026-02-17
```

**Step 2: Commit**

```bash
git add docs/contributing/maintenance-checklist.md
git commit -m "docs: add maintenance checklist for keeping docs current"
```

---

### Task 26: Verification & Final Commit

**Files:**
- Verify all structure

**Step 1: Verify directory structure**

```bash
tree docs/ -L 2 -d
```

Expected output should show:
- getting-started/
- guides/
- concepts/
- reference/
  - api/
  - plugins/
  - services/
  - schemas/
- contributing/
- for-ai-assistants/
- roadmap/
- _archive/

**Step 2: Verify key files exist**

```bash
ls -la docs/STATUS.md
ls -la docs/README.md
ls -la docs/for-ai-assistants/CLAUDE.md
ls -la docs/roadmap/MASTER_ROADMAP.md
```

**Step 3: Check for broken links (optional)**

Manually check a few key navigation paths work.

**Step 4: Final commit**

```bash
git add docs/
git commit -m "docs: complete documentation restructuring to industry-standard OSS pattern

COMPLETE:
- STATUS.md as single source of truth
- Role-based navigation (docs/README.md)
- Industry-standard directory structure (getting-started/guides/concepts/reference)
- Section navigation READMEs
- Migrated key content (CLAUDE.md, architecture docs, stream-schemas)
- Archive with deprecation notice
- Contributing guidelines
- Maintenance checklist

TODO (incremental):
- Fill stub documents (getting-started tutorials, guides)
- Expand reference docs (API, plugins, services)
- Create plugin detail pages (i1-indicators.md, etc.)
- Migrate remaining valuable content from old architecture/

Phase 1 complete — foundation ready for incremental content migration.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Success Criteria

### Phase 1 (Foundation) — COMPLETE
- [ ] New directory structure created
- [ ] STATUS.md exists as single source of truth
- [ ] docs/README.md routes users by role
- [ ] Section navigation READMEs in place
- [ ] CLAUDE.md moved to for-ai-assistants/
- [ ] Key content migrated (architecture docs, stream-schemas)
- [ ] Archive created with deprecation notice
- [ ] Contributing guidelines in place

### Phase 2 (Content) — TODO (Incremental)
- [ ] Fill getting-started stubs (quickstart, installation, first-plugin, architecture-overview)
- [ ] Fill guides stubs (adding-plugins, running-services, monitoring, testing, etc.)
- [ ] Create detailed plugin reference pages (i1-indicators.md with all 16 plugins)
- [ ] Create service reference pages (hf-tws-daemon.md, etc.)
- [ ] Create API reference docs (REST endpoints, SSE protocol)
- [ ] Migrate remaining architecture/ content
- [ ] Update all cross-references

### Phase 3 (Validation) — TODO (After Content)
- [ ] External contributor can onboard via quickstart.md
- [ ] AI assistants can navigate effectively
- [ ] No broken internal links
- [ ] Zero "where do I find X?" questions

---

## Notes

**Incremental Approach:** This plan creates the foundation (directory structure, STATUS.md, navigation) immediately. Content migration happens incrementally — fill stubs as needed, prioritizing high-traffic docs first.

**Backward Compatibility:** Old docs remain in original locations during transition. Archive happens after migration complete.

**Maintenance:** Use docs/contributing/maintenance-checklist.md to keep docs current.

---

**Total Tasks:** 26
**Estimated Time:** 3-4 hours (Phase 1 foundation), ongoing for content migration
**Next Step:** Execute this plan with superpowers:executing-plans or superpowers:subagent-driven-development
