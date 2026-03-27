---
phase: 52.4-signal-tracker-agent
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/persistence/repository/signal_ledger_repository.py
  - services/signal_tracker_agent.py
  - services/signal_lifecycle_service.py
  - services/indicagent-signal-tracker.service
  - tests/unit/service_tests/test_signal_tracker_agent.py
  - tests/unit/service_tests/test_lifecycle_freshness.py
  - tests/unit/service_tests/test_lifecycle_active_index.py
  - tests/unit/intelligence/test_lifecycle_tracker.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "SignalTrackerAgent inherits BaseAgent and uses self._stop_event for shutdown"
    - "All SQL in signal_tracker_agent.py is delegated to self._ledger_repo methods"
    - "All 4 test files import from signal_tracker_agent, not signal_lifecycle_service"
    - "Zero pre-existing test failures (the 6 AttributeError failures are resolved)"
    - "Systemd unit indicagent-signal-tracker.service exists and runs the new agent"
  artifacts:
    - path: "services/signal_tracker_agent.py"
      provides: "SignalTrackerAgent(BaseAgent) class"
      contains: "class SignalTrackerAgent(BaseAgent)"
    - path: "src/persistence/repository/signal_ledger_repository.py"
      provides: "Extended repo with chandelier + shadow methods"
      contains: "record_chandelier_update"
    - path: "services/indicagent-signal-tracker.service"
      provides: "Systemd unit for new agent"
      contains: "signal_tracker_agent.py"
  key_links:
    - from: "services/signal_tracker_agent.py"
      to: "src/persistence/repository/signal_ledger_repository.py"
      via: "self._ledger_repo = SignalLedgerRepository(db_manager)"
      pattern: "self\\._ledger_repo"
    - from: "services/signal_tracker_agent.py"
      to: "src/core/agent/base.py"
      via: "class SignalTrackerAgent(BaseAgent)"
      pattern: "class SignalTrackerAgent\\(BaseAgent\\)"
---

<objective>
Rename SignalLifecycleService to SignalTrackerAgent, inheriting BaseAgent. Extract remaining
inline SQL to SignalLedgerRepository. Fix 6 pre-existing test failures caused by stale
module-level function calls. Migrate all 4 test files. Create systemd unit. Delete old service file.

Purpose: Renaissance DAG taxonomy compliance — agent owns lifecycle logic, repository owns SQL.
Output: services/signal_tracker_agent.py, extended signal_ledger_repository.py, 4 migrated test files, systemd unit.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/52.4-signal-tracker-agent/52.4-CONTEXT.md

<interfaces>
<!-- Existing BaseAgent interface (src/core/agent/base.py): -->

class BaseAgent(abc.ABC):
    def __init__(self, name: str) -> None:
        self.name = name
        self._stop_event: asyncio.Event = asyncio.Event()
        self.logger: structlog.BoundLogger = structlog.get_logger().bind(agent=name)

    def _register_signal_handlers(self) -> None: ...
    async def start(self) -> None: ...       # registers signals, creates lag_task, calls _run(), finally stop()
    async def stop(self) -> None: ...        # override to add flush/drain
    async def _report_consumer_lag(self) -> None: ...  # override for metrics
    @abc.abstractmethod
    async def _run(self) -> None: ...

<!-- Existing SignalLedgerRepository (src/persistence/repository/signal_ledger_repository.py): -->

class SignalLedgerRepository:
    def __init__(self, db_manager: Any): ...
    async def insert_signals(self, entries: list[LedgerEntry]) -> None: ...
    async def insert_signals_with_features(self, entries, features, cis_result=None) -> None: ...
    async def update_signal_status(self, signal_id: str, **kwargs) -> None: ...
    async def get_active_signals(self, symbol: str | None = None) -> list[dict]: ...
    async def record_activation(self, signal_id: str, **kwargs) -> None: ...
    async def record_zone_resolution(self, signal_id: str, **kwargs) -> None: ...
    async def record_market_resolution(self, signal_id: str, **kwargs) -> None: ...
    async def record_zone_resolution_with_activation(self, signal_id: str, **kwargs) -> None: ...

