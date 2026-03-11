---
created: 2026-02-27T15:38:24.811Z
title: Improve signal banner between price hero and timeframes
area: ui
files:
  - dashboard/src/components/
---

## Problem

The signal banner at the top of the instrument card (between the Price Hero and the timeframe tabs) is sparse — it doesn't convey enough information at a glance. The bottom signal panel has richer detail but takes more vertical space.

## Solution

Enrich the top signal banner with more signal info — similar to what the bottom signal panel shows — but keep it compact to avoid consuming too much card space. Consider showing: setup type, direction, entry/SL/TP, RR ratio, confidence score. Use compact inline layout (single row or two tight rows) rather than the expanded card format used at the bottom.
