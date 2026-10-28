-- Migration 530: typed concept domains, research CVR namespaces, research stage view
-- (phase 187 plan 11; unified design 10.2, 15.1).
--
-- concept_registry.domain was feature / ensemble_strategy / construction. It becomes one of
-- feature, family, member, combiner, construction_rule, book, method:
--   * construction rows retype by metadata kind (member -> member, family -> family,
--     book_version -> book); the five unkinded deprecated construction rows are old tested
--     verdicts and become family rows.
--   * the five ensemble_strategy rows (ic_proportional, e1_shrunk_ic, e2_mean_variance,
--     e3_hierarchical_pooling, e4_decay_half_life) and their dependents are deleted (design
--     10.2.3), after docs/research/summary-cards/legacy-ensemble-strategy-registry.md records
--     their theses and observations verbatim and the rows were dumped to data/backups/187-11/.
--
-- Counts recorded 2026-10-28 (the migration raises if they differ when it runs):
--   ensemble_strategy: concept_registry 5, concept_gate 5, concept_transition_log 1,
--   concept_annotation 12, concept_evaluation 0, concept_parent edges 0, research_run 0,
--   concept_recipe 0, children by parent_concept_id 0.
--   construction: 11 = member 4 + family 1 + book_version 1 + unkinded 5.
--
-- concept_evaluation's domain CHECK takes the same seven values (it held only feature rows).
-- Two foreign keys had no covering index: research_run.recipe_hash and
-- instrument_classification (scheme, code); both are indexed here.
-- controlled_vocabulary gains research_construction_rule, research_combiner and
-- research_timeframe, which the recipe writer validates against (plan 187-11 Task 2).
-- concept_research_stage derives each concept's research stage; nothing stores it.

BEGIN;

SET LOCAL lock_timeout = '30s';
LOCK TABLE concept_registry, concept_gate, concept_transition_log, concept_evaluation,
    concept_annotation, concept_parent, concept_recipe, research_run
    IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    got record;
BEGIN
    SELECT
        (SELECT count(*) FROM concept_registry WHERE domain = 'ensemble_strategy') AS registry,
        (SELECT count(*) FROM concept_gate g JOIN concept_registry c USING (concept_id)
          WHERE c.domain = 'ensemble_strategy') AS gate,
        (SELECT count(*) FROM concept_transition_log t JOIN concept_registry c USING (concept_id)
          WHERE c.domain = 'ensemble_strategy') AS transition,
        (SELECT count(*) FROM concept_annotation a JOIN concept_registry c USING (concept_id)
          WHERE c.domain = 'ensemble_strategy') AS annotation,
        (SELECT count(*) FROM concept_evaluation e JOIN concept_registry c USING (concept_id)
          WHERE c.domain = 'ensemble_strategy') AS evaluation,
        (SELECT count(*) FROM concept_parent p JOIN concept_registry c
            ON c.concept_id IN (p.child_concept_id, p.parent_concept_id)
          WHERE c.domain = 'ensemble_strategy') AS parent_edges,
        (SELECT count(*) FROM research_run r JOIN concept_registry c USING (concept_id)
          WHERE c.domain = 'ensemble_strategy') AS runs,
        (SELECT count(*) FROM concept_recipe r JOIN concept_registry c USING (concept_id)
          WHERE c.domain = 'ensemble_strategy') AS recipes,
        (SELECT count(*) FROM concept_registry k JOIN concept_registry c
            ON c.concept_id = k.parent_concept_id
          WHERE c.domain = 'ensemble_strategy') AS children,
        (SELECT count(*) FROM concept_registry WHERE domain = 'construction') AS construction,
        (SELECT count(*) FROM concept_registry
          WHERE domain = 'construction' AND metadata ->> 'kind' = 'member') AS members,
        (SELECT count(*) FROM concept_registry
          WHERE domain = 'construction' AND metadata ->> 'kind' = 'family') AS families,
        (SELECT count(*) FROM concept_registry
          WHERE domain = 'construction' AND metadata ->> 'kind' = 'book_version') AS books,
        (SELECT count(*) FROM concept_registry
          WHERE domain = 'construction' AND metadata ->> 'kind' IS NULL
            AND name IN ('alpha_score_residual_single_security_15m', 'bars_since_high_fast_xs_ls_h5',
                         'phase148_alpha_score_directional', 'range_pct_fast_xs_ls_h5',
                         'range_pct_fast_xs_ls_h5_single_name_only')) AS legacy
    INTO got;
    -- A baseline database (the integration test database) holds neither domain: nothing to
    -- reconcile. Any database that has either must match the recorded counts exactly.
    IF (got.registry, got.construction) IS DISTINCT FROM (0, 0)
       AND (got.registry, got.gate, got.transition, got.annotation, got.evaluation,
            got.parent_edges, got.runs, got.recipes, got.children, got.construction,
            got.members, got.families, got.books, got.legacy)
           IS DISTINCT FROM (5, 5, 1, 12, 0, 0, 0, 0, 0, 11, 4, 1, 1, 5) THEN
        RAISE EXCEPTION 'live counts differ from the recorded ones, reconcile before migrating: %',
            got;
    END IF;
