---
created: 2026-02-25T01:11:42.841Z
title: Review signal_orchestrator_service for deletion
area: general
files:
  - services/signal_orchestrator_service.py
  - services/signal_generator_service.py
  - tests/unit/test_signal_orchestrator*.py
---

## Problem

`services/signal_orchestrator_service.py` is not managed by systemd, not listed in CLAUDE.md's active services, and has no systemd unit file — but its header says "Status: Production Ready" and it has 22 passing unit tests.

During housekeeping cleanup, it was left undeleted pending review. Unclear whether its functionality was fully absorbed into `signal_generator_service.py` or if it's just dead code.

## Solution

1. Compare functionality of `signal_orchestrator_service.py` vs `signal_generator_service.py` — check for anything not covered
2. Check if the 22 orchestrator tests duplicate coverage already in signal_generator tests
3. If fully superseded: delete `signal_orchestrator_service.py` and consolidate/remove its tests
4. If partially unique: document what's missing from `signal_generator_service.py` before deleting
