-- Migration 528: vendor_disagreement joins threshold.bar_scrub.quarantine_rules (todo 545, data
-- lane decision 2026-10-28)
--
-- The D-191-Q arbitration lists short spans where IBKR equals Tradier and Alpaca's 1d close is
-- off by more than threshold.bar_scrub.view_disagreement_rel; the policy apply
-- (scripts/ops/bars/ops_source_policy.py --plan) writes each as a bar_quality_flag of rule
-- vendor_disagreement through bar_scrub.write_flags, and refuses unless the rule is in this
-- list. The list only decides the quarantine bit of a flag at the moment it is written: no
-- vendor_disagreement flag exists before the apply, so today's tradeable view is unchanged.
-- Idempotent: re-running appends nothing.

BEGIN;

UPDATE config_state
SET config_value = (config_value::jsonb || '["vendor_disagreement"]'::jsonb)::text,
    version = version + 1
WHERE config_key = 'threshold.bar_scrub.quarantine_rules'
  AND NOT (config_value::jsonb ? 'vendor_disagreement');

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), cs.config_key, cs.version, cs.config_value, 'data_lane',
       'D-191-Q arbitration quarantine: vendor_disagreement flags quarantine a 1d bar (migration 528)'
FROM config_state cs
WHERE cs.config_key = 'threshold.bar_scrub.quarantine_rules'
  AND cs.config_value::jsonb ? 'vendor_disagreement'
  AND NOT EXISTS (
      SELECT 1 FROM config_history ch
      WHERE ch.config_key = cs.config_key AND ch.version = cs.version
        AND ch.changed_by = 'data_lane'
  );

COMMIT;
