---
phase: 140-ic-engine-correctness
plan: P1
type: execute
wave: 1
depends_on: []
files_modified:
  - production/migrations/171_ic_correctness.sql
autonomous: true

must_haves:
  truths:
    - "feature_ic_scores has a nullable cluster_id SMALLINT column"
    - "config_state has alpha.ensemble.meta_fdr_min_fraction = 0.50"
    - "config_state has alpha.ic.cluster_max_corr = 0.70"
    - "config_state alpha.ic.sharpe_min_windows is updated from 10 to 30"
  artifacts:
    - path: "production/migrations/171_ic_correctness.sql"
      provides: "cluster_id column + 2 new APR keys + sharpe_min_windows update"
      contains: "cluster_id"
  key_links:
    - from: "production/migrations/171_ic_correctness.sql"
      to: "config_state / config_schema"
      via: "INSERT ... ON CONFLICT DO NOTHING + UPDATE"
      pattern: "alpha.ic.cluster_max_corr"
---

<objective>
Author and apply migration 171, the single schema + APR change that unblocks both P1 statistical fixes (collinearity clustering and the meta-FDR gate) and raises the IC Sharpe reliability floor.

Purpose: The clustering work (P2 plan) needs a `cluster_id` column and the `alpha.ic.cluster_max_corr` threshold; the ensemble meta-FDR gate (P3 plan) needs `alpha.ensemble.meta_fdr_min_fraction`; and Issue 5 raises `alpha.ic.sharpe_min_windows` from 10 (SE≈0.32) to 30 (SE≈0.18). All four are one migration.

Output: `production/migrations/171_ic_correctness.sql`, applied to the live database.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/140-ic-engine-correctness/140-RESEARCH.md
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Write and apply migration 171 (cluster_id column + APR keys)</name>
  <read_first>
    - production/migrations/170_feature_factory_workers_apr.sql (canonical config_schema + config_state INSERT pattern with ON CONFLICT DO NOTHING)
    - production/migrations/169_hmm_parallelism_apr_keys.sql (multi-key APR migration example)
    - .planning/phases/140-ic-engine-correctness/140-RESEARCH.md ("Schema Changes" section — exact column comment, APR key table, and sharpe_min_windows UPDATE)
    - CLAUDE.md (APR mandate — every numeric value lives in config_state with provenance tag in description)
  </read_first>
  <action>
    Create `production/migrations/171_ic_correctness.sql` with these statements (in order):

    1. Schema column — add nullable cluster_id to feature_ic_scores:
       ```sql
       ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS cluster_id SMALLINT NULL;
       COMMENT ON COLUMN feature_ic_scores.cluster_id IS
           'Correlation cluster ID for this (symbol, tf, regime, training_window_end) run. '
           'Cluster representative has the highest |ic_value| within cluster. '
           'Non-representatives have passes_fdr=false. NULL for pre-Phase-140 rows.';
       ```

    2. New APR key `alpha.ensemble.meta_fdr_min_fraction` (float, default 0.50). Follow the 170 pattern:
       INSERT into config_schema (config_key, value_type, default_value, min_value, max_value, description)
       with value_type 'float', min 0.0, max 1.0, and description:
       `'[initial_estimate] Minimum fraction of (symbol, tf) cells in which a feature must pass BH-FDR before it is eligible for ensemble weight. Guards meta-level false discovery across the 232-cell universe. Candidate ML learning target.'`
       Then INSERT into config_state (config_key, config_value, version) VALUES (..., '0.50', 1)
       ON CONFLICT (config_key) DO NOTHING. (Both INSERTs use ON CONFLICT DO NOTHING.)

    3. New APR key `alpha.ic.cluster_max_corr` (float, default 0.70). config_schema value_type 'float',
       min 0.0, max 1.0, description:
       `'[initial_estimate] Correlation distance threshold for hierarchical clustering of features before BH-FDR. Features with pairwise correlation >= this value cluster together; only the cluster representative receives multiple-testing correction. Candidate ML learning target.'`
       config_state value '0.70', version 1, ON CONFLICT DO NOTHING for both.

    4. Update existing key `alpha.ic.sharpe_min_windows` from 10 to 30:
       ```sql
       UPDATE config_state SET config_value = '30', updated_at = NOW()
       WHERE config_key = 'alpha.ic.sharpe_min_windows';
       ```
       (Verify the config_state table has an `updated_at` column by checking migration 170 / config history
       conventions; if writes are tracked via config_history, also INSERT a config_history row with
       changed_by='migration_171' and reason='Raise IC Sharpe reliability floor: SE 0.32->0.18 (Phase 140 Issue 5)'.
       Read the config_history schema before writing this — match its exact column set. If config_state writes
       are auto-mirrored to config_history by trigger, skip the manual history INSERT.)

    Wrap the whole migration in a single transaction (BEGIN; ... COMMIT;) only if the other migrations do so —
    match the existing convention in 170/169.

    Apply the migration:
    `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/171_ic_correctness.sql`
  </action>
  <verify>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_ic_scores" | grep cluster_id` shows `cluster_id | smallint`
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "SELECT config_key, config_value FROM config_state WHERE config_key IN ('alpha.ensemble.meta_fdr_min_fraction','alpha.ic.cluster_max_corr','alpha.ic.sharpe_min_windows') ORDER BY config_key"` returns: `alpha.ensemble.meta_fdr_min_fraction|0.50`, `alpha.ic.cluster_max_corr|0.70`, `alpha.ic.sharpe_min_windows|30`
  </verify>
  <acceptance_criteria>
    - Artifact: `production/migrations/171_ic_correctness.sql` exists.
    - Behavior: `\d feature_ic_scores` shows a nullable `cluster_id smallint` column with the documented comment.
    - Behavior: config_state row `alpha.ensemble.meta_fdr_min_fraction` = `0.50`.
    - Behavior: config_state row `alpha.ic.cluster_max_corr` = `0.70`.
    - Behavior: config_state row `alpha.ic.sharpe_min_windows` = `30` (was `10`).
    - Source: re-running the migration is idempotent (ADD COLUMN IF NOT EXISTS, ON CONFLICT DO NOTHING, idempotent UPDATE).
  </acceptance_criteria>
  <done>cluster_id column exists; the two new APR keys are seeded; sharpe_min_windows is 30. P2 and P3 plans can now read these.</done>
</task>

</tasks>

<verification>
- Migration file exists and applies cleanly with no errors
- All four DB assertions in the task verify block pass
- Migration is idempotent (safe to re-run)
</verification>

<success_criteria>
- feature_ic_scores.cluster_id column present (nullable SMALLINT)
- alpha.ensemble.meta_fdr_min_fraction = 0.50, alpha.ic.cluster_max_corr = 0.70 seeded
- alpha.ic.sharpe_min_windows raised to 30
</success_criteria>

<output>
After completion, create `.planning/phases/140-ic-engine-correctness/140-P1-SUMMARY.md`
</output>
