# Temporal Data Architecture

**Version:** 2.0
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** time-series, immutability, timescaledb, data-retention

> Every market event is a timestamped, immutable record — nothing is dropped, everything is queryable by time.

> **Rewritten for v3.0 (2026-09-04):** The prior version cited `intelligence_features` and
> `signal_events`/`trade_frames`/`trade_executions`/`signal_ledger` (v2.x, no live consumer
> since 2026-07-02) as the primary durable hypertables. The table list below now reflects the
> live v3.0 pipeline (`feature_vectors` → `forward_returns` → `alpha_frames`/`alpha_events`).
> The underlying principle — append-only, no retention policy, never UPDATE a row that recorded
> something that happened — is unchanged.

## The Problem It Solves

Generic relational databases treat time as just another column. This leads to: slow range queries requiring full-table scans, no native compression for time-series data, schema designs that mix mutable state with immutable events, and lost history when records are updated in-place. For a quantitative system where every historical signal is a labeled training sample, these are fatal flaws.

## The Principle

Time-series data has a natural append-only structure — events happen, are recorded, and never change. A temporal data architecture exploits this:

1. **Hypertables** — partition data automatically by time. Range queries hit only the relevant partitions.
2. **Compression** — time-ordered data compresses at 10-20x versus row-store. Old data costs nearly nothing.
3. **Immutable events** — never UPDATE a row that represents something that happened. Corrections are new rows.
4. **No retention policies** — storage is the cheapest resource. Every data point is a potential training sample.

## How IndicAgent Applies It

TimescaleDB (PostgreSQL extension) is used for all time-series tables. Primary hypertables in the live v3.0 pipeline:

| Table | Time column | Purpose |
|-------|-------------|---------|
| `market_data_ohlcv` | `timestamp` | Raw OHLCV bars — read via `market_data_ohlcv_tradeable` view (`volume > 0`) for compute/measurement; the raw table is a continuous calendar grid with synthetic-fill/flat-carry-forward placeholder rows |
| `feature_vectors` | (bar timestamp) | Atomic Feature Factory output — one row per symbol/timeframe/bar, written by `FeatureVectorWriter` |
| `forward_returns` | `bar_ts` | Forward-looking executable returns per symbol/tf/bar, written by `forward_return_writer`; `ic_engine` reads this exclusively (`return_type = 'executable_open_to_open'`) |
| `feature_ic_scores` | (per IC-engine run) | Measured IC per feature × symbol × TF × regime × lookahead |
| `alpha_frames` | `bar_ts` | Ensemble/trade-construction output rows, keyed by deterministic `frame_id` (`BaseBatch.content_key`) |
| `alpha_events` | (event ts) | Sole governed emission point — written only by `alpha_publisher` |

**`feature_vectors` is the training dataset foundation.** Every feature is computed and persisted for every bar, unconditionally — there is no upstream detection/suppression step that could introduce execution-selection bias into what gets measured (see `docs/concepts/signal-ledger-architecture.md` for why that matters and how v2.x solved the analogous problem). These tables have no retention policy and never will.

**Connection pattern:** All DB access via `asyncpg` through `src/core/database_manager.py`. JSONB columns return `dict` directly — never call `json.loads()` on asyncpg results. Timestamps return `datetime` objects. Always `str()` UUID values before JSON serialization.

**Connection safety:** `conn.fetch()` results must be consumed inside the `async with get_connection()` block. Assigning outside risks `NameError` if `fetch()` raises.

## Invariants

- No table that records a market event may have rows deleted or updated in place.
- `feature_vectors`, `forward_returns`, `feature_ic_scores`, `alpha_frames`, and `alpha_events` have no retention policies — verified against `timescaledb_information.jobs`. `llm_calls` is the exception: it carries a live 90-day `drop_after` retention policy (verified 2026-09-04) — it is an audit log for prompt A/B testing and back-filled outcomes, not a training corpus, so this table's exemption from the no-retention rule is intentional. Check `timescaledb_information.jobs` per table rather than assuming every hypertable is retention-exempt.
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
