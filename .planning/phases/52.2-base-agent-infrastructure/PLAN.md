# Phase 52.2: BaseAgent Infrastructure + IndicatorComputeAgent Class Rename

**Status:** 📋 Planned

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 52.1 (wiring fixes complete, services import cleanly)

---

## Goals

Create the `BaseAgent` abstract base class that codifies the Renaissance Agentic DAG standard — SIGTERM drain, Golden Signal metrics registration, consumer lag reporting — so every current and future agent inherits operational behaviour rather than hand-rolling it. Then apply it immediately to `IndicatorComputeAgent` (whose class is still named `IndicatorService`) as the first concrete inheritor.

**Rule:** Build the foundation once. Every agent that follows inherits for free.

---

## Success Criteria

1. `src/core/agent/__init__.py` and `src/core/agent/base.py` exist
2. `BaseAgent` provides: `start()`, `stop()`, SIGTERM handler registration, `_report_consumer_lag()` background task, Golden Signal metric scaffolding
3. `isinstance(IndicatorComputeAgent(), BaseAgent)` → `True`
4. `IndicatorComputeAgent` class name used everywhere (class def, logs, metrics labels)
5. No hot-path DB writes in `IndicatorComputeAgent` (startup warmup read is allowed)
6. `AgentRegistry` can register and enumerate live agents
7. All unit tests pass; no import regressions

---

## Tasks

### Task 1: Define `BaseAgent` contract (TDD-first)

**Files:** `src/core/agent/__init__.py`, `src/core/agent/base.py`, `tests/unit/test_base_agent.py`

- [ ] Write failing tests:
  ```python
  # tests/unit/test_base_agent.py
  from src.core.agent.base import BaseAgent

  class MinimalAgent(BaseAgent):
      async def _run(self): pass

  def test_base_agent_is_abstract():
      import inspect
      assert inspect.isabstract(BaseAgent)

  def test_minimal_agent_inherits():
      agent = MinimalAgent(name="test_agent")
      assert isinstance(agent, BaseAgent)

  def test_base_agent_has_lifecycle_methods():
      agent = MinimalAgent(name="test_agent")
      assert hasattr(agent, "start")
      assert hasattr(agent, "stop")
      assert hasattr(agent, "_report_consumer_lag")

  def test_base_agent_name_sets_logger_context():
      agent = MinimalAgent(name="test_agent")
      assert agent.name == "test_agent"

  async def test_sigterm_sets_stop_flag():
      import asyncio, signal as sig
      agent = MinimalAgent(name="test_agent")
      agent._register_signal_handlers()
      # Simulate SIGTERM
      import os
      os.kill(os.getpid(), sig.SIGTERM)
      await asyncio.sleep(0.01)
      assert agent._stop_event.is_set()
  ```
  Run: `.venv/bin/pytest tests/unit/test_base_agent.py -v` → FAIL (module missing)

- [ ] Create `src/core/agent/__init__.py` (empty)
- [ ] Create `src/core/agent/base.py`:
  ```python
  """BaseAgent — Renaissance Agentic DAG standard lifecycle base class."""
  from __future__ import annotations
  import abc
  import asyncio
  import signal
  from datetime import UTC, datetime
  import structlog

  class BaseAgent(abc.ABC):
      """
      Abstract base for all IndicAgent pipeline agents.

      Provides:
      - SIGTERM/SIGINT graceful drain via _stop_event
      - _report_consumer_lag() background reporting hook
      - start() / stop() lifecycle contract
      - Structured logger bound with agent name
      """

      def __init__(self, name: str) -> None:
          self.name = name
          self._stop_event = asyncio.Event()
          self.log = structlog.get_logger().bind(agent=name)

      def _register_signal_handlers(self) -> None:
          loop = asyncio.get_event_loop()
          for sig in (signal.SIGTERM, signal.SIGINT):
              loop.add_signal_handler(sig, self._stop_event.set)

      async def start(self) -> None:
          """Entry point: register signals, start lag reporter, run main loop."""
          self._register_signal_handlers()
          self.log.info("agent.starting")
          lag_task = asyncio.create_task(self._report_consumer_lag())
          try:
              await self._run()
          finally:
              lag_task.cancel()
              await self.stop()

      async def stop(self) -> None:
          """Drain and clean up. Override to add flush logic."""
          self.log.info("agent.stopped")

      async def _report_consumer_lag(self) -> None:
          """
          Override to publish persistence_consumer_lag to Prometheus.
          Default: no-op background task (safe to call without override).
          """
          while not self._stop_event.is_set():
              await asyncio.sleep(15)

      @abc.abstractmethod
      async def _run(self) -> None:
          """Main processing loop. Must check _stop_event and exit cleanly."""
          ...
  ```
  Run tests → PASS

