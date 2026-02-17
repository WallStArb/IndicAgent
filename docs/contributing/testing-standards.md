# Testing Standards

Test guidelines for IndicAgent.

---

## Running Tests

```bash
pytest tests/unit/ -v                  # Unit tests
pytest tests/integration/ -v           # Integration tests
python tests/run_all_tests.py          # Full suite
python tests/run_all_tests.py --coverage  # With coverage
```

**Current:** See [STATUS.md](../STATUS.md) for test count

---

## Test Organization

```
tests/
├── unit/           # Fast, isolated tests
├── integration/    # Multi-component tests (requires Redis/PostgreSQL)
└── e2e/            # End-to-end tests
```

---

## Writing Tests

### Unit Tests

[TODO: Examples of good unit tests]

### Integration Tests

[TODO: Examples of integration tests]

---

## Coverage Requirements

[TODO: Define coverage thresholds]

---

**Guide:** [Testing](../guides/testing.md)
