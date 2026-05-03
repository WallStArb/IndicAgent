-- Phase 79: Signal quality fix
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS signal_schema_version text DEFAULT 'v0';
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS entry_type text;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_count int DEFAULT 1;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS co_fire_partners text[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_ledger_schema_version ON signal_ledger (signal_schema_version) WHERE signal_schema_version = 'v1';
