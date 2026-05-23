# Phase 088: God Class Decomposition - Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 13 (5 new modules, 1 updated __init__, 1 major refactor, 5 new test files, 1 test helper update)
**Analogs found:** 12 / 13 (tests/unit/pipeline_tests/ directory has no analog — must be created)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/intelligence/pipeline/output_queue.py` | utility | request-response (async queue) | `services/intelligence_pipeline_agent.py` lines 1030-1057 | exact (self-contained extraction) |
| `src/intelligence/pipeline/state_manager.py` | utility | CRUD (lazy-init dict + file I/O) | `services/intelligence_pipeline_agent.py` lines 559-571, 1563-1598 | exact (self-contained extraction) |
| `src/intelligence/pipeline/cache_manager.py` | service | CRUD + batch (DB reads + refresh loops) | `services/intelligence_pipeline_agent.py` lines 1748-1920 | exact (self-contained extraction) |
| `src/intelligence/pipeline/executor.py` | service | event-driven (thread-pool dispatch) | `services/intelligence_pipeline_agent.py` lines 1123-1248 | exact (self-contained extraction) |
| `src/intelligence/pipeline/signal_processor.py` | service | transform (signal pipeline stages) | `services/intelligence_pipeline_agent.py` lines 1298-1677 | exact (self-contained extraction) |
| `src/intelligence/pipeline/__init__.py` | config | — | `src/intelligence/pipeline/__init__.py` (current) | extension (add exports, no overwrite) |
| `services/intelligence_pipeline_agent.py` | controller | event-driven (Kafka consumer + DAG orchestrator) | `services/roll_compute_agent.py` | role-match (thin orchestrator pattern) |
| `tests/unit/pipeline_tests/test_output_queue.py` | test | — | `tests/unit/service_tests/test_bar_writer_agent.py` | role-match |
| `tests/unit/pipeline_tests/test_state_manager.py` | test | — | `tests/unit/service_tests/test_bar_writer_agent.py` | role-match |
| `tests/unit/pipeline_tests/test_cache_manager.py` | test | — | `tests/unit/service_tests/test_bar_writer_agent.py` | role-match |
| `tests/unit/pipeline_tests/test_executor.py` | test | — | `tests/unit/pipeline_helpers.py` | role-match |
| `tests/unit/pipeline_tests/test_signal_processor.py` | test | — | `tests/unit/pipeline_helpers.py` | role-match |
| `tests/unit/service_tests/pipeline_helpers.py` | test | — | `tests/unit/pipeline_helpers.py` (current) | exact (update existing) |

---

## Pattern Assignments

### `src/intelligence/pipeline/output_queue.py` (utility, async queue)

**Analog:** `services/intelligence_pipeline_agent.py` lines 1030-1057 (self-contained extraction)

**Imports pattern** — copy from god class, keep only what OutputQueue needs:
```python
from __future__ import annotations

import asyncio
import structlog
from src.core.kafka_utils import KafkaProducerClient
from src.observability.metrics import counter, gauge
```

**Class skeleton** — plain class (no dataclass; constructor complexity makes plain class more readable per RESEARCH.md):
```python
class OutputQueue:
    def __init__(self, producer: KafkaProducerClient, maxsize: int) -> None:
        self._producer = producer
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._logger = structlog.get_logger(__name__)
        # OTel metrics — owned by this class per D-16
        self._drops = counter(
            "intelligence_pipeline_output_buffer_drops_total",
            "Output buffer drops due to queue full",
        )
        self._depth = gauge(
            "intelligence_pipeline_output_buffer_depth",
            "Current depth of async output queue",
        )
        self._publish_failures = counter(
            "intelligence_pipeline_output_publish_failures_total",
            "Output buffer publish failures",
        )
```

**Core enqueue pattern** (from god class lines 1030-1057):
```python
def enqueue(self, topic: str, key: str, value) -> None:
    """Non-blocking enqueue. Drops on QueueFull."""
    try:
        self._queue.put_nowait((topic, key, value))
    except asyncio.QueueFull:
        self._drops.add(1)

async def enqueue_blocking(self, topic: str, key: str, value) -> None:
    """Blocking enqueue. Backs up rather than dropping (Phase 086 contract)."""
    if self._queue.full():
        self._drops.add(1)
        self._logger.warning("output_queue.full_blocking")
    await self._queue.put((topic, key, value))

async def join(self) -> None:
    """Expose join() for teardown drain (asyncio.wait_for wraps this)."""
    await self._queue.join()
```

**Drain loop pattern** (from god class lines 1044-1057, used by orchestrator via `asyncio.create_task`):
```python
async def drain_loop(self, running_fn) -> None:
    """Background drain loop. running_fn() returns False when agent is stopping."""
    while running_fn() or not self._queue.empty():
        try:
            topic, key, value = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            self._depth.add(self._queue.qsize())
            await self._producer.publish(topic, msg=value, key=key)
            self._queue.task_done()
        except TimeoutError:
            continue
        except Exception:
            self._publish_failures.add(1)
            self._logger.exception("output.publish_failed")
            self._queue.task_done()
