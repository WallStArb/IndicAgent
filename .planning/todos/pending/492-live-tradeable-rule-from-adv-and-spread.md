---
status: pending
priority: P2
filed: 2026-10-03
source: interactive session (universe wave 2 review)
---

# `live_tradeable` has no rule: all 1,529 names are false

## What

`instruments.live_tradeable` (migration 337) is false for every name and nothing sets it. Ranks
501-1000 and the depth draws include names where a personal book cannot trade size. Todo 437 adds
commission and spread, and phase 188 adds the capacity curve, but neither defines which names are
eligible for capital.

## Fix

Derive `live_tradeable` by a written rule from measured median daily dollar volume and quoted spread
(APR keys, `infra.*` or `alpha.*` namespace), not by hand. A single writer, run after promote and
refreshed on a schedule; the spec's `live_tradeable` universe then means something.

## Gate

After 437's spread measurement exists. Not before the build lands.
