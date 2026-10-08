-- 461: held names, void rows on corporate_action and the split recognition rule (phase 185
-- plan 51, todo 515).
--
-- The 189-10 refresh's in-process overlap judge recorded every constant rescale as a split:
-- CTVA's 39/7 restatement after the Vylor spin-off (company record: one VYLR per CTVA,
-- distribution 2026-10-01) became a split row, and ETHA's one 1-for-3 reverse split (effective
-- 2026-10-06, Nasdaq ECA2026-713) holds two rows at wrong dates. No sanctioned path could
-- retract or correct a row.
--
-- 1. corporate_action stays append-only. A void row (action_type void, inferred_by operator)
--    supersedes the row it retracts; corporate_action_current hides superseded and void rows.
--    By-hand corrections are inferred_by operator (scripts/ops/bars/ops_split_detect.py
--    --supersede, --void, --hold-rescale). A row is superseded at most once.
-- 2. bar_hold: the one definition of a held name. A name is held for a timeframe while
--    bar_hold_current has a row for it; the daily stage skips it (no rewrite is applied), the
--    overlap judge does not hold the same rescale twice, D7 reports it. One writer:
--    services/bar_hold.py under bar_derivation_writer. Append-only; a release is a new row
--    whose releases names the hold. Reason today: unclassified_rescale, a constant vendor
--    rescale whose factor is no recognised split ratio.
-- 3. APR infra.backfill.split_ratio_*: a factor is a split only when it or its inverse is p/q
--    within a relative tolerance, q and p capped. Real splits are small integer ratios (2:1,
--    3:2, 5:4, 4:1, 1:3, 1:20); 39/7 is not. The numerator cap equals infer_split's snap bound
--    (50); the tolerance equals threshold.seam.rel_tol (0.002), the constancy a seam already
--    needs. Measured on the two events: CTVA 5.5711 is 1.3 % from 11/2, rejected; ETHA 1/3
--    exact. Known limit: a rescale that lands within the tolerance of a small ratio passes
--    (Tradier's CTVA factor 6.665 is 0.025 % from 20/3).
-- Idempotent: constraints are dropped and re-added, objects created IF NOT EXISTS or replaced,
-- seeds ON CONFLICT DO NOTHING, history rows written once.

BEGIN;

-- 1. corporate_action: void rows and operator corrections.
ALTER TABLE corporate_action DROP CONSTRAINT IF EXISTS corporate_action_action_type_check;
ALTER TABLE corporate_action
    ADD CONSTRAINT corporate_action_action_type_check
    CHECK (action_type IN ('split', 'reverse_split', 'void'));

ALTER TABLE corporate_action DROP CONSTRAINT IF EXISTS corporate_action_inferred_by_check;
ALTER TABLE corporate_action
    ADD CONSTRAINT corporate_action_inferred_by_check
    CHECK (inferred_by IN ('seam_audit', 'nightly_overlap', 'tradier_refetch', 'operator'));

ALTER TABLE corporate_action DROP CONSTRAINT IF EXISTS ck_corporate_action_void_supersedes;
ALTER TABLE corporate_action
    ADD CONSTRAINT ck_corporate_action_void_supersedes
    CHECK (action_type <> 'void' OR supersedes IS NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS uq_corporate_action_supersedes
    ON corporate_action (supersedes) WHERE supersedes IS NOT NULL;

CREATE OR REPLACE VIEW corporate_action_current AS
SELECT ca.*
FROM corporate_action ca
WHERE ca.action_type <> 'void'
  AND NOT EXISTS (
    SELECT 1 FROM corporate_action newer WHERE newer.supersedes = ca.action_id
);

COMMENT ON VIEW corporate_action_current IS
    'corporate_action rows that no later row supersedes, void rows excluded (migrations 400, 461).';

COMMENT ON TABLE corporate_action IS
    'Append-only record of splits and reverse splits (migration 400, D-21/D-24). factor is '
    'stored/fresh on the old scale (2.0 = 2-for-1, 0.125 = 1-for-8); effective_date is the last '
    'day on the old scale. evidence_request_ids name the ohlcv_request rows behind the record. '
    'Permanent: UPDATE, DELETE and TRUNCATE raise; corrections are new rows with supersedes, a '
    'void row retracts the row it supersedes (migration 461), inferred_by operator marks a '
    'by-hand correction (ops_split_detect.py).';

-- 2. bar_hold.
CREATE TABLE IF NOT EXISTS bar_hold (
    hold_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    timeframe text NOT NULL CHECK (timeframe = '1d'),
    reason text NOT NULL CHECK (reason IN ('unclassified_rescale', 'release')),
    factor double precision NULL
        CHECK (factor IS NULL OR (factor > 0 AND factor <> 'Infinity' AND factor <> 'NaN')),
    first_affected_date date NULL,
    last_affected_date date NULL,
    action_id uuid NULL REFERENCES corporate_action(action_id),
    detail jsonb NOT NULL DEFAULT '{}',
    recorded_by text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    releases uuid NULL REFERENCES bar_hold(hold_id),
    CONSTRAINT ck_bar_hold_release CHECK ((reason = 'release') = (releases IS NOT NULL)),
    CONSTRAINT ck_bar_hold_rescale CHECK (
        reason <> 'unclassified_rescale'
        OR (factor IS NOT NULL AND first_affected_date IS NOT NULL
            AND last_affected_date IS NOT NULL AND first_affected_date <= last_affected_date)
    ),
    CONSTRAINT ck_bar_hold_detail_object CHECK (jsonb_typeof(detail) = 'object')
);

COMMENT ON TABLE bar_hold IS
    'Held names (migration 461, plan 185-51): a name is held for a timeframe while '
    'bar_hold_current has a row for it, and its canonical bars stay as they are. Reason '
    'unclassified_rescale: a constant vendor rescale whose factor is no recognised split ratio '
    '(never a corporate_action row). The daily stage skips held names, D7 reports them. One '
    'writer: services/bar_hold.py under bar_derivation_writer. Append-only; a release is a new '
    'row whose releases names the hold.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_bar_hold_releases
    ON bar_hold (releases) WHERE releases IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bar_hold_symbol ON bar_hold (symbol, timeframe);

DROP TRIGGER IF EXISTS trg_bar_hold_append_only ON bar_hold;
CREATE TRIGGER trg_bar_hold_append_only
    BEFORE UPDATE OR DELETE ON bar_hold
    FOR EACH ROW
    EXECUTE FUNCTION corporate_action_append_only();

DROP TRIGGER IF EXISTS trg_bar_hold_no_truncate ON bar_hold;
CREATE TRIGGER trg_bar_hold_no_truncate
    BEFORE TRUNCATE ON bar_hold
    FOR EACH STATEMENT
    EXECUTE FUNCTION corporate_action_append_only();

CREATE OR REPLACE VIEW bar_hold_current AS
SELECT h.*
FROM bar_hold h
WHERE h.reason <> 'release'
  AND NOT EXISTS (SELECT 1 FROM bar_hold r WHERE r.releases = h.hold_id);

COMMENT ON VIEW bar_hold_current IS
    'Open holds: bar_hold rows that are not releases and that no release names (migration 461).';

GRANT INSERT, SELECT ON bar_hold TO bar_derivation_writer;
GRANT SELECT ON bar_hold_current TO bar_derivation_writer;
REVOKE UPDATE, DELETE, TRUNCATE ON bar_hold FROM PUBLIC;

-- 3. The split recognition rule.
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.backfill.split_ratio_max_numerator', 'int', '50', 2, 1000,
 '[initial_estimate] Largest numerator of a recognised split ratio p/q (the larger term of the ratio read as a number above 1, so 20 for 1-for-20). A constant overlap rescale is recorded as a split or reverse_split only when its factor or the inverse is p/q within infra.backfill.split_ratio_rel_tol with p and q under their caps; otherwise the name is held as an unclassified rescale (services/bar_hold.py, plan 185-51). Equal to the snap bound of infer_split. Not an ML learning target.'),
('infra.backfill.split_ratio_max_denominator', 'int', '4', 1, 50,
 '[initial_estimate] Largest denominator of a recognised split ratio p/q (3-for-2 has 2, 5-for-4 has 4). Real splits are small integer ratios; the CTVA spin-off rescale of 2026-10-08 (39/7) was recorded as a split under the snap bound alone (todo 515). Not an ML learning target.'),
('infra.backfill.split_ratio_rel_tol', 'float', '0.002', 0.00001, 0.05,
 '[initial_estimate] Relative distance between a measured overlap rescale factor and p/q within which it is a recognised split ratio. Equal to threshold.seam.rel_tol, the constancy a seam already needs; measured: ETHA 1-for-3 exact, CTVA 5.5711 is 1.3 percent from 11/2. A rescale within this distance of a small ratio still passes. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.backfill.split_ratio_max_numerator', '50', 1),
    ('infra.backfill.split_ratio_max_denominator', '4', 1),
    ('infra.backfill.split_ratio_rel_tol', '0.002', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration_461',
       'Initial value [initial_estimate]: split recognition rule (plan 185-51, todo 515)'
  FROM config_state s
 WHERE s.config_key IN ('infra.backfill.split_ratio_max_numerator',
                        'infra.backfill.split_ratio_max_denominator',
                        'infra.backfill.split_ratio_rel_tol')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = s.config_key AND h.changed_by = 'migration_461');

COMMIT;
