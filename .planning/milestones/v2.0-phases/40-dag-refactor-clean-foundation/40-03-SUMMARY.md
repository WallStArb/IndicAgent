---
phase: 40-dag-refactor-clean-foundation
plan: 03
subsystem: infra
tags: [redpanda, kafka, systemd, microservices, dag, pipeline, prometheus]

requires:
  - phase: 40-01
    provides: Stage base class, CircuitBreaker, DataQualityMonitor
  - phase: 40-02
    provides: QualityGateService, RegimeGateService, TODAdjusterService, CalibratorService, RankerService, WinnerSelectorService stage implementations

provides:
  - 8 Redpanda topics with 7-day retention (quality_gated, regime_gated, tod_adjusted, calibrated, ranked, winner, attribution, data_quality)
  - 6 Python microservice entry points (quality_gate_service.py through winner_selector_service.py)
  - 6 systemd service units deployed and enabled (indicagent-quality-gate through indicagent-winner-selector)
  - 6 Prometheus metrics endpoints (:9119–:9124)
  - Topic creation script (create_stage_topics.py) for idempotent re-deployment

affects: [40-04, observability, prometheus-scraping, systemd-deployment]

tech-stack:
  added: []
  patterns:
    - "Stage microservice entry point: imports Stage subclass from src/intelligence/stages/, calls setup_service_logging('logs/<name>_service.log'), start_metrics_server(PORT), Stage(settings), await stage.run()"
    - "Redpanda topic creation: rpk topic create -c retention.ms=604800000 (not --set); alter-config --set for existing topics"
    - "Stage metrics ports: :9119 (quality_gate) through :9124 (winner_selector), incrementing from :9118 (cross_asset)"

key-files:
  created:
    - production/scripts/create_stage_topics.py
    - services/quality_gate_service.py
    - services/regime_gate_service.py
    - services/tod_adjuster_service.py
    - services/calibrator_service.py
    - services/ranker_service.py
    - services/winner_selector_service.py
    - production/systemd/indicagnet-quality-gate.service
    - production/systemd/indicagnet-regime-gate.service
    - production/systemd/indicagnet-tod-adjuster.service
    - production/systemd/indicagnet-calibrator.service
    - production/systemd/indicagnet-ranker.service
    - production/systemd/indicagnet-winner-selector.service
  modified:
    - src/intelligence/stages/base.py

key-decisions:
  - "rpk topic create uses -c key=value for config, not --set (unlike redis and some other tools)"
  - "Systemd service ordering: each stage Wants/After the previous stage to model DAG dependency"
  - "Service log paths: logs/<name>_service.log — setup_service_logging expects full path not bare name"
  - "Stage.run() must start() Kafka clients before consumer.messages() loop — AIOKafkaConsumer._coordinator is None before start()"

requirements-completed: []

duration: 7min
completed: 2026-03-20
---

# Phase 40 Plan 03: DAG Stage Infrastructure Summary

**8 Redpanda pipeline topics and 6 systemd microservices deployed — full DAG stage infrastructure running on :9119–:9124**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-20T03:19:01Z
- **Completed:** 2026-03-20T03:26:01Z
- **Tasks:** 5
- **Files modified:** 15 (8 new services/configs + 6 fixed log paths + 1 base.py bug fix)

## Accomplishments

- All 8 Redpanda pipeline topics created with 7-day retention (quality_gated, regime_gated, tod_adjusted, calibrated, ranked, winner, attribution, data_quality)
- 6 Python microservice entry points deployed and operational
- 6 systemd service units installed, enabled, and confirmed active
- All 6 Prometheus metrics endpoints responding on :9119–:9124
- Fixed AIOKafkaConsumer not being started before message loop in Stage base class

## Task Commits

Each task was committed atomically:

1. **Task 1: Create topic creation script** - `5add62c` (feat)
2. **Task 2: Create quality_gate_service.py** - `dd47328` (feat)
3. **Task 3: Create remaining 5 stage services** - `7ae94f4` (feat)
4. **Task 4: Create systemd service units** - `2ad40e5` (feat)
5. **Rule 1 Fix: Start Kafka clients in Stage.run()** - `22703dd` (fix)
6. **Task 5: Enable and start services; fix log paths** - `329f9c7` (feat)
7. **Ruff fix: unused loop variable** - `5688a93` (fix)

## Files Created/Modified

