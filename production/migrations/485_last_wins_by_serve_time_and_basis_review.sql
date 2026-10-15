-- Migration 485: last-wins by serve time, the basis-change review queue, detector v2
-- (phase 191, fourth review of plan 191-07; D-191-N)
--
-- 1. ohlcv_revision gains origin 'superseded': a vendor offer older than the stored row's serve
--    time (an artifact replay, a late page) does not replace raw; the offered value is logged
--    under the offering load and request instead. The 80 offers the one-time release
--    (logs/pending_release_191_apply.json, release false) logged as origin raw are relabeled,
--    so the origin alone tells a displaced value from a superseded offer.
-- 2. ohlcv_load.n_superseded counts those offers per load.
-- 3. ohlcv_restatement_flag gains reviewed_by; a flag carrying a basis-change signature
--    (price_ratio, volume_ratio, time_shift) with reviewed_at NULL makes the selection gate fail
--    and the D7 gauge ohlcv_restatement_unreviewed_basis_flags nonzero. reviewed_at and
--    reviewed_by are set together (scripts/ops/bars/ops_restatement_review.py).
-- 4. Detector v2 APR (src/intelligence/bars/restatement.py): robust price multiple, volume
--    multiple, cent rounding; signature_min_bars 20 -> 5 and flag_min_stored 500 -> 78 so a
--    one-session 5m overlap is judged.
-- 5. bar_session_choice.n_grid_slots NULL on a 5m row records a calendar mismatch.
--
-- The origin constraint is swapped NOT VALID then validated (3.9M rows, no long exclusive lock).

BEGIN;

SET LOCAL lock_timeout = '10s';

ALTER TABLE ohlcv_revision DROP CONSTRAINT ohlcv_revision_origin_check;
ALTER TABLE ohlcv_revision ADD CONSTRAINT ohlcv_revision_origin_check
    CHECK (origin = ANY (ARRAY['load'::text, 'archive_segment'::text, 'raw'::text,
                               'superseded'::text])) NOT VALID;

