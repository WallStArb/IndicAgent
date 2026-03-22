---
created: 2026-03-22T00:00:00Z
title: Fix Phase 47 ROADMAP success criterion referencing undefined requirement D-07
area: planning
files:
  - .planning/ROADMAP.md:717
---

## Problem

Phase 47 success criteria reference "(D-07)" but the Phase 47 Requirements block only lists SHADOW-01 through SHADOW-04 and INTEL-04. D-07 is undefined in the requirements list — stale reference from planning.

## Solution

Either add D-07 to the Phase 47 requirements block or replace the D-07 reference in the `roll_premium_pct` success criterion with the correct requirement code.
