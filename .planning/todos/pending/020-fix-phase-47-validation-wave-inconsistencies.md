---
created: 2026-03-22T00:00:00Z
title: Fix Phase 47 VALIDATION.md wave assignment inconsistencies
area: planning
files:
  - .planning/phases/47-shadow-mode-graduation/47-VALIDATION.md:41-54
---

## Problem

Three inconsistencies in the per-task verification map:
1. Tasks 47-01 and 47-02 show Wave 1 in the Wave column but "❌ W0" in File Exists — confusing wave dependency vs assignment.
2. Task 47-04 shows Wave 2 but "❌ W0" in File Exists — same mismatch.
3. SHADOW-04 in Wave 0 requirements references `test_shadow_stats.py` but per-task map for 47-04 references `test_weight_updater.py -k shadow` — these should be reconciled to one canonical file.

## Solution

Align Wave column and File Exists cells, and reconcile the SHADOW-04 test file reference to a single canonical path.
