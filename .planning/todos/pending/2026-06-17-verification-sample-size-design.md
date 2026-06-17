---
created: 2026-06-17
priority: low
resolves_phase:
tags: [verification, phase-133, corpus-rebuild]
---

# Verification Sample Size: Use Fixed Bar Count, Not Wall-Clock Window

## Problem

Phase 131 plan 131-07 used "1-week sample replay" as the verification gate scope. This is arbitrary — wall-clock windows produce different signal counts depending on market activity (holidays, low-vol sessions, etc.) and are slower than necessary for a gate check.

## Proposed approach

For Phase 133 verification (and future replay verification gates):

- Use **N bars per (symbol, TF)** — e.g. 100 bars × 1m × each active symbol, 100 bars × 5m, 100 bars × 15m, 100 bars × 1h
- Gate passes when: each eligible plugin fires ≥1 time across the sample, ctf_score distribution shows ≥85% > 0.05
- This is faster, deterministic, and reproducible regardless of which date range is chosen

## Why it matters

- A fixed bar count means the same test always takes the same time
- Plugin coverage (≥1 fire per plugin) is a stricter gate than "ran for 1 week and assumed plugins fired"
- Easier to add to CI/pre-commit as a smoke test

## Raised during

Phase 131 execution — noted while 131-07 verification replay was running.
