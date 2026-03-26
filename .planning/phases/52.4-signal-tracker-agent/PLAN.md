# Phase 52.4: SignalTrackerAgent Refactor

**Status:** 📋 Planned

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 52.2 (BaseAgent available), Phase 52.1 (services import cleanly)

---

## Goals

Rename `signal_lifecycle_service.py` / `SignalLifecycleService` to `signal_tracker_agent.py` / `SignalTrackerAgent`, conforming to the Agentic DAG taxonomy. Extract all direct SQL into `SignalLedgerRepository` and inject it — making the agent DB-ignorant in its core processing path. Inherit `BaseAgent` for SIGTERM drain, lag reporting, and metrics.

**Principle:** Separation of concerns. The agent tracks lifecycle logic and state; the repository owns the SQL.

---

## Success Criteria

1. `services/signal_tracker_agent.py` exists; `services/signal_lifecycle_service.py` deleted (or symlinked for backward compat during transition)
2. Class name is `SignalTrackerAgent`, inherits `BaseAgent`
3. No direct SQL in `SignalTrackerAgent._process_*` methods — all SQL delegated to `SignalLedgerRepository`
4. `SignalLedgerRepository` exists in `src/persistence/repository/signal_ledger_repository.py`
5. Systemd unit renamed: `indicagent-signal-tracker.service` (replaces `indicagent-signal-lifecycle.service`)
6. Log file: `logs/signal_tracker_agent.log`
7. Metric labels updated to `signal_tracker_agent`
8. All existing signal lifecycle unit tests pass under the new class name
9. SIGTERM: drains in-flight lifecycle updates before exit

---

## Tasks

### Task 1: Create `SignalLedgerRepository`

**File:** `src/persistence/repository/signal_ledger_repository.py`
**Test:** `tests/unit/test_signal_ledger_repository.py`

- [ ] Check existing repository dir: `ls src/persistence/repository/`
- [ ] Write failing tests:
  ```python
  # tests/unit/test_signal_ledger_repository.py
  from unittest.mock import AsyncMock, patch
  from src.persistence.repository.signal_ledger_repository import SignalLedgerRepository

  def test_repository_exists():
      repo = SignalLedgerRepository.__new__(SignalLedgerRepository)
      assert repo is not None

  def test_update_lifecycle_state_method_exists():
      assert hasattr(SignalLedgerRepository, "update_lifecycle_state")

  def test_update_mae_mfe_method_exists():
      assert hasattr(SignalLedgerRepository, "update_mae_mfe")

  def test_fetch_active_signals_method_exists():
      assert hasattr(SignalLedgerRepository, "fetch_active_signals")
  ```
  Run → FAIL

- [ ] Create `SignalLedgerRepository`:
  - `__init__(self, pool: asyncpg.Pool)` — accepts injected pool, no DatabaseManager
  - `async def update_lifecycle_state(self, signal_id: str, new_status: str, outcome: str | None, exit_price: float | None, ...) -> None`
  - `async def update_mae_mfe(self, signal_id: str, mae: float, mfe: float) -> None`
  - `async def fetch_active_signals(self, symbol: str, tf: str) -> list[dict]`
  - `async def fetch_pending_signals(self) -> list[dict]`
  - All SQL extracted from `signal_lifecycle_service.py` lifecycle update methods
  - Use `asyncpg` pool directly (not DatabaseManager)

- [ ] Run tests → PASS

### Task 2: Write `SignalTrackerAgent` class (TDD-first)

**File:** `services/signal_tracker_agent.py`
**Test:** `tests/unit/service_tests/test_signal_tracker_agent.py`

