# Ruff Auto-Fix + Pre-Commit Hook

**Created:** 2026-03-11
**Priority:** Medium
**Effort:** Small (30 min auto-fix + 30 min manual)
**Source:** CONCERNS.md audit

## Problem

139 ruff errors currently in codebase — all E501 (line too long). 41 are auto-fixable.
Hotspot: `production/scripts/historical_backfill.py` (34 errors in docstrings/help text).

This number grew back from 0 (v1.1 sprint) because there's no gate preventing new violations.

## Fix

### Step 1 — Auto-fix (41 errors)
```bash
.venv/bin/ruff check . --fix
```

### Step 2 — Manual fixes (remaining ~98)
Mostly docstring line wraps and long help text in argparse definitions.
Focus on `production/scripts/historical_backfill.py` first (34 errors).

### Step 3 — Pre-commit hook
Add ruff check to pre-commit so E501 can't creep back in:
```yaml
# .pre-commit-config.yaml (create if not exists)
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [--fix]
```

Or simpler — add a git hook in `.git/hooks/pre-commit`:
```bash
#!/bin/bash
.venv/bin/ruff check . --exit-non-zero-on-fix
```

## Notes

- Run from project root, not absolute paths
- After fix, update CLAUDE.md test count + ruff error count in Status section
