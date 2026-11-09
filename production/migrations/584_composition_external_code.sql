-- Migration 584: the composition namespace gains the external code (todo 603 step 5)
--
-- External-source features (FINRA short volume, earnings events, macro series, dated
-- market cap, published calendars) fit neither base (a name's own bars or the timestamp
-- alone) nor interaction (built from other features). One code, not two: a published
-- calendar is an external observation with a publication date, so calendar-schedule
-- features are external too and the admission gate checks availability time uniformly
-- (lead ruling 2026-11-09, amending the register doc's two-code proposal).
-- The name `calendar` was rejected: it collides with the legacy concept_registry
-- feature_group `calendar` (glossary `calendar primitive`, todo 116). Existing base and
-- interaction rows are unchanged; nothing recomputes.

BEGIN;

SET LOCAL lock_timeout = '30s';
LOCK TABLE controlled_vocabulary IN SHARE ROW EXCLUSIVE MODE;

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
    ('composition', 'external', 'External',
     'A feature computed from a dated external-source observation joined to the name; '
     'every input carries its availability time', 3);

COMMIT;