- `production/scripts/create_stage_topics.py` - Idempotent topic creation script for all 8 stage topics
- `services/quality_gate_service.py` - QualityGate microservice entry point, metrics :9119
- `services/regime_gate_service.py` - RegimeGate microservice entry point, metrics :9120
- `services/tod_adjuster_service.py` - TODAdjuster microservice entry point, metrics :9121
- `services/calibrator_service.py` - Calibrator microservice entry point, metrics :9122
- `services/ranker_service.py` - Ranker microservice entry point, metrics :9123
- `services/winner_selector_service.py` - WinnerSelector microservice entry point, metrics :9124
- `production/systemd/indicagnet-quality-gate.service` - Systemd unit, After=signal-generator
- `production/systemd/indicagnet-regime-gate.service` - Systemd unit, After=quality-gate
- `production/systemd/indicagnet-tod-adjuster.service` - Systemd unit, After=regime-gate
- `production/systemd/indicagnet-calibrator.service` - Systemd unit, After=tod-adjuster
- `production/systemd/indicagnet-ranker.service` - Systemd unit, After=calibrator
- `production/systemd/indicagnet-winner-selector.service` - Systemd unit, After=ranker
- `src/intelligence/stages/base.py` - Fixed: start() Kafka clients before consumer loop; stop() after loop

## Decisions Made

- Used `rpk topic create -c retention.ms=604800000` (correct rpk create syntax — plan used `--set` which doesn't exist for create subcommand)
- Systemd units follow DAG chain: quality-gate → regime-gate → tod-adjuster → calibrator → ranker → winner-selector
- Log paths use `logs/<name>_service.log` convention matching all other services

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Wrong rpk topic create flag in plan code**
- **Found during:** Task 1 (create topic creation script)
- **Issue:** Plan used `--set retention.ms=...` but rpk topic create uses `-c key=value` for config flags; `--set` is only for `alter-config`
- **Fix:** Changed create to use `-c retention.ms={RETENTION_MS}`; added separate `alter-config --set` call for idempotent retention enforcement on existing topics
- **Files modified:** production/scripts/create_stage_topics.py
- **Verification:** All 8 topics created successfully confirmed via `rpk topic list`
- **Committed in:** 5add62c (Task 1 commit)

**2. [Rule 1 - Bug] Plan had syntax error: `project_root = __file__.parent.parent`**
- **Found during:** Task 2 (create quality_gate_service.py)
- **Issue:** `__file__` is a `str`, not a `Path` — `.parent` attribute doesn't exist on str; needs `Path(__file__).parent.parent`
- **Fix:** Used `Path(__file__).parent.parent` in all 6 service files
- **Files modified:** All 6 services/*_service.py
- **Verification:** Services import and start without AttributeError
- **Committed in:** dd47328, 7ae94f4 (Tasks 2+3 commits)

**3. [Rule 1 - Bug] AIOKafkaConsumer not started before message loop in Stage.run()**
- **Found during:** Task 5 (enable and test services)
- **Issue:** `AttributeError: 'NoneType' object has no attribute 'check_errors'` — AIOKafkaConsumer._coordinator is None until `start()` is called; `run()` entered the message loop without starting clients
- **Fix:** Added `await consumer.start()`, `await producer.start()`, `await attribution_producer.start()` before the loop; added `stop()` calls after loop exits for graceful shutdown
- **Files modified:** src/intelligence/stages/base.py
- **Verification:** All 6 services active (systemctl is-active); metrics endpoints responding
- **Committed in:** 22703dd (separate bug fix commit)

**4. [Rule 1 - Bug] setup_service_logging passed bare name instead of full path**
- **Found during:** Task 5 (enable and test services)
- **Issue:** `setup_service_logging("quality_gate")` creates log file at `./quality_gate` in cwd; convention is `logs/<name>_service.log`
- **Fix:** Updated all 6 service files to pass `"logs/<name>_service.log"`
- **Files modified:** All 6 services/*_service.py
- **Verification:** Log files appear in `logs/` directory
- **Committed in:** 329f9c7 (Task 5 commit)

---

**Total deviations:** 4 auto-fixed (all Rule 1 bugs — wrong CLI flags, Python type error, missing async initialization, wrong log path)
**Impact on plan:** All fixes necessary for correctness. No scope creep.

## Issues Encountered

- Services hit `StartLimitIntervalSec` burst limit on first attempt (rapid restart loop before base.py fix) — required `systemctl reset-failed` before clean restart

## User Setup Required

None — all services deployed and running. Prometheus scrape configs for :9119–:9124 may need updating if monitoring is configured.

## Next Phase Readiness

- All 6 DAG stage microservices deployed and running
- Topics ready to receive messages when signal pipeline is wired through DAG
- Metrics endpoints available for Prometheus scraping
- Phase 40-04 (integration wiring) can now connect signal_generator output to quality_gate input

---
*Phase: 40-dag-refactor-clean-foundation*
*Completed: 2026-03-20*
