---
phase: 111
reviewers: [gemini, codex]
reviewed_at: 2026-05-30T00:00:00Z
plans_reviewed:
  - 111-01-PLAN.md
  - 111-02-PLAN.md
  - 111-03-PLAN.md
  - 111-04-PLAN.md
---

# Cross-AI Plan Review — Phase 111

## Gemini Review

### Summary

The plan is logically structured and appropriately modularized, effectively addressing the "drifting" nomenclature in IndicAgent. By sequencing the changes from foundational (BaseDaemon) to peripheral (tests/docs), the plan minimizes broken references and maximizes testability. The approach to using `git mv` for file renames and surgical string replacements is disciplined and aligns well with the existing project standards.

### Strengths

- **Sequential Dependency Management:** Moving from base infrastructure (Plan 01) to peripheral documentation (Plan 04) is the correct approach to minimize cascading breakages.
- **Surgical Execution:** The explicit move away from global `sed` in favor of per-file edits for event strings (Plan 03) prevents accidental collateral damage to non-event strings or code comments.
- **Comprehensive Scope:** Including monitoring (Grafana/Alertmanager) and systemd paths ensures runtime surface consistency, not just codebase consistency.
- **Test Integrity:** The explicit focus on renaming test files and classes while preserving git history (`git mv`) maintains developer velocity and traceability.

### Concerns

- **MEDIUM: Metric Label Telemetry Gap** — Fixing the hardcoded `"feature_writer_agent"` label in `feature_writer.py` while simultaneously migrating all services to auto-derived names risks a "gap" in telemetry data if Prometheus queries expect the old label for historical aggregations. Ensure Prometheus queries are compatible with the new naming scheme immediately.
- **MEDIUM: Systemd/Service Coupling** — Changing file names in `services/` and `systemd/` concurrently with class renames within those files requires precise execution to avoid service boot failures.
- **LOW: Pre-commit Hook Maintenance** — The Ring 0 pre-commit hook (grep-based) could be brittle if the project structure evolves slightly. Ensure the regex pattern is strictly scoped.

### Suggestions

- Add a `verify_no_stale_references` step at the end of each wave to search the entire project for strings/constants just removed/renamed.
- Before Plan 01, document expected changes to dashboard metrics to assist in debugging potential "flatlining" graphs post-migration.
- Consider using a simple Python snippet instead of raw grep in `.git/hooks/pre-commit` for more context-aware checking.

### Risk Assessment

**Overall Risk: LOW**

The plan is conservative, highly granular, and relies on established patterns within the codebase. The biggest technical risk (service breakage) is mitigated by the modular design and the fact that most changes are renaming rather than functional refactoring.

---

## Codex Review

### Summary

The four-wave structure is sensible and mostly maps to the phase goal: first fix derivation, then rename runtime files, then normalize event strings, then enforce the boundary and clean docs/tests. The main weakness is that several plans rely on counts and grep checks that are too narrow for the current repo. The highest-risk gaps are `BaseWriter` still requiring `name`, local `.git/hooks/pre-commit` not being versioned or enforced in CI, existing `src/core` imports from `src.intelligence`, stale systemd `LOG_FILE` overrides, and service/unit naming inconsistencies that may survive because the acceptance criteria search only part of the surface.

### Strengths

- Sequential waves are well ordered: deriving names before removing overrides, and renaming files before event-prefix replacement, reduces churn.
- The phase has concrete success criteria with command-level validation.
- Using `git mv` for service and test renames is correct and preserves history.
- The plan recognizes monitoring surfaces, not just Python code: Grafana, Alertmanager, and `service_auditor.py` are included.
- Structlog replacement is planned as precise per-file edits, which is safer than a broad sed pass across the repo.
- The `_to_snake_case('MLDiscoveryAnalyzer') == 'ml_discovery_analyzer'` check targets a real acronym edge case.

### Concerns

- **HIGH: `BaseWriter` is not covered by Plan 01.** `BaseWriter.__init__(name: str, **kwargs)` still requires `name` and passes it to `BaseDaemon`. Removing `name=` from writer services like `bar_writer.py`, `lineage_writer.py`, `signal_metrics_writer.py`, and others will break unless `BaseWriter` also accepts `name: str | None = None` and derives consistently.

- **HIGH: Ring 0 hook will likely fail against the current tree.** Current `src/core` may have imports from `src.intelligence` in files such as `src/core/ai/context.py`, `src/core/ai/base_group_service.py`, `src/core/bar_history_seeder.py`, and `src/core/state_serializer.py`. Plan 04 says "verify zero current Ring 0 violations," which is correct pre-flight behavior, but the plan must explicitly state what to do if violations are found (fix them or add allowlist) rather than treating it as an edge case.

- **HIGH: `.git/hooks/pre-commit` is local-only and not versioned.** Adding the check only there will not protect CI, other developers, or fresh clones. Should also be a versioned script called from CI.

- **HIGH: ML signal training rename appears inaccurate.** The roadmap says `ml_signal_training_materialize_agent.py`, but the actual service file may be `services/ml_signal_training_agent.py`. The implementation plan needs to reconcile actual file names before execution.

- **MEDIUM: Systemd log environment overrides not included in Wave 1.** At least some systemd units still have `Environment=LOG_FILE=logs/macro_compute_agent.log`. Removing Python `setup_service_logging()` overrides is not enough if units still force old paths.

