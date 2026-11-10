-- Migration 586: Massive admission step 1, the schema (todo 600; admission design
-- docs/plans/2026-11-10-massive-admission-db-design.md section 8 step 1).
--
-- What lands, and nothing else:
--   1. CVR: bar_vendor `massive`; bar_kind `sip_flat_agg`, `sip_flat`, `sip_flat_adj`
--      (design section 3 and 5; glossary entries landed in a79093763).
--   2. corporate_action.inferred_by gains `massive_reference` (design section 5: the split
--      reconciliation against Massive's splits endpoint records under its own code). The live
--      CHECK was read first (2026-11-10): seam_audit, nightly_overlap, tradier_refetch,
--      operator, calendar_audit; this keeps all five.
--   3. reference_raw: every vendor reference answer as served (design section 6).
--   4. security_identifier and ticker_event: the ticker to entity map (design section 6).
--   5. definition_epoch: dated changes of a vendor column's meaning (design section 7), seeded
--      with the one measured epoch.
--
-- Decided here, against the design text (reasons in the admission step 1 report):
--   - No APR key infra.massive.artifact_max_answer_lag_days. Every archive file's LastModified
--     (servetimes_*.jsonl, measured 2026-11-10) is either 2026-03-30 (5,673 files, a vendor
--     regeneration: lags up to 8,238 days, median 4,009) or 1.1 to 1.6 days after its session
--     (156 files since 2026-04). A bound that admits the archive must exceed its oldest file's
--     age and grow by a day each day, so it can never refuse a legitimate file. The Alpaca bound
--     guards against a rewritten file's mtime posing as a serve time; Massive's answered_at is
--     the vendor's LastModified joined on ETag, which a rewrite or copy cannot move. The checks
--     that remain are definitions, not tunables: LastModified after the file's session, at or
--     before our download, and the manifest-to-servetimes ETag join (design section 4).
--   - No issuer table. Design section 6 rules that CIK never decides a mapping (one CIK spans
--     BRK.A and BRK.B), so no stage 1 reader exists; the CIK of every active ticker is already
--     stored as served in reference_raw (overview and events bodies), and a security's issuer
--     changes over time (a holding-company reorganisation issues a new CIK), so the link is a
--     dated table of its own. It belongs to stage 2, where SEC identifiers for dead names make
--     CIK decisive.
--
-- Mutation rule shared by security_identifier, ticker_event and definition_epoch: a row is
-- immutable once inserted; the only update retires it (retired_at stamped by the trigger,
-- retired_reason required). A correction or a close retires the row and inserts its
-- replacement in the same transaction, so every assertion keeps its recorded_at and the
-- overlap constraints hold among unretired rows (the bar_source_policy grammar with one
-- mutation instead of two). DELETE and TRUNCATE raise. reference_raw is insert only.
--
-- No compressed hypertable is touched (no VACUUM is owed). Idempotent.

BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- 1. CVR codes. sort_order is the within-vendor selection precedence (lowest wins,
-- selection.py): the reader's regular-hours aggregate ranks above the served day file should a
-- 1d slot ever hold both (design section 3 builds 1d from one or the other, never both).
INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES
    ('bar_vendor', 'massive', 'Massive',
     'Massive flat files: consolidated SIP minute and day aggregates, unadjusted, from 2003-09-10 (Alpaca-served SIP stays alpaca)', 5),
    ('bar_kind', 'sip_flat_agg', 'sip_flat_agg',
     'Massive minute aggregates cut to the NYSE regular session and aggregated by our reader (5m; 1d if the day file fails the day-against-minute check), unadjusted', 13),
    ('bar_kind', 'sip_flat', 'sip_flat',
     'Massive day aggregate as served, unadjusted (1d)', 14),
    ('bar_kind', 'sip_flat_adj', 'sip_flat_adj',
     'Split-adjusted canonical row selected from Massive raw (canonical only, never in ohlcv_raw)', 15)
ON CONFLICT (namespace, code) DO NOTHING;

-- 2. corporate_action.inferred_by.
ALTER TABLE corporate_action DROP CONSTRAINT IF EXISTS corporate_action_inferred_by_check;
ALTER TABLE corporate_action
    ADD CONSTRAINT corporate_action_inferred_by_check
    CHECK (inferred_by IN ('seam_audit', 'nightly_overlap', 'tradier_refetch', 'operator',
                           'calendar_audit', 'massive_reference'));

-- 3. reference_raw.
CREATE TABLE IF NOT EXISTS reference_raw (
    reference_raw_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor text NOT NULL CHECK (vendor ~ '^[a-z][a-z0-9_]*$'),
    endpoint text NOT NULL CHECK (endpoint <> ''),
    request_key text NOT NULL CHECK (request_key <> ''),
    page integer NOT NULL CHECK (page >= 1),
    as_of date NULL,
    url text NOT NULL,
    http_status smallint NOT NULL CHECK (http_status BETWEEN 100 AND 599),
    body jsonb NOT NULL,
    served_at timestamptz NOT NULL,
    manifest_path text NOT NULL,
    manifest_line integer NOT NULL CHECK (manifest_line >= 1),
    file_path text NOT NULL,
    file_sha256 text NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_reference_raw_manifest_line UNIQUE (manifest_path, manifest_line),
    CONSTRAINT uq_reference_raw_one_capture_per_manifest
        UNIQUE (vendor, endpoint, request_key, page, manifest_path)
);

COMMENT ON TABLE reference_raw IS
    'Every vendor reference answer as served (migration 586, admission design section 6), one '
    'row per stored response file. vendor is a CVR bar_vendor code; endpoint and request_key '
    'are the capture''s own labels (request_key keeps the capture''s disambiguator, e.g. A@active '
    'or AABA@2019-10-07, because a reused ticker is two requests); page is 1-based; as_of is the '
    'date the request asked about (NULL: the vendor''s state at served_at). http_status and body '
    'are as served, a NOT_FOUND answer included; readers judge the body''s status, never the HTTP '
    'status alone. served_at is the vendor''s HTTP Date header, or the capture timestamp where '
    'the capture recorded none (capture_log.jsonl); either is at or after the true answer, the '
    'safe side for availability. Lineage: manifest_path and manifest_line (repo-relative; the '
    'path also tells the layout: capture_log.jsonl or the canonical dated manifest/YYYYMMDD.jsonl), '
    'file_path and file_sha256 (the manifest''s hash of the stored file, which holds the exact '
    'bytes; jsonb normalises key order and number spelling). Every answer enters through a '
    'capture file and its manifest line, an IBKR capture included; a manifest file holds one '
    'capture of a request, so a re-capture writes a new manifest file (a second capture in the '
    'same file is refused, never merged). Insert only, last-wins by '
    'served_at per request through reference_raw_current. Single writer: the admission reference '
    'loader (step 3).';

CREATE INDEX IF NOT EXISTS idx_reference_raw_request
    ON reference_raw (vendor, endpoint, request_key, served_at DESC);

CREATE OR REPLACE FUNCTION reference_raw_append_only()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is insert only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$;

DROP TRIGGER IF EXISTS trg_reference_raw_append_only ON reference_raw;
CREATE TRIGGER trg_reference_raw_append_only
    BEFORE UPDATE OR DELETE ON reference_raw
    FOR EACH ROW EXECUTE FUNCTION reference_raw_append_only();

DROP TRIGGER IF EXISTS trg_reference_raw_no_truncate ON reference_raw;
CREATE TRIGGER trg_reference_raw_no_truncate
    BEFORE TRUNCATE ON reference_raw
    FOR EACH STATEMENT EXECUTE FUNCTION reference_raw_append_only();

-- The current answer to a request is every page of its latest capture: per-page last-wins
-- would keep a stale trailing page when a later capture of a paged list is shorter. A capture
-- is (request, manifest_path), unique per page by uq_reference_raw_one_capture_per_manifest.
CREATE OR REPLACE VIEW reference_raw_current AS
WITH latest AS (
    SELECT DISTINCT ON (vendor, endpoint, request_key)
           vendor, endpoint, request_key, manifest_path
      FROM reference_raw
     ORDER BY vendor, endpoint, request_key, served_at DESC, manifest_path DESC
)
SELECT r.*
  FROM reference_raw r
  JOIN latest l USING (vendor, endpoint, request_key, manifest_path);

COMMENT ON VIEW reference_raw_current IS
    'The latest capture of each (vendor, endpoint, request_key): all its pages (migration 586).';

-- Shared trigger for the retire-only tables below.
CREATE OR REPLACE FUNCTION retire_once_append_only()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.retired_at IS NOT NULL OR NEW.retired_reason IS NOT NULL THEN
            RAISE EXCEPTION '%: a row is retired by an update, never inserted retired',
                TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.retired_at IS NOT NULL THEN
            RAISE EXCEPTION '%: the row is retired and immutable', TG_TABLE_NAME
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.retired_reason IS NULL OR btrim(NEW.retired_reason) = '' THEN
            RAISE EXCEPTION '%: the only update retires a row and names retired_reason',
                TG_TABLE_NAME USING ERRCODE = 'check_violation';
        END IF;
        IF (to_jsonb(NEW) - 'retired_at' - 'retired_reason')
           IS DISTINCT FROM (to_jsonb(OLD) - 'retired_at' - 'retired_reason') THEN
            RAISE EXCEPTION '%: a retirement changes only retired_at and retired_reason '
                '(retire the row and insert its replacement)', TG_TABLE_NAME
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.retired_at := now();
        RETURN NEW;
    END IF;
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$;

COMMENT ON FUNCTION retire_once_append_only() IS
    'Retire-only guard (migration 586): inserts arrive unretired, the one update stamps '
    'retired_at and sets retired_reason, nothing else changes, DELETE and TRUNCATE raise.';

-- 4a. security_identifier.
CREATE TABLE IF NOT EXISTS security_identifier (
    security_identifier_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    scheme text NOT NULL
        CHECK (scheme IN ('share_class_figi', 'composite_figi', 'isin', 'cusip')),
    value text NOT NULL,
    valid_from date NOT NULL,
    valid_to date NULL,
    reference_raw_id uuid NOT NULL REFERENCES reference_raw(reference_raw_id),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    retired_at timestamptz NULL,
    retired_reason text NULL,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK ((retired_at IS NULL) = (retired_reason IS NULL)),
    CONSTRAINT ck_security_identifier_value_format CHECK (
        CASE scheme
            WHEN 'isin' THEN value ~ '^[A-Z]{2}[0-9A-Z]{9}[0-9]$'
            WHEN 'cusip' THEN value ~ '^[0-9A-Z*@#]{8}[0-9]$'
            ELSE value ~ '^[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]$'
        END
    ),
    CONSTRAINT uq_security_identifier_id_symbol UNIQUE (security_identifier_id, symbol),
    CONSTRAINT ex_security_identifier_one_value EXCLUDE USING gist (
        symbol WITH =, scheme WITH =, daterange(valid_from, valid_to, '[)') WITH &&
    ) WHERE (retired_at IS NULL),
    CONSTRAINT ex_security_identifier_one_security EXCLUDE USING gist (
        scheme WITH =, value WITH =, daterange(valid_from, valid_to, '[)') WITH &&
    ) WHERE (retired_at IS NULL)
);

COMMENT ON TABLE security_identifier IS
    'Dated external identifiers of a security, the instrument row (migration 586, admission '
    'design section 6): [valid_from, valid_to) per scheme, valid_from the earliest date the '
    'cited answer supports. Among unretired rows a security holds one value per scheme at a '
    'time and a value names one security at a time, so two instruments claiming one FIGI or '
    'ISIN fail loudly. composite_figi is a scheme because the events bodies carry only it, the '
    'join key across a ticker chain; it never stands in for share_class_figi, the matching key. '
    'Issuer identifiers (CIK, LEI) are not security identifiers. reference_raw_id is the answer '
    'that asserts the row. Retire-only (retire_once_append_only). Single writer: the admission '
    'reference loader (step 3).';

DROP TRIGGER IF EXISTS trg_security_identifier_append_only ON security_identifier;
CREATE TRIGGER trg_security_identifier_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON security_identifier
    FOR EACH ROW EXECUTE FUNCTION retire_once_append_only();

DROP TRIGGER IF EXISTS trg_security_identifier_no_truncate ON security_identifier;
CREATE TRIGGER trg_security_identifier_no_truncate
    BEFORE TRUNCATE ON security_identifier
    FOR EACH STATEMENT EXECUTE FUNCTION retire_once_append_only();

CREATE OR REPLACE VIEW security_identifier_current AS
SELECT * FROM security_identifier WHERE retired_at IS NULL;

COMMENT ON VIEW security_identifier_current IS
    'Unretired security_identifier rows (migration 586); readers go through it.';

-- 4b. ticker_event.
CREATE TABLE IF NOT EXISTS ticker_event (
    ticker_event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    security_identifier_id uuid NOT NULL,
    symbol text NOT NULL,
    vendor text NOT NULL CHECK (vendor IN ('massive')),
    ticker text NOT NULL CHECK (ticker ~ '^\S+$'),
    valid_from date NOT NULL,
    valid_to date NULL,
    reference_raw_id uuid NOT NULL REFERENCES reference_raw(reference_raw_id),
    evidence jsonb NOT NULL CHECK (evidence <> '{}'::jsonb),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    retired_at timestamptz NULL,
    retired_reason text NULL,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK ((retired_at IS NULL) = (retired_reason IS NULL)),
    CONSTRAINT fk_ticker_event_security_identifier FOREIGN KEY (security_identifier_id, symbol)
        REFERENCES security_identifier (security_identifier_id, symbol),
    CONSTRAINT ex_ticker_event_one_security EXCLUDE USING gist (
        vendor WITH =, ticker WITH =, daterange(valid_from, valid_to, '[)') WITH &&
    ) WHERE (retired_at IS NULL),
    CONSTRAINT ex_ticker_event_one_ticker EXCLUDE USING gist (
        vendor WITH =, symbol WITH =, daterange(valid_from, valid_to, '[)') WITH &&
    ) WHERE (retired_at IS NULL)
);

COMMENT ON TABLE ticker_event IS
    'Dated span of one vendor ticker string on one security (migration 586, admission design '
    'section 6): [valid_from, valid_to), the security_identifier it resolves to (symbol carried '
    'for the overlap rule and pinned to the identifier''s own symbol by the composite foreign '
    'key), reference_raw_id (the events answer that asserts the span) and the evidence (the '
    'other answers cited, the identifier match, the price continuity verdict by level over the '
    'span). vendor is the CVR bar_vendor code whose ticker vocabulary this is (massive only in '
    'stage 1; a new vocabulary widens the CHECK). An unretired span always resolves to an '
    'unretired identifier: a span cannot be inserted against a retired one, and an identifier '
    'with unretired spans cannot be retired (retire the spans first). Among unretired rows a ticker names one security at a time and a security has one '
    'ticker at a time, so one vendor row can never load under two instruments. A Massive row is '
    'loaded into ohlcv_raw only inside an unretired span, and the load detail records the '
    'ticker_event_id; retiring a span is the trigger for the mapping retract path. Retire-only '
    '(retire_once_append_only). Single writer: the admission reference loader (step 3).';

DROP TRIGGER IF EXISTS trg_ticker_event_append_only ON ticker_event;
CREATE TRIGGER trg_ticker_event_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON ticker_event
    FOR EACH ROW EXECUTE FUNCTION retire_once_append_only();

DROP TRIGGER IF EXISTS trg_ticker_event_no_truncate ON ticker_event;
CREATE TRIGGER trg_ticker_event_no_truncate
    BEFORE TRUNCATE ON ticker_event
    FOR EACH STATEMENT EXECUTE FUNCTION retire_once_append_only();

-- An unretired span resolves only to an unretired identifier, from both sides.
CREATE OR REPLACE FUNCTION ticker_event_identity_unretired()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'ticker_event' THEN
        IF EXISTS (SELECT 1 FROM security_identifier
                    WHERE security_identifier_id = NEW.security_identifier_id
                      AND retired_at IS NOT NULL) THEN
            RAISE EXCEPTION 'ticker_event: security_identifier % is retired',
                NEW.security_identifier_id USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.retired_reason IS NOT NULL AND OLD.retired_at IS NULL
          AND EXISTS (SELECT 1 FROM ticker_event
                       WHERE security_identifier_id = OLD.security_identifier_id
                         AND retired_at IS NULL) THEN
        RAISE EXCEPTION 'security_identifier %: unretired ticker_event spans resolve to it; '
            'retire them first', OLD.security_identifier_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ticker_event_identity_unretired ON ticker_event;
CREATE TRIGGER trg_ticker_event_identity_unretired
    BEFORE INSERT ON ticker_event
    FOR EACH ROW EXECUTE FUNCTION ticker_event_identity_unretired();

DROP TRIGGER IF EXISTS trg_security_identifier_spans_unretired ON security_identifier;
CREATE TRIGGER trg_security_identifier_spans_unretired
    BEFORE UPDATE ON security_identifier
    FOR EACH ROW EXECUTE FUNCTION ticker_event_identity_unretired();

CREATE OR REPLACE VIEW ticker_event_current AS
SELECT * FROM ticker_event WHERE retired_at IS NULL;

COMMENT ON VIEW ticker_event_current IS
    'Unretired ticker_event spans (migration 586); the loader and selection read through it.';

-- 5. definition_epoch.
CREATE TABLE IF NOT EXISTS definition_epoch (
    definition_epoch_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor text NOT NULL CHECK (vendor ~ '^[a-z][a-z0-9_]*$'),
    column_name text NOT NULL
        CHECK (column_name IN ('timestamp', 'open', 'high', 'low', 'close', 'volume')),
    effective_from date NOT NULL,
    meaning text NOT NULL CHECK (btrim(meaning) <> ''),
    evidence jsonb NOT NULL CHECK (evidence <> '{}'::jsonb),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    retired_at timestamptz NULL,
    retired_reason text NULL,
    CHECK ((retired_at IS NULL) = (retired_reason IS NULL))
);

COMMENT ON TABLE definition_epoch IS
    'Dated change in what a vendor column means (migration 586, admission design section 7): '
    'from effective_from (the first session of the new meaning) the column means `meaning`. '
    'Never a data correction (that is a revision). The loader tags loads with the epoch they '
    'fall in; feature code that must not mix definitions reads it. Retire-only '
    '(retire_once_append_only). Written by migrations only: each epoch is a measured fact with '
    'its evidence.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_definition_epoch_current
    ON definition_epoch (vendor, column_name, effective_from) WHERE retired_at IS NULL;

DROP TRIGGER IF EXISTS trg_definition_epoch_append_only ON definition_epoch;
CREATE TRIGGER trg_definition_epoch_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON definition_epoch
    FOR EACH ROW EXECUTE FUNCTION retire_once_append_only();

DROP TRIGGER IF EXISTS trg_definition_epoch_no_truncate ON definition_epoch;
CREATE TRIGGER trg_definition_epoch_no_truncate
    BEFORE TRUNCATE ON definition_epoch
    FOR EACH STATEMENT EXECUTE FUNCTION retire_once_append_only();

CREATE OR REPLACE VIEW definition_epoch_current AS
SELECT * FROM definition_epoch WHERE retired_at IS NULL;

COMMENT ON VIEW definition_epoch_current IS
    'Unretired definition_epoch rows (migration 586).';

-- The one measured epoch. Counted 2026-11-10 over the archived files: 2026-02-20 serves no
-- volume with a decimal point (day 0 of 11,868 rows, minute 0 of 1,805,890); 2026-02-23 serves
-- every volume with six decimals (day 11,788 of 11,788, minute 1,828,017 of 1,828,017), a
-- non-zero fraction on day 10,188 and minute 531,165 rows. The 23/5 SIP session (2026-12-06)
-- is not seeded: it is an announced future change, recorded by its own migration once a served
-- file shows it.
INSERT INTO definition_epoch (vendor, column_name, effective_from, meaning, evidence)
SELECT 'massive', 'volume', DATE '2026-02-23',
       'Volume is served in fractional shares (six decimals) in the minute and day files from '
       'this session; earlier sessions serve whole shares. ohlcv_raw.volume stays bigint: the '
       'reader rounds half to even once per stored bar (after summing minutes into a bucket); '
       'the fractional values stay in the archived files.',
       jsonb_build_object(
           'measured', '2026-11-10',
           'design', 'docs/plans/2026-11-10-massive-admission-db-design.md sections 4 and 7',
           'last_whole_share_session', jsonb_build_object(
               'day_aggs_v1/2026/02/2026-02-20.csv.gz', jsonb_build_object('rows', 11868, 'decimal_rows', 0),
               'minute_aggs_v1/2026/02/2026-02-20.csv.gz', jsonb_build_object('rows', 1805890, 'decimal_rows', 0)
           ),
           'first_fractional_session', jsonb_build_object(
               'day_aggs_v1/2026/02/2026-02-23.csv.gz',
                   jsonb_build_object('rows', 11788, 'decimal_rows', 11788, 'nonzero_fraction_rows', 10188),
               'minute_aggs_v1/2026/02/2026-02-23.csv.gz',
                   jsonb_build_object('rows', 1828017, 'decimal_rows', 1828017, 'nonzero_fraction_rows', 531165)
           )
       )
WHERE NOT EXISTS (
    SELECT 1 FROM definition_epoch
     WHERE vendor = 'massive' AND column_name = 'volume' AND effective_from = DATE '2026-02-23'
);

COMMIT;
