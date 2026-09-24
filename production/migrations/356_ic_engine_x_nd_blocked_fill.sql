-- Migration 356: row-blocked X_nd memmap fill for disk-backed cross-sectional cells (todo 401)
--
-- infra.ic_engine.x_nd_fill_block_rows = 262144 (new, OPERATIONAL). _build_blocked_x_nd now fills
-- a disk-backed cell's row-major X_nd memmap in contiguous row blocks instead of one column at a
-- time. The column-wise fill dirtied every page of the file per column, so under default kernel
-- writeback limits one cell's build wrote about n_nd times the file size (measured 2026-09-24 on
-- equity/5m/high_bear: 710 GB written in 18 minutes for a 9.5 GB X_nd). The copy is exact, so
-- X_nd is byte-identical for any block size and the key is not a fingerprint field. Transient
-- memory is block_rows x n_nd x 4 bytes, about 270 MB at 262144 rows and ~260 features.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.ic_engine.x_nd_fill_block_rows',
    'int',
    '262144',
    1024, 16777216,
    '[rca_analysis] Todo 401: rows per block when ic_engine fills a disk-backed cross-sectional '
    'cell''s X_nd memmap. The copy is exact, so the array is identical for any value '
    '(operational). Transient memory is this times n_nd x 4 bytes. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.ic_engine.x_nd_fill_block_rows', '262144', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_356',
       'Seeded 262144: row-blocked X_nd fill replaces the column-wise fill that rewrote the '
       'whole memmap once per column. Operational. [rca_analysis], todo 401.'
FROM config_state
WHERE config_key = 'infra.ic_engine.x_nd_fill_block_rows';

COMMIT;
