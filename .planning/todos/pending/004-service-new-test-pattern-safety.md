---
created: 2026-03-11T00:00:00.000Z
updated: 2026-03-28T00:00:00.000Z
title: Service __new__ test pattern — add sync safety
area: testing
priority: 4
tier: immediate
files:
  - services/feature_writer_agent.py
---

# Service `__new__` Test Pattern — Add Sync Safety

**Created:** 2026-03-11
**Effort:** Small (1–2h)
**Source:** CONCERNS.md audit

## Problem

Unit tests in `tests/unit/service_tests/` and `tests/unit/services/` use `ServiceClass.__new__(ServiceClass)` to bypass `__init__` and avoid full async/DB initialization. This requires manually setting all instance attributes the tests need.

**Fragile:** When `__init__` adds a new attribute (e.g., `self._new_cache = {}`), tests silently fail with a misleading `AttributeError` deep in a method call — not at the fixture setup.

**Files already affected:**
- `tests/unit/service_tests/test_concurrent_lock_behavior.py`
- `tests/unit/service_tests/test_feature_writer_service.py`
- `tests/unit/test_indicator_service_warmup.py`

Note: `services/indicator_service.py` and `services/market_analysis_service.py` have been retired/merged. The pattern still applies to agent files like `services/feature_writer_agent.py` and any other agents with complex `__init__` methods.

## Fix Options

### Option A (recommended) — Extract `_init_attributes()` method
Add a `_init_attributes()` method to each agent/service that sets all instance attributes. Call it from `__init__` AND from test fixtures:

```python
class FeatureWriterAgent(BaseAgent):
    def __init__(self, config):
        self._init_attributes(config)
        # ... async setup ...

    def _init_attributes(self, config=None):
        self._batch = []
        self._batch_size = 500
        # ... all attrs ...
```

Test fixture:
```python
svc = FeatureWriterAgent.__new__(FeatureWriterAgent)
svc._init_attributes()  # one line, always in sync
```

### Option B (minimal) — Add a comment block to each `__init__`
Document which attributes test fixtures must set, to make the contract explicit.

## Scope

Start with the most-tested agents:
1. `services/feature_writer_agent.py` + `tests/unit/service_tests/test_feature_writer_service.py`
2. Other agents that have unit tests using `__new__` bypass pattern

## Notes

Option A is safer long-term but requires touching agent `__init__` — run full test suite after each refactor.
