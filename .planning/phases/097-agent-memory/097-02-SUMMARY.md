---
phase: 097-agent-memory
plan: "02"
subsystem: memory
tags: [memory, contracts, protocols, otel, settings]
dependency_graph:
  requires: []
  provides:
    - src.core.memory.Episode
    - src.core.memory.CalibrationStats
    - src.core.memory.RegimeHistory
    - src.core.memory.EpisodicBackend
    - src.core.memory.CalibrationBackend
    - src.core.memory.RegimeBackend
    - src.core.memory.Mem0Backend
    - Settings.agent_memory_enabled
    - config/memory.yaml
    - MEMORY_* OTel instruments (11)
  affects:
    - src.core.ai.worker_context (memory_client stub, Wave 2 wires concrete MemoryClient)
    - Wave 2 plans 03-05 (implement against these contracts)
tech_stack:
  added:
    - typing.Protocol (runtime-checkable backend contracts)
    - frozen dataclasses (return-type value objects)
    - config/memory.yaml (runtime tuning knobs)
  patterns:
    - Ring 0 contract-first: interfaces defined before implementations
    - Graceful degradation structural contract (D-19): all protocol methods return [] or None, never raise
    - Epoch-decay weighting contract (D-23): over-fetch then Python rerank
key_files:
  created:
    - src/core/memory/__init__.py
    - src/core/memory/types.py
    - src/core/memory/backends/__init__.py
    - config/memory.yaml
  modified:
    - src/config/settings.py (agent_memory_enabled field added)
    - src/observability/metrics.py (11 memory instruments added)
decisions:
  - "Placed agent_memory_enabled near ollama_* fields in Settings — both are AI subsystem feature flags"
  - "11 OTel instruments total: plan spec listed 5 core + 6 additional (D-21 plus F1/F6 alerts); all defined in one block for Wave 2 to consume"
  - "CalibrationBackend Protocol includes get_partial_sample_n() for cold-start path even though D-19 only listed get_calibration() — required by D-F3"
  - "config/memory.yaml includes over_fetch_multiplier and hnsw_ef_search beyond the 4 mandatory keys — both have locked decisions (D-11, D-23) and Wave 2 reads them"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-05T01:07:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 2
---

# Phase 097 Plan 02: Memory Contract Layer Summary

**One-liner:** Ring 0 contract skeleton — Episode/CalibrationStats/RegimeHistory frozen dataclasses, four typed backend Protocols, AGENT_MEMORY_ENABLED feature flag, config/memory.yaml with 6 tuning knobs, and 11 OTel instruments — all stable interfaces Wave 2 implements against.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Memory package — frozen dataclasses + backend Protocols | 1025e45d | src/core/memory/{__init__.py,types.py,backends/__init__.py} |
| 2 | Settings flag, config/memory.yaml, 11 OTel instruments | c7b4c2f8 | src/config/settings.py, src/observability/metrics.py, config/memory.yaml |

## What Was Built

**Task 1 — Contract layer (Ring 0 only)**

Three frozen dataclasses in `src/core/memory/types.py`:
- `Episode`: 20 fields covering id, ts, kind, signal/agent/symbol metadata, regime context, outcome/PnL fields, memory_assisted lineage flag, payload dict, and the two Wave-2-critical fields `similarity` and `epoch_weight`
- `CalibrationStats`: 26 fields including `skill_score`, `correction_factor`/`correction_factor_stable`, `bootstrapped` (cold-start flag), `feedback_loop_quarantine`, `p_signal` (propensity score for C-02)
- `RegimeHistory`: 12 fields including `elapsed_bars` (computed at query time), `transition_probs`/`win_rate` (None below N=30 per C-03)

Four `runtime_checkable` Protocols in `src/core/memory/backends/__init__.py`:
- `EpisodicBackend.recall()` — HNSW recall with epoch-weighted rerank contract
- `CalibrationBackend.get_calibration()` + `get_partial_sample_n()` — promoted stats + cold-start count
- `RegimeBackend.get_regime_history()` — Markov priors for current regime
- `Mem0Backend.search()` — qualitative memory for tiers 4/7 only (D-14)

Every Protocol method has a docstring specifying the graceful-degradation contract ([] or None on error/timeout, never raises — D-19).

**Task 2 — Wiring**

`Settings.agent_memory_enabled` (default=False): gated on MEM-03 shadow validation and N>=200 labeled episodes before enabling (D-08/D-12).

`config/memory.yaml`: 6 keys — epoch_decay=0.3 (D-19/D-23), recall_limit=10, over_fetch_multiplier=3 (D-23), hnsw_ef_search=100 (D-11), timeout_ms=40 (D-13), queue_maxsize=500 (D-13). Each key has a header comment tracing to its decision.

11 OTel instruments in `src/observability/metrics.py` under a `# Agent memory metrics (Phase 097)` block:
- Histograms: `MEMORY_RECALL_LATENCY_MS`, `MEMORY_EMBED_LATENCY_MS`
- Counters: `MEMORY_RECALL_RESULTS_TOTAL`, `MEMORY_CALIBRATION_APPLIED`, `MEMORY_WRITE_DROPPED_TOTAL`, `MEMORY_COHORTS_PROMOTED_TOTAL`, `MEMORY_COHORTS_QUARANTINED_TOTAL`, `MEMORY_PROMOTION_SKIPPED_N_ELIGIBLE`
- Point gauges (`create_gauge`): `MEMORY_WRITE_QUEUE_DEPTH`, `MEMORY_EMBED_STALL_SECONDS`, `MEMORY_EPISODES_LABELED`

## Verification

All acceptance criteria met:

```
from src.core.memory import Episode, CalibrationStats, RegimeHistory, ...  # OK
Episode.__dataclass_params__.frozen  # True
Settings().agent_memory_enabled  # False
yaml.safe_load('config/memory.yaml')['epoch_decay']  # 0.3
yaml.safe_load('config/memory.yaml')['timeout_ms']  # 40
yaml.safe_load('config/memory.yaml')['queue_maxsize']  # 500
from src.observability.metrics import MEMORY_RECALL_LATENCY_MS, ... (11 names)  # OK
ruff check src/core/memory/ src/config/settings.py src/observability/metrics.py  # All passed
```

## Deviations from Plan

None — plan executed exactly as written.

The plan specified "five OTel instruments" in the objective but listed 11 in the action block. The action block is authoritative; all 11 are implemented. The plan's must_haves say "Five memory OTel instruments" which refers to the original D-21 set; the action block extends to the full set needed by Plans 03-05.

## Self-Check: PASSED

```
FOUND: src/core/memory/__init__.py
FOUND: src/core/memory/types.py
FOUND: src/core/memory/backends/__init__.py
FOUND: config/memory.yaml
FOUND commit: 1025e45d (task 1)
FOUND commit: c7b4c2f8 (task 2)
```