END
$$;

-- The ensemble_strategy rows and dependents, children first (backup: data/backups/187-11/).
DELETE FROM concept_annotation WHERE concept_id IN
    (SELECT concept_id FROM concept_registry WHERE domain = 'ensemble_strategy');
DELETE FROM concept_gate WHERE concept_id IN
    (SELECT concept_id FROM concept_registry WHERE domain = 'ensemble_strategy');
DELETE FROM concept_transition_log WHERE concept_id IN
    (SELECT concept_id FROM concept_registry WHERE domain = 'ensemble_strategy');
DELETE FROM concept_registry WHERE domain = 'ensemble_strategy';

-- Typed domains.
ALTER TABLE concept_registry DROP CONSTRAINT concept_registry_domain_check;
ALTER TABLE concept_evaluation DROP CONSTRAINT concept_evaluation_domain_check;

UPDATE concept_registry
   SET domain = CASE metadata ->> 'kind'
                    WHEN 'member' THEN 'member'
                    WHEN 'family' THEN 'family'
                    WHEN 'book_version' THEN 'book'
                END,
       -- The ledger writes metadata kind book from now on; keep one spelling.
       metadata = CASE WHEN metadata ->> 'kind' = 'book_version'
                       THEN jsonb_set(metadata, '{kind}', '"book"') ELSE metadata END
 WHERE domain = 'construction' AND metadata ->> 'kind' IN ('member', 'family', 'book_version');
UPDATE concept_registry
   SET domain = 'family'
 WHERE domain = 'construction'
   AND name IN ('alpha_score_residual_single_security_15m', 'bars_since_high_fast_xs_ls_h5',
                'phase148_alpha_score_directional', 'range_pct_fast_xs_ls_h5',
                'range_pct_fast_xs_ls_h5_single_name_only');

ALTER TABLE concept_registry ADD CONSTRAINT concept_registry_domain_check
    CHECK (domain = ANY (ARRAY['feature', 'family', 'member', 'combiner', 'construction_rule',
                               'book', 'method']));
ALTER TABLE concept_evaluation ADD CONSTRAINT concept_evaluation_domain_check
    CHECK (domain = ANY (ARRAY['feature', 'family', 'member', 'combiner', 'construction_rule',
                               'book', 'method']));

-- Foreign keys that had no covering index.
CREATE INDEX IF NOT EXISTS research_run_recipe_hash_idx ON research_run (recipe_hash);
CREATE INDEX IF NOT EXISTS instrument_classification_scheme_code_idx
    ON instrument_classification (scheme, code);