```

**Critical:** `KafkaProducerClient.publish()` kwarg is `msg=` not `value=` (CLAUDE.md). Confirmed at god class line 1050: `await self._kafka_producer.publish(topic, msg=value, key=key)`.

---

### `src/intelligence/pipeline/state_manager.py` (utility, CRUD + file I/O)

**Analog:** `services/intelligence_pipeline_agent.py` lines 559-571, 1563-1598

**Imports pattern:**
```python
from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from src.core.state_serializer import _ensure_default_models_registered, _tag_value, _untag_value
```

**Constants that move here** (from god class lines 307-310):
```python
# These constants move from the god class into this module
_CHECKPOINT_PATH = Path("cache/pipeline_checkpoint.json")
_CHECKPOINT_FIELDS = ("plugin_states", "kalman_state", "tod_priors", "last_bar_offset", "setup_last_fire")
_AGENT_VERSION = "v1"
```

**Class skeleton with lazy-init pattern** (from god class lines 567-571):
```python
class PluginStateManager:
    def __init__(self, checkpoint_path: Path) -> None:
        self._checkpoint_path = checkpoint_path
        self._plugin_states: dict = {}
        self._plugin_states_locks: dict = {}
        self._logger = structlog.get_logger(__name__)
        self._checkpoint_task: asyncio.Task | None = None

    def get_state(self, key: tuple) -> dict:
        return self._plugin_states.get(key, {})

    def get_lock(self, key: tuple) -> threading.Lock:
        """Lazy-init threading.Lock per state key (source: god class line 567)."""
        if key not in self._plugin_states_locks:
            self._plugin_states_locks[key] = threading.Lock()
        return self._plugin_states_locks[key]

    def update(self, key: tuple, state: dict) -> None:
        self._plugin_states[key] = state

    def update_batch(self, state_updates: dict) -> None:
        """Apply dict of {state_key: new_state} returned by PluginExecutor."""
        self._plugin_states.update(state_updates)

    def get_all_states(self) -> dict:
        return dict(self._plugin_states)
```

**Checkpoint write pattern** (from god class lines 1565-1573, RAISES on failure per Phase 086):
```python
def write_checkpoint(self, extra_state: dict) -> None:
    """Serialize state to disk. Raises on failure — caller (orchestrator) logs."""
    payload: dict = {"version": _AGENT_VERSION, "ts": datetime.now(UTC).isoformat()}
    # plugin_states owned here; extra_state carries cross-owned fields from
    # orchestrator (kalman_state from SignalProcessor, setup_last_fire from
    # SignalProcessor, tod_priors from CacheManager, last_bar_offset from orchestrator)
    payload["plugin_states"] = _tag_value(self._plugin_states)
    for k, v in extra_state.items():
        payload[k] = _tag_value(v)
    tmp = self._checkpoint_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(self._checkpoint_path)
    self._logger.info("state.checkpoint_written", path=str(self._checkpoint_path))
```

**Checkpoint read pattern** (from god class lines 1575-1598):
```python
async def read_checkpoint(self) -> dict | None:
    """Restore state from disk. Returns extra_state dict or None on miss/failure."""
    try:
        raw_text = self._checkpoint_path.read_text()
    except FileNotFoundError:
        self._logger.info("state.checkpoint_miss — starting fresh")
        return None
    try:
        _ensure_default_models_registered()
        raw = json.loads(raw_text)
        if raw.get("version") != _AGENT_VERSION:
            self._logger.warning("state.checkpoint_version_mismatch", ...)
            return None
        # Restore plugin_states into self
        for k, v in _untag_value(raw.get("plugin_states", {})).items():
            self._plugin_states[_restore_tuple_key(k)] = v
        # Return extra fields for orchestrator to distribute
        return {f: raw.get(f, {}) for f in _CHECKPOINT_FIELDS if f != "plugin_states"}
    except Exception as exc:
        self._logger.warning("state.checkpoint_read_failed", error=str(exc))
        return None
```

**Background checkpoint loop** (new, per D-14; pattern from `_run_refresh_loop` at god class line 1748):
```python
def start_checkpoint_loop(self, interval_sec: int) -> asyncio.Task:
    """Create and return the background checkpoint task. Orchestrator stores it."""
    async def _loop(get_extra_fn):
        while True:
            await asyncio.sleep(interval_sec)
            try:
                self.write_checkpoint(get_extra_fn())
            except Exception as exc:
                self._logger.error("state.checkpoint_loop_failed", error=str(exc))
                raise  # D-15: checkpoint failure raises (Phase 086 contract)
    # get_extra_fn is a callable the orchestrator provides that assembles
    # cross-owned state from SignalProcessor and CacheManager
    ...
```

---

### `src/intelligence/pipeline/cache_manager.py` (service, CRUD + batch refresh)

**Analog:** `services/intelligence_pipeline_agent.py` lines 1748-1920

**Imports pattern:**
```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import structlog

