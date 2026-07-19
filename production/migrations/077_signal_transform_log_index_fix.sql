-- Migration 077: Fix signal_transform_log unique index for TimescaleDB
--
-- idx_stl_identity was a UNIQUE index on (signal_id, transform_id, transform_version)
-- without the partitioning column (ts). TimescaleDB requires the partition key in
-- every unique index, so this index could not be enforced across chunks. Replaced
-- with a non-unique index that supports the evaluation query access pattern.

DROP INDEX IF EXISTS idx_stl_identity;

CREATE INDEX IF NOT EXISTS idx_stl_signal_transform
    ON signal_transform_log (signal_id, transform_id, transform_version);
