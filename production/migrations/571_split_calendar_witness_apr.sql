-- Migration 571: the split calendar audit's per-series and share-count witnesses (todo 587).
--
-- ops_split_calendar_audit confirms a calendar split with three independent witnesses: the
-- calendar's clean ratio on its date, canonical's price step by that ratio, and the share count
-- stepping with it (corporate_actions.share_count_step), so a spin-off or stock dividend a calendar
-- writes as a clean ratio (SNX 2020-12-01, Concentrix, written 2:1 by Yahoo) is not recorded as a
-- split. It then measures every raw 1d series with observations before the date on its own (its
-- close over the calendar's split-adjusted close across the date), and the row names each series
-- measured unadjusted; the daily rule (d2-v5) rescales exactly those.
--
-- threshold.split_calendar.witness_sessions: sessions on each side of the date (inside the
-- neighbouring calendar events) the medians run over, for the per-series price ratio and the
-- share count. [rca_analysis] 60: over the 380 price-confirmed splits of 2026-11-04, 20 sessions
-- left SNX's share-count step at 0.83 of log 2 (post-event index flows), 60 at 0.25, 120 at 0.12
-- with 40 splits unmeasurable; 60 is the shortest window that separates the spin-off.
-- threshold.split_calendar.volume_rel_tol: the share-count step must reach (1 - this) of log f in
-- log f's direction (one-sided against the no-split alternative, a step near 0). [conventional]
-- 0.5, the midpoint between the two hypotheses; at 60 sessions it passes 279 of 364 measurable
-- splits (the rest go to review).
-- Neither is an ML learning target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.split_calendar.witness_sessions',
        'int', '60', 5, 250,
        '[rca_analysis] Sessions on each side of a calendar split date (inside the neighbouring calendar events) over which ops_split_calendar_audit takes the median of each raw series'' close over the calendar''s split-adjusted close (the per-series scale) and of the daily volume on canonical''s series (the share-count witness), todo 587. 60 is the shortest window that separates the SNX 2020-12-01 spin-off (2026-11-04). Not an ML learning target.'
    ),
    (
        'threshold.split_calendar.volume_rel_tol',
        'float', '0.5', 0.05, 0.95,
        '[conventional] A calendar split''s share-count witness passes when log(median volume after / before) reaches (1 - this) of log f in log f''s direction (one-sided against a spin-off or stock dividend, whose count does not step), todo 587. 0.5 is the midpoint between the two hypotheses. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.split_calendar.witness_sessions', '60', 1),
    ('threshold.split_calendar.volume_rel_tol', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_571',
       'seed: split calendar witnesses (todo 587)'
  FROM config_state s
 WHERE s.config_key IN ('threshold.split_calendar.witness_sessions',
                        'threshold.split_calendar.volume_rel_tol')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_571'
 );

COMMIT;
