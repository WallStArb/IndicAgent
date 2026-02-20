# Testing Standards

Test guidelines for IndicAgent.

---

## Running Tests

```bash
# Unit tests (fast, no external dependencies)
.venv/bin/python3 -m pytest tests/unit/ -q

# Integration tests (require live Redis + PostgreSQL)
.venv/bin/python3 -m pytest tests/integration/ -v

# Full suite with coverage
.venv/bin/python3 -m pytest tests/unit/ --cov=src --cov-report=term-missing -q
```

**Current:** 383 unit tests passing, 0 ruff errors. Integration tests require running infrastructure and have pre-existing failures unrelated to unit work.

---

## Test Organization

```
tests/
├── unit/           # Fast, isolated — no Redis, no DB, no network
│   ├── core/       # Core infrastructure tests (circuit breaker, state manager, metrics)
│   ├── indicators/ # I1 indicator plugin tests
│   ├── intelligence/ # I1–I8 plugin tests (context, patterns, structure, etc.)
│   └── ...
└── integration/    # Multi-component tests (requires Redis + PostgreSQL)
```

---

## Writing Tests

### Unit Tests

Unit tests cover a single plugin or function in isolation. Use `pytest` fixtures and mock external dependencies.

```python
# tests/unit/indicators/test_my_indicator.py
import pytest
from src.intelligence.indicators.my_indicator import MyIndicator

def test_basic_output():
    plugin = MyIndicator()
    bar = {"close": 100.0, "high": 101.0, "low": 99.0, "volume": 1000}
    result = plugin.compute_next(bar)
    assert "my_value" in result
    assert isinstance(result["my_value"], float)

def test_warmup_period():
    plugin = MyIndicator()
    # Plugin should return None until warm-up bars are consumed
    for _ in range(plugin.warmup_period - 1):
        result = plugin.compute_next({"close": 100.0, "high": 101.0, "low": 99.0, "volume": 1000})
    assert result is None or result.get("my_value") is None
```

**Rules:**
- One `assert` per logical claim — don't bundle unrelated assertions
- Test edge cases: empty input, NaN, zero volume, single bar
- Name tests descriptively: `test_returns_none_before_warmup`, not `test_1`

### Integration Tests

Integration tests verify service interactions — Redis stream reads/writes, DB queries, multi-plugin pipelines. Mark with `@pytest.mark.integration` and skip in CI if infrastructure is unavailable.

---

## Coverage

No hard threshold today. Aim for full branch coverage on new plugins. The pattern detection and indicator plugins all have dedicated test files — follow that convention for any new plugin.

---

**Guide:** [Testing](../guides/testing.md)