- [ ] Write failing tests:
  ```python
  # tests/unit/service_tests/test_signal_tracker_agent.py
  from src.core.agent.base import BaseAgent

  def test_class_name():
      import ast, pathlib
      src = pathlib.Path("services/signal_tracker_agent.py").read_text()
      tree = ast.parse(src)
      class_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
      assert "SignalTrackerAgent" in class_names
      assert "SignalLifecycleService" not in class_names

  def test_inherits_base_agent():
      import pathlib
      src = pathlib.Path("services/signal_tracker_agent.py").read_text()
      assert "BaseAgent" in src

  def test_no_direct_sql():
      import pathlib
      src = pathlib.Path("services/signal_tracker_agent.py").read_text()
      # No raw SQL in the agent class — all delegated to repository
      assert "UPDATE signal_ledger" not in src
      assert "INSERT INTO signal_ledger" not in src

  def test_uses_signal_ledger_repository():
      import pathlib
      src = pathlib.Path("services/signal_tracker_agent.py").read_text()
      assert "SignalLedgerRepository" in src

  def test_has_sigterm_drain():
      import pathlib
      src = pathlib.Path("services/signal_tracker_agent.py").read_text()
      assert "_stop_event" in src or "SIGTERM" in src
  ```
  Run → FAIL

- [ ] Implement `services/signal_tracker_agent.py`:
  - Copy logic from `signal_lifecycle_service.py` as starting point
  - Replace `DatabaseManager` with injected `SignalLedgerRepository`
  - Rename class `SignalLifecycleService` → `SignalTrackerAgent`
  - Inherit `BaseAgent(name="signal_tracker_agent")`
  - Override `_run()` as the main consumer loop
  - Override `_report_consumer_lag()` to emit `persistence_consumer_lag`
  - Override `stop()` to drain in-flight updates before exit
  - Remove any direct SQL from the class body (all via repository)
  - Update logger bindings to use `signal_tracker_agent`
  - Update metric labels to `signal_tracker_agent`

- [ ] Run tests → PASS

### Task 3: Migrate existing unit tests

**File:** `tests/unit/service_tests/test_signal_lifecycle_service.py` (if exists)

- [ ] Check: `ls tests/unit/service_tests/test_signal_lifecycle_service.py 2>/dev/null`
- [ ] If exists: rename to `test_signal_tracker_agent.py`, update class import and `__new__` pattern:
  ```python
  # Replace:
  svc = SignalLifecycleService.__new__(SignalLifecycleService)
  # With:
  svc = SignalTrackerAgent.__new__(SignalTrackerAgent)
  svc._repo = MagicMock()  # injected repository
  ```
- [ ] Run migrated tests → PASS

### Task 4: Update systemd unit

- [ ] Create `production/systemd/indicagent-signal-tracker.service` (copy from `indicagent-signal-lifecycle.service`, update ExecStart path)
- [ ] Stop old unit, install and start new unit:
  ```bash
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl stop indicagent-signal-lifecycle
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl disable indicagent-signal-lifecycle
  echo 'PASSWORD' | /usr/bin/sudo.ws -S cp production/systemd/indicagent-signal-tracker.service /etc/systemd/system/
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl daemon-reload
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl enable --now indicagent-signal-tracker
  ```
- [ ] Verify: `journalctl -u indicagent-signal-tracker --since "1 minute ago" -n 20`
- [ ] Update CLAUDE.md Active Services table: `indicagent-signal-lifecycle` → `indicagent-signal-tracker`

### Task 5: Keep `signal_lifecycle_service.py` as compatibility shim (one cycle only)

- [ ] Add a one-line deprecation shim to `services/signal_lifecycle_service.py` (or delete if no external references):
  ```python
  # DEPRECATED — use services/signal_tracker_agent.py
  from services.signal_tracker_agent import SignalTrackerAgent as SignalLifecycleService  # noqa: F401
  ```
- [ ] Grep for any external imports of `signal_lifecycle_service`: `grep -rn "signal_lifecycle_service" . --include="*.py" | grep -v "services/signal_lifecycle_service"`
- [ ] Update any found references to import from `signal_tracker_agent`

### Task 6: Full test suite + lint + commit

- [ ] `.venv/bin/pytest tests/unit/ -q` — pass
- [ ] `.venv/bin/ruff check . --fix && .venv/bin/black .`
- [ ] Commit: `refactor(lifecycle): SignalLifecycleService → SignalTrackerAgent, extract SignalLedgerRepository`

---

## Source Plan

- `docs/plans/2026-03-25-signal-tracker-agent-refactor.md`
