-- Migration 364: Layer 1 security classification schema (Phase 182, todo 384).
--
-- Requirements: D-01 (schema exactly as the design doc), D-02 (scheme shape: explicit
-- parent_code, level, path), D-07 (valid_from/valid_to as-of semantics), D-11 (numbered
-- migration, applied and committed together).
--
-- Three tables only: classification_scheme, classification_node, instrument_classification.
-- The first scheme (indicagent_v1) is project-owned and is NOT GICS -- GICS assignments are
-- licensed data; indicagent_v1's equity levels reuse public GICS sector/industry-group names
-- only, per D-03. No seed rows land here: the scheme, node list and assignments are a later,
-- human-reviewed migration (Plan 03 renders it, Plan 07 applies it).
--
-- Do not add IF NOT EXISTS anywhere in this file: a second apply must fail loudly, not
-- silently no-op.
BEGIN;

CREATE TABLE classification_scheme (
    scheme      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    authority   TEXT NOT NULL,
    source_ref  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (scheme ~ '^[a-z0-9_]+$')
);

COMMENT ON TABLE classification_scheme IS
    'Reference data, migration-seeded. One row per classification scheme (e.g. '
    'indicagent_v1 -- project-owned, not GICS; GICS assignments are licensed data and '
    'this scheme only reuses public GICS sector/industry-group names, per D-03).';

CREATE TABLE classification_node (
    scheme      TEXT     NOT NULL REFERENCES classification_scheme(scheme),
    code        TEXT     NOT NULL,
    parent_code TEXT,
    level       SMALLINT NOT NULL,
    name        TEXT     NOT NULL,
    path        TEXT[]   NOT NULL,
    valid_from  DATE     NOT NULL,
    valid_to    DATE,
    PRIMARY KEY (scheme, code),
    FOREIGN KEY (scheme, parent_code) REFERENCES classification_node(scheme, code),
    CHECK (level >= 1),
    CHECK ((parent_code IS NULL) = (level = 1)),
    CHECK (cardinality(path) = level AND path[cardinality(path)] = code),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

COMMENT ON TABLE classification_node IS
    'Reference data, migration-seeded. One row per node in a classification tree '
    '(scheme, code) -- append-only in effect: parent_code and level are immutable per '
    '(scheme, code); a reparent mints a new code, never an UPDATE of an existing row''s '
    'parent or level (node-immutability invariant, D-01). name may update in place '
    '(display metadata only, no consumer keys on historical node names).';

CREATE TABLE instrument_classification (
    symbol      TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    scheme      TEXT NOT NULL,
    code        TEXT NOT NULL,
    valid_from  DATE NOT NULL,
    valid_to    DATE,
    source_ref  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, scheme, valid_from),
    FOREIGN KEY (scheme, code) REFERENCES classification_node(scheme, code),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);

COMMENT ON TABLE instrument_classification IS
    'Reference data, migration-seeded initially. Membership stores the deepest known '
    'node only; ancestors are derived via classification_node.path. Append-only in '
    'effect: a reclassification closes the prior row (valid_to) and inserts a new row, '
    'never an UPDATE of code on an existing row. symbol has ON DELETE RESTRICT (not '
    'CASCADE): instruments are deactivated, not deleted, and a delete attempt must '
    'crash loudly rather than silently destroy point-in-time classification history.';

-- Exactly one current assignment per (symbol, scheme).
CREATE UNIQUE INDEX uq_instrument_classification_current
    ON instrument_classification (symbol, scheme)
    WHERE valid_to IS NULL;

COMMIT;
