-- Migration 377: annotate family 1's E16 evidence records as biased toward zero
-- (methodology-change-ledger E17, condition 4; todo 432).
--
-- Family 1's four member evidence runs (spec b828c285, code 531da089d, 2026-09-25) were scored
-- with E16's timing statistic as built. For a member built from its own cell's recent returns
-- that statistic is biased under H0 toward negative t (the causal cell mean it subtracts
-- contains the returns that built the weight), so the recorded t (13.5 to 18.6) is biased
-- toward zero: the detection stands, the magnitudes understate it. research_run rows are
-- immutable (trg_research_run_guard), so the annotation lives on each member concept.
-- Idempotent: re-running inserts nothing.

BEGIN;

INSERT INTO concept_annotation (concept_id, annotation_type, content, source)
SELECT c.concept_id,
       'observation',
       'Evidence run under spec b828c285 (code 531da089d, 2026-09-25) used the E16 timing '
       'statistic as built, which is biased toward negative t for own-history members '
       '(methodology-change-ledger E17, todo 432). Its recorded t is biased toward zero: the '
       'detection stands, the magnitude is understated. Its sub-period, bootstrap and null-shape '
       'diagnostics are also defective (np.median over shifts, fixed 562a031c9).',
       'empirical'
FROM concept_registry c
WHERE c.name IN (
        'member.intraday_periodicity.same_slot_lag1',
        'member.intraday_periodicity.same_slot_mean5',
        'member.intraday_periodicity.same_slot_mean20',
        'member.intraday_periodicity.same_slot_mean40'
      )
  AND NOT EXISTS (
        SELECT 1 FROM concept_annotation a
        WHERE a.concept_id = c.concept_id
          AND a.content LIKE 'Evidence run under spec b828c285%E16 timing statistic%'
      );

COMMIT;
