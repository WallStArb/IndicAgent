# HYGIENE-07 BaseAgent Inheritance Audit

**Audit date:** 2026-05-28
**Auditor:** Phase 108 Plan 07 executor
**Requirement:** HYGIENE-07 — all Python daemon services must inherit BaseAgent (directly or transitively)
**Method:** D-12 from CONTEXT.md — `grep -rL "BaseAgent"` to find non-inheriting services, then confirm each is not a daemon.

---

## Step 1 — grep audit: files NOT containing any known base class

Command run:
```
grep -rL "BaseAgent\|BaseWriterAgent\|BaseGroupService\|BaseProviderAgent" services/*.py
```

Output (verbatim):
```
services/hmm_training_agent.py
services/ml_signal_training_agent.py
services/ml_training_agent.py
services/__init__.py
services/feature_validation_agent.py
services/_path_bootstrap.py
services/shadow_auditor_agent.py
```

---

## Step 2 — verify each file against systemd daemon registry

The output above lists files that contain no reference to BaseAgent, BaseWriterAgent,
BaseGroupService, or BaseProviderAgent. For each, the corresponding systemd unit type
was checked:

| File | Unit file | Type | Daemon? |
|------|-----------|------|---------|
| services/hmm_training_agent.py | indicagent-hmm-training.service | Type=oneshot | No — batch timer |
| services/ml_signal_training_agent.py | indicagent-ml-signal-training-materialize.service | Type=oneshot | No — batch timer |
| services/ml_training_agent.py | indicagent-ml-training.service | Type=oneshot | No — batch timer |
| services/feature_validation_agent.py | indicagent-feature-validation.service | Type=oneshot | No — batch timer |
| services/shadow_auditor_agent.py | indicagent-shadow-auditor.service | Type=oneshot | No — batch timer |
| services/__init__.py | no unit file | N/A | No — Python package init |
| services/_path_bootstrap.py | no unit file | N/A | No — utility import helper |

No file in the grep output is registered as a `Type=simple` systemd daemon. All are
either oneshot timer-triggered scripts or utility files (package init, path bootstrap).
Oneshot scripts do not require BaseAgent inheritance because they run to completion and
exit; the BaseAgent lifecycle loop (`_run()`, watchdog, etc.) would prevent clean exit.

---

## Step 3 — verify the two named HYGIENE-07 targets

CONTEXT.md (D-11, D-12) named `signal_replay_auditor` and `bar_replay_provider` as
migration targets. Audit confirms both already inherit BaseAgent directly:

Command run:
```
grep -E "^class\s+\w+(Agent|Service)\(" services/signal_replay_auditor_agent.py services/bar_replay_provider_agent.py
```

Output (verbatim):
```
services/signal_replay_auditor_agent.py:class SignalReplayAuditorAgent(BaseAgent):
services/bar_replay_provider_agent.py:class BarReplayProviderAgent(BaseAgent):
```

Both `signal_replay_auditor_agent.py` and `bar_replay_provider_agent.py` inherit
BaseAgent directly. No migration required.

---

## Step 4 — complete daemon registry cross-check

All `Type=simple` daemon unit files in `production/systemd/` map to service files that
use one of the four known base classes:

| Base class | Services using it |
|------------|-------------------|
| BaseAgent | SignalReplayAuditorAgent, BarReplayProviderAgent, and any direct subclasses |
| BaseWriterAgent | All writer agents (feature_writer, signal_writer, lifecycle_writer, etc.) — inherits BaseAgent transitively |
| BaseGroupService | AlphaSwarmComputeAgent, NarrativeGroupComputeAgent, etc. — inherits BaseAgent transitively |
| BaseProviderAgent | IBKRProviderAgent, ProviderMergerAgent — inherits BaseAgent transitively |

Services using BaseWriterAgent, BaseGroupService, and BaseProviderAgent inherit BaseAgent
transitively. They do not appear in the grep-rL output above because their source files
contain a direct reference to their immediate base class, which itself contains
"BaseAgent" or "Agent" in the class hierarchy.

---

## Conclusion

**HYGIENE-07 closed: no migration required.**

All Python daemon services (Type=simple systemd units) inherit BaseAgent either directly
or transitively through BaseWriterAgent, BaseGroupService, or BaseProviderAgent.

The grep audit returned seven files; none of them is a `Type=simple` daemon. The two
named targets (`signal_replay_auditor_agent.py` and `bar_replay_provider_agent.py`) were
already on BaseAgent before Phase 108 began.

This finding aligns with RESEARCH.md Open Question 1, which noted: "The grep-rL
'BaseAgent' false positives were services using BaseWriterAgent, BaseGroupService, or
BaseProviderAgent which all inherit from BaseAgent. True HYGIENE-07 gap is closed."

No follow-up migration plan is needed.

---

*Reference: RESEARCH.md (HYGIENE-07 status section, Open Question 1)*
*Phase: 108-self-healing-hardening*
*Audit date: 2026-05-28*