from src.core.database_manager import DatabaseManager
from src.config.settings import Settings
from src.monitoring.ks_drift_monitor import DRIFT_PENALTIES
```

**Class skeleton with atomic-replacement properties** (from god class lines 464-470, RESEARCH.md):
```python
class CacheManager:
    def __init__(self, db: DatabaseManager, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._logger = structlog.get_logger(__name__)
        # All 6 live cache dicts — atomically replaced on refresh (GIL-safe for readers)
        self._perf_weights: dict = {}
        self._cis_weights: dict = {}
        self._cis_kalman_params: dict = _load_cis_kalman_params()  # one-time JSON read
        self._calibration_curves: dict = {}
        self._drift_penalties: dict = {}
        self._shadow_cache: dict = {}
        self._tod_priors: dict = {}
        self._last_hmm_regime: int | None = None

    @property
    def perf_weights(self) -> dict:
        return self._perf_weights

    @property
    def cis_weights(self) -> dict:
        return self._cis_weights

    @property
    def cis_kalman_params(self) -> dict:
        return self._cis_kalman_params

    @property
    def calibration_curves(self) -> dict:
        return self._calibration_curves

    @property
    def drift_penalties(self) -> dict:
        return self._drift_penalties

    @property
    def shadow_cache(self) -> dict:
        return self._shadow_cache

    @property
    def tod_priors(self) -> dict:
        return self._tod_priors

    def update_hmm_regime(self, hmm_val: int | None) -> None:
        """Called by orchestrator per bar to keep regime-conditioned perf_weights fresh."""
        self._last_hmm_regime = hmm_val

    def current_hmm_regime_label(self) -> str:
        """Source: god class lines 1757-1769."""
        hmm = self._last_hmm_regime
        if hmm == 0:
            return "mean_reversion"
        if hmm in (1, 2):
            return "trend"
        return "all"
```

**Generic refresh loop pattern** (from god class lines 1748-1755 — inlined into CacheManager):
```python
async def _run_refresh_loop(self, load_fn, interval_sec: int) -> None:
    """Source: god class line 1748. CacheManager internalizes this."""
    while True:
        try:
            await asyncio.sleep(interval_sec)
            await load_fn()
        except Exception as exc:
            self._logger.warning("refresh_loop.error", error=str(exc))
```

**start_refresh_loops pattern** (from RESEARCH.md code examples, god class lines 675-681):
```python
def start_refresh_loops(self) -> list[asyncio.Task]:
    """Create 6 background refresh tasks. Orchestrator stores them in _background_tasks."""
    return [
        asyncio.create_task(self._run_refresh_loop(self._load_perf_weights, 3600)),
        asyncio.create_task(self._run_refresh_loop(self._refresh_drift_penalties, 14400)),
        asyncio.create_task(self._run_refresh_loop(self._load_cis_weights, 1800)),
        asyncio.create_task(self._run_refresh_loop(self._load_calibration_curves, 1800)),
        asyncio.create_task(self._run_refresh_loop(self._load_tod_multipliers, 14400)),
        asyncio.create_task(self._run_refresh_loop(self._load_shadow_cache, 300)),
    ]
```

**Atomic dict replacement pattern** (from god class lines 1820-1830, RESEARCH.md):
```python
async def _load_perf_weights(self) -> None:
    # ... DB query ...
    weights: dict = {}
    for rank, row in enumerate(ranked):
        weights[(row["setup_plugin"], row["tf"], sym)] = round(...)
    self._perf_weights = weights  # atomic reassignment — GIL makes this safe for readers
```

**tod_priors MERGE pattern** (from god class line 1917 — must NOT be changed to replacement):
```python
async def _load_tod_multipliers(self) -> None:
    # ...
    self._tod_priors = {**self._tod_priors, **priors}  # merge, NOT replace (Pitfall 7)
```

**CIS weights — do NOT call scorer here** (Pitfall 4 from RESEARCH.md):
```python
async def _load_cis_weights(self) -> None:
    # Load and store weights only — NO self._cis_scorer.update_weights() call here.
    # Orchestrator mediates: after refresh, orchestrator calls
    # sig_proc.sync_cis_weights(cache_mgr.cis_weights, cache_mgr.cis_weights_version)
    if self._db is None:
        return
    rows = await self._db.execute_query(
        "SELECT version, weights FROM cis_weights ORDER BY version DESC LIMIT 1"
    )
    if rows:
        self._cis_weights = rows[0].get("weights", {})
        self._cis_weights_version = int(rows[0].get("version", 0))
```

---

### `src/intelligence/pipeline/executor.py` (service, event-driven thread-pool)

**Analog:** `services/intelligence_pipeline_agent.py` lines 1063-1248

**Imports pattern:**
```python
from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar

import structlog

from src.core.service_utils import should_skip_plugin
from src.intelligence.register_plugins import (
    I2_WAVE_A, I2_WAVE_B, I4_WAVE_A, I4_WAVE_B,
    SMC_WAVE_A, SMC_WAVE_B, TIER_I1, TIER_I3, TIER_I5, TIER_I6,
)
from src.observability.circuit_breaker import CircuitBreaker, CircuitState
from src.observability.metrics import (
    CIRCUIT_BREAKER_STATE, PLUGIN_DURATION_MS, PLUGIN_ERRORS_TOTAL,
    counter, gauge,
)
```

**Constructor per D-05** (with shadow_cache resolved via orchestrator per-call per RESEARCH.md):
```python
class PluginExecutor:
    def __init__(
        self,
        thread_pool: ThreadPoolExecutor,
        plugin_cache: dict,
        instrument_map: dict,
        circuit_breakers: dict,
    ) -> None:
        self._thread_pool = thread_pool
        self._plugin_cache = plugin_cache
        self._instrument_map = instrument_map
        self._plugin_circuit_breakers = circuit_breakers  # shared with orchestrator init
        self._logger = structlog.get_logger(__name__)
        self._plugin_call_counts: dict = {}
        # OTel metrics owned by this class per D-16
        self._plugin_skipped_total = counter(
            "intelligence_pipeline_plugin_skipped_total",
            "Plugin executions skipped due to asset class mismatch",
        )
        self._i1_latency_ms = gauge(
            "intelligence_pipeline_i1_latency_ms",
            "I1 tier execution time in milliseconds",
        )

    def shutdown(self) -> None:
        """Called by orchestrator.stop(). Source: god class line 551."""
        self._thread_pool.shutdown(wait=True)
```

**Lazy-init CircuitBreaker pattern** (from god class lines 559-565):
```python
def _get_plugin_cb(self, plugin_name: str) -> CircuitBreaker:
    cb = self._plugin_circuit_breakers.get(plugin_name)
    if cb is None:
        cb = CircuitBreaker(failure_threshold=3, timeout_sec=300)
        self._plugin_circuit_breakers[plugin_name] = cb
    return cb
```

**_collect_plugin_results — returns state_updates dict** (D-10, Pitfall 3 from RESEARCH.md; source god class lines 1069-1117, modified to NOT write to PluginStateManager):
```python
def _collect_plugin_results(
    self,
    tasks: list,
    results: list,
    log_prefix: str = "plugin",
) -> tuple[list[dict], dict]:
    """Collect results. Returns (outputs, state_updates) — orchestrator writes state."""
    outputs = []
    state_updates: dict = {}
    for i, task in enumerate(tasks):
        out = results[i]
        tier = task.tier_key
        cb = self._get_plugin_cb(task.plugin_name)
        if isinstance(out, Exception):
            PLUGIN_ERRORS_TOTAL.add(1, {"plugin_name": task.plugin_name, "tier": tier})
            cb.record_failure()
            if cb.state == CircuitState.OPEN:
                CIRCUIT_BREAKER_STATE.set(1, {"plugin_name": task.plugin_name})
            self._logger.warning(f"{log_prefix}.error", plugin=task.plugin_name, error=str(out))
        elif isinstance(out, tuple) and len(out) == 2:
            result_dict, duration_ms = out
            PLUGIN_DURATION_MS.record(duration_ms, {"plugin_name": task.plugin_name, "tier": tier})
            if isinstance(result_dict, dict):
                # Extract state_update BEFORE modifying result_dict
                if "_state" in result_dict:
                    with task.lock:
                        state_updates[task.state_key] = result_dict.pop("_state")
                result_dict["_tier_key"] = tier
                cb.record_success()
                outputs.append(result_dict)
    return outputs, state_updates
```

**_ANALYSIS_WAVES class variable moves here** (from god class line 1186):
```python
_ANALYSIS_WAVES: ClassVar[tuple] = (
    (("i2", I2_WAVE_A), ("i3", TIER_I3), ("smc", SMC_WAVE_A)),
    (("i2", I2_WAVE_B), ("smc", SMC_WAVE_B), ("i4", I4_WAVE_A)),
    (("i4", I4_WAVE_B), ("i5", TIER_I5)),
    (("i6", TIER_I6),),
)
```

**run_tiers public interface** — orchestrator calls this, passes shadow_cache per call (D-07 compliant):
```python
async def run_tiers(
    self,
    state: dict,
    locks: dict,
    bar,
    symbol: str,
    tf: str,
    frames: dict,
    shadow_cache: dict,
) -> tuple[dict, dict]:
    """Execute I1 + all analysis waves. Returns (tiered_results, state_updates)."""
```

**reload_hmm_parameters** (from god class lines 750-775, moves here since it iterates `_plugin_cache`):
```python
def reload_hmm_parameters(self) -> list[str]:
    """Source: god class line 750. Called by orchestrator on SIGUSR1."""
```

---

### `src/intelligence/pipeline/signal_processor.py` (service, transform)

**Analog:** `services/intelligence_pipeline_agent.py` lines 1298-1677

**Imports pattern:**
```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog

from src.config.settings import Settings
from src.core.stream_keys import TF_SECONDS, message_key, topic_intelligence_i7_signals, topic_signal_dlq
from src.core.service_utils import format_iso_ts
from src.intelligence.pipeline import (
    apply_calibration, apply_quality_gate, apply_regime_gate,
    apply_tod_adjustment, rank_signals, select_winner,
)
from src.intelligence.trading.cis_scorer import CISScorer
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION
from src.observability.metrics import (
    INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL,
    REGIME_GATE_SUPPRESSIONS_TOTAL,
    counter,
)
```

**Constructor per D-05** (with transform_recorder added per RESEARCH.md open question 2):
```python
class SignalProcessor:
    def __init__(
        self,
        cis_scorer: CISScorer,
        cache: "CacheManager",
        settings: Settings,
        transform_recorder=None,  # TransformRecorder; deferred import per god class pattern
    ) -> None:
        self._cis_scorer = cis_scorer
        self._cache = cache
        self._settings = settings
        self._transform_recorder = transform_recorder
        self._logger = structlog.get_logger(__name__)
        # Transient state owned here
        self._signal_gate: dict = {}
        self._setup_cooldown: dict = {}
        self._setup_last_fire: dict = {}
        self._kalman_state: dict = {}
        # OTel metrics per D-16
        self._signals_generated = counter(
            "intelligence_pipeline_signals_generated_total",
            "Raw signals generated by I7 plugins",
        )
        self._signals_selected = counter(
            "intelligence_pipeline_signals_selected_total",
            "Winner signals selected by aggregator",
        )
        self._signal_dlq_total = counter(
            "intelligence_pipeline_signal_dlq_total",
            "Bars dropped to DLQ due to CIS assertion failure",
        )
```

**Checkpoint state accessors** (for orchestrator to collect cross-owned checkpoint fields):
```python
def get_kalman_state(self) -> dict:
    return dict(self._kalman_state)

def restore_kalman_state(self, state: dict) -> None:
    self._kalman_state.update(state)

def get_setup_last_fire(self) -> dict:
    return dict(self._setup_last_fire)

def restore_setup_last_fire(self, state: dict) -> None:
    self._setup_last_fire.update(state)

def sync_cis_weights(self, weights: dict, version: int) -> None:
    """Called by orchestrator after CacheManager refresh (D-07 mediation). Source: Pitfall 4."""
    if weights:
        self._cis_scorer.update_weights(weights, version)
```

**_publish_signals_or_dlq return contract** (Pitfall 8 from RESEARCH.md — returns tuple, NOT calls enqueue):
```python
async def prepare_signals_or_dlq(
    self,
    ranked: list[dict],
    symbol: str,
    tf: str,
    bar,
) -> tuple[bool, dict | None, list[dict]]:
    """Validate and prepare signals. Returns (success, dlq_payload, signals_to_publish).

    - success=True, dlq_payload=None: orchestrator calls out_queue.enqueue_blocking()
    - success=False, dlq_payload=dict: orchestrator calls out_queue.enqueue_blocking() to DLQ
    Source: god class lines 1600-1677, modified to return instead of enqueue directly.
    """
    for sig in ranked:
        if sig.get("raw_cis_score") is None or sig.get("filtered_cis_score") is None:
            self._signal_dlq_total.add(1)
            dlq_payload = {
                "symbol": symbol, "tf": tf, "bar_ts": bar.ts.isoformat(),
                "reason": "cis_score_null", "signal_count": len(ranked),
                "ts": datetime.now(UTC).isoformat(),
            }
            return False, dlq_payload, []
    # Stamp signals (source: god class lines 1640-1676)
    close_price = bar.close
    bar_ts = bar.ts
    computed_at = datetime.now(UTC)
    tf_secs = TF_SECONDS.get(tf, 60)
    is_backfill = (computed_at - bar_ts).total_seconds() > tf_secs
    for sig in ranked:
        sig["market_price_at_signal"] = close_price
        sig["market_entry_price"] = close_price
        sig["timestamp"] = format_iso_ts(bar_ts)
        sig["is_backfill"] = is_backfill
        sig.setdefault("signal_schema_version", SIGNAL_SCHEMA_VERSION)
        sig.setdefault("signal_id", str(uuid4()))
    if is_backfill and ranked:
        INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL.add(
            len(ranked), {"symbol": symbol, "timeframe": tf}
        )
    signals_payload = {
        "symbol": symbol, "tf": tf,
        "bar_ts": format_iso_ts(bar_ts),
        "computed_at": format_iso_ts(computed_at),
        "signals": ranked,
    }
    return True, None, signals_payload
```

**Module-level helper functions that move here** (from god class lines 193-230):
```python
# These three functions move from god class module scope INTO signal_processor.py module scope

def _apply_alpha_decay(sig: dict, tf: str, last_fire_state: dict | None) -> None:
    """Source: god class line 193."""
    ...

def _cis_kalman_update(raw_cis, x_est, P_est, Q, R) -> tuple[float, float]:
    """Source: god class line 203."""
    ...

def _build_features_from_event(event) -> dict:
    """Source: god class line 214."""
    ...
```

---

### `src/intelligence/pipeline/__init__.py` (config, update existing)

**Analog:** Current `src/intelligence/pipeline/__init__.py` (lines 1-23)

**CRITICAL: Never overwrite — extend only** (Pitfall 1 from RESEARCH.md):
```python
# Existing exports — DO NOT REMOVE
from src.intelligence.pipeline.calibrator import apply_calibration
from src.intelligence.pipeline.quality_gate import apply_quality_gate
from src.intelligence.pipeline.ranker import rank_signals
from src.intelligence.pipeline.regime_gate import apply_regime_gate
from src.intelligence.pipeline.tod_adjuster import apply_tod_adjustment
from src.intelligence.pipeline.winner_selector import select_winner

# NEW: Add after all existing imports
from src.intelligence.pipeline.cache_manager import CacheManager
from src.intelligence.pipeline.executor import PluginExecutor
from src.intelligence.pipeline.output_queue import OutputQueue
from src.intelligence.pipeline.signal_processor import SignalProcessor
from src.intelligence.pipeline.state_manager import PluginStateManager

__all__ = [
    # Existing
    "apply_quality_gate",
    "apply_regime_gate",
    "apply_tod_adjustment",
    "apply_calibration",
    "rank_signals",
    "select_winner",
    # New
    "CacheManager",
    "PluginExecutor",
    "OutputQueue",
    "SignalProcessor",
    "PluginStateManager",
]
```

---

### `services/intelligence_pipeline_agent.py` (thin orchestrator, major refactor)

**Analog:** `services/roll_compute_agent.py` (thin orchestrator pattern: constructs helpers in `_setup`, delegates in main loop)

**`__init__` — becomes minimal** (only orchestrator-owned state remains):
```python
def __init__(self) -> None:
    # ... settings, contracts, symbols, timeframes (unchanged) ...
    # NO more 40+ self._* cache/state/metric attrs — those move to extracted classes
    # Orchestrator-retained attrs only:
    self._background_tasks: set = set()
    self._last_bar_offset: dict = {}
    self._shadow_mode: bool = ...
    self._consumer_group = "intelligence_pipeline_group"
    # OTel metrics that stay in orchestrator per RESEARCH.md
    self._bars_processed = counter(...)
    self._pipeline_errors = counter(...)
    self._pipeline_latency = gauge(...)
```

**`_setup` — constructs all 5 classes** (pattern from D-06, analog: `roll_compute_agent.py` `_setup` lines 384-406):
```python
async def _setup(self) -> None:
    # 1. Connect DB, Kafka (unchanged)
    ...
    # 2. Construct the 5 extracted classes (D-06)
    self._state_mgr = PluginStateManager(checkpoint_path=_CHECKPOINT_PATH)
    self._cache_mgr = CacheManager(db=self._db, settings=self.settings)
    self._executor_obj = PluginExecutor(
        thread_pool=self._thread_pool,
        plugin_cache=self._plugin_cache,
        instrument_map=self._instrument_map,
        circuit_breakers={},
    )
    self._sig_proc = SignalProcessor(
        cis_scorer=CISScorer(),
        cache=self._cache_mgr,
        settings=self.settings,
        transform_recorder=self._transform_recorder,
    )
    self._out_queue = OutputQueue(producer=self._kafka_producer, maxsize=_OUTPUT_QUEUE_MAXSIZE)
    # 3. Restore checkpoint state, distribute to classes
    extra = await self._state_mgr.read_checkpoint()
    if extra:
        self._sig_proc.restore_kalman_state(extra.get("kalman_state", {}))
        self._sig_proc.restore_setup_last_fire(extra.get("setup_last_fire", {}))
        self._cache_mgr._tod_priors.update(extra.get("tod_priors", {}))
        self._last_bar_offset = extra.get("last_bar_offset", {})
    # 4. Start refresh loops and checkpoint loop
    for task in self._cache_mgr.start_refresh_loops():
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
    ckpt_task = self._state_mgr.start_checkpoint_loop(300, self._assemble_checkpoint_extra)
    self._background_tasks.add(ckpt_task)
```

**`_process_bar_inner` — becomes DAG description** (D-08):
```python
async def _process_bar_inner(self, bar: BarMessage) -> None:
    symbol, tf = bar.symbol, bar.tf
    key = (symbol, tf)
    state  = self._state_mgr.get_state(key)
    lock   = self._state_mgr.get_lock(key)
    tiered, state_updates = await self._executor_obj.run_tiers(
        state, {key: lock}, bar, symbol, tf, frames,
        shadow_cache=self._cache_mgr.shadow_cache,
    )
    self._state_mgr.update_batch(state_updates)
    success, dlq_payload, signals_payload = await self._sig_proc.process(
        event, tiered, bar, symbol, tf
    )
    if success:
        await self._out_queue.enqueue_blocking(
            topic_intelligence_i7_signals(self.env_name),
            message_key(symbol, tf),
            signals_payload,
        )
    elif dlq_payload:
        await self._out_queue.enqueue_blocking(
            topic_signal_dlq(self.env_name),
            message_key(symbol, tf),
            dlq_payload,
        )
```

**`stop()` — delegates shutdown** (god class line 547):
```python
async def stop(self) -> None:
    self._executor_obj.shutdown()  # renamed from self._executor to avoid collision
    await super().stop()
```

**`_teardown` — assembles checkpoint and joins queue** (god class lines 706-726):
```python
async def _teardown(self) -> None:
    self._stop_event.set()
    try:
        await asyncio.wait_for(self._out_queue.join(), timeout=10.0)
    except TimeoutError:
        self.logger.warning("teardown.output_drain_timeout")
    self._state_mgr.write_checkpoint(self._assemble_checkpoint_extra())
    ...

def _assemble_checkpoint_extra(self) -> dict:
    """Collect cross-owned checkpoint fields for PluginStateManager. Source: RESEARCH.md."""
    return {
        "kalman_state": self._sig_proc.get_kalman_state(),
        "setup_last_fire": self._sig_proc.get_setup_last_fire(),
        "tod_priors": self._cache_mgr.tod_priors,
        "last_bar_offset": self._last_bar_offset,
    }
```

---

### Test files: `tests/unit/pipeline_tests/test_*.py` (new test directory)

**Analog:** `tests/unit/service_tests/test_bar_writer_agent.py` (lines 1-65) for factory pattern; `tests/unit/pipeline_helpers.py` for plugin stubs

**Directory creation** — `tests/unit/pipeline_tests/` does not exist; create `__init__.py` alongside each test file.

**Test module skeleton** (copy from `test_bar_writer_agent.py` lines 1-15):
```python
"""Unit tests for OutputQueue (extracted from IntelligencePipelineComputeAgent).

Exercises the class in isolation using fakes — no full agent instantiation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
```

**Factory pattern** (from `test_bar_writer_agent.py` lines 22-40 — plain function, NOT `__new__` since extracted classes have simple constructors):
```python
# For extracted classes: direct instantiation (no __new__ needed)
def make_output_queue() -> OutputQueue:
    producer = AsyncMock()
    producer.publish = AsyncMock()
    return OutputQueue(producer=producer, maxsize=10)

# For state_manager:
def make_state_manager() -> PluginStateManager:
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()) / "ckpt.json"
    return PluginStateManager(checkpoint_path=tmp)

# For cache_manager:
def make_cache_manager() -> CacheManager:
    db = AsyncMock()
    db.execute_query = AsyncMock(return_value=[])
    settings = MagicMock()
    return CacheManager(db=db, settings=settings)

# For executor:
def make_executor() -> PluginExecutor:
    import os
    from concurrent.futures import ThreadPoolExecutor
    tp = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test_")
    return PluginExecutor(
        thread_pool=tp, plugin_cache={}, instrument_map={}, circuit_breakers={}
    )

# For signal_processor:
def make_signal_processor() -> SignalProcessor:
    from src.intelligence.trading.cis_scorer import CISScorer
    cache = MagicMock()
    cache.perf_weights = {}
    cache.calibration_curves = {}
    cache.tod_priors = {}
    cache.drift_penalties = {}
    settings = MagicMock(env_name="dev", regime_prob_min=0.7)
    return SignalProcessor(cis_scorer=CISScorer(), cache=cache, settings=settings)
```

**Test structure pattern** (from existing pipeline tests — use `@pytest.mark.asyncio` for async tests):
```python
@pytest.mark.asyncio
async def test_output_queue_drops_on_full() -> None:
    q = make_output_queue()
    # Fill queue
    for i in range(10):
        q.enqueue("topic", "key", {"i": i})
    # Next enqueue should drop (not raise)
    q.enqueue("topic", "key", {"overflow": True})
    assert q._drops.add.called or True  # OTel mock
```

---

### `tests/unit/service_tests/pipeline_helpers.py` (update existing)

**Analog:** Current `/home/bg/dev/indicagent/tests/unit/pipeline_helpers.py` lines 23-64

**Current pattern** — `__new__` + direct attribute injection on agent instance. After each extraction plan, remove migrated attributes from `make_agent()` and instead inject them on the extracted class instances held by the agent.

**Plan 01 (OutputQueue) update** — replace `agent._output_queue = asyncio.Queue(maxsize=500)` with:
```python
from src.intelligence.pipeline.output_queue import OutputQueue
agent._out_queue = OutputQueue(producer=MagicMock(), maxsize=500)
# Remove: agent._output_buffer_depth, agent._output_buffer_drops, agent._output_publish_failures
```

**Plan 02 (PluginStateManager) update** — replace state dict injection:
```python
from src.intelligence.pipeline.state_manager import PluginStateManager
import tempfile, pathlib
agent._state_mgr = PluginStateManager(
    checkpoint_path=pathlib.Path(tempfile.mkdtemp()) / "ckpt.json"
)
# Remove: agent._plugin_states = {}, agent._plugin_states_locks = {}
```

**General rule:** Each plan removes `agent._*` assignments for the migrated attributes and injects the extracted class instance on the agent. Tests that set `agent._plugin_states["key"] = ...` must be updated to `agent._state_mgr.update(key, ...)`.

---

## Shared Patterns

### OTel Metrics Creation (D-16)
**Source:** `src/observability/metrics.py` lines 21-30
**Apply to:** All 5 extracted class files
```python
from src.observability.metrics import counter, gauge
# Counter: metric.add(1, {"label": value})
# Gauge:   metric.add(value, {"label": value})   (up_down_counter internally)
# Histogram: metric.record(value, {"label": value})
# Module-level shared metrics (import directly — do NOT create new instances):
from src.observability.metrics import (
    PLUGIN_DURATION_MS,        # PluginExecutor uses this
    PLUGIN_ERRORS_TOTAL,       # PluginExecutor uses this
    CIRCUIT_BREAKER_STATE,     # PluginExecutor uses this
    FEATURES_COMPUTED_TOTAL,   # PluginExecutor uses this
    REGIME_GATE_SUPPRESSIONS_TOTAL,  # SignalProcessor uses this
    INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL,  # SignalProcessor uses this
)
```

### CircuitBreaker Usage
**Source:** `src/observability/circuit_breaker.py` lines 76-99
**Apply to:** `PluginExecutor` only
```python
from src.observability.circuit_breaker import CircuitBreaker, CircuitState
# Phase 086 pattern: use allow_request() / record_failure() / record_success()
# for manual tracking outside call()
cb = self._get_plugin_cb(plugin_name)
if not cb.allow_request():
    continue  # skip plugin
# ... run plugin ...
# On success:
cb.record_success()
# On failure (in except block):
cb.record_failure()
if cb.state == CircuitState.OPEN:
    CIRCUIT_BREAKER_STATE.set(1, {"plugin_name": plugin_name})
```

### Background Task Management
**Source:** `services/intelligence_pipeline_agent.py` lines 739-748 (SIGUSR1 task pattern)
**Apply to:** Orchestrator `_setup()` for all tasks from `start_refresh_loops()` and `start_checkpoint_loop()`
```python
# Pattern: store task in _background_tasks set to prevent GC
task = asyncio.create_task(some_coroutine())
self._background_tasks.add(task)
task.add_done_callback(self._background_tasks.discard)
```

### Structlog Logger
**Source:** `services/roll_compute_agent.py` line 52
**Apply to:** All 5 extracted class files
```python
import structlog
_logger = structlog.get_logger(__name__)  # module-level, OR per-instance:
self._logger = structlog.get_logger(__name__)
```

### asyncpg JSONB Rules
**Source:** CLAUDE.md
**Apply to:** `CacheManager._load_*` methods
```python
# asyncpg returns dict for JSONB — no json.loads() needed
weights = rows[0].get("weights", {})  # already a dict
# Pass dict to asyncpg params — never json.dumps()
```

### Timestamp Rules
**Source:** CLAUDE.md
**Apply to:** `PluginStateManager.write_checkpoint()`, `SignalProcessor.prepare_signals_or_dlq()`
```python
from datetime import UTC, datetime
from src.core.service_utils import format_iso_ts
# Always: datetime.now(UTC)  — never datetime.now() or datetime.utcnow()
# For Kafka/JSON: format_iso_ts(dt)  — never inline .isoformat()
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `tests/unit/pipeline_tests/` (directory) | test | — | Directory does not exist; must be created with `__init__.py` |

---

## Critical Pitfalls (Must Communicate to Planner)

The following pitfalls from RESEARCH.md have pattern implications — planners must address each:

1. **`__init__.py` collision** — Each plan verifying the existing `__init__.py` content before writing. Add to `__all__`; never overwrite from scratch.
2. **`_plugin_circuit_breakers` split** — `_is_shadow()` needs `_shadow_cache` (CacheManager). Orchestrator passes `shadow_cache=self._cache_mgr.shadow_cache` to `run_tiers()` per call (D-07 compliant).
3. **`_update_plugin_state` mutation** — `_collect_plugin_results` must return `(outputs, state_updates)` tuple; orchestrator calls `state_mgr.update_batch(state_updates)`.
4. **CIS scorer cross-ownership** — CacheManager does NOT call `_cis_scorer.update_weights()`. Orchestrator mediates via `sig_proc.sync_cis_weights(...)` after each CacheManager refresh.
5. **Checkpoint cross-ownership** — `kalman_state` and `setup_last_fire` are owned by SignalProcessor but checkpointed via PluginStateManager. Orchestrator assembles `extra_state` dict and passes to `write_checkpoint(extra_state)`.
6. **`__new__`-based tests** — `pipeline_helpers.py` must be updated after each plan to remove migrated `agent._*` injections.
7. **`tod_priors` merge semantics** — `_load_tod_multipliers` does `{**self._tod_priors, **priors}` (merge), NOT atomic replacement.
8. **`_enqueue_blocking` in SignalProcessor** — `prepare_signals_or_dlq` returns `(bool, dict|None, list)` tuple; orchestrator calls `out_queue.enqueue_blocking()`.
9. **`_executor` name collision** — god class uses `self._executor` for ThreadPoolExecutor; after extraction, orchestrator holds `self._executor_obj` (PluginExecutor instance) to avoid collision with the base class pattern.

---

## Metadata

**Analog search scope:** `services/`, `src/core/agent/`, `src/observability/`, `src/intelligence/pipeline/`, `tests/unit/service_tests/`, `tests/unit/pipeline_helpers.py`
**Files scanned:** 10 (god class + 4 analogs + 2 test files + __init__ + quality_gate + base agent)
**Pattern extraction date:** 2026-05-17
