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

## 4. Enhanced Intelligence Rules

- **Identity Preservation:** Never merge distinct signals (e.g., OFI vs CVD) into one class. They must be separable features for ML.
- **Confluence Obligation:** Every I7 plugin MUST consume `ctf_*` scores from I6. If it doesn't, it must document WHY in the plugin's docstring.
- **Validation-First:** New plugins must include a unit test in `tests/unit/intelligence/` that verifies expected output against a mocked 10-bar sequence.
- **No Shadowing:** Ensure new SSE event names (e.g., `signal_scorecard`) are checked in `sse.py` BEFORE general domain checks.

---

## 5. Memory & Context Management
- Use `save_memory` ONLY for global preferences (e.g., "I prefer functional over OOP for utilities").
- NEVER use `save_memory` for project state, paths, or todo lists. Use `.planning/` files for that.
