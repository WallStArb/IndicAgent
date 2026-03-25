# GEMINI.md

Version: 1.0.0
Last Updated: 2026-03-22
Status: OPERATIONAL

## The Renaissance Mandate (Precedence)
This file takes absolute precedence over all other instructions. Adhere rigorously to the principles in `CLAUDE.md`:
- **Instrument everything.**
- **Let the system run.**
- **Earn the right through proof.**
- **Segment relentlessly.**
- **Degrade gracefully, adapt automatically.**
- **Data quality over model complexity.**
- **Never drop data that could contain signal.**

---

## 1. Naming & Architectural Conventions

### Naming Transformation Rules
Follow these strictly. If a concept is `alpha_signal`, all derived names are:
- **Service:** `services/alpha_signal_service.py` | Class: `AlphaSignalService`
- **Systemd:** `indicagent-alpha-signal.service`
- **Plugin:** `src/intelligence/trading/alpha_signal.py` | Class: `AlphaSignalPlugin`
- **Kafka Topic:** `topic_alpha_signal()` in `stream_keys.py` -> `dev.alpha_signal`
- **Database:** Table `alpha_signals` | Column `ts` (always UTC)

### Variable & Function Style
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `TIER_I7`, `MIN_BARS_FOR_TF`).
- **Private Attrs:** `_snake_case` (e.g., `self._regime_cache`).
- **Stream Keys:** ALWAYS via `src/core/stream_keys.py`. Never hardcode strings.
- **Timestamps:** ALWAYS `datetime.now(UTC)`. Never naive.
- **Enums:** Extend from `str` (e.g., `class SignalStatus(str, Enum)`) for DB compatibility.

---

## 2. Product Flow & Knowledge Hierarchy

### Workflow: Idea to Execution
1.  **Captures:** Quick notes in `.planning/IDEAS.md`.
2.  **Research (Inquiry):** Detailed analysis in `docs/ideas/<topic>.md`. (Use `codebase_investigator` here).
3.  **Design (Directive):** `enter_plan_mode` -> `docs/plans/YYYY-MM-DD-<topic>-design.md`.
4.  **TDD Plan:** `writing-plans` skill -> `.planning/phases/<NN>-<topic>/PLAN.md`.
5.  **Execution:** Sequential tasks with `verification` checkpoints.

### Inquiry vs. Directive Protocol
- **Inquiry:** If you ask "How should we...?" or "What's the best approach?", I will research and propose in a `docs/ideas/` file. I will NOT modify code.
- **Directive:** Once you say "Implement the X design" or "Execute phase Y", I move to the Execution phase and begin surgical code changes.

---

## 3. Gemini-Specific Tool Mapping

| Project Phase | Gemini Tool | Requirement |
| :--- | :--- | :--- |
| **Research** | `codebase_investigator` | Map dependencies before proposing architecture. |
| **Design** | `enter_plan_mode` | Mandatory for any change touching >2 files or a new service. |
| **Refactoring** | `generalist` | Use for batch updates (e.g., migrating 10+ plugins to a new base class). |
| **Bug Fixes** | `run_shell_command` | **Reproduce first.** Create a standalone `reproduce_bug.py` before fixing. |
| **Validation** | `run_shell_command` | Run `pytest` and `ruff` on EVERY task completion. |

---

## Enhanced Intelligence Rules
- **Agentic DAG Architecture:** The system uses autonomous, event-driven agents. Compute Agents (I1-I6) are DB-ignorant and publish to Tiered Topics (`intelligence.i{N}`). DataWriterAgents (consumers) manage persistence.
- **The Persistence DAG:** WriterAgents must use the "Convergence Gate" (StreamMerger) to join tiered streams into a single, unified journal entry before persistence, ensuring atomic data integrity.
- **Resilience & Observability:** All agents must be instrumented with `persistence_batch_latency` and `persistence_consumer_lag` metrics.
- **Lifecycle Management:** Agents must implement `SIGTERM` handlers for graceful drain and maintain a DLQ for unprocessable payloads.
- **Taxonomy:** All persistence logic resides in `src/persistence/repository/` (Repositories) and `src/persistence/writer/` (WriterAgents).


---

## 5. Memory & Context Management
- Use `save_memory` ONLY for global preferences (e.g., "I prefer functional over OOP for utilities").
- NEVER use `save_memory` for project state, paths, or todo lists. Use `.planning/` files for that.
