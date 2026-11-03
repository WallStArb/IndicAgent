---
phase: 184-multi-timeframe-research-inputs
plan: 07
subsystem: research S0
tags: [snapshot, closes_at, warmup, vendor-rule]
requires: [184-01, 184-04, 184-06]
provides: [build_panel closes_at/warmup_sessions, warmup_fetch_start, B1d refusal]
key-files:
  modified: [src/intelligence/research/snapshot.py, docs/foundation/glossary.md]
  created: [tests/unit/research/test_snapshot_mtf.py]
requirements-completed: [MTF-B1a, MTF-B1b, MTF-B1c, MTF-B1d, MTF-B7]
---

# Phase 184 Plan 07: S0 closes_at, warmup prefix, intraday vendor rule

S0 now writes a hashed per-row closes_at, fetches a recorded warmup prefix, and refuses non-derived 15m/1h bars.

## What changed
- `build_panel(..., fields=(), warmup_sessions=0)`: `fields` accepts `closes_at` (via `clock.closes_at` on the built grid); high/low already flowed through the one bar SELECT (187-15), asserted by test.
- `warmup_fetch_start(start, tf, sessions)`: the open of the N-th NYSE session before start (midnight UTC on 1d). Manifest `warmup_prefix {sessions, fetch_start, scored_start}` only when sessions > 0. The prefix moves lo only; the OOS refusal on hi runs before any fetch. Label inputs, digests and dividends use the prefixed lo.
- `_VENDOR_SET_SQL`: separate pinned query, run at 15m/1h on every build and at any tf when `fields` is set; `check_intraday_vendors` result recorded as manifest `bar_vendor_kinds` only when `fields` is set. FeatureInputRefused becomes ValueError naming B1d.
- Glossary: `warmup prefix`.

## Gates
TDD tests (11) green; unit suite exit 0; repro_frozen bit-identical; pinned spec hashes and ohlcv boundary green; default bytes pinned (panel_9ff105717b6a7a71, equal on pre-change code). compare-all not run (lead, after 184-10).

## Deviations
None. Tests were written alongside the implementation rather than strictly red first.