<!-- IndicatorComputeAgent pattern (services/indicator_compute_agent.py) — follow this: -->
<!-- - Override start() (NOT _run()) for full lifecycle -->
<!-- - Call self._register_signal_handlers() first in start() -->
<!-- - Create lag_task = asyncio.create_task(self._report_consumer_lag()) -->
<!-- - asyncio.gather() for process_loop + health_monitor + reseed tasks -->
<!-- - _run() raises NotImplementedError("Use start() directly") -->
<!-- - stop() drains kafka, pending_tasks, closes DB -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Extend SignalLedgerRepository with chandelier + shadow + fetch methods</name>

  <read_first>
    - src/persistence/repository/signal_ledger_repository.py (630 lines — the repo to EXTEND, per D-04)
    - services/signal_lifecycle_service.py lines 56-73 (_UPDATE_CHANDELIER_SQL, _UPDATE_SHADOW_SQL)
    - services/signal_lifecycle_service.py lines 614-625 (inline chandelier_vol_source SQL)
    - services/signal_lifecycle_service.py lines 795-801 (inline shadow_tracking_start_ts SQL)
  </read_first>

  <files>src/persistence/repository/signal_ledger_repository.py</files>

  <action>
  EXTEND the existing SignalLedgerRepository class (per D-04). Do NOT recreate it. Do NOT change the constructor signature — it takes `db_manager: Any` (a DatabaseManager instance), not asyncpg.Pool.

  Add these SQL constants ABOVE the class definition (after the existing _RECORD_ZONE_WITH_ACTIVATION_SQL):

  1. _UPDATE_CHANDELIER_SQL — move from signal_lifecycle_service.py lines 56-64 verbatim:
     ```sql
     UPDATE signal_ledger
     SET trailing_stop_price = $2::jsonb,
         trailing_stop_tightening_rate = $3,
         staleness_score = $4,
         staleness_trigger_reason = $5,
         chandelier_vol_source = COALESCE(chandelier_vol_source, $6)
     WHERE signal_id = $1::uuid
     ```

  2. _UPDATE_SHADOW_SQL — move from signal_lifecycle_service.py lines 66-73 verbatim:
     ```sql
     UPDATE signal_ledger
     SET shadow_tracking_start_ts = $2,
         shadow_mae = $3,
         shadow_mfe = $4,
         shadow_outcome = $5
     WHERE signal_id = $1::uuid
     ```

  3. _UPDATE_CHANDELIER_VOL_SOURCE_SQL (new — extracted from inline SQL at line 617):
     ```sql
     UPDATE signal_ledger SET chandelier_vol_source = $2
     WHERE signal_id = $1::uuid AND chandelier_vol_source IS NULL
     ```

  4. _UPDATE_SHADOW_TRACKING_START_SQL (new — extracted from inline SQL at line 798):
     ```sql
     UPDATE signal_ledger SET shadow_tracking_start_ts = $2
     WHERE signal_id = $1::uuid
     ```

  Add these methods to SignalLedgerRepository class:

  ```python
  async def record_chandelier_update(self, signal_id: str, **kwargs: Any) -> None:
      """Write Chandelier trailing stop state + staleness to signal_ledger."""
      await self._db_manager.execute_command(
          _UPDATE_CHANDELIER_SQL,
          signal_id,
          kwargs.get("trailing_stop_history"),   # jsonb string
          kwargs.get("tightening_rate"),
          kwargs.get("staleness_score"),
          kwargs.get("staleness_trigger_reason"),
          kwargs.get("vol_source"),
      )

  async def record_chandelier_vol_source(self, signal_id: str, vol_source: str) -> None:
      """Write chandelier_vol_source at initialization time (COALESCE — only if NULL)."""
      await self._db_manager.execute_command(
          _UPDATE_CHANDELIER_VOL_SOURCE_SQL,
          signal_id,
          vol_source,
      )

  async def record_shadow_tracking_start(self, signal_id: str, start_ts: datetime) -> None:
      """Write shadow_tracking_start_ts when condition_expired signal enters shadow mode."""
      await self._db_manager.execute_command(
          _UPDATE_SHADOW_TRACKING_START_SQL,
          signal_id,
          start_ts,
      )

  async def record_shadow_outcome(self, signal_id: str, **kwargs: Any) -> None:
      """Write shadow tracking outcome when shadow signal TTL expires."""
      await self._db_manager.execute_command(
          _UPDATE_SHADOW_SQL,
          signal_id,
          kwargs.get("shadow_tracking_start_ts"),
          kwargs.get("shadow_mae"),
          kwargs.get("shadow_mfe"),
          kwargs.get("shadow_outcome"),
      )
  ```

  Add `from datetime import datetime` to the existing imports at the top of the file (datetime is already imported there but verify).
  </action>

  <verify>
    <automated>.venv/bin/python -c "from src.persistence.repository.signal_ledger_repository import SignalLedgerRepository; r = SignalLedgerRepository.__new__(SignalLedgerRepository); assert hasattr(r, 'record_chandelier_update'); assert hasattr(r, 'record_chandelier_vol_source'); assert hasattr(r, 'record_shadow_tracking_start'); assert hasattr(r, 'record_shadow_outcome'); print('OK')"</automated>
  </verify>

  <acceptance_criteria>
    - grep "record_chandelier_update" src/persistence/repository/signal_ledger_repository.py returns a match
    - grep "record_chandelier_vol_source" src/persistence/repository/signal_ledger_repository.py returns a match
    - grep "record_shadow_tracking_start" src/persistence/repository/signal_ledger_repository.py returns a match
    - grep "record_shadow_outcome" src/persistence/repository/signal_ledger_repository.py returns a match
    - grep "_UPDATE_CHANDELIER_SQL" src/persistence/repository/signal_ledger_repository.py returns a match
    - grep "_UPDATE_SHADOW_SQL" src/persistence/repository/signal_ledger_repository.py returns a match
    - grep "def __init__(self, db_manager" src/persistence/repository/signal_ledger_repository.py still works (constructor unchanged)
  </acceptance_criteria>

  <done>SignalLedgerRepository has 4 new methods: record_chandelier_update, record_chandelier_vol_source, record_shadow_tracking_start, record_shadow_outcome. SQL constants moved from service. Constructor unchanged (takes db_manager).</done>