- **MEDIUM: `name=` removal scope is too narrow.** The acceptance criteria grep may miss `super().__init__(name=...)` in `src/intelligence/ai/*` and `src/core/ai/base_group_service.py`.

- **MEDIUM: Event string convention conflict in Plan 03.** The stated convention is `"derived_agent_id.action"`, but Plan 03 changes base events to `"daemon.*"` and `"ai_worker.*"`. This exception should be stated explicitly or derive from bound logger context instead.

- **MEDIUM: Grafana and Alertmanager are not the only observability surfaces.** Prometheus scrape config, Grafana provisioning alert rules, logrotate, systemd `SyslogIdentifier`, and docs may also contain stale labels or paths.

- **LOW: Acceptance criteria overfit exact greps.** Checks like `grep "bar_aggregator.*indicagent-bar-aggregator"` prove one mapping but not all mappings. Prefer generated expected mappings from classes to agent IDs.

- **LOW: Test rename checks may rename too much.** `find tests/ -name "*_agent*.py"` would also flag AI-agent tests where "agent" may be domain-correct.

### Suggestions

- Update Plan 01 to include `src/core/agent/base_writer.py`; make `BaseWriter.__init__(name: str | None = None, **kwargs)` pass `name=None` through to `BaseDaemon`.
- Add explicit tests for name derivation including acronym cases: `DLQDrain`, `MLSignalTrainingMaterializer`, `IBKRProvider`.
- Add a versioned Ring 0 check script (e.g., `scripts/check_ring0_imports.sh`) called from both `.git/hooks/pre-commit` and CI.
- Before Plan 04, explicitly audit existing `src/core` to `src.intelligence` imports and decide: move to Ring 1, invert dependencies, or add tracked allowlist.
- Include systemd `Environment=LOG_FILE=...` and `SyslogIdentifier` in the stale-name search (Wave 1 scope).
- In Plan 02, build an explicit actual-path rename table from the current repo before implementing ML signal training rename.
- Add an acceptance check that imports every service module after renames (a small pytest parametrized over `services/*.py`).

### Risk Assessment

**Overall Risk: MEDIUM-HIGH**

The phase is mostly mechanical but touches runtime identity across service startup, logs, metrics, dashboards, alerting, systemd, tests, and docs. The current plans under-specify several real repo surfaces and have at least one likely implementation breakage around `BaseWriter`. Tightening the inventory, making enforcement versioned, and reconciling existing Ring 0 violations would bring the risk down to medium.

---

## Consensus Summary

### Agreed Strengths

- Sequential 4-wave dependency structure is correct — foundational changes before peripheral ones
- `git mv` for file renames preserves git history
- Surgical per-file edits for structlog event strings (not broad sed) is the right approach
- Comprehensive monitoring scope (Grafana, Alertmanager, service_auditor) is a strength
- Concrete acceptance criteria with command-level validation

### Agreed Concerns

- **Monitoring alignment risk** (both): Changing `agent_id` label values while Grafana/Prometheus queries still reference old names risks a telemetry gap. Verify all observability surfaces are captured, not just the 4 Grafana JSONs mentioned.
- **Systemd completeness** (both): Beyond ExecStart paths, systemd units may have `Environment=LOG_FILE=` entries that also need updating.

### Critical Concerns (Codex only — HIGH priority, should verify)

1. **BaseWriter gap**: If `BaseWriter` has `name: str` (non-optional) in its `__init__`, removing `name=` from writer services will raise TypeError at service startup. Verify `src/core/agent/base_writer.py` signature before executing Plan 01.

2. **Ring 0 pre-flight**: Plan 04 Task 1 already includes a pre-flight check for existing violations — this is correct. But the plan needs to state clearly what happens when violations are found (currently: "fix them or adjust the hook"), not just discover them.

3. **ML signal training filename**: Verify the actual filename on disk before Plan 02 execution. The CONTEXT.md says `ml_signal_training_materialize_agent.py` but this should be confirmed.

4. **Pre-commit hook not in CI**: For a single-developer passion project, this is LOW practical risk — but worth noting if the repo ever has collaborators.

### Divergent Views

- **Risk level**: Gemini rates this LOW; Codex rates it MEDIUM-HIGH. The divergence is mainly about whether `BaseWriter` signature and existing Ring 0 violations are real blockers. These are verifiable before execution — a quick `grep` resolves both.
- **Pre-commit hook robustness**: Gemini wants a Python-based linter; Codex wants a versioned shell script in CI. For this single-developer project, the current grep-based approach in `.git/hooks/pre-commit` is sufficient given the pre-flight verification step already in Plan 04.

### Recommended Pre-Execution Checks

Before starting Wave 1, run:
```bash
# 1. Verify BaseWriter signature
grep -n "def __init__" src/core/agent/base_writer.py

# 2. Check for existing Ring 0 violations
grep -rn "from src\.intelligence\|from src\.providers\|from src\.self_healing\|from services" \
  src/core/ src/observability/ --include="*.py" | grep -v "^\s*#"

# 3. Verify ML signal training actual filename
ls services/ml_signal_training*.py src/intelligence/services/ml_signal_training*.py 2>/dev/null

# 4. Check systemd LOG_FILE env overrides
grep -rn "LOG_FILE" production/systemd/ | head -20
```
