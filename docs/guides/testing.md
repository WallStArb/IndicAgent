# Testing Guide

**Last Updated:** 2026-05-02

[TODO: Writing tests, running suite, coverage]

---

## Running Tests

```bash
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
python tests/run_all_tests.py
```

Use `UV_CACHE_DIR=/tmp/uv-cache uv run pytest ...` in sandboxed environments where `$HOME/.cache` is not writable.

See current test count: [STATUS.md](../STATUS.md)

---

## Writing Tests

[TODO: Add test writing guide]

---

## Coverage

[TODO: Add coverage guide]
