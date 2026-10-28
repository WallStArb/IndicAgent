-- Migration 535: genesis_seed transition rows for the 11 HMM columns migration 533 registered
-- (187-12 review). Every governed feature has one (migration 284 wrote hmm_entropy's); without
-- it the transition log has no origin entry for these columns. Like 284's, it establishes the
-- status at registration time without fabricating a promotion event.

BEGIN;

INSERT INTO concept_transition_log
    (concept_id, domain, name, from_status, to_status, trigger_reason, notes)
SELECT r.concept_id, r.domain, r.name, 'candidate', 'active', 'genesis_seed',
       'Registered by migration 533 (phase 187-12, todo 459). Establishes the incumbent status '
       'at registration time without fabricating a promotion event.'
FROM concept_registry r
WHERE r.domain = 'feature' AND r.metadata->>'registered_by' = 'migration_533'
  AND NOT EXISTS (SELECT 1 FROM concept_transition_log t WHERE t.concept_id = r.concept_id);

COMMIT;