</task>

<task type="auto">
  <name>Task 2: Create SignalTrackerAgent from SignalLifecycleService + fix broken call sites (D-03, D-05)</name>

  <read_first>
    - services/signal_lifecycle_service.py (ALL 1162 lines — the source to refactor)
    - services/indicator_compute_agent.py lines 669-761 (canonical start/stop/_run pattern per D-05)
    - src/core/agent/base.py (BaseAgent interface)
    - src/persistence/repository/signal_ledger_repository.py (repo methods available after Task 1)
  </read_first>

  <files>services/signal_tracker_agent.py</files>

  <action>
  Create services/signal_tracker_agent.py by copying services/signal_lifecycle_service.py and applying these changes:

  **Class rename and inheritance (per D-05):**
  - Rename `class SignalLifecycleService` to `class SignalTrackerAgent(BaseAgent)`
  - In `__init__`: call `super().__init__(name="signal_tracker_agent")` AFTER loading config (same pattern as IndicatorComputeAgent line 208)
  - Remove `self.running = False` (not used — BaseAgent uses `self._stop_event`)
  - Remove `self.shutdown_requested = False` (replaced by `self._stop_event.is_set()`)
  - Remove `self.shutdown_event: asyncio.Event = asyncio.Event()` (replaced by `self._stop_event`)
  - Remove `signal.signal(signal.SIGINT, self._signal_handler)` and `signal.signal(signal.SIGTERM, self._signal_handler)` (BaseAgent handles via `_register_signal_handlers()`)
  - Remove `self.logger = structlog.get_logger(__name__)` (BaseAgent provides `self.logger`)
  - Remove the `_signal_handler` method entirely
  - Keep `self._ledger_repo` initialization as-is: `SignalLedgerRepository(db_manager) if db_manager else None`
  - Keep all instance attributes: `_mae`, `_mfe`, `_activated_at`, `_market_*`, `_chandelier_state`, `_staleness_consecutive`, `_shadow_signals`, `_active_index`, `_pending_tasks`, metrics

  **DB injection (per D-06):**
  - Keep the existing pattern: `__init__` takes optional `db_manager: DatabaseManager | None = None` and constructs `self._ledger_repo = SignalLedgerRepository(db_manager) if db_manager else None`
  - In `_connect_database()`: after creating DatabaseManager and initializing, also create the repo: `self._ledger_repo = SignalLedgerRepository(self.db_manager)`

  **start() override (per D-05 — follow IndicatorComputeAgent exactly):**
  ```python
  async def start(self) -> None:
      self._register_signal_handlers()
      lag_task = asyncio.create_task(self._report_consumer_lag())
      self.logger.info("Starting Signal Tracker Agent")
      try:
          await self._connect_database()
          start_metrics_server(port=self.config.get("metrics_port", 9115))
          await self._setup_kafka_clients()
          await self._reseed_chandelier_state()
          await self._seed_active_index()
          tasks = [
              asyncio.create_task(self._process_loop()),
              asyncio.create_task(self._health_monitor_loop()),
              asyncio.create_task(self._active_index_reseed_loop()),
          ]
          self.logger.info("Signal Tracker Agent started")
          await asyncio.gather(*tasks, return_exceptions=True)
      except Exception as e:
          self.logger.error("Failed to start signal tracker agent", error=str(e))
          raise
      finally:
          lag_task.cancel()
          try:
              await lag_task
          except asyncio.CancelledError:
              pass
          await self.stop()
  ```

  **_run() override (per D-05):**
  ```python
  async def _run(self) -> None:
      """Main loop managed by start() directly -- not called via BaseAgent.start()."""
      raise NotImplementedError("Use start() directly")
  ```

  **stop() override (per D-05):**
  ```python
  async def stop(self) -> None:
      self.logger.info("Stopping Signal Tracker Agent")
      self._stop_event.set()  # Signal all loops to exit
      if self._pending_tasks:
          self.logger.info("Draining background tasks", count=len(self._pending_tasks))
          await asyncio.gather(*self._pending_tasks, return_exceptions=True)
      if self._kafka_consumer:
          await self._kafka_consumer.stop()
      if self._kafka_producer:
          await self._kafka_producer.stop()
      if self.db_manager:
          await self.db_manager.close()
      self.logger.info("Signal Tracker Agent stopped")
  ```

  **Replace all shutdown checks (global search-replace):**
  - `self.shutdown_requested` -> `self._stop_event.is_set()`
  - `self.shutdown_event.wait()` -> `self._stop_event.wait()`
  - `self.shutdown_event.set()` -> `self._stop_event.set()` (only in stop())
  - `self.running and not self.shutdown_requested` -> `not self._stop_event.is_set()`

  **Fix broken call sites (D-03 — CRITICAL):**
  These 4 call sites use stale module-level function names. Change them to use `self._ledger_repo`:

  1. Line ~473: `await update_signal_status(self.db_manager, sid, ...)` ->
     `await self._ledger_repo.update_signal_status(sid, ...)`
     Remove `self.db_manager` as first arg — the repo already has it internally.

  2. Line ~553: `await record_market_resolution(self.db_manager, sid, ...)` ->
     `await self._ledger_repo.record_market_resolution(sid, ...)`
     Remove `self.db_manager` as first arg.

  3. Line ~821: `await record_activation(self.db_manager, sid, ...)` ->
     `await self._ledger_repo.record_activation(sid, ...)`
     Remove `self.db_manager` as first arg.

  4. Line ~830: `await record_zone_resolution(self.db_manager, sid, ...)` ->
     `await self._ledger_repo.record_zone_resolution(sid, ...)`
     Remove `self.db_manager` as first arg.

  **Replace inline SQL with repo methods (no direct SQL in agent):**

  5. Lines ~614-625 (chandelier_vol_source write):
     Replace `await self.db_manager.execute_command("UPDATE signal_ledger SET chandelier_vol_source..."` with:
     `await self._ledger_repo.record_chandelier_vol_source(sid, vol_source)`

  6. Lines ~688-703 (chandelier state write):
     Replace `await self.db_manager.execute_command(_UPDATE_CHANDELIER_SQL, ...)` with:
     ```python
     await self._ledger_repo.record_chandelier_update(
         sid,
         trailing_stop_history=json.dumps(history),
         tightening_rate=tightening_rate,
         staleness_score=staleness_score_val,
         staleness_trigger_reason=staleness_reason_val,
         vol_source=ch_state.get("vol_source"),
     )
     ```

  7. Lines ~795-801 (shadow_tracking_start_ts write):
     Replace `await self.db_manager.execute_command("UPDATE signal_ledger SET shadow_tracking_start_ts..."` with:
     `await self._ledger_repo.record_shadow_tracking_start(sid, bar_time)`

  8. Lines ~896-903 (shadow outcome write):
     Replace `await self.db_manager.execute_command(_UPDATE_SHADOW_SQL, ...)` with:
     ```python
     await self._ledger_repo.record_shadow_outcome(
         shadow_sid,
         shadow_tracking_start_ts=shadow["start_ts"],
         shadow_mae=round(shadow["shadow_mae"], 4),
         shadow_mfe=round(shadow["shadow_mfe"], 4),
         shadow_outcome=s_outcome,
     )
     ```

  **Remove _UPDATE_CHANDELIER_SQL and _UPDATE_SHADOW_SQL constants** from the agent file — they now live in the repository.

  **Logging config (per D-07):**
  - Change log file in config default: `"logs/signal_lifecycle_service.log"` -> `"logs/signal_tracker_agent.log"`

  **Consumer group (Claude's discretion):**
  - Keep `group_id="signal_lifecycle"` to avoid Redpanda offset reset.

  **Metrics port:** Keep 9115 (unchanged).

  **Import changes:**
  - Add: `from src.core.agent.base import BaseAgent`
  - Remove: `import signal` (BaseAgent handles signal registration)
  - Keep all other imports

  **Module-level functions to KEEP in the agent file** (they are pure functions, not DB calls):
  - `_tf_to_seconds`, `_compute_tightening_rate`, `FRESHNESS_HALF_LIFE_BARS`, `_compute_freshness_decay`, `_bars_elapsed`, `_bars_in_trade`, `_build_outcome_payload`

  **main() function:** Update class name: `SignalTrackerAgent(args.config)` instead of `SignalLifecycleService(args.config)`
  </action>

  <verify>
    <automated>.venv/bin/python -c "
from services.signal_tracker_agent import SignalTrackerAgent
from src.core.agent.base import BaseAgent
assert issubclass(SignalTrackerAgent, BaseAgent), 'Must inherit BaseAgent'
assert hasattr(SignalTrackerAgent, '_stop_event') or True  # instance attr
import ast, pathlib
src = pathlib.Path('services/signal_tracker_agent.py').read_text()
assert 'UPDATE signal_ledger' not in src, 'No raw SQL in agent'
assert 'class SignalTrackerAgent(BaseAgent)' in src
assert 'self._ledger_repo.record_activation' in src
assert 'self._ledger_repo.record_zone_resolution' in src
assert 'self._ledger_repo.record_market_resolution' in src
assert 'self._ledger_repo.update_signal_status' in src
assert 'signal_tracker_agent.log' in src
print('OK')
"</automated>
  </verify>

  <acceptance_criteria>
    - grep "class SignalTrackerAgent(BaseAgent)" services/signal_tracker_agent.py returns a match
    - grep "UPDATE signal_ledger" services/signal_tracker_agent.py returns NO match (zero raw SQL)
    - grep "_UPDATE_CHANDELIER_SQL" services/signal_tracker_agent.py returns NO match
    - grep "_UPDATE_SHADOW_SQL" services/signal_tracker_agent.py returns NO match
    - grep "self._ledger_repo.record_activation" services/signal_tracker_agent.py returns a match
    - grep "self._ledger_repo.update_signal_status" services/signal_tracker_agent.py returns a match
    - grep "self._ledger_repo.record_market_resolution" services/signal_tracker_agent.py returns a match
    - grep "self._ledger_repo.record_zone_resolution" services/signal_tracker_agent.py returns a match
    - grep "self._ledger_repo.record_chandelier_update" services/signal_tracker_agent.py returns a match
    - grep "self._ledger_repo.record_chandelier_vol_source" services/signal_tracker_agent.py returns a match
    - grep "self._ledger_repo.record_shadow_tracking_start" services/signal_tracker_agent.py returns a match
    - grep "self._ledger_repo.record_shadow_outcome" services/signal_tracker_agent.py returns a match
    - grep "self._register_signal_handlers()" services/signal_tracker_agent.py returns a match
    - grep "_stop_event" services/signal_tracker_agent.py returns at least 3 matches
    - grep "self.running" services/signal_tracker_agent.py returns NO match
    - grep "self.shutdown_requested" services/signal_tracker_agent.py returns NO match
    - grep "self.shutdown_event" services/signal_tracker_agent.py returns NO match
    - grep "signal_tracker_agent.log" services/signal_tracker_agent.py returns a match
    - grep "raise NotImplementedError" services/signal_tracker_agent.py returns a match (in _run)
  </acceptance_criteria>

  <done>SignalTrackerAgent(BaseAgent) exists with zero raw SQL, all DB calls via self._ledger_repo, BaseAgent lifecycle (start/stop/_run/_stop_event), and all 4 broken call sites fixed.</done>
</task>

<task type="auto">
  <name>Task 3: Migrate all 4 test files to use SignalTrackerAgent (D-01, D-02, D-03)</name>

  <read_first>
    - tests/unit/service_tests/test_signal_lifecycle_service.py (primary test file to rename)
    - tests/unit/service_tests/test_lifecycle_freshness.py (update imports)
    - tests/unit/service_tests/test_lifecycle_active_index.py (update imports + __new__ pattern)
    - tests/unit/intelligence/test_lifecycle_tracker.py (update imports)
    - services/signal_tracker_agent.py (the new module — verify available names)
  </read_first>

  <files>
    tests/unit/service_tests/test_signal_tracker_agent.py
    tests/unit/service_tests/test_lifecycle_freshness.py
    tests/unit/service_tests/test_lifecycle_active_index.py
    tests/unit/intelligence/test_lifecycle_tracker.py
  </files>

  <action>
  **File 1: Rename + migrate tests/unit/service_tests/test_signal_lifecycle_service.py -> test_signal_tracker_agent.py (D-01)**

  Copy the file to `test_signal_tracker_agent.py` and apply these changes:

  Global replacements across the file:
  - `from services.signal_lifecycle_service import SignalLifecycleService` -> `from services.signal_tracker_agent import SignalTrackerAgent`
  - `SignalLifecycleService()` -> `SignalTrackerAgent()` (constructor calls)
  - `SignalLifecycleService.__new__(SignalLifecycleService)` -> `SignalTrackerAgent.__new__(SignalTrackerAgent)` (if any)
  - `SignalLifecycleService` -> `SignalTrackerAgent` (remaining class references)
  - `from services.signal_lifecycle_service import` -> `from services.signal_tracker_agent import` (all remaining imports)

  For tests that mock DB calls (D-02):
  - Where tests patch `services.signal_lifecycle_service.update_signal_status` or similar module-level function patches, replace with:
    ```python
    svc = SignalTrackerAgent.__new__(SignalTrackerAgent)
    svc._ledger_repo = MagicMock()
    # ... then assert:
    svc._ledger_repo.update_signal_status.assert_called_with(...)
    ```
  - NOTE: use `svc._ledger_repo` (NOT `svc._repo`) per D-02.

  For tests that instantiate via `SignalTrackerAgent()` (full constructor):
  - The constructor still accepts optional `db_manager` param, so `SignalTrackerAgent()` works
  - For tests needing a mock DB: `svc = SignalTrackerAgent(); svc._ledger_repo = MagicMock()`
  - For the `__new__` pattern tests: `svc = SignalTrackerAgent.__new__(SignalTrackerAgent); svc._ledger_repo = MagicMock()`

  After renaming, DELETE the old test_signal_lifecycle_service.py file.

  **File 2: Update tests/unit/service_tests/test_lifecycle_freshness.py**

  Replace all `from services.signal_lifecycle_service import` with `from services.signal_tracker_agent import`.
  The functions imported (_compute_freshness_decay, FRESHNESS_HALF_LIFE_BARS) are module-level pure functions
  that exist in the new agent file unchanged.

  **File 3: Update tests/unit/service_tests/test_lifecycle_active_index.py**

  - Replace `from services.signal_lifecycle_service import SignalLifecycleService` -> `from services.signal_tracker_agent import SignalTrackerAgent`
  - Replace `SignalLifecycleService.__new__(SignalLifecycleService)` -> `SignalTrackerAgent.__new__(SignalTrackerAgent)`
  - Replace all remaining `SignalLifecycleService` references -> `SignalTrackerAgent`

  **File 4: Update tests/unit/intelligence/test_lifecycle_tracker.py**

  This file imports from `src.intelligence.trading.lifecycle_tracker` (NOT from the service).
  Check if it has any `signal_lifecycle_service` references in patch decorators or imports.
  If it does, update those. If it only imports from `lifecycle_tracker`, no changes needed
  except to verify it passes.

  After all 4 files are updated, run the full test suite to confirm zero failures:
  `.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_agent.py tests/unit/service_tests/test_lifecycle_freshness.py tests/unit/service_tests/test_lifecycle_active_index.py tests/unit/intelligence/test_lifecycle_tracker.py -v`
  </action>

  <verify>
    <automated>.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_agent.py tests/unit/service_tests/test_lifecycle_freshness.py tests/unit/service_tests/test_lifecycle_active_index.py tests/unit/intelligence/test_lifecycle_tracker.py -v --tb=short 2>&1 | tail -30</automated>
  </verify>

  <acceptance_criteria>
    - File tests/unit/service_tests/test_signal_lifecycle_service.py does NOT exist (deleted)
    - File tests/unit/service_tests/test_signal_tracker_agent.py EXISTS
    - grep "signal_lifecycle_service" tests/unit/service_tests/test_signal_tracker_agent.py returns NO match
    - grep "signal_lifecycle_service" tests/unit/service_tests/test_lifecycle_freshness.py returns NO match
    - grep "signal_lifecycle_service" tests/unit/service_tests/test_lifecycle_active_index.py returns NO match
    - grep "SignalLifecycleService" tests/unit/service_tests/test_signal_tracker_agent.py returns NO match
    - grep "SignalLifecycleService" tests/unit/service_tests/test_lifecycle_active_index.py returns NO match
    - grep "SignalTrackerAgent" tests/unit/service_tests/test_signal_tracker_agent.py returns at least 1 match
    - grep "_ledger_repo" tests/unit/service_tests/test_signal_tracker_agent.py returns at least 1 match (D-02 pattern)
    - All 4 test files pass with 0 failures (pytest exit code 0)
    - The 6 pre-existing AttributeError failures (D-03) are resolved
  </acceptance_criteria>

  <done>All 4 test files migrated to use SignalTrackerAgent. Zero test failures. Old test file deleted. No references to signal_lifecycle_service in any test file.</done>
</task>

<task type="auto">
  <name>Task 4: Create systemd unit + cleanup + final verification (D-07)</name>

  <read_first>
    - services/indicagent-signal-lifecycle.service (existing unit to use as template)
    - services/signal_tracker_agent.py (verify the ExecStart path)
  </read_first>

  <files>
    services/indicagent-signal-tracker.service
    services/signal_lifecycle_service.py
  </files>

  <action>
  **4a: Create systemd unit (per D-07):**

  Create `services/indicagent-signal-tracker.service` by copying the existing `indicagent-signal-lifecycle.service` and changing:
  - `Description=IndicAgent Signal Lifecycle Service` -> `Description=IndicAgent Signal Tracker Agent`
  - `ExecStart=...signal_lifecycle_service.py` -> `ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/signal_tracker_agent.py`
  - `SyslogIdentifier=indicagent-signal-lifecycle` -> `SyslogIdentifier=indicagent-signal-tracker`
  - Add `Environment=PYTHONUNBUFFERED=1` (required per CLAUDE.md — missing from old unit)
  - Keep all other settings (After, Wants, Restart, User, etc.)

  **4b: Delete signal_lifecycle_service.py (Claude's discretion — delete preferred):**

  First verify no external scripts import it:
  ```bash
  grep -rn "signal_lifecycle_service" --include="*.py" . | grep -v ".claude/worktrees" | grep -v "__pycache__" | grep -v "test_signal" | grep -v "services/signal_lifecycle_service.py"
  ```

  External references are only comments (in signal_generator_agent.py and trade_framer.py). These are documentation comments, not imports. Safe to delete.

  Delete `services/signal_lifecycle_service.py`.

  Update the comment references:
  - `services/signal_generator_agent.py` line 11: change "signal_lifecycle_service" to "signal_tracker_agent" in the comment
  - `src/intelligence/trading/trade_framer.py` line 828: change "signal_lifecycle_service" to "signal_tracker_agent" in the comment

  **4c: Full test suite + lint:**

  ```bash
  .venv/bin/pytest tests/unit/ -q --tb=short
  .venv/bin/ruff check . --fix
  .venv/bin/black .
  ```

  **4d: Update CLAUDE.md Active Services table:**

  In CLAUDE.md, find the Active Services table row for "Signal Lifecycle" and update:
  - Service name: `Signal Lifecycle` -> `Signal Tracker`
  - Unit name: `indicagent-signal-lifecycle` -> `indicagent-signal-tracker`
  - Purpose stays the same: "Zone-aware lifecycle: activation, MAE/MFE, 8-class outcome"
  </action>

  <verify>
    <automated>.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -5</automated>
  </verify>

  <acceptance_criteria>
    - File services/indicagent-signal-tracker.service EXISTS
    - grep "signal_tracker_agent.py" services/indicagent-signal-tracker.service returns a match
    - grep "SyslogIdentifier=indicagent-signal-tracker" services/indicagent-signal-tracker.service returns a match
    - grep "PYTHONUNBUFFERED=1" services/indicagent-signal-tracker.service returns a match
    - File services/signal_lifecycle_service.py does NOT exist (deleted)
    - grep "indicagent-signal-tracker" CLAUDE.md returns a match (Active Services table updated)
    - .venv/bin/pytest tests/unit/ -q exits with code 0 (all tests pass)
    - .venv/bin/ruff check . exits with code 0 (no lint errors)
  </acceptance_criteria>

  <done>Systemd unit created. Old service file deleted. Comment references updated. CLAUDE.md updated. Full test suite passes. Lint clean.</done>
</task>

</tasks>

<verification>
After all tasks complete:

1. `grep -rn "signal_lifecycle_service" --include="*.py" . | grep -v ".claude/worktrees" | grep -v "__pycache__"` — should return ZERO matches
2. `.venv/bin/pytest tests/unit/ -q` — all tests pass
3. `.venv/bin/ruff check .` — no lint errors
4. `python -c "from services.signal_tracker_agent import SignalTrackerAgent; from src.core.agent.base import BaseAgent; assert issubclass(SignalTrackerAgent, BaseAgent)"` — passes
5. `grep "UPDATE signal_ledger" services/signal_tracker_agent.py` — returns NO match (zero raw SQL in agent)
6. File `services/signal_lifecycle_service.py` does NOT exist
7. File `services/indicagent-signal-tracker.service` EXISTS
</verification>

<success_criteria>
- SignalTrackerAgent(BaseAgent) is the sole lifecycle agent class
- Zero raw SQL in the agent file — all DB via self._ledger_repo
- All 4 test files migrated, zero test failures
- The 6 pre-existing AttributeError failures (D-03) are resolved
- Systemd unit ready for deployment
- signal_lifecycle_service.py deleted
- CLAUDE.md Active Services table updated
</success_criteria>

<output>
After completion, create `.planning/phases/52.4-signal-tracker-agent/52.4-01-SUMMARY.md`
</output>
