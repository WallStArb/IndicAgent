---
created: 2026-03-11T00:00:00.000Z
title: Service __new__ test pattern — add sync safety
area: testing
priority: 2
tier: immediate
phase: unblocked
files:
  - services/indicator_service.py
  - services/feature_writer_service.py
  - services/market_analysis_service.py
---

# Service `__new__` Test Pattern — Add Sync Safety

**Created:** 2026-03-11
**Effort:** Small (1–2h)
**Source:** CONCERNS.md audit

## Problem

Unit tests in `tests/unit/service_tests/` and `tests/unit/services/` use `ServiceClass.__new__(ServiceClass)` to bypass `__init__` and avoid full async/Redis/DB initialization. This requires manually setting all instance attributes the tests need.

**Fragile:** When `__init__` adds a new attribute (e.g., `self._new_cache = {}`), tests silently fail with a misleading `AttributeError` deep in a method call — not at the fixture setup.

**Files already affected:**
- `tests/unit/service_tests/test_concurrent_lock_behavior.py`
- `tests/unit/service_tests/test_feature_writer_service.py`
- `tests/unit/test_indicator_service_warmup.py`

## Fix Options

### Option A (recommended) — Extract `_init_attributes()` method
Add a `_init_attributes()` method to each service that sets all instance attributes. Call it from `__init__` AND from test fixtures:

```python
class IndicatorService:
    def __init__(self, config):
        self._init_attributes(config)
        # ... async setup ...

    def _init_attributes(self, config=None):
        self.bar_history = defaultdict(OrderedDict)
        self._bar_history_max = 5
        self._plugin_cache = {}
        # ... all attrs ...
```

Test fixture:
```python
svc = IndicatorService.__new__(IndicatorService)
svc._init_attributes()  # one line, always in sync
```

### Option B (minimal) — Add a comment block to each `__init__`
Document which attributes test fixtures must set, to make the contract explicit.

## Scope

Start with the most-tested services:
1. `services/indicator_service.py` + `tests/unit/test_indicator_service_warmup.py`
2. `services/feature_writer_service.py` + `tests/unit/service_tests/test_feature_writer_service.py`
3. `services/market_analysis_service.py`

## Notes

Option A is safer long-term but requires touching service `__init__` — run full test suite after each refactor.
