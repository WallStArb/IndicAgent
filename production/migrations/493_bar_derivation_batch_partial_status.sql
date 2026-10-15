-- 493: bar_derivation_batch.status gains 'partial' (D-191-O, todo 535 item 40;
-- docs/plans/2026-10-12-unified-raw-bar-table-design.md).
--
-- Per-name isolation: a derivation run where some names failed or were refused and others wrote
-- closes partial, not failed, so the record says the other names' writes stand. failed now means
-- names failed and none wrote.
BEGIN;
ALTER TABLE bar_derivation_batch DROP CONSTRAINT bar_derivation_batch_status_check;
ALTER TABLE bar_derivation_batch ADD CONSTRAINT bar_derivation_batch_status_check
    CHECK (status = ANY (ARRAY['running'::text, 'completed'::text, 'partial'::text, 'failed'::text]));
COMMIT;
