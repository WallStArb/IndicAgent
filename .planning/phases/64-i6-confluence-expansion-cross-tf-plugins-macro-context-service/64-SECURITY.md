---
phase: 64
slug: i6-confluence-expansion-cross-tf-plugins-macro-context-service
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-27
---

# Phase 64 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Kafka consumer (MacroComputeAgent) | Reads `topic_market_bars` from internal Redpanda bus | OHLCV bar data — internal, no PII |
| Kafka producer (MacroComputeAgent) | Writes to `topic_macro_signals` | Computed macro factor scalars — internal |
| TimescaleDB writer (MacroComputeAgent) | INSERT to `macro_features` hypertable | Macro factor scalars — internal |
| TimescaleDB reader (backtest tools) | SELECT from `intelligence_features`, `signal_ledger`, `market_data_ohlcv` | Historical features and outcomes — internal read-only |
| CLI surface (backtest tools) | argparse CLI accepting `--symbols`, `--start`, `--end`, `--output` | Date strings, symbol strings, file paths |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-64-01 | Tampering | MacroComputeAgent DB INSERT | mitigate | All INSERTs use asyncpg `$N` parameterized queries — no string interpolation. Verified in `services/macro_compute_agent.py:286-319`. | closed |
| T-64-02 | Tampering | backtest_i6_plugin.py SQL | mitigate | Dynamic WHERE clauses use `$N` positional params via `param_idx` counter — no f-string SQL concatenation. Verified in `tools/backtest_i6_plugin.py:93-134`. | closed |
| T-64-03 | Tampering | backtest_macro_factors.py SQL | mitigate | All queries use `$1/$2/$3` parameterized bindings. Verified in `tools/backtest_macro_factors.py:48-56,79-90`. | closed |
| T-64-04 | Information Disclosure | backtest tool `--output` path | accept | CLI tools are developer-only scripts run locally. Output path is user-provided; no server-side path traversal risk. Accepted: internal tooling. | closed |
| T-64-05 | Denial of Service | MacroComputeAgent rolling deque | accept | Unbounded symbol set from `topic_market_bars` could grow deque count. Mitigated by `MACRO_RATE_FUTURES` allowlist filter — only ZT/ZN/ZB/ZF processed. Accepted: allowlist enforced at compute entry. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-64-01 | T-64-04 | Backtest CLI `--output` path is developer-only tooling. No server-side execution. Users are trusted developers with local DB access. | Brandon | 2026-04-27 |
| AR-64-02 | T-64-05 | MacroComputeAgent filters by `MACRO_RATE_FUTURES` allowlist before any computation. Only 4 symbols (ZT/ZN/ZB/ZF) ever enter rolling deques. Risk is negligible. | Brandon | 2026-04-27 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-27 | 5 | 5 | 0 | gsd-secure-phase (inline audit) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-27
