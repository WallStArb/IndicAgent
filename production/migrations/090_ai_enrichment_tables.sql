-- Migration 090: AI Enrichment Tables — AI-SEP-01 (Phase 70)
-- Idempotent: safe to re-apply.
--
-- Creates two AI-owned enrichment tables that decouple AI/ML annotations from
-- the quant tables (signal_ledger, intelligence_features). Quant tables remain
-- pure and immutable after initial write — AI enrichment is written separately.
--
-- Also adds features_snapshot JSONB column to signal_ledger so the ML training
-- query can read per-signal _shadow dicts from a flat column rather than
-- traversing the i7 JSONB signals array.
--
-- Tables created:
--   signal_ai_enrichment         — AI-owned swarm + ML annotations per signal
--   intelligence_ai_enrichment   — AI-owned i8 narrative annotations per bar
--
-- Column added:
--   signal_ledger.features_snapshot JSONB   — ML training flat feature source
--
-- NOTE on FK constraint: signal_ledger is a TimescaleDB hypertable with a composite
-- PK (signal_id, timestamp). TimescaleDB does not support unique indexes on a subset
-- of partitioning columns, so a declarative FK REFERENCES signal_ledger(signal_id)
-- cannot be enforced at the DB constraint level. Referential integrity is enforced
-- at the application layer (signal_writer_agent populates both tables atomically).
-- The logical relationship is: signal_ai_enrichment.signal_id → signal_ledger(signal_id)

-- signal_ai_enrichment: AI-owned swarm + ML annotations for signals
-- Logical FK: signal_id → REFERENCES signal_ledger(signal_id)
-- (TimescaleDB hypertable partitioning prevents declarative FK on signal_id alone)
CREATE TABLE IF NOT EXISTS signal_ai_enrichment (
    signal_id           UUID        PRIMARY KEY,
    swarm_multiplier    FLOAT,
    adjusted_confidence FLOAT,
    swarm_agent_count   INT,
    ml_score            FLOAT,
    ml_model_id         UUID,
    enriched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Logical constraint documentation (enforced at application layer):
--   signal_ai_enrichment.signal_id REFERENCES signal_ledger(signal_id)

-- intelligence_ai_enrichment: AI-owned i8 narrative annotations for bar rows
-- Primary key mirrors intelligence_features (ts, symbol, tf) for LEFT JOIN reads
CREATE TABLE IF NOT EXISTS intelligence_ai_enrichment (
    ts           TIMESTAMPTZ NOT NULL,
    symbol       TEXT        NOT NULL,
    tf           TEXT        NOT NULL,
    i8           JSONB,
    narrative_id UUID,
    enriched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts, symbol, tf)
);

-- features_snapshot: flat ML training feature source — populated at INSERT time
-- by signal_writer_agent.py from signal['features_snapshot'] (_shadow dict).
-- NULL for legacy rows predating migration 084. Reads must handle NULL.
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS features_snapshot JSONB;