### Task 2: `AgentRegistry`

**Files:** `src/core/agent/registry.py`, `tests/unit/test_agent_registry.py`

- [ ] Write failing tests:
  ```python
  from src.core.agent.registry import AgentRegistry
  from src.core.agent.base import BaseAgent

  class FakeAgent(BaseAgent):
      async def _run(self): pass

  def test_register_and_list():
      registry = AgentRegistry()
      agent = FakeAgent(name="fake")
      registry.register(agent)
      assert "fake" in registry.list_names()

  def test_registry_is_singleton():
      from src.core.agent.registry import AgentRegistry
      r1, r2 = AgentRegistry(), AgentRegistry()
      assert r1 is r2
  ```

- [ ] Create `src/core/agent/registry.py`:
  ```python
  """AgentRegistry — tracks live agents, their topics, and resource thresholds."""
  from __future__ import annotations
  from typing import ClassVar
  from src.core.agent.base import BaseAgent

  class AgentRegistry:
      _instance: ClassVar[AgentRegistry | None] = None
      _agents: dict[str, BaseAgent]

      def __new__(cls) -> AgentRegistry:
          if cls._instance is None:
              cls._instance = super().__new__(cls)
              cls._instance._agents = {}
          return cls._instance

      def register(self, agent: BaseAgent) -> None:
          self._agents[agent.name] = agent

      def list_names(self) -> list[str]:
          return list(self._agents.keys())

      def get(self, name: str) -> BaseAgent | None:
          return self._agents.get(name)
  ```
  Run tests → PASS

### Task 3: Rename `IndicatorService` → `IndicatorComputeAgent`, inherit `BaseAgent`

**File:** `services/indicator_compute_agent.py`

- [ ] Write test:
  ```python
  # tests/unit/test_indicator_compute_agent_class.py
  def test_class_is_indicator_compute_agent():
      import ast, pathlib
      src = pathlib.Path("services/indicator_compute_agent.py").read_text()
      tree = ast.parse(src)
      class_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
      assert "IndicatorComputeAgent" in class_names
      assert "IndicatorService" not in class_names

  def test_inherits_base_agent():
      import ast, pathlib
      src = pathlib.Path("services/indicator_compute_agent.py").read_text()
      assert "BaseAgent" in src
  ```
  Run → FAIL

- [ ] In `services/indicator_compute_agent.py`:
  - Add import: `from src.core.agent.base import BaseAgent`
  - Rename class: `class IndicatorService:` → `class IndicatorComputeAgent(BaseAgent):`
  - In `__init__`: add `super().__init__(name="indicator_compute_agent")`
  - Override `_report_consumer_lag()` to emit `persistence_consumer_lag` metric if available
  - Update any `IndicatorService(` instantiation references in `if __name__ == "__main__"` block

- [ ] Verify no hot-path DB writes exist (startup warmup read is acceptable — it uses DatabaseManager only in `__init__` for seeding history):
  ```bash
  grep -n "db_manager\." services/indicator_compute_agent.py | grep -v "def \|#\|init\|seed\|warm"
  ```
  Expected: 0 results (all DB calls are in warmup/init path)

- [ ] Run tests → PASS

### Task 4: Update systemd unit and log references

- [ ] Check if `/etc/systemd/system/indicagent-indicator-compute.service` already uses the new filename (it should — file was renamed earlier)
- [ ] Verify `ExecStart` points to `services/indicator_compute_agent.py`
- [ ] Verify `logs/indicator_compute_agent.log` path in service (already correct since file is named `indicator_compute_agent.py`)
- [ ] If systemd unit needs updating:
  ```bash
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl daemon-reload
  ```

### Task 5: Full test suite + lint

- [ ] `.venv/bin/pytest tests/unit/ -q` — pass
- [ ] `.venv/bin/ruff check . --fix`
- [ ] `.venv/bin/black .`
- [ ] Commit: `feat(agent): add BaseAgent + AgentRegistry; rename IndicatorService → IndicatorComputeAgent`

---

## Source Plans

- `docs/plans/2026-03-25-agent-bootstrap-standard.md`
- `docs/plans/2026-03-25-indicator-compute-agent-refactor.md`
