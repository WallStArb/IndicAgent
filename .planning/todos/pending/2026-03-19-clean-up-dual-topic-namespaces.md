---
created: 2026-03-19T15:51:25.948Z
title: Clean up dual topic namespaces
area: infrastructure
files:
  - src/core/stream_keys.py
  - services/tws_daemon.py
  - services/indicator_service.py
  - services/market_analysis_service.py
---

## Problem

Redpanda has duplicate topics for the same data with two different prefixes:
- `dev.indicators`, `dev.intelligence`, `dev.market.bars`, `dev.market.ticks` (old/hardcoded)
- `development.indicators`, `development.intelligence`, `development.market.bars`, etc. (from `INDICAGENT_ENV=development`)

This wastes resources and creates confusion about which topics are authoritative. The `development.*` topics are correct (services use `topic_market_bars(self.env_name)` which resolves properly), but `dev.*` topics linger from legacy hardcoded references.

## Solution

Two options:
1. **Deprecate `dev.*`**: Ensure all services use `topic_*()` helpers from `stream_keys.py` (which correctly use `env_name`), then delete old topics via `rpk topic delete`
2. **Standardize prefix**: Update `INDICAGENT_ENV` default and hardcode one prefix everywhere

First step: grep services for any remaining hardcoded `"dev.indicators"` or `"dev.market.bars"` strings to find legacy code paths before deleting topics.
