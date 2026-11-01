---
status: pending
priority: P3
filed: 2026-11-01
source: indicagent-93, observed during the 538 landing (2026-11-01)
---

# Fetcher watchdog unit tests write stall events into the shared logs/ibkr_history_fetcher.log

## What

The 538 watchdog's unit tests emit `stall_warning` / `stall_abort` structlog events into the
real `logs/ibkr_history_fetcher.log` (the constructor's `setup_service_logging` configure swaps
in a processor list writing the shared file). A test-scoped structlog sink (or building the
fetcher against a injected logger in tests) stops the pollution of an operational log that the
534 lane reads during wedges.

## Why now

Operational-noise hygiene only, but cheap: any session touching the fetcher tests next can fold
it in. The abort test already captures via `structlog.testing.capture_logs` (commit `def74ce4c`);
the leak is the constructor-time configure, not the assertions.

## Done when

Running the fetcher test file leaves `logs/ibkr_history_fetcher.log` byte-identical (modulo the
real fetcher's own concurrent lines).