UPDATE ohlcv_revision r SET origin = 'superseded'
  FROM (VALUES
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T16:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T16:20:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T16:35:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T16:40:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T16:50:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T17:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T17:20:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T17:50:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T18:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T18:30:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T18:55:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T19:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('898c4a50-ed50-494f-839f-ddbf4fdaaec7'::uuid, 'ADM', '5m', '2026-10-12T19:55:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:00:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:25:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:35:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:40:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:45:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T16:50:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T17:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T17:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T17:45:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T17:55:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T18:00:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T18:30:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T18:55:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T19:00:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T19:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T19:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T19:25:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('04f17062-072c-4247-8c72-927d4eb8648f'::uuid, 'AEP', '5m', '2026-10-12T19:50:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T16:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T16:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T16:35:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T17:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T17:25:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T17:30:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T17:45:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T18:00:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T18:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T18:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T18:25:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T18:40:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T18:50:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('59097ead-1058-497f-8b8d-441dd918fc12'::uuid, 'AMT', '5m', '2026-10-12T19:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('86c21967-454c-4d4b-93ef-1c6b4d10c745'::uuid, 'AMZN', '5m', '2026-10-12T16:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('86c21967-454c-4d4b-93ef-1c6b4d10c745'::uuid, 'AMZN', '5m', '2026-10-12T16:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('86c21967-454c-4d4b-93ef-1c6b4d10c745'::uuid, 'AMZN', '5m', '2026-10-12T17:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('86c21967-454c-4d4b-93ef-1c6b4d10c745'::uuid, 'AMZN', '5m', '2026-10-12T18:20:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('86c21967-454c-4d4b-93ef-1c6b4d10c745'::uuid, 'AMZN', '5m', '2026-10-12T19:05:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('86c21967-454c-4d4b-93ef-1c6b4d10c745'::uuid, 'AMZN', '5m', '2026-10-12T19:45:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T16:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T16:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T16:40:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T16:45:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T17:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T17:45:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T17:50:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T18:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T18:25:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T18:30:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T19:00:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('49aa4190-e593-4a9a-b261-6241ceb1bbc8'::uuid, 'ASML', '5m', '2026-10-12T19:15:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T16:00:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T16:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T16:35:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T16:40:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T16:55:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T17:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T17:20:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T17:50:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T18:10:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T18:25:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T18:35:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T18:45:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T18:55:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T19:35:00+00:00'::timestamptz, 'ibkr', 'named'),
    ('4e945cfd-7a9e-4b6a-abc9-69af742ad399'::uuid, 'BA', '5m', '2026-10-12T19:40:00+00:00'::timestamptz, 'ibkr', 'named')
  ) AS s(load_id, symbol, timeframe, ts, vendor, kind)
 WHERE r.load_id = s.load_id AND r.symbol = s.symbol AND r.timeframe = s.timeframe
   AND r."timestamp" = s.ts AND r.vendor = s.vendor AND r.kind = s.kind AND r.origin = 'raw';

DO $$
BEGIN
    IF (SELECT count(*) FROM ohlcv_revision WHERE origin = 'superseded') <> 80 THEN
        RAISE EXCEPTION 'expected exactly the 80 superseded release offers';
    END IF;
END $$;

COMMENT ON COLUMN ohlcv_revision.origin IS
    'raw: a value a later serve displaced (load_id = the replacing load, request_id = the old '
    'answer). superseded: an offer older than the stored row''s serve time, never written to raw '
    '(load_id and request_id = the offer). load and archive_segment: pre-191 history. '
    'Migration 485.';

ALTER TABLE ohlcv_load ADD COLUMN IF NOT EXISTS n_superseded integer NOT NULL DEFAULT 0
    CHECK (n_superseded >= 0);
COMMENT ON COLUMN ohlcv_load.n_superseded IS
    'Offered rows older than the stored row''s serve time: logged as superseded revisions, raw '
    'unchanged (last-wins by serve time). Migration 485.';

ALTER TABLE ohlcv_restatement_flag ADD COLUMN IF NOT EXISTS reviewed_by text;
ALTER TABLE ohlcv_restatement_flag ADD CONSTRAINT ohlcv_restatement_flag_review_check
    CHECK ((reviewed_at IS NULL) = (reviewed_by IS NULL));
CREATE INDEX IF NOT EXISTS idx_ohlcv_restatement_flag_unreviewed
    ON ohlcv_restatement_flag (symbol, timeframe) WHERE reviewed_at IS NULL;
COMMENT ON COLUMN ohlcv_restatement_flag.reviewed_at IS
    'Set with reviewed_by and review_note by scripts/ops/bars/ops_restatement_review.py. A flag '
    'with a basis-change signature and no review fails the selection gate. Migration 485.';

COMMENT ON COLUMN bar_session_choice.n_grid_slots IS
    'The calendar''s regular-hours slots of the session. NULL on a timeframe with a grid (5m): '
    'the calendar grid does not apply, because no ranked vendor holds a stamp on it (IBKR opened '
    '14:30 UTC on 2006-12-27 where the calendar says 14:32) or the date is no NYSE session; '
    'completeness is then judged on the vendors'' own slots. Migration 485.';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.bar_integrity.restatement_ratio_min_share',
        'float', '0.8', 0, 1,
        '[initial_estimate] price_ratio and volume_ratio signatures: share of the changed bars '
        'that must agree with the median new/old multiple, so a few unrelated corrected bars in '
        'the same re-serve do not hide a split. Reporting and review only (D-191-N). Not an ML '
        'learning target.'
    ),
    (
        'threshold.bar_integrity.restatement_ratio_min_move',
        'float', '0.002', 0, 1,
        '[initial_estimate] price_ratio signature: the median price multiple must differ from 1 '
        'by more than this (and by more than two ticks on the typical price). Not an ML '
        'learning target.'
    ),
    (
        'threshold.bar_integrity.restatement_price_tick',
        'float', '0.01', 0, 1,
        '[conventional] The price grid vendor answers are rounded to (US equities quote in cents '
        'above 1 dollar): the price_ratio test allows the rounding of both answers. Not an ML '
        'learning target.'
    ),
    (
        'threshold.bar_integrity.restatement_volume_tolerance',
        'float', '0.01', 0, 1,
        '[initial_estimate] volume_ratio signature: relative distance of a changed bar''s volume '
        'from the median multiple, plus one unit of the coarser volume grid. Not an ML learning '
        'target.'
    ),
    (
        'threshold.bar_integrity.restatement_volume_min_move',
        'float', '0.2', 0, 100,
        '[initial_estimate] volume_ratio signature: the median volume multiple must differ from 1 '
        'by more than this; routine late-print revisions move volume by a few percent and vary '
        'by bar. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.restatement_ratio_min_share', '0.8', 1),
    ('threshold.bar_integrity.restatement_ratio_min_move', '0.002', 1),
    ('threshold.bar_integrity.restatement_price_tick', '0.01', 1),
    ('threshold.bar_integrity.restatement_volume_tolerance', '0.01', 1),
    ('threshold.bar_integrity.restatement_volume_min_move', '0.2', 1)
ON CONFLICT (config_key) DO NOTHING;

-- Retuned seeds: a one-session overlap (78 5m bars) is judged.
UPDATE config_schema SET default_value = '78', description =
    '[rca_analysis] Stored rows a load must overlap before its changed share (the informational '
    'share signature) is judged: one regular 5m session, so the nightly overlap is judged '
    '(fourth review of 191-07; was 500). Basis signatures never wait on it. Not an ML learning '
    'target.'
 WHERE config_key = 'threshold.bar_integrity.restatement_flag_min_stored';
UPDATE config_schema SET default_value = '5', description =
    '[rca_analysis] Changed bars a load needs before a basis-change signature (price_ratio, '
    'volume_ratio, time_shift) is tested; low enough for a short 1d overlap (fourth review of '
    '191-07; was 20). Not an ML learning target.'
 WHERE config_key = 'threshold.bar_integrity.restatement_signature_min_bars';
UPDATE config_schema SET description =
    '[initial_estimate] price_ratio signature: relative distance of each changed price from the '
    'median new/old multiple, on top of the cent rounding of both answers. Not an ML learning '
    'target.'
 WHERE config_key = 'threshold.bar_integrity.restatement_ratio_tolerance';

UPDATE config_state SET config_value = '78', version = version + 1
 WHERE config_key = 'threshold.bar_integrity.restatement_flag_min_stored' AND config_value = '500';
UPDATE config_state SET config_value = '5', version = version + 1
 WHERE config_key = 'threshold.bar_integrity.restatement_signature_min_bars' AND config_value = '20';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:485',
       'fourth review of 191-07, finding 3: detector judges a one-session overlap'
  FROM config_state s
 WHERE s.config_key IN (
           'threshold.bar_integrity.restatement_ratio_min_share',
           'threshold.bar_integrity.restatement_ratio_min_move',
           'threshold.bar_integrity.restatement_price_tick',
           'threshold.bar_integrity.restatement_volume_tolerance',
           'threshold.bar_integrity.restatement_volume_min_move',
           'threshold.bar_integrity.restatement_flag_min_stored',
           'threshold.bar_integrity.restatement_signature_min_bars'
       )
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:485'
   );

COMMIT;

ALTER TABLE ohlcv_revision VALIDATE CONSTRAINT ohlcv_revision_origin_check;
