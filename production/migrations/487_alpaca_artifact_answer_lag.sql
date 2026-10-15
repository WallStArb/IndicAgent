-- Migration 487: bound on an Alpaca artifact's answer time against its newest bar
-- (phase 191 plan 10, review of 191-08 finding M2)
--
-- Raw is last-wins by serve time, so an artifact's answer time decides whether it may replace a
-- stored value. The Alpaca pull now writes the time of its last page's answer into the parquet
-- metadata; an older artifact falls back to its file modification time, which a rewrite or a
-- copy moves. ops_bar_load refuses an artifact whose stamp is not after its newest bar, or is
-- later than it by more than this many hours, so a re-stamped old artifact cannot pass as a
-- fresh serve. 120 hours covers a weekend plus a Monday holiday plus a long pull; a name halted
-- longer than that is refused loudly and needs a fresh pull.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'infra.alpaca.artifact_max_answer_lag_hours',
    'float', '120', 1, 2160,
    '[initial_estimate] Largest gap in hours between an Alpaca artifact''s newest bar and its '
    'recorded answer time that ops_bar_load accepts (a weekend plus a holiday plus a long pull). '
    'A larger gap means a rewritten or copied artifact; it is refused. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.alpaca.artifact_max_answer_lag_hours', '120', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:487',
       'seed (phase 191 plan 10: Alpaca artifact answer-time plausibility, review of 08 M2)'
  FROM config_state s
 WHERE s.config_key = 'infra.alpaca.artifact_max_answer_lag_hours'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:487'
   );

COMMIT;
