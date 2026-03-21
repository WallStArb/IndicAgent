---
created: 2026-02-27T15:38:24.811Z
title: Add volume profile POC/VAH/VAL as S/R anchors
area: general
priority: 7
tier: phase-45-46
phase: "46"
files:
  - src/intelligence/plugins/
---

## Problem

No volume profile is computed — Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL) would be ideal T1/T2 S/R anchors for signal confluence but aren't available yet.

## Solution

Research and implement a volume profile plugin (I3 or I4 tier). Emit POC/VAH/VAL as structured output. Wire into the confluence and signal plugins as additional S/R reference levels. Consider session-based vs rolling-window profile.
