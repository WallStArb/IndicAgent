# Temporal Data Architecture

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-05-30
**Tags:** time-series, immutability, timescaledb, data-retention

> Every market event is a timestamped, immutable record — nothing is dropped, everything is queryable by time.

## The Problem It Solves

Generic relational databases treat time as just another column. This leads to: slow range queries requiring full-table scans, no native compression for time-series data, schema designs that mix mutable state with immutable events, and lost history when records are updated in-place. For a quantitative system where every historical signal is a labeled training sample, these are fatal flaws.

## The Principle

Time-series data has a natural append-only structure — events happen, are recorded, and never change. A temporal data architecture exploits this:

1. **Hypertables** — partition data automatically by time. Range queries hit only the relevant partitions.
2. **Compression** — time-ordered data compresses at 10-20x versus row-store. Old data costs nearly nothing.
3. **Immutable events** — never UPDATE a row that represents something that happened. Corrections are new rows.
4. **No retention policies** — storage is the cheapest resource. Every data point is a potential training sample.

## How IndicAgent Applies It

TimescaleDB (PostgreSQL extension) is used for all time-series tables. Three primary hypertables:

| Table | Time column | Purpose |
|-------|-------------|---------|
| `market_data_ohlcv` | `timestamp` | Raw OHLCV bars |
| `intelligence_features` | `ts` | Full feature vectors per bar (I1-I7 outputs) |
| `signal_ledger` | `timestamp` | All signals + lifecycle outcomes, forever |

**`signal_ledger` is the crown jewel.** Every I7 signal ever fired is stored with its full feature context, entry/exit prices, PnL-R, MAE, MFE, and outcome. This is the labeled training dataset for every future model. It has no retention policy and never will.

**Volume Profile columns:** `poc_price`/`vah`/`val` = session VP (1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (15m/1h). Different names for semantically different calculations — do not conflate.

**Connection pattern:** All DB access via `asyncpg` through `src/core/database_manager.py`. JSONB columns return `dict` directly — never call `json.loads()` on asyncpg results. Timestamps return `datetime` objects. Always `str()` UUID values before JSON serialization.

**Connection safety:** `conn.fetch()` results must be consumed inside the `async with get_connection()` block. Assigning outside risks `NameError` if `fetch()` raises.

## Invariants

- No table that records a market event may have rows deleted or updated in place.
- `intelligence_features`, `signal_ledger`, and `llm_calls` have no retention policies — ever.
- All timestamps stored as `timestamptz` (UTC). `datetime.now(UTC)` only — never `datetime.now()` or `datetime.utcnow()`.
- DB queries use `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`. Plain `psql -U postgres` fails (no socket auth).

## Recipe

When designing time-series storage for a new system:

1. **Choose a time-series native DB** — TimescaleDB, InfluxDB, QuestDB. Generic SQL is a poor fit.
2. **Identify immutable event tables vs. mutable state tables** — different retention and access patterns.
3. **Never drop historical signal data** — today's noise is tomorrow's training sample.
4. **Design the schema around queries** — time-range queries and point lookups have different optimal layouts.
5. **Separate hot state from cold storage** — real-time systems should not query the DB on the hot path (see `hot-path-isolation.md`).
6. **Timestamp discipline from day one** — all timestamps UTC, stored as `timestamptz`, ISO-8601 with Z suffix in JSON.

## See Also

- Operations: `docs/operations/operations-database.md` — asyncpg patterns, connection gotchas
- Related concept: `docs/concepts/hot-path-isolation.md` — why DB is on the cold path only
- Data layer: `docs/data/data-foundation.md` — table schemas, hypertable configuration
