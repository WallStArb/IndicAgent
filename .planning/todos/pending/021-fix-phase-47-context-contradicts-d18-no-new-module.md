---
created: 2026-03-22T00:00:00Z
title: Fix 47-CONTEXT.md reference to roll_calendar.py contradicts D-18
area: planning
files:
  - .planning/phases/47-shadow-mode-graduation/47-CONTEXT.md:138
---

## Problem

Line 138 of 47-CONTEXT.md suggests creating `src/core/roll_calendar.py` as a "pure module pattern", but decision D-18 explicitly says "No new module — extend src/config/contracts.py directly." The context doc is out of sync with the architectural decision.

## Solution

Update line 138 to reference `src/config/contracts.py` as the location for roll-calendar logic, removing the mention of `roll_calendar.py`.
