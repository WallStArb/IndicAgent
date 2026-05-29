#!/usr/bin/env python3
"""OutboxDispatcherAgent — publishes OPS config updates to Kafka.

Polls config_outbox for pending rows, publishes to topic_config_updates,
updates status with retry semantics. Transactional outbox pattern.

Adaptive polling: 100ms when backlog exists, exponential backoff to 2s when idle
(per review feedback - reduces DB load during quiet periods).

Port convention:
  - No HTTP port (poll-only agent, no API)
  - OTel metrics exposed on the shared metrics port via env METRICS_PORT

Phase 109 Plan 02.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.outbox_dispatcher import OutboxDispatcherAgent

if __name__ == "__main__":
    asyncio.run(OutboxDispatcherAgent().start())