-- Research CVR namespaces (codes from the construction rules, combiners and timeframes the
-- research specs accept).
INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES
    ('research_construction_rule', 'rank_vol_neutral', 'rank_vol_neutral', 'R1: rank of the forecast, inverse-vol scaled, market-neutral (the discovery rule)', 1),
    ('research_construction_rule', 'vol_normalized', 'vol_normalized', 'Linear in the forecast, inverse vol', 2),
    ('research_construction_rule', 'ic_proportional', 'ic_proportional', 'mu = IC * sigma * z', 3),
    ('research_construction_rule', 'mean_variance', 'mean_variance', 'Sigma^-1 mu with a Ledoit-Wolf covariance', 4),
    ('research_construction_rule', 'fixed_sign', 'fixed_sign', 'Pre-registered direction, inverse vol', 5),
    ('research_combiner', 'ridge', 'ridge', 'Walk-forward ridge over the member stack', 1),
    ('research_combiner', 'equal_weight', 'equal_weight', 'Fixed or in-fold signed mean of member z-scores', 2),
    ('research_combiner', 'pod', 'pod', 'Session-level sum of member books recorded D_s series', 3),
    ('research_timeframe', '5m', '5m', 'Five-minute research panel', 1),
    ('research_timeframe', '15m', '15m', 'Fifteen-minute research panel', 2),
    ('research_timeframe', '1h', '1h', 'Hourly research panel', 3),
    ('research_timeframe', '1d', '1d', 'Daily research panel', 4)
ON CONFLICT DO NOTHING;

-- Research stage (glossary `research stage`): first matching rule wins.
CREATE VIEW concept_research_stage AS
WITH attempts AS (
    SELECT concept_id,
           count(*) AS attempts,
           count(*) FILTER (WHERE status = 'started') AS started,
           count(*) FILTER (WHERE status IN ('completed', 'failed')
                              AND kind <> 'legacy_verdict') AS tested,
           count(*) FILTER (WHERE status IN ('refused', 'guard_failed')) AS refused,
           count(*) FILTER (WHERE kind = 'legacy_verdict') AS legacy,
           max(started_at) AS last_attempt_at
      FROM research_run
     GROUP BY concept_id
), recipes AS (
    SELECT concept_id,
           count(*) AS recipe_versions,
           max(version) AS latest_version,
           max(created_at) AS last_recipe_at
      FROM concept_recipe
     GROUP BY concept_id
)
SELECT c.concept_id, c.domain, c.name, c.status,
       CASE
           WHEN c.domain = 'book' AND c.status = 'active' THEN 'confirmed'
           WHEN c.domain = 'book' AND c.status = 'shadow_only' THEN 'frozen'
           WHEN c.status = 'deprecated' THEN 'refused'
           WHEN coalesce(a.started, 0) > 0 THEN 'registered'
           WHEN coalesce(a.tested, 0) > 0 THEN 'tested'
           -- Refused attempts only, unless a newer recipe reopened the idea.
           WHEN coalesce(a.refused, 0) > 0
                AND NOT coalesce(r.last_recipe_at > a.last_attempt_at, false) THEN 'refused'
           WHEN coalesce(r.recipe_versions, 0) > 0 THEN 'specified'
           WHEN coalesce(a.legacy, 0) > 0 THEN 'refused'
           ELSE 'idea'
       END AS stage,
       coalesce(r.recipe_versions, 0) AS recipe_versions,
       r.latest_version,
       coalesce(a.attempts, 0) AS attempts,
       coalesce(a.started, 0) AS started,
       coalesce(a.tested, 0) AS tested,
       coalesce(a.refused, 0) AS refused,
       coalesce(a.legacy, 0) AS legacy_verdicts
  FROM concept_registry c
  LEFT JOIN attempts a USING (concept_id)
  LEFT JOIN recipes r USING (concept_id);

COMMENT ON VIEW concept_research_stage IS
    'One row per concept: its research stage (idea, specified, registered, tested, refused, '
    'frozen, confirmed), derived from concept_registry, concept_recipe and research_run. '
    'Nothing stores the stage (design 10.2.4).';

COMMIT;
