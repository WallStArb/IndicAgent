# Dashboard SSE Stress Tests

**Created:** 2026-03-11
**Priority:** Low
**Effort:** Medium (half-day)
**Source:** CONCERNS.md audit

## Problem

Known untested areas in the dashboard:

1. **SSE reconnection** — `use-market-stream.ts` reconnect logic not end-to-end tested; no verification that state recovers correctly after disconnect
2. **Multi-client SSE fan-out** — no test that N clients all receive the same events without duplicate Redis reads (each client should share one Redis reader, not have N independent pollers)
3. **Service graceful shutdown under load** — SIGINT/SIGTERM handling with pending writes not fully stress-tested
4. **PostgreSQL transaction failures** — retry logic in `database_manager.py` not tested for mid-batch failure
5. **LLM fallback chain timeouts** — `llm_providers.py` fallback order tested but not realistic timeout scenarios

## Fix

For the SSE/dashboard items, use Playwright for E2E tests:
- Simulate SSE disconnect + reconnect, verify signal state restored
- Open N browser tabs, verify all receive same events
- Check that SSE snapshot age filter (Phase 27-03) works on reconnect

For the service items:
- Mock mid-batch DB failure in `database_manager.py` tests
- Mock Ollama timeout in LLM provider tests (not just connection refused)

## Notes

- Dashboard test runner not yet configured (`dashboard/tsconfig.json` excludes `**/__tests__/**`)
- May need to set up Vitest or Playwright as a prerequisite
- Low urgency — add to v1.8+ milestone when dashboard work is in scope
