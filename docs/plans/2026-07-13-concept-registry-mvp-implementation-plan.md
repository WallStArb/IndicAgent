# Concept Registry MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the four-table Concept Registry MVP (todo 058), seed `domain='ensemble_strategy'` from today's verified live state, and wire `ops_ensemble_weight_compare.py`'s win-decision gate to a narrowly-scoped `ConceptRegistryService` method as the domain's sole deterministic status-flipper (invariant 1).

**Architecture:** Two migrations (231 schema + APR keys, 232 seed data) create `concept_registry` / `concept_gate` / `concept_transition_log` (TimescaleDB hypertable, with `corpus_build_ref` per finding F3) / `concept_annotation`. A new Ring 1 service `src/intelligence/concept_registry_service.py` separates a pure decision function (`decide_comparison_action`, unit-testable without DB) from a transactional async apply method (`record_comparison_outcome`, compare-and-swap status writes per invariant 9). `ops_ensemble_weight_compare.py` gains optional `--challenger-concept` / `--champion-concept` / `--corpus-build-ref` args; without them it behaves exactly as today (report-only).

**Tech Stack:** PostgreSQL/TimescaleDB (raw SQL migrations, applied via psql), asyncpg, structlog, pytest (asyncio_mode=auto; service tests use a hand-rolled FakeConn, no DB).

## Global Constraints

- **Migration numbering:** next free numbers are **231** and **232** (`production/migrations/` currently tops out at `229_regime_group.sql`). If another session lands 231/232 first, renumber to the next free pair and update every reference in this plan's files.
- **Migration application:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f <file>` (plain `psql -U postgres` fails; `-h localhost` is mandatory).
- **APR mandate:** every tunable numeric introduced here is APR-backed (`config_schema` + `config_state` + `config_history` inserts, provenance tag in description). No hard-coded thresholds in `src/` or `services/`.
- **No em dashes** in any new text (docs, comments, commit messages). Use a plain dash, comma, or semicolon. This is a user-global rule.
- **No AI attribution in commits.** Never add `Co-Authored-By: Claude` or "Generated with Claude Code" footers. This user-global rule overrides any harness default.
- **Timestamps:** `datetime.now(UTC)` only; column types `TIMESTAMPTZ`.
- **Logging:** structlog; never pass `event=` as a kwarg. Exception variable name is `error` (`except X as error:`).
- **Unit tests are CI-clean:** no DB, no Kafka. DB behavior is tested through SQL-constant assertions and a FakeConn, mirroring `tests/unit/test_ensemble_weight_compare.py`'s style.
- **Ring rule:** the service lives in `src/intelligence/` (Ring 1 domain code), named per the concept-name derivation rule: concept `concept_registry_service` -> class `ConceptRegistryService`.
- **Done-Coding SOP** applies at the end: code-simplifier pass, review, `pytest tests/unit/ -q` green, feature branch, `--ff-only` merge to main.
- **Scope guard (todo 058 item 1):** do NOT create `concept_gate_template` (reference-architecture only, excluded per F7). Do NOT create `concept_gate_stack`, `concept_eval_run`, or any other reference-architecture table.
- **Scope guard (todo 058 item 7):** do NOT migrate `feature_registry` / `domain='feature'` rows in this work. The `domain` CHECK includes `'feature'` (per the canonical doc's MVP sketch) but zero feature rows are seeded; the migration is a separate follow-on (Task 6 files it as todo 109).

## Verified Live State (2026-07-13, supersedes the todo's stale 2026-07-04 snapshot)

The todo says `ensemble_weights` holds only `weight_version='v1'` (103 rows). **That is no longer true.** Verified against live DB 2026-07-13:

| weight_version | rows | computed_at (max) | what it is |
|---|---|---|---|
| `run_2025122405150000` | 193 | 2026-07-10 | E1 (shrunk-IC input, ic_proportional weighting): APR at run time was `alpha.ensemble.ic_input='ic_shrunk'`, `alpha.ensemble.weight_method='ic_proportional'`, and `alpha.ensemble.weight_version='run_2025122405150000'` (all three verified in live `config_state`) |
| `run_2025122405150000_mv` | 251 | 2026-07-09 | E2 (mean-variance) challenger rows from the 2026-07-09 A/B, produced via `ensemble_trainer --weight-version run_2025122405150000_mv` with the mean-variance method (manifest `.planning/corpus_manifests/ensemble_trainer__run_2025122405150000_mv.json`) |

Key structural fact: **`ensemble_weights` has NO column identifying which E-variant produced a row.** `weight_version` is a per-corpus-build epoch tag (`WEIGHT_EPOCH="run_$(echo "$TRAINING_WINDOW_END" | tr -cd '0-9')"` in `scripts/ops/corpus/ops_corpus_pipeline_run.sh`), and migration 224's header states it explicitly: "weight_version remains a data-scoping tag only." The actual recipe is selected by APR (`alpha.ensemble.ic_input` + `alpha.ensemble.weight_method`) at trainer run time; the `_mv` suffix was a one-off manual convention for the A/B challenger. **Consequence adopted by this plan:** concept identity is never derived from `weight_version` strings. The registry names recipes (`ic_proportional`, `e1_shrunk_ic`, ...), and the compare script is told which registry concept each weight_version corresponds to via explicit CLI args at comparison time.

E3 (hierarchical partial pooling) and E4 (per-feature decay half-lives): **no code exists** (verified: `src/intelligence/ensemble/` contains `shrinkage.py::shrink_ic`, `weights.py::mean_variance_weights`, `covariance.py::compute_shrinkage_covariance`; nothing for partial pooling or per-feature half-lives). The global `alpha.ensemble.weight_half_life_days=30` staleness decay is NOT E4 (it is one global half-life, not per-feature); the seed annotations record this to prevent conflation. E3/E4 remain `candidate` with thesis-only annotations, exactly as the todo assumed.

Status assignments (judgment call, recorded): per the F2 resolution, `status` = recipe validity, deployment = fact elsewhere. No E-variant has ever cleared a formal A/B win (E2's 2026-07-09 rejection, 20/20 strata LOSS, was itself invalidated as an all-long-vs-all-long comparison pre-todo-094; the E1-vs-E2 re-run is sequenced in Phase 143.1). So: `ic_proportional` seeds `active` (genesis incumbent, never evidence-demoted), and `e1_shrunk_ic` seeds `candidate` even though it is the operationally deployed champion-by-default; its deployment is recorded as an `observation` annotation, not as status. E2/E3/E4 seed `candidate`.

## File Structure

- `production/migrations/231_concept_registry_mvp.sql` - four tables + three APR gate keys (create)
- `production/migrations/232_concept_registry_seed_ensemble_strategy.sql` - seed 5 concepts, 5 gate rows, 1 genesis transition, 12 annotations (create)
- `src/intelligence/concept_registry_service.py` - dataclasses, pure decision function, SQL constants, async apply method (create)
- `tests/unit/test_concept_registry_service.py` - pure-logic + SQL-constant + FakeConn tests (create)
- `scripts/ops/alpha/ops_ensemble_weight_compare.py` - new CLI args + `_registry_outcome()` helper + service call (modify)
- `tests/unit/test_ensemble_weight_compare.py` - tests for `_registry_outcome()` (modify)
- `docs/research/concept-unified-registry.md` - invariant-6 exception paragraph + status line (modify)
- `docs/research/concept-governance-registries.md` - status table updates (modify)
- `.planning/todos/pending/109-migrate-feature-domain-into-concept-registry.md` - follow-on todo (create)
- `.planning/todos/completed/058-concept-registry-mvp-seed-ensemble-strategy.md` - moved from pending at the end (move)

---

### Task 1: Migration 231 - schema + APR gate keys

**Files:**
- Create: `production/migrations/231_concept_registry_mvp.sql`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: tables `concept_registry` (PK `concept_id UUID`, `UNIQUE (domain, name)`, `domain CHECK IN ('feature','ensemble_strategy')`, `status CHECK IN ('candidate','shadow_only','active','deprecated')`), `concept_gate` (PK `concept_id`, gate config + folded eval-state cache incl. `baseline_metric`, `promotion_consecutive`, `promotion_eval_metrics DOUBLE PRECISION[]`, `last_eval_corpus_build_ref`, `min_new_observations`, `fdr_required`, `fdr_alpha`), `concept_transition_log` (hypertable on `triggered_at`, PK `(id, triggered_at)`, `corpus_build_ref TEXT`, `trigger_reason` CHECK incl. `'genesis_seed'`), `concept_annotation`. APR keys `alpha.concept_registry.ensemble_strategy_min_promotion_consecutive` (2), `alpha.concept_registry.ensemble_strategy_min_new_observations` (2000), `alpha.concept_registry.ensemble_strategy_min_observations` (1000). Tasks 2-5 depend on these exact table/column names.

- [ ] **Step 1: Create the feature branch**

```bash
cd /home/bg/dev/indicagent
git status --short   # verify no unrelated staged files (shared-dir rule)
git checkout -b feature/todo-058-concept-registry-mvp
```

- [ ] **Step 2: Confirm 231 is still the next free migration number**

Run: `ls /home/bg/dev/indicagent/production/migrations/ | sort -t_ -k1 -n | tail -3`
Expected: last line is `229_regime_group.sql`. If a 231+ file exists, renumber this plan's two migrations to the next free pair and adjust all references.

- [ ] **Step 3: Write the migration file**

Create `production/migrations/231_concept_registry_mvp.sql` with exactly this content:

```sql
-- Migration 231: Concept Registry MVP - four-table schema + APR gate keys (todo 058)
--
-- Builds the Minimal Viable Version from docs/research/concept-unified-registry.md:
-- concept_registry / concept_gate / concept_transition_log / concept_annotation. Deliberately
-- NOT created (reference architecture only, per the canonical doc's "do not build the
-- ten-table version" and cluster-review F7): concept_gate_template, concept_gate_stack,
-- concept_eval_run, concept_eval_state (folded into concept_gate), concept_dependency,
-- concept_regime_ic, concept_correlation.
--
-- MVP deltas vs the canonical doc's sketches, each with provenance:
--   * concept_transition_log.corpus_build_ref (F3): invariant 2's re-evaluation guard needs
--     a corpus identity to compare against, not just triggered_at timestamps. Value is the
--     WEIGHT_EPOCH / CorpusManifest identity (e.g. 'run_2025122405150000'), never invented.
--   * concept_gate.min_new_observations (F3): evidence-mass re-eval floor; re-evaluation is
--     permitted only once >= N new independent observations accrued since the last eval.
--     NULL = inherit the per-domain APR default seeded below.
--   * concept_gate carries the folded eval-state cache (last_eval_*, baseline_metric,
--     decay_ratio, promotion counters) - the MVP merges concept_eval_state into concept_gate,
--     mirroring how feature_registry holds last_ic_* on the registry row today.
--   * concept_gate.promotion_eval_metrics (F8 winner's-curse guard): the gate metric of each
--     consecutive winning evaluation is appended here; at promotion, baseline_metric is the
--     MEAN of this array, never the final (selection-inflated) value.
--   * trigger_reason 'genesis_seed': establishes an incumbent at seeding time without
--     fabricating a promotion event.
--   * concept_transition_log is a TimescaleDB hypertable on triggered_at (canonical doc,
--     2026-07-06 stress-test pass), so its PK must include the partitioning column.
--
-- domain CHECK includes 'feature' per the canonical doc's sketch, but NO feature rows are
-- seeded here (todo 058 item 7): feature_registry stays the live governor for domain='feature'
-- until the follow-on migration item (todo 109) executes.
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, ON CONFLICT DO NOTHING. Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS concept_registry (
    concept_id        UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    domain            TEXT    NOT NULL
        CHECK (domain IN ('feature', 'ensemble_strategy')),
    name              TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'shadow_only', 'active', 'deprecated')),
    enabled           BOOLEAN NOT NULL DEFAULT false,
    parent_concept_id UUID    REFERENCES concept_registry(concept_id),
    redundancy_group  TEXT,
    metadata          JSONB,
    added_phase       TEXT,
    sensitivity       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (domain, name)
);

COMMENT ON TABLE concept_registry IS
    'Unified Concept Registry (Type 2 lifecycle governance) - identity and current status per '
    'research recipe. status = recipe validity; per-stratum deployment stays a fact in domain '
    'fact tables (F2 resolution: ensemble_weights holds per-stratum champions, not this table). '
    'redundancy_group displacement is DISABLED for domain=ensemble_strategy (competing weighting '
    'strategies are the normal state, resolved per stratum by the A/B judge).';

CREATE TABLE IF NOT EXISTS concept_gate (
    concept_id                UUID PRIMARY KEY REFERENCES concept_registry(concept_id),
    gate_metric_name          TEXT NOT NULL,
    gate_eval_method          TEXT NOT NULL
        CHECK (gate_eval_method IN ('oos_holdout', 'walk_forward', 'bootstrap_ci')),
    min_gate_metric           DOUBLE PRECISION,
    min_gate_n                DOUBLE PRECISION,
    min_promotion_consecutive INTEGER,
    min_new_observations      DOUBLE PRECISION,
    demotion_threshold        DOUBLE PRECISION,
    decay_floor               DOUBLE PRECISION,
    regime_scope              TEXT,
    fdr_required              BOOLEAN NOT NULL DEFAULT false,
    fdr_alpha                 DOUBLE PRECISION,
    last_eval_metric          DOUBLE PRECISION,
    last_eval_n               DOUBLE PRECISION,
    last_eval_at              TIMESTAMPTZ,
    last_eval_corpus_build_ref TEXT,
    baseline_metric           DOUBLE PRECISION,
    decay_ratio               DOUBLE PRECISION,
    promotion_consecutive     INTEGER NOT NULL DEFAULT 0,
    promotion_eval_metrics    DOUBLE PRECISION[] NOT NULL DEFAULT '{}',
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE concept_gate IS
    'Per-concept promotion/demotion gate PLUS folded last-eval cache (MVP merges '
    'concept_eval_state here, mirroring feature_registry). min_gate_n and min_new_observations '
    'are EFFECTIVE-N floors (invariant 7): overlapping forward returns are autocorrelated, so '
    'raw bar counts never satisfy them. NULL gate columns inherit the per-domain APR default '
    '(alpha.concept_registry.<domain>_* keys). baseline_metric stores the MEAN of '
    'promotion_eval_metrics at promotion (F8 winner''s-curse guard), never the final eval alone.';

CREATE TABLE IF NOT EXISTS concept_transition_log (
    id               BIGSERIAL,
    concept_id       UUID NOT NULL REFERENCES concept_registry(concept_id),
    domain           TEXT NOT NULL,
    name             TEXT NOT NULL,
    from_status      TEXT NOT NULL,
    to_status        TEXT NOT NULL,
    trigger_reason   TEXT NOT NULL
        CHECK (trigger_reason IN (
            'promotion', 'demotion_performance', 'demotion_decay',
            'demotion_redundancy', 'operator_override', 'parent_cascade',
            'candidate_timeout', 'implementation_change', 'genesis_seed'
        )),
    corpus_build_ref TEXT,
    gate_metric      DOUBLE PRECISION,
    gate_n           DOUBLE PRECISION,
    ci_lower         DOUBLE PRECISION,
    decay_ratio      DOUBLE PRECISION,
    regime_scope     TEXT,
    triggered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes            TEXT,
    PRIMARY KEY (id, triggered_at)
);

COMMENT ON TABLE concept_transition_log IS
    'Immutable append-only state-change audit trail. corpus_build_ref (F3) is the '
    'WEIGHT_EPOCH / CorpusManifest identity the deciding evaluation read from - invariant 2''s '
    're-evaluation guard compares against it. Hypertable on triggered_at (same storage engine '
    'as config_history / llm_calls, this project''s other append-only audit trails).';

SELECT create_hypertable(
    'concept_transition_log',
    'triggered_at',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS concept_transition_log_concept_idx
    ON concept_transition_log (concept_id, triggered_at);

CREATE TABLE IF NOT EXISTS concept_annotation (
    annotation_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id      UUID NOT NULL REFERENCES concept_registry(concept_id),
    annotation_type TEXT NOT NULL CHECK (annotation_type IN (
        'thesis', 'assumption', 'failure_mode', 'observation',
        'open_question', 'implementation', 'reference'
    )),
    content         TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('human', 'ai', 'empirical')),
    confidence      DOUBLE PRECISION CHECK (confidence BETWEEN 0 AND 1),
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS concept_annotation_concept_idx
    ON concept_annotation (concept_id, annotation_type);

COMMENT ON TABLE concept_annotation IS
    'Typed knowledge layer. The gate proves, the annotation explains - never invert: no gate '
    'decision may read annotation content, and no promotion may require an annotation to exist.';

-- APR gate defaults for domain=ensemble_strategy. Per-concept concept_gate columns override
-- these when non-NULL; the service receives them caller-supplied (never hard-coded), same
-- pattern as feature_registry's alpha.feature_registry.min_ic_sharpe_default.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive',
    'int', '2', 1, 10,
    '[initial_estimate] Consecutive winning A/B evaluation rounds required before a candidate '
    'ensemble_strategy concept promotes to active. Set below the canonical doc''s generic '
    'default of 3 because this domain''s per-round bar is already far stronger than a scalar '
    'p<0.05 gate: non-overlapping CIs (challenger ic_ci_lower > champion ic_ci_upper) AND '
    'walk_forward_stable AND BH-FDR survival across strata. ML learning target: no; operator '
    'may tune.'
),
(
    'alpha.concept_registry.ensemble_strategy_min_new_observations',
    'float', '2000', 100, 100000,
    '[conventional] Evidence-mass re-evaluation floor (F3, invariant 2): a concept may not be '
    're-evaluated until >= this many NEW independent observations (sum of n_independent across '
    'compared strata, delta vs the last recorded eval) have accrued. Mirrors '
    'alpha.decay.recovery_min_observations (2000), the identical standard Phase 143 applies to '
    'feature-recovery evidence. Corpus-advance (corpus_build_ref changed) remains a necessary '
    'but insufficient precondition. ML learning target: no.'
),
(
    'alpha.concept_registry.ensemble_strategy_min_observations',
    'float', '1000', 100, 100000,
    '[initial_estimate] Initial-promotion effective-N observation floor (invariant 7): no '
    'promotion fires until the evaluation carries >= this many independent observations, '
    'regardless of statistical significance. Value from the canonical doc''s Domains table '
    'floor for ensemble_strategy (1,000, per-TF fold minimum), stated against effective N '
    '(n_independent), never raw overlapping bars. ML learning target: no.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.concept_registry.ensemble_strategy_min_promotion_consecutive', '2', 1),
('alpha.concept_registry.ensemble_strategy_min_new_observations', '2000', 1),
('alpha.concept_registry.ensemble_strategy_min_observations', '1000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive', 1, '2',
 'migration_231', 'Concept Registry MVP gate seed (todo 058) [initial_estimate]'),
(NOW(), 'alpha.concept_registry.ensemble_strategy_min_new_observations', 1, '2000',
 'migration_231', 'Concept Registry MVP evidence-mass floor seed, mirrors '
 'alpha.decay.recovery_min_observations (todo 058, F3) [conventional]'),
(NOW(), 'alpha.concept_registry.ensemble_strategy_min_observations', 1, '1000',
 'migration_231', 'Concept Registry MVP initial-promotion floor seed (todo 058, invariant 7) '
 '[initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 4: Apply the migration**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -f /home/bg/dev/indicagent/production/migrations/231_concept_registry_mvp.sql
```
Expected output ends with `COMMIT` and contains no `ERROR` lines. (`NOTICE` lines from `IF NOT EXISTS` on re-run are fine.)

- [ ] **Step 5: Verify schema and APR keys**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -c "SELECT to_regclass('concept_registry') IS NOT NULL AS cr,
             to_regclass('concept_gate') IS NOT NULL AS cg,
             to_regclass('concept_transition_log') IS NOT NULL AS ctl,
             to_regclass('concept_annotation') IS NOT NULL AS ca,
             to_regclass('concept_gate_template') IS NULL AS no_template;" \
  -c "SELECT count(*) FROM timescaledb_information.hypertables
      WHERE hypertable_name = 'concept_transition_log';" \
  -c "SELECT config_key, config_value FROM config_state
      WHERE config_key LIKE 'alpha.concept_registry.%' ORDER BY config_key;"
```
Expected: first query all `t`; second query `1`; third query lists exactly the 3 keys with values `2`, `2000`, `1000`.

- [ ] **Step 6: Commit**

```bash
cd /home/bg/dev/indicagent
git status --short   # confirm only the migration file is being staged (shared-dir rule)
git add production/migrations/231_concept_registry_mvp.sql
git commit -m "feat(concept-registry): migration 231 - four-table Concept Registry MVP schema + APR gate keys (todo 058)"
```

---

### Task 2: Migration 232 - seed domain='ensemble_strategy' from verified live state

**Files:**
- Create: `production/migrations/232_concept_registry_seed_ensemble_strategy.sql`

**Interfaces:**
- Consumes: Task 1's tables and CHECK vocabularies (`concept_registry(domain, name, description, status, enabled, metadata, added_phase)`, `concept_gate(concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required, fdr_alpha)`, `concept_transition_log(..., trigger_reason='genesis_seed', corpus_build_ref)`, `concept_annotation(concept_id, annotation_type, content, source)`).
- Produces: 5 `concept_registry` rows with exact names `ic_proportional`, `e1_shrunk_ic`, `e2_mean_variance`, `e3_hierarchical_pooling`, `e4_decay_half_life` (Task 5's CLI examples and Task 4's tests reference these names); 5 `concept_gate` rows; 1 genesis transition; 12 annotations.

- [ ] **Step 1: Write the seed migration**

Create `production/migrations/232_concept_registry_seed_ensemble_strategy.sql` with exactly this content:

```sql
-- Migration 232: seed domain='ensemble_strategy' into the Concept Registry MVP (todo 058)
--
-- Seed data re-derived against live DB 2026-07-13 - the todo's 2026-07-04 snapshot
-- ("only weight_version='v1', 103 rows") is stale. Live state: ensemble_weights holds
-- run_2025122405150000 (193 rows, E1: APR ic_input='ic_shrunk' + weight_method=
-- 'ic_proportional' at run time) and run_2025122405150000_mv (251 rows, E2 mean-variance
-- challenger from the 2026-07-09 A/B). weight_version is a data-scoping epoch tag only
-- (migration 224); no ensemble_weights column identifies the E-variant, so concept identity
-- lives HERE, in metadata->'recipe' (the definitional ic_input/weight_method combination,
-- which is recipe identity like the 5 in momentum_z_5, not a tunable value copy).
--
-- Status semantics (F2 resolution, recorded in concept_registry's table comment):
-- status = recipe validity; per-stratum champions stay facts in ensemble_weights;
-- redundancy_group displacement is disabled for this domain (redundancy_group left NULL).
-- No E-variant has ever cleared a formal A/B win (E2's 2026-07-09 20/20-LOSS result was
-- invalidated as all-long-vs-all-long pre-todo-094; re-run sequenced in Phase 143.1), so
-- ic_proportional seeds active (genesis incumbent) and e1_shrunk_ic seeds candidate even
-- though it is the deployed champion-by-default - deployment is an observation annotation,
-- not a status.
--
-- Invariant-6 exception (todo 058 item 6): E1-E4 are human-authored, so the mandatory
-- shadow_only stage between candidate and active does not bind for this domain the way it
-- would for an AI-sourced concept. The OOS A/B judged by EnsembleICEngine on live corpus
-- runs (per-stratum, non-overlapping-CI win rule, walk-forward-stable veto, BH-FDR
-- corrected, via ops_ensemble_weight_compare.py) is this domain's evidentiary substitute
-- for a live shadow period. Documented in docs/research/concept-unified-registry.md
-- Invariant 6, same pattern as the domain='feature' exception.
--
-- gate rows: gate_eval_method='oos_holdout' (the Domains table's "OOS, via EnsembleICEngine");
-- gate_metric_name='ensemble_ic_ci_lower' (D-15 citation rule: ic_ci_lower, never ic_value);
-- min_gate_metric NULL because the win rule is relative CI ordering vs the champion, not an
-- absolute scalar threshold; min_gate_n=1000 effective observations (invariant 7, Domains
-- floor); min_promotion_consecutive / min_new_observations NULL = inherit the APR defaults
-- seeded by migration 231; fdr_required=true with fdr_alpha NULL = inherit
-- alpha.ensemble.compare_fdr_alpha (the compare script's existing BH-FDR key).
--
-- Idempotent: every INSERT is ON CONFLICT DO NOTHING or guarded by WHERE NOT EXISTS.
-- Safe to re-run.

BEGIN;

INSERT INTO concept_registry (domain, name, description, status, enabled, metadata, added_phase)
VALUES
(
    'ensemble_strategy', 'ic_proportional',
    'v1 incumbent: per-stratum weights proportional to raw HAC IC Sharpe '
    '(alpha.ensemble.ic_input=ic_sharpe_hac, alpha.ensemble.weight_method=ic_proportional).',
    'active', true,
    '{"recipe": {"ic_input": "ic_sharpe_hac", "weight_method": "ic_proportional"}}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e1_shrunk_ic',
    'E1: empirical-Bayes shrunk IC inputs (shrink_ic) feeding ic_proportional weighting '
    '(alpha.ensemble.ic_input=ic_shrunk, alpha.ensemble.weight_method=ic_proportional).',
    'candidate', true,
    '{"recipe": {"ic_input": "ic_shrunk", "weight_method": "ic_proportional"}}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e2_mean_variance',
    'E2: mean-variance weighting (inverse Ledoit-Wolf covariance times shrunk IC vector, '
    'alpha.ensemble.weight_method=mean_variance, condition-number capped).',
    'candidate', true,
    '{"recipe": {"ic_input": "ic_shrunk", "weight_method": "mean_variance"}}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e3_hierarchical_pooling',
    'E3: hierarchical partial pooling of per-stratum IC estimates toward tf/regime-level '
    'hyperpriors before weighting. Thesis only; no shipped mechanism.',
    'candidate', false,
    '{"recipe": null}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e4_decay_half_life',
    'E4: per-feature IC decay half-lives replacing the single global staleness half-life. '
    'Thesis only; no shipped mechanism.',
    'candidate', false,
    '{"recipe": null}'::jsonb,
    'todo-058'
)
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required)
SELECT concept_id, 'ensemble_ic_ci_lower', 'oos_holdout', 1000, true
FROM concept_registry
WHERE domain = 'ensemble_strategy'
ON CONFLICT (concept_id) DO NOTHING;

-- Genesis transition for the incumbent only: establishes ic_proportional as active without
-- fabricating a promotion event. corpus_build_ref NULL - pre-registry incumbency is not
-- attributable to a specific corpus build.
INSERT INTO concept_transition_log
    (concept_id, domain, name, from_status, to_status, trigger_reason, notes)
SELECT concept_id, 'ensemble_strategy', 'ic_proportional', 'candidate', 'active',
       'genesis_seed',
       'Genesis seed (todo 058): incumbent by construction since Phase 139/142A, no formal '
       'promotion event exists. Recipe validity granted by incumbency; deployment has since '
       'moved to e1_shrunk_ic via the alpha.ensemble.ic_input APR flip (a deployment fact, '
       'not a registry demotion).'
FROM concept_registry
WHERE domain = 'ensemble_strategy' AND name = 'ic_proportional'
  AND NOT EXISTS (
      SELECT 1 FROM concept_transition_log t
      WHERE t.domain = 'ensemble_strategy' AND t.name = 'ic_proportional'
        AND t.trigger_reason = 'genesis_seed'
  );

-- Annotations. All source='human' (E1-E4 are human-authored; nothing here was written by
-- the evaluation engine). Idempotency guard: one row per (concept, type, first 40 chars).
INSERT INTO concept_annotation (concept_id, annotation_type, content, source)
SELECT r.concept_id, a.annotation_type, a.content, 'human'
FROM concept_registry r
JOIN (VALUES
    ('ic_proportional', 'thesis',
     'Weighting each eligible feature proportionally to its measured IC strength is the '
     'simplest defensible aggregation: it preserves sign, requires no covariance estimate, '
     'and degrades gracefully when per-feature IC estimates are noisy.'),
    ('ic_proportional', 'implementation',
     'services/ensemble_trainer.py compute path with alpha.ensemble.ic_input=ic_sharpe_hac '
     'and alpha.ensemble.weight_method=ic_proportional; weights derived via derive_weights() '
     'in src/intelligence/ensemble/ with the max_feature_weight cap.'),
    ('ic_proportional', 'observation',
     '2026-07-13: superseded as the deployed default by e1_shrunk_ic via the '
     'alpha.ensemble.ic_input APR flip to ic_shrunk. Remains active in the registry: recipe '
     'validity was never evidence-revoked; deployment is a fact recorded in APR and '
     'ensemble_weights, not in status (F2 resolution).'),
    ('e1_shrunk_ic', 'thesis',
     'Per-feature IC estimates are noisy at stratum grain; empirical-Bayes shrinkage toward '
     'the peer mean (weighted by effective N) reduces estimation variance in the weight '
     'vector, so weights track persistent skill rather than single-window luck.'),
    ('e1_shrunk_ic', 'implementation',
     'src/intelligence/ensemble/shrinkage.py::shrink_ic feeding the ic_proportional path in '
     'services/ensemble_trainer.py; selected by alpha.ensemble.ic_input=ic_shrunk. The '
     'shrunk-IC column in feature_ic_scores is written solely by the gate script.'),
    ('e1_shrunk_ic', 'observation',
     '2026-07-13: deployed operational champion-by-default (live APR: ic_input=ic_shrunk, '
     'weight_method=ic_proportional; live rows weight_version=run_2025122405150000, 193 '
     'rows, computed 2026-07-10). Has NEVER cleared a formal A/B win against '
     'ic_proportional; status stays candidate until the registry gate is earned (the '
     'deployed-vs-proven distinction is exactly what this registry exists to keep honest).'),
    ('e2_mean_variance', 'thesis',
     'IC-proportional weighting ignores feature covariance and so over-allocates to '
     'correlated clusters. Mean-variance combination (inverse shrunk covariance times the '
     'shrunk IC vector) is the portfolio-theoretic optimum under Gaussian assumptions, with '
     'a condition-number cap (alpha.ensemble.mv_condition_max) guarding ill-conditioned '
     'covariance inversions.'),
    ('e2_mean_variance', 'implementation',
     'src/intelligence/ensemble/weights.py::mean_variance_weights over '
     'src/intelligence/ensemble/covariance.py::compute_shrinkage_covariance (Ledoit-Wolf); '
     'selected by alpha.ensemble.weight_method=mean_variance; falls back to ic_proportional '
     'when the condition number exceeds alpha.ensemble.mv_condition_max '
     '(method_used=mean_variance_fallback).'),
    ('e2_mean_variance', 'observation',
     '2026-07-13: the 2026-07-09 A/B vs e1_shrunk_ic (challenger rows weight_version='
     'run_2025122405150000_mv, 251 rows) returned 20/20 strata LOSS, but that result is '
     'INVALIDATED - both sides were all-long pre-todo-094 (sign-symmetric eligibility), so '
     'the comparison does not carry forward. Re-run sequenced in Phase 143.1 after '
     'components 094/097. No transition was or will be logged from the invalidated round.'),
    ('e3_hierarchical_pooling', 'thesis',
     'Per-stratum IC estimates share structure across tf and regime; hierarchical partial '
     'pooling (stratum estimates shrunk toward tf-level and global hyperpriors in '
     'proportion to within-stratum precision) should outperform flat shrinkage when strata '
     'are thin. No code exists; deferred at 142B.1 decision level.'),
    ('e4_decay_half_life', 'thesis',
     'Features decay at different rates; a per-feature IC decay half-life (estimated from '
     'each feature''s own IC time series) should replace any single global staleness '
     'half-life when weighting historical evidence. No code exists; deferred at 142B.1 '
     'decision level.'),
    ('e4_decay_half_life', 'observation',
     '2026-07-13 conflation guard: the live alpha.ensemble.weight_half_life_days=30 key is '
     'a single GLOBAL staleness decay applied in services/ensemble_trainer.py - it is not '
     'E4 and its existence does not make E4 partially shipped.')
) AS a(name, annotation_type, content)
  ON r.domain = 'ensemble_strategy' AND r.name = a.name
WHERE NOT EXISTS (
    SELECT 1 FROM concept_annotation ca
    WHERE ca.concept_id = r.concept_id
      AND ca.annotation_type = a.annotation_type
      AND left(ca.content, 40) = left(a.content, 40)
);

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -f /home/bg/dev/indicagent/production/migrations/232_concept_registry_seed_ensemble_strategy.sql
```
Expected: ends with `COMMIT`, no `ERROR` lines, and the INSERT tags report `INSERT 0 5` (registry), `INSERT 0 5` (gates), `INSERT 0 1` (transition), `INSERT 0 12` (annotations).

- [ ] **Step 3: Verify seed state**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -c "SELECT name, status, enabled FROM concept_registry
      WHERE domain='ensemble_strategy' ORDER BY name;" \
  -c "SELECT count(*) AS gates FROM concept_gate g JOIN concept_registry r USING (concept_id)
      WHERE r.domain='ensemble_strategy';" \
  -c "SELECT name, trigger_reason FROM concept_transition_log
      WHERE domain='ensemble_strategy';" \
  -c "SELECT r.name, a.annotation_type, a.source FROM concept_annotation a
      JOIN concept_registry r USING (concept_id) ORDER BY r.name, a.annotation_type;"
```
Expected: 5 concepts with statuses `e1_shrunk_ic=candidate`, `e2_mean_variance=candidate`, `e3_hierarchical_pooling=candidate`, `e4_decay_half_life=candidate`, `ic_proportional=active`; `gates=5`; one transition row `ic_proportional | genesis_seed`; 12 annotation rows, all `source=human`.

- [ ] **Step 4: Re-run migration 232 to prove idempotency**

Run the same psql `-f` command from Step 2 again.
Expected: all INSERT tags report `INSERT 0 0`; re-running Step 3's counts returns identical results (still 5 / 5 / 1 / 12).

- [ ] **Step 5: Commit**

```bash
cd /home/bg/dev/indicagent
git status --short
git add production/migrations/232_concept_registry_seed_ensemble_strategy.sql
git commit -m "feat(concept-registry): migration 232 - seed domain=ensemble_strategy from 2026-07-13 live state (todo 058)"
```

---

### Task 3: ConceptRegistryService pure decision core

**Files:**
- Create: `src/intelligence/concept_registry_service.py`
- Test: `tests/unit/test_concept_registry_service.py`

**Interfaces:**
- Consumes: nothing from earlier tasks at import time (pure Python; the DB schema from Task 1 defines the column names the dataclasses mirror).
- Produces (Task 4 and Task 5 rely on these exact names):
  - `GateState(status: str, promotion_consecutive: int, promotion_eval_metrics: tuple[float, ...], last_eval_corpus_build_ref: str | None, last_eval_n: float | None, min_promotion_consecutive: int, min_new_observations: float, min_gate_n: float)` frozen dataclass
  - `ComparisonDecision(action: str, new_promotion_consecutive: int, new_promotion_eval_metrics: tuple[float, ...], baseline_metric: float | None)` frozen dataclass
  - `decide_comparison_action(state: GateState, *, won: bool, eval_metric: float | None, eval_n: float, corpus_build_ref: str) -> ComparisonDecision`
  - Action vocabulary (exact strings): `'promote'`, `'record_win'`, `'record_loss'`, `'blocked_same_corpus'`, `'blocked_min_n'`, `'blocked_evidence_floor'`, `'noop_deprecated'`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_concept_registry_service.py`:

```python
"""Unit tests: ConceptRegistryService (todo 058).

decide_comparison_action is the pure invariant-enforcement core: invariant 2
(re-evaluation needs new evidence: corpus-advance precondition + F3 evidence-mass
floor), invariant 7 (initial effective-N floor), F8 (baseline_metric = mean of the
consecutive winning evals, never the final one), and the deprecated-is-operator-only
rule. No DB, no Kafka. Pure Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from src.intelligence.concept_registry_service import (
    ComparisonDecision,
    GateState,
    decide_comparison_action,
)


def _state(**overrides) -> GateState:
    base = dict(
        status="candidate",
        promotion_consecutive=0,
        promotion_eval_metrics=(),
        last_eval_corpus_build_ref=None,
        last_eval_n=None,
        min_promotion_consecutive=2,
        min_new_observations=2000.0,
        min_gate_n=1000.0,
    )
    base.update(overrides)
    return GateState(**base)


def test_deprecated_is_untouchable():
    """Automated path never acts on a deprecated concept (operator-only status)."""
    decision = decide_comparison_action(
        _state(status="deprecated"),
        won=True, eval_metric=0.05, eval_n=5000.0, corpus_build_ref="run_A",
    )
    assert decision.action == "noop_deprecated"


def test_same_corpus_build_is_blocked():
    """Invariant 2 precondition: never evaluate twice against the same corpus build."""
    decision = decide_comparison_action(
        _state(last_eval_corpus_build_ref="run_A", last_eval_n=3000.0),
        won=True, eval_metric=0.05, eval_n=9000.0, corpus_build_ref="run_A",
    )
    assert decision.action == "blocked_same_corpus"


def test_initial_effective_n_floor_blocks():
    """Invariant 7: eval_n below min_gate_n blocks regardless of the win."""
    decision = decide_comparison_action(
        _state(),
        won=True, eval_metric=0.05, eval_n=999.0, corpus_build_ref="run_A",
    )
    assert decision.action == "blocked_min_n"


def test_evidence_mass_floor_blocks_reeval():
    """F3: re-evaluation needs >= min_new_observations NEW independent observations
    since the last recorded eval; corpus-advance alone is insufficient."""
    decision = decide_comparison_action(
        _state(last_eval_corpus_build_ref="run_A", last_eval_n=5000.0),
        won=True, eval_metric=0.05, eval_n=6999.0, corpus_build_ref="run_B",
    )
    assert decision.action == "blocked_evidence_floor"


def test_first_eval_skips_evidence_mass_floor():
    """The F3 floor governs RE-evaluation. A first-ever eval (last_eval_n None) is
    governed by min_gate_n only."""
    decision = decide_comparison_action(
        _state(),
        won=True, eval_metric=0.05, eval_n=1500.0, corpus_build_ref="run_A",
    )
    assert decision.action == "record_win"


def test_loss_resets_consecutive_and_metrics():
    decision = decide_comparison_action(
        _state(promotion_consecutive=1, promotion_eval_metrics=(0.04,),
               last_eval_corpus_build_ref="run_A", last_eval_n=3000.0),
        won=False, eval_metric=None, eval_n=6000.0, corpus_build_ref="run_B",
    )
    assert decision.action == "record_loss"
    assert decision.new_promotion_consecutive == 0
    assert decision.new_promotion_eval_metrics == ()
    assert decision.baseline_metric is None


def test_win_below_consecutive_floor_records_but_does_not_promote():
    decision = decide_comparison_action(
        _state(),
        won=True, eval_metric=0.04, eval_n=3000.0, corpus_build_ref="run_A",
    )
    assert decision.action == "record_win"
    assert decision.new_promotion_consecutive == 1
    assert decision.new_promotion_eval_metrics == (0.04,)
    assert decision.baseline_metric is None


def test_promotion_baseline_is_mean_of_consecutive_evals_not_final():
    """F8 winner's-curse guard: baseline_metric = mean(promotion_eval_metrics including
    this eval), NEVER the final (selection-inflated) eval alone."""
    decision = decide_comparison_action(
        _state(promotion_consecutive=1, promotion_eval_metrics=(0.02,),
               last_eval_corpus_build_ref="run_A", last_eval_n=3000.0),
        won=True, eval_metric=0.06, eval_n=6000.0, corpus_build_ref="run_B",
    )
    assert decision.action == "promote"
    assert decision.new_promotion_consecutive == 2
    assert decision.new_promotion_eval_metrics == (0.02, 0.06)
    assert decision.baseline_metric == 0.04  # mean(0.02, 0.06), not 0.06


def test_win_on_already_active_concept_records_win_not_promote():
    """F2: a WIN for an already-active recipe updates the eval cache; it neither
    re-promotes nor displaces anything (redundancy displacement is disabled here)."""
    decision = decide_comparison_action(
        _state(status="active", promotion_consecutive=3,
               promotion_eval_metrics=(0.02, 0.03, 0.04),
               last_eval_corpus_build_ref="run_A", last_eval_n=3000.0),
        won=True, eval_metric=0.05, eval_n=6000.0, corpus_build_ref="run_B",
    )
    assert decision.action == "record_win"


def test_won_requires_eval_metric():
    with pytest.raises(ValueError):
        decide_comparison_action(
            _state(),
            won=True, eval_metric=None, eval_n=3000.0, corpus_build_ref="run_A",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_concept_registry_service.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'src.intelligence.concept_registry_service'`.

- [ ] **Step 3: Write the pure core**

Create `src/intelligence/concept_registry_service.py`:

```python
"""ConceptRegistryService - Concept Registry lifecycle governance (todo 058).

Invariant 1 (canonical doc, docs/research/concept-unified-registry.md):
proposal and decision are different roles, structurally. The ONLY code path that
flips concept_registry.status for domain='ensemble_strategy' is
record_comparison_outcome() below, called by ops_ensemble_weight_compare.py's
deterministic win-decision gate (no LLM anywhere in the path). No other caller,
human or AI, gets a code path that both writes annotation content and flips status.

Structure: decide_comparison_action() is the pure invariant-enforcement core
(unit-tested without DB); record_comparison_outcome() reads the registry+gate row,
delegates the decision, and applies it transactionally with a compare-and-swap
status write (invariant 9).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

_logger = structlog.get_logger()

# Automated comparison outcomes may never target 'deprecated' - deprecated is
# operator-only (same rule as FeatureRegistryService._AUTOMATED_REASONS).


@dataclass(frozen=True)
class GateState:
    """Snapshot of one concept's registry status + gate/eval-cache state.

    min_* fields arrive APR-resolved by the caller (per-concept concept_gate
    override when non-NULL, else the alpha.concept_registry.<domain>_* default) -
    never hard-coded here.
    """

    status: str
    promotion_consecutive: int
    promotion_eval_metrics: tuple[float, ...]
    last_eval_corpus_build_ref: str | None
    last_eval_n: float | None
    min_promotion_consecutive: int
    min_new_observations: float
    min_gate_n: float


@dataclass(frozen=True)
class ComparisonDecision:
    """What the registry should do with one A/B comparison outcome.

    action vocabulary:
        'promote'                - CAS candidate -> active + transition log row
        'record_win'             - update eval cache, advance consecutive counter
        'record_loss'            - update eval cache, reset consecutive counter
        'blocked_same_corpus'    - invariant 2 precondition: corpus has not advanced
        'blocked_min_n'          - invariant 7: initial effective-N floor unmet
        'blocked_evidence_floor' - F3: < min_new_observations new evidence since last eval
        'noop_deprecated'        - deprecated is operator-only; automated path never touches it
    Blocked/noop decisions write nothing to the DB. The service layer (Task 4's
    record_comparison_outcome) additionally produces 'blocked_status_race' when its
    compare-and-swap promotion UPDATE matches zero rows; the pure core never emits it.
    """

    action: str
    new_promotion_consecutive: int
    new_promotion_eval_metrics: tuple[float, ...]
    baseline_metric: float | None


def decide_comparison_action(
    state: GateState,
    *,
    won: bool,
    eval_metric: float | None,
    eval_n: float,
    corpus_build_ref: str,
) -> ComparisonDecision:
    """Pure decision core for one A/B comparison outcome against one concept.

    Ordering matters: status guard, then invariant 2's corpus-advance precondition,
    then invariant 7's initial floor, then F3's evidence-mass floor, then the
    win/loss bookkeeping. eval_metric is the challenger's mean ic_ci_lower over WIN
    strata (D-15 citation rule: never ic_value); eval_n is the challenger's summed
    n_independent over all compared strata (effective N, not raw bars).
    """
    if won and eval_metric is None:
        raise ValueError("won=True requires eval_metric (mean ic_ci_lower over WIN strata)")

    if state.status == "deprecated":
        return ComparisonDecision(
            "noop_deprecated",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    if corpus_build_ref == state.last_eval_corpus_build_ref:
        return ComparisonDecision(
            "blocked_same_corpus",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    if eval_n < state.min_gate_n:
        return ComparisonDecision(
            "blocked_min_n",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    if (
        state.last_eval_n is not None
        and (eval_n - state.last_eval_n) < state.min_new_observations
    ):
        return ComparisonDecision(
            "blocked_evidence_floor",
            state.promotion_consecutive,
            state.promotion_eval_metrics,
            None,
        )

    if not won:
        return ComparisonDecision("record_loss", 0, (), None)

    new_consecutive = state.promotion_consecutive + 1
    new_metrics = state.promotion_eval_metrics + (float(eval_metric),)

    if state.status == "candidate" and new_consecutive >= state.min_promotion_consecutive:
        baseline = sum(new_metrics) / len(new_metrics)
        return ComparisonDecision("promote", new_consecutive, new_metrics, baseline)

    return ComparisonDecision("record_win", new_consecutive, new_metrics, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_concept_registry_service.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/bg/dev/indicagent
git status --short
git add src/intelligence/concept_registry_service.py tests/unit/test_concept_registry_service.py
git commit -m "feat(concept-registry): pure comparison-decision core for ConceptRegistryService (todo 058)"
```

---

### Task 4: ConceptRegistryService transactional apply (CAS status flip)

**Files:**
- Modify: `src/intelligence/concept_registry_service.py` (append below `decide_comparison_action`)
- Test: `tests/unit/test_concept_registry_service.py` (append)

**Interfaces:**
- Consumes: Task 3's `GateState`, `ComparisonDecision`, `decide_comparison_action` (exact signatures above); Task 1's tables/columns; asyncpg connection semantics (`fetchrow`, `execute` returning a status string like `'UPDATE 1'`, `conn.transaction()` async context manager).
- Produces (Task 5 relies on these exact names):
  - module-level SQL constants `_LOAD_CONCEPT_SQL`, `_CAS_PROMOTE_SQL`, `_TRANSITION_INSERT_SQL`, `_GATE_CACHE_UPDATE_SQL`, `_GATE_PROMOTE_UPDATE_SQL`
  - `class ConceptRegistryService` with `async def record_comparison_outcome(self, conn: Any, *, domain: str, name: str, won: bool, eval_metric: float | None, eval_n: float, corpus_build_ref: str, default_min_promotion_consecutive: int, default_min_new_observations: float, default_min_gate_n: float, notes: str | None = None) -> ComparisonDecision`
  - `class ConceptNotFoundError(Exception)`
  - extra runtime action string `'blocked_status_race'` (CAS matched zero rows)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_concept_registry_service.py`:

```python
# ---------------------------------------------------------------------------
# Transactional apply (Task 4): SQL-constant regression tests + FakeConn flows.
# asyncio_mode=auto (pytest.ini), so async tests run directly.
# ---------------------------------------------------------------------------

from src.intelligence.concept_registry_service import (
    _CAS_PROMOTE_SQL,
    _GATE_CACHE_UPDATE_SQL,
    _GATE_PROMOTE_UPDATE_SQL,
    _LOAD_CONCEPT_SQL,
    _TRANSITION_INSERT_SQL,
    ConceptNotFoundError,
    ConceptRegistryService,
)


class _FakeTransaction:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        self._conn.tx_entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._conn.tx_rolled_back += 1
        return False


class _FakeConn:
    """Minimal asyncpg-shaped stub: canned fetchrow row, recorded execute calls."""

    def __init__(self, row, cas_result="UPDATE 1"):
        self.row = row
        self.cas_result = cas_result
        self.executed: list[tuple[str, tuple]] = []
        self.tx_entered = 0
        self.tx_rolled_back = 0

    def transaction(self):
        return _FakeTransaction(self)

    async def fetchrow(self, sql, *args):
        return self.row

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        if sql is _CAS_PROMOTE_SQL:
            return self.cas_result
        return "UPDATE 1"


def _row(**overrides):
    base = dict(
        concept_id="11111111-1111-1111-1111-111111111111",
        status="candidate",
        promotion_consecutive=1,
        promotion_eval_metrics=[0.02],
        last_eval_corpus_build_ref="run_A",
        last_eval_n=3000.0,
        min_promotion_consecutive=None,
        min_new_observations=None,
        min_gate_n=None,
    )
    base.update(overrides)
    return base


_DEFAULTS = dict(
    default_min_promotion_consecutive=2,
    default_min_new_observations=2000.0,
    default_min_gate_n=1000.0,
)


def test_cas_promote_sql_has_optimistic_lock():
    """Invariant 9: the status UPDATE must carry AND status = <from> so a racing or
    stale evaluator can never log a transition whose from_status never matched."""
    assert "AND status = " in _CAS_PROMOTE_SQL
    assert "UPDATE concept_registry" in _CAS_PROMOTE_SQL


def test_transition_insert_sql_carries_corpus_build_ref():
    """F3: every automated transition records the corpus build that produced it."""
    assert "corpus_build_ref" in _TRANSITION_INSERT_SQL
    assert "concept_transition_log" in _TRANSITION_INSERT_SQL


def test_load_sql_joins_gate():
    assert "concept_gate" in _LOAD_CONCEPT_SQL
    assert "concept_registry" in _LOAD_CONCEPT_SQL


def test_gate_update_sqls_touch_cache_columns():
    for sql in (_GATE_CACHE_UPDATE_SQL, _GATE_PROMOTE_UPDATE_SQL):
        assert "last_eval_corpus_build_ref" in sql
        assert "promotion_consecutive" in sql
    assert "baseline_metric" in _GATE_PROMOTE_UPDATE_SQL


async def test_unknown_concept_raises():
    service = ConceptRegistryService()
    conn = _FakeConn(row=None)
    with pytest.raises(ConceptNotFoundError):
        await service.record_comparison_outcome(
            conn, domain="ensemble_strategy", name="nope", won=True,
            eval_metric=0.05, eval_n=6000.0, corpus_build_ref="run_B", **_DEFAULTS,
        )


async def test_blocked_decision_writes_nothing():
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row())
    decision = await service.record_comparison_outcome(
        conn, domain="ensemble_strategy", name="e1_shrunk_ic", won=True,
        eval_metric=0.05, eval_n=6000.0, corpus_build_ref="run_A",  # same corpus
        **_DEFAULTS,
    )
    assert decision.action == "blocked_same_corpus"
    assert conn.executed == []


async def test_promotion_flow_is_cas_plus_transition_plus_gate_in_one_tx():
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row())
    decision = await service.record_comparison_outcome(
        conn, domain="ensemble_strategy", name="e1_shrunk_ic", won=True,
        eval_metric=0.06, eval_n=6000.0, corpus_build_ref="run_B", **_DEFAULTS,
    )
    assert decision.action == "promote"
    assert decision.baseline_metric == pytest.approx(0.04)
    executed_sqls = [sql for sql, _ in conn.executed]
    assert executed_sqls == [_CAS_PROMOTE_SQL, _TRANSITION_INSERT_SQL, _GATE_PROMOTE_UPDATE_SQL]
    assert conn.tx_entered == 1


async def test_promotion_cas_race_returns_blocked_status_race():
    """CAS matched zero rows (status changed under us): abort, no transition row."""
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row(), cas_result="UPDATE 0")
    decision = await service.record_comparison_outcome(
        conn, domain="ensemble_strategy", name="e1_shrunk_ic", won=True,
        eval_metric=0.06, eval_n=6000.0, corpus_build_ref="run_B", **_DEFAULTS,
    )
    assert decision.action == "blocked_status_race"
    executed_sqls = [sql for sql, _ in conn.executed]
    assert _TRANSITION_INSERT_SQL not in executed_sqls


async def test_record_loss_updates_gate_cache_only():
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row())
    decision = await service.record_comparison_outcome(
        conn, domain="ensemble_strategy", name="e2_mean_variance", won=False,
        eval_metric=None, eval_n=6000.0, corpus_build_ref="run_B", **_DEFAULTS,
    )
    assert decision.action == "record_loss"
    executed_sqls = [sql for sql, _ in conn.executed]
    assert executed_sqls == [_GATE_CACHE_UPDATE_SQL]


async def test_gate_row_overrides_beat_apr_defaults():
    """A non-NULL concept_gate.min_promotion_consecutive overrides the APR default:
    with override 3, the second consecutive win records but does not promote."""
    service = ConceptRegistryService()
    conn = _FakeConn(row=_row(min_promotion_consecutive=3))
    decision = await service.record_comparison_outcome(
        conn, domain="ensemble_strategy", name="e1_shrunk_ic", won=True,
        eval_metric=0.06, eval_n=6000.0, corpus_build_ref="run_B", **_DEFAULTS,
    )
    assert decision.action == "record_win"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/pytest tests/unit/test_concept_registry_service.py -v`
Expected: the 10 Task 3 tests pass; the new tests fail at import with `ImportError: cannot import name '_CAS_PROMOTE_SQL'`.

- [ ] **Step 3: Implement the transactional apply**

Append to `src/intelligence/concept_registry_service.py`:

```python
# ---------------------------------------------------------------------------
# Transactional apply (asyncpg)
# ---------------------------------------------------------------------------

_LOAD_CONCEPT_SQL = """
    SELECT r.concept_id, r.status,
           g.promotion_consecutive, g.promotion_eval_metrics,
           g.last_eval_corpus_build_ref, g.last_eval_n,
           g.min_promotion_consecutive, g.min_new_observations, g.min_gate_n
    FROM concept_registry r
    JOIN concept_gate g USING (concept_id)
    WHERE r.domain = $1 AND r.name = $2
"""

# Invariant 9: compare-and-swap. Zero rows updated means the status changed under
# us (or a rerun raced) - the whole transaction, including the transition-log
# insert, is aborted rather than logging a transition whose from_status never
# matched the row.
_CAS_PROMOTE_SQL = """
    UPDATE concept_registry SET status = $1
    WHERE concept_id = $2 AND status = $3
"""

_TRANSITION_INSERT_SQL = """
    INSERT INTO concept_transition_log
        (concept_id, domain, name, from_status, to_status, trigger_reason,
         corpus_build_ref, gate_metric, gate_n, ci_lower, triggered_at, notes)
    VALUES ($1, $2, $3, $4, $5, 'promotion', $6, $7, $8, $9, $10, $11)
"""

_GATE_CACHE_UPDATE_SQL = """
    UPDATE concept_gate
    SET last_eval_metric = $2, last_eval_n = $3, last_eval_at = $4,
        last_eval_corpus_build_ref = $5,
        promotion_consecutive = $6, promotion_eval_metrics = $7,
        updated_at = $4
    WHERE concept_id = $1
"""

_GATE_PROMOTE_UPDATE_SQL = """
    UPDATE concept_gate
    SET last_eval_metric = $2, last_eval_n = $3, last_eval_at = $4,
        last_eval_corpus_build_ref = $5,
        promotion_consecutive = $6, promotion_eval_metrics = $7,
        baseline_metric = $8, decay_ratio = 1.0,
        updated_at = $4
    WHERE concept_id = $1
"""


class ConceptNotFoundError(Exception):
    """No concept_registry+concept_gate row for the given (domain, name)."""


def _rowcount(execute_status: str) -> int:
    """Parse asyncpg's execute() status string ('UPDATE 1' -> 1)."""
    return int(execute_status.rsplit(" ", 1)[-1])


class ConceptRegistryService:
    """Narrowly-scoped Concept Registry writer (invariant 1).

    Stateless: every method takes an asyncpg connection. The only status-flipping
    path is record_comparison_outcome; it can only ever write
    candidate -> active with trigger_reason='promotion'. It structurally cannot
    target 'deprecated' (operator-only) or write annotation content.
    """

    async def record_comparison_outcome(
        self,
        conn: Any,
        *,
        domain: str,
        name: str,
        won: bool,
        eval_metric: float | None,
        eval_n: float,
        corpus_build_ref: str,
        default_min_promotion_consecutive: int,
        default_min_new_observations: float,
        default_min_gate_n: float,
        notes: str | None = None,
    ) -> ComparisonDecision:
        """Apply one A/B comparison outcome for one concept, transactionally.

        The default_* floors are APR-resolved by the caller
        (alpha.concept_registry.<domain>_* keys); a non-NULL concept_gate column
        overrides its default. Blocked/noop decisions write nothing.
        """
        row = await conn.fetchrow(_LOAD_CONCEPT_SQL, domain, name)
        if row is None:
            raise ConceptNotFoundError(
                f"no concept_registry+concept_gate row for domain={domain!r} name={name!r}"
            )

        state = GateState(
            status=row["status"],
            promotion_consecutive=row["promotion_consecutive"],
            promotion_eval_metrics=tuple(row["promotion_eval_metrics"] or ()),
            last_eval_corpus_build_ref=row["last_eval_corpus_build_ref"],
            last_eval_n=row["last_eval_n"],
            min_promotion_consecutive=(
                row["min_promotion_consecutive"]
                if row["min_promotion_consecutive"] is not None
                else default_min_promotion_consecutive
            ),
            min_new_observations=(
                row["min_new_observations"]
                if row["min_new_observations"] is not None
                else default_min_new_observations
            ),
            min_gate_n=(
                row["min_gate_n"] if row["min_gate_n"] is not None
                else default_min_gate_n
            ),
        )

        decision = decide_comparison_action(
            state,
            won=won,
            eval_metric=eval_metric,
            eval_n=eval_n,
            corpus_build_ref=corpus_build_ref,
        )

        if decision.action in (
            "noop_deprecated",
            "blocked_same_corpus",
            "blocked_min_n",
            "blocked_evidence_floor",
        ):
            _logger.info(
                "concept_registry.comparison_blocked",
                domain=domain,
                name=name,
                action=decision.action,
                corpus_build_ref=corpus_build_ref,
            )
            return decision

        now = datetime.now(UTC)
        metrics_list = list(decision.new_promotion_eval_metrics)

        if decision.action == "promote":
            async with conn.transaction():
                cas_status = await conn.execute(
                    _CAS_PROMOTE_SQL, "active", row["concept_id"], "candidate"
                )
                if _rowcount(cas_status) == 0:
                    _logger.warning(
                        "concept_registry.promotion_cas_race",
                        domain=domain,
                        name=name,
                        corpus_build_ref=corpus_build_ref,
                    )
                    return ComparisonDecision(
                        "blocked_status_race",
                        state.promotion_consecutive,
                        state.promotion_eval_metrics,
                        None,
                    )
                await conn.execute(
                    _TRANSITION_INSERT_SQL,
                    row["concept_id"],
                    domain,
                    name,
                    "candidate",
                    "active",
                    corpus_build_ref,
                    decision.baseline_metric,
                    eval_n,
                    eval_metric,
                    now,
                    notes,
                )
                await conn.execute(
                    _GATE_PROMOTE_UPDATE_SQL,
                    row["concept_id"],
                    eval_metric,
                    eval_n,
                    now,
                    corpus_build_ref,
                    decision.new_promotion_consecutive,
                    metrics_list,
                    decision.baseline_metric,
                )
            _logger.info(
                "concept_registry.promoted",
                domain=domain,
                name=name,
                baseline_metric=decision.baseline_metric,
                corpus_build_ref=corpus_build_ref,
            )
            return decision

        # record_win / record_loss: eval-cache bookkeeping only.
        await conn.execute(
            _GATE_CACHE_UPDATE_SQL,
            row["concept_id"],
            eval_metric,
            eval_n,
            now,
            corpus_build_ref,
            decision.new_promotion_consecutive,
            metrics_list,
        )
        _logger.info(
            "concept_registry.comparison_recorded",
            domain=domain,
            name=name,
            action=decision.action,
            corpus_build_ref=corpus_build_ref,
        )
        return decision
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_concept_registry_service.py -v`
Expected: 20 passed (10 from Task 3, 10 from Task 4).

- [ ] **Step 5: Commit**

```bash
cd /home/bg/dev/indicagent
git status --short
git add src/intelligence/concept_registry_service.py tests/unit/test_concept_registry_service.py
git commit -m "feat(concept-registry): transactional CAS promotion apply in ConceptRegistryService (todo 058)"
```

---

### Task 5: Wire the win-decision gate to the registry (invariant 1)

**Files:**
- Modify: `scripts/ops/alpha/ops_ensemble_weight_compare.py`
- Test: `tests/unit/test_ensemble_weight_compare.py` (append)

**Interfaces:**
- Consumes: Task 4's `ConceptRegistryService.record_comparison_outcome(...)` and `ConceptNotFoundError` (exact signature in Task 4); Task 2's seeded concept names (`e1_shrunk_ic`, `e2_mean_variance`, ...); Task 1's APR keys `alpha.concept_registry.ensemble_strategy_min_promotion_consecutive` / `..._min_new_observations` / `..._min_observations`; the script's existing `stratum_data` / `challenger_by_stratum` structures and `_final_verdict` vocabulary (`WIN`, `LOSS`, `HOLD`, `WIN-FDR-VETO`).
- Produces: pure helper `_registry_outcome(rows: list[dict]) -> tuple[bool, float | None, float]` where each input dict has keys `verdict` (str), `ic_ci_lower` (float | None), `n_independent` (float | None); CLI args `--challenger-concept`, `--champion-concept`, `--corpus-build-ref`. Backward compatibility contract: without `--challenger-concept` the script's behavior and output are byte-identical to today.

Why concept names arrive via CLI and are never derived from `weight_version`: `weight_version` is a per-corpus-build epoch tag (migration 224: "a data-scoping tag only"); the recipe that produced a given epoch's rows is determined by APR state at trainer run time and is not recorded on `ensemble_weights`. The invoker (operator or `ops_corpus_pipeline_run.sh` follow-on) knows which recipe each side is, so it states it explicitly. `--corpus-build-ref` defaults to the challenger `weight_version` because `WEIGHT_EPOCH` IS the corpus-build identity (derived from `TRAINING_WINDOW_END`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ensemble_weight_compare.py`:

```python
# ---------------------------------------------------------------------------
# _registry_outcome (todo 058: invariant-1 wiring to ConceptRegistryService)
# ---------------------------------------------------------------------------

from ops_ensemble_weight_compare import _registry_outcome


def test_registry_outcome_win_metric_is_mean_ci_lower_over_win_strata_only():
    """D-15 citation rule: the recorded metric is ic_ci_lower (never ic_value), and
    only WIN strata contribute to it - a WIN-FDR-VETO stratum is not a promotable
    win and must not inflate the recorded evidence."""
    rows = [
        {"verdict": "WIN", "ic_ci_lower": 0.04, "n_independent": 1000.0},
        {"verdict": "WIN", "ic_ci_lower": 0.02, "n_independent": 2000.0},
        {"verdict": "WIN-FDR-VETO", "ic_ci_lower": 0.90, "n_independent": 500.0},
        {"verdict": "LOSS", "ic_ci_lower": -0.01, "n_independent": 1500.0},
    ]
    won, eval_metric, eval_n = _registry_outcome(rows)
    assert won is True
    assert eval_metric == 0.03  # mean(0.04, 0.02); the 0.90 veto stratum excluded
    assert eval_n == 5000.0  # n_independent summed over ALL compared strata


def test_registry_outcome_no_win_strata():
    rows = [
        {"verdict": "LOSS", "ic_ci_lower": -0.01, "n_independent": 1500.0},
        {"verdict": "WIN-FDR-VETO", "ic_ci_lower": 0.05, "n_independent": 500.0},
        {"verdict": "HOLD", "ic_ci_lower": None, "n_independent": None},
    ]
    won, eval_metric, eval_n = _registry_outcome(rows)
    assert won is False
    assert eval_metric is None
    assert eval_n == 2000.0  # None n_independent skipped, not treated as 0-vs-crash


def test_registry_outcome_empty():
    won, eval_metric, eval_n = _registry_outcome([])
    assert won is False
    assert eval_metric is None
    assert eval_n == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_ensemble_weight_compare.py -v`
Expected: existing tests pass; the three new ones fail with `ImportError: cannot import name '_registry_outcome'`.

- [ ] **Step 3: Add the pure helper to the ops script**

In `scripts/ops/alpha/ops_ensemble_weight_compare.py`, add this function directly after `_final_verdict` (after its closing `return "WIN" if bh_reject else "WIN-FDR-VETO"` line):

```python
def _registry_outcome(rows: list[dict]) -> tuple[bool, float | None, float]:
    """Pure helper: reduce per-stratum verdicts to one registry-recordable outcome.

    won = any stratum verdict is WIN (F2: recipe validity is earned by winning
    anywhere; per-stratum champions stay facts in ensemble_weights).
    eval_metric = mean challenger ic_ci_lower over WIN strata only (D-15 citation
    rule: ic_ci_lower, never ic_value; a WIN-FDR-VETO stratum is not a promotable
    win and contributes nothing). eval_n = challenger n_independent summed over ALL
    compared strata (the evidence mass this comparison consumed, win or lose).
    """
    win_ci_lowers = [
        r["ic_ci_lower"]
        for r in rows
        if r["verdict"] == "WIN" and r["ic_ci_lower"] is not None
    ]
    eval_n = float(sum(r["n_independent"] for r in rows if r["n_independent"] is not None))
    if not win_ci_lowers:
        return False, None, eval_n
    return True, float(sum(win_ci_lowers) / len(win_ci_lowers)), eval_n
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_ensemble_weight_compare.py -v`
Expected: all pass (existing + 3 new).

- [ ] **Step 5: Add the CLI args and the registry-recording block**

Still in `scripts/ops/alpha/ops_ensemble_weight_compare.py`:

5a. Add the service import after the existing `from src.intelligence.statistics.ic_math import ...` line:

```python
from src.intelligence.concept_registry_service import (
    ConceptNotFoundError,
    ConceptRegistryService,
)
```

5b. In `main()`, after the existing `--challenger` `parser.add_argument(...)` call and before `args = parser.parse_args()`, add:

```python
    parser.add_argument(
        "--challenger-concept",
        default=None,
        help=(
            "concept_registry name (domain=ensemble_strategy) for the challenger "
            "recipe, e.g. e2_mean_variance. weight_version is a data-scoping epoch "
            "tag (migration 224) and cannot identify the recipe, so it is stated "
            "explicitly here. Omit to run report-only (no registry write)."
        ),
    )
    parser.add_argument(
        "--champion-concept",
        default=None,
        help="concept_registry name for the champion recipe (informational, for the transition notes).",
    )
    parser.add_argument(
        "--corpus-build-ref",
        default=None,
        help=(
            "Corpus build identity for invariant 2's re-evaluation guard. Defaults "
            "to the challenger weight_version (the WEIGHT_EPOCH is the corpus-build "
            "identity, derived from TRAINING_WINDOW_END)."
        ),
    )
```

5c. At the very end of `main()`'s body, replace the final `        return 0` (the one after the "Reporting rule (D-15)" print, NOT the early-exit `return 0`s) with:

```python
        if args.challenger_concept:
            outcome_rows = [
                {
                    "verdict": (
                        "HOLD"
                        if stratum_data[key]["win"] is None
                        else _final_verdict(
                            stratum_data[key]["win"], stratum_data[key]["bh_reject"]
                        )
                    ),
                    "ic_ci_lower": challenger_by_stratum[key]["ic_ci_lower"],
                    "n_independent": challenger_by_stratum[key]["n_independent"],
                }
                for key in strata
            ]
            won, eval_metric, eval_n = _registry_outcome(outcome_rows)
            corpus_build_ref = args.corpus_build_ref or args.challenger

            async with pool.acquire() as conn:
                apr_rows = await conn.fetch(
                    "SELECT config_key, config_value FROM config_state "
                    "WHERE config_key IN ("
                    "'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive',"
                    "'alpha.concept_registry.ensemble_strategy_min_new_observations',"
                    "'alpha.concept_registry.ensemble_strategy_min_observations')"
                )
                apr = {r["config_key"]: r["config_value"] for r in apr_rows}
                if len(apr) != 3:
                    print()
                    print(
                        "REGISTRY: FAILED - alpha.concept_registry.* gate keys missing "
                        "from config_state; apply migration 231 before recording."
                    )
                    return 0

                service = ConceptRegistryService()
                try:
                    decision = await service.record_comparison_outcome(
                        conn,
                        domain="ensemble_strategy",
                        name=args.challenger_concept,
                        won=won,
                        eval_metric=eval_metric,
                        eval_n=eval_n,
                        corpus_build_ref=corpus_build_ref,
                        default_min_promotion_consecutive=int(
                            apr[
                                "alpha.concept_registry."
                                "ensemble_strategy_min_promotion_consecutive"
                            ]
                        ),
                        default_min_new_observations=float(
                            apr[
                                "alpha.concept_registry."
                                "ensemble_strategy_min_new_observations"
                            ]
                        ),
                        default_min_gate_n=float(
                            apr[
                                "alpha.concept_registry."
                                "ensemble_strategy_min_observations"
                            ]
                        ),
                        notes=(
                            f"A/B vs champion "
                            f"{args.champion_concept or args.champion} "
                            f"(weight_versions {args.champion} vs {args.challenger}). "
                            "Invariant-6 exception applies: human-authored candidate; "
                            "this OOS A/B on live corpus runs is the domain's "
                            "documented evidentiary substitute for a live shadow "
                            "period (docs/research/"
                            "concept-unified-registry.md, Invariant 6)."
                        ),
                    )
                except ConceptNotFoundError as error:
                    print()
                    print(f"REGISTRY: FAILED - {error}")
                    return 0

            print()
            print(
                f"REGISTRY: concept={args.challenger_concept} won={won} "
                f"eval_metric={eval_metric} eval_n={eval_n} "
                f"corpus_build_ref={corpus_build_ref} -> action={decision.action}"
                + (
                    f" baseline_metric={decision.baseline_metric}"
                    if decision.action == "promote"
                    else ""
                )
            )

        return 0
```

Note: `pool` is still open at this point (the registry block sits inside the `try:` whose `finally: await pool.close()` ends `main()`), and `strata` / `stratum_data` / `challenger_by_stratum` are all still in scope. The champion side is deliberately never written: a challenger LOSS does not demote the champion, and a challenger WIN does not displace it (F2: displacement disabled for this domain).

- [ ] **Step 6: Backward-compatibility smoke (report-only path unchanged)**

Run:
```bash
cd /home/bg/dev/indicagent
.venv/bin/python scripts/ops/alpha/ops_ensemble_weight_compare.py \
  --champion run_2025122405150000 --challenger run_2025122405150000_mv
```
Expected: the same "## D-12 Ensemble Weight Compare" report as before this change, with NO `REGISTRY:` line (no `--challenger-concept` given), exit code 0. **Do NOT pass `--challenger-concept` against live data in this task**: the live champion/challenger pair is the invalidated pre-todo-094 all-long comparison (see the `e2_mean_variance` observation annotation); recording it would write exactly the outcome Phase 143.1 has ruled non-carrying. The recording path is exercised by unit tests and by the 143.1 re-run when it happens.

- [ ] **Step 7: Run the full compare-script test file**

Run: `.venv/bin/pytest tests/unit/test_ensemble_weight_compare.py tests/unit/test_concept_registry_service.py -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
cd /home/bg/dev/indicagent
git status --short
git add scripts/ops/alpha/ops_ensemble_weight_compare.py tests/unit/test_ensemble_weight_compare.py
git commit -m "feat(concept-registry): wire win-decision gate to ConceptRegistryService (invariant 1, todo 058)"
```

---

### Task 6: Documentation sync + follow-on todo for domain='feature'

**Files:**
- Modify: `docs/research/concept-unified-registry.md`
- Modify: `docs/research/concept-governance-registries.md`
- Create: `.planning/todos/pending/109-migrate-feature-domain-into-concept-registry.md`

**Interfaces:**
- Consumes: the shipped migrations/service from Tasks 1-5 (referenced by name only).
- Produces: nothing code-level; doc state that later sessions rely on.

- [ ] **Step 1: Record the invariant-6 exception for ensemble_strategy (todo 058 item 6)**

In `docs/research/concept-unified-registry.md`, find Invariant 6's closing sentence (exact text):

```
Any domain claiming this exception must document why its gate already provides the evidence live observation would add, not merely assert it; proposer-driven domains (`confluence` especially, once real) do not get it by default.
```

Append directly after it, in the same paragraph block:

```
**Documented exception: `domain='ensemble_strategy'` (recorded 2026-07-13, todo 058 build).** E1-E4 candidates are human-authored, not proposer-driven, so mandatory `shadow_only` does not bind here the way it would for an AI-sourced concept. The evidentiary substitute for a live shadow period is the OOS A/B judged by `EnsembleICEngine` over live corpus runs: per-stratum non-overlapping-CI win rule (challenger `ic_ci_lower` > champion `ic_ci_upper`), `walk_forward_stable` veto, and BH-FDR correction across strata, executed by `ops_ensemble_weight_compare.py` and recorded through `ConceptRegistryService.record_comparison_outcome()` - which is also this domain's invariant-1 deterministic status-flipper. Promotion therefore runs `candidate -> active` directly for this domain; every promotion transition's `notes` cites this exception.
```

- [ ] **Step 2: Update the canonical doc's status line**

Same file, the header `**Status**:` line currently begins:

```
**Status**: Design complete, not built — zero `concept_*` tables, migrations, or service code exist (verified against `src/`, `services/`, `production/migrations/`, and the live DB 2026-07-06). MVP build trigger fired 2026-07-04 (todo 058).
```

Replace that leading portion (keep the rest of the line about sibling registries unchanged) with:

```
**Status**: MVP BUILT 2026-07-13 (todo 058, migrations 231/232): `concept_registry`/`concept_gate`/`concept_transition_log`/`concept_annotation` live, `domain='ensemble_strategy'` seeded (5 concepts), `ConceptRegistryService` (`src/intelligence/concept_registry_service.py`) wired as invariant-1 status-flipper from `ops_ensemble_weight_compare.py`. `domain='feature'` NOT yet migrated (todo 109); reference-architecture tables remain unbuilt by design.
```

- [ ] **Step 3: Update the hub doc's three status cells**

In `docs/research/concept-governance-registries.md`, make these three replacements:

3a. In the "Three complementary types" table, the Type 2 row's Status cell currently reads:

```
⏳ Design complete, MVP build trigger fired 2026-07-04 (todo 058), not built; zero `concept_*` tables exist. Feature Registry (a separate sibling system, not part of Concept Registry) is live with 61 rows
```

Replace with:

```
✅ MVP live 2026-07-13 (todo 058, migrations 231/232): four tables + `ConceptRegistryService`, `ensemble_strategy` seeded (5 concepts). `feature` domain not yet migrated (todo 109). Feature Registry (a separate sibling system, not part of Concept Registry) is live with 61 rows
```

3b. In the "Type 2 — Lifecycle Registries" section, the line:

```
- **Status:** Feature Registry (separate sibling system) live (61 features); Concept Registry design complete, MVP build trigger fired 2026-07-04 (todo 058), not built
```

Replace with:

```
- **Status:** Feature Registry (separate sibling system) live (61 features); Concept Registry MVP live 2026-07-13 (todo 058, migrations 231/232), `ensemble_strategy` seeded; `feature` migration pending (todo 109)
```

3c. In the "Implementation Status" table, the row:

```
| Concept Registry (full Type 2) | 4 designed (`concept_registry`, `concept_gate`, `concept_transition_log`, `concept_annotation`) | `ConceptRegistryService` (designed) | ⏳ Build trigger fired 2026-07-04 (todo 058), not started |
```

Replace with:

```
| Concept Registry (full Type 2) | 4 live (`concept_registry`, `concept_gate`, `concept_transition_log`, `concept_annotation`) | `ConceptRegistryService` (live, `src/intelligence/concept_registry_service.py`) | ✅ MVP shipped 2026-07-13 (todo 058, migrations 231/232); `ensemble_strategy` seeded, `feature` migration pending (todo 109) |
```

- [ ] **Step 4: File the follow-on todo (todo 058 item 7's sequencing note, updated to today's reality)**

The todo's item 7 said Phase 143's LIFECYCLE-01 amendments were "pending" against `feature_registry`. That has since resolved: Phase 143 COMPLETED 2026-07-10 and shipped its lifecycle state machine against `feature_registry` directly (`record_transition_sync`, shadow counters), not through `concept_registry`. So intel-14 OQ3's build-time check resolves to: `feature_registry` stays the live governor for `domain='feature'` today, and folding it in is now unblocked follow-on work.

Create `.planning/todos/pending/109-migrate-feature-domain-into-concept-registry.md` (if 109 is taken by the time this executes, use the next free number in the pending sequence and fix the two references to "todo 109" written by Steps 2-3):

```markdown
---
**Created:** 2026-07-13
**Area:** intelligence / governance
**Type:** refactor
**Priority:** P2
**Effort:** 1-2 sessions
**Risk:** medium (touches the live feature lifecycle path: ic_engine post-run hook + ensemble_trainer alignment gate)
**Gate:** none - Phase 143 (the previous blocker) completed 2026-07-10
---

# 109 - Migrate domain='feature' (feature_registry) into the Concept Registry

Concept Registry MVP shipped 2026-07-13 (todo 058, migrations 231/232) with
domain='ensemble_strategy' seeded. The `domain` CHECK already includes 'feature';
zero feature rows were seeded, per todo 058 item 7.

The original sequencing blocker is resolved: Phase 143's LIFECYCLE-01 amendments
(demote-to-shadow_only, evidence-based shadow_only -> active recovery, deprecated
operator-only) shipped 2026-07-10 against feature_registry itself
(FeatureRegistryService.record_transition_sync / advance_shadow_counters_sync).
That answers intel-14 OQ3's build-time check: 143 did NOT route through
concept_registry, so the migration is now a plain fold-in.

## Scope

1. Migration: one concept_registry row per feature_registry row (150 rows,
   derived from FeatureVector fields - verify count at build time), concept_gate
   rows carrying min_ic_sharpe/min_ic_n/fdr_required/fdr_alpha, genesis or
   history-preserving transition rows (decide: replay feature_transition_log into
   concept_transition_log vs genesis-seed with a pointer back).
2. Port record_transition_sync's semantics (CAS + counter resets + deprecated
   operator-only) onto concept tables, or teach ConceptRegistryService a sync
   psycopg2 path for ic_engine's no-event-loop context.
3. Repoint consumers: ic_engine post-run lifecycle hook, ensemble_trainer
   alignment gate + eligibility reads, integrity_monitor diagnostics queries.
4. Retire feature_registry/feature_transition_log only after a full corpus run
   verifies identical lifecycle decisions (shadow mode first).

## References

- docs/research/concept-unified-registry.md (Invariants 8/9; the
  FeatureRegistryService CAS critique is already implemented in
  ConceptRegistryService - reuse it)
- docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md (todo 058)
- docs/research/intel-14-integrity-monitor.md OQ3 (resolved as described above)
- src/intelligence/feature_registry_service.py, services/ic_engine.py
```

- [ ] **Step 5: Commit**

```bash
cd /home/bg/dev/indicagent
git status --short
git add docs/research/concept-unified-registry.md \
        docs/research/concept-governance-registries.md \
        .planning/todos/pending/109-migrate-feature-domain-into-concept-registry.md
git commit -m "docs(concept-registry): record MVP build, invariant-6 ensemble_strategy exception, file feature-domain follow-on (todo 058)"
```

---

### Task 7: Final verification, close todo 058, merge

**Files:**
- Move: `.planning/todos/pending/058-concept-registry-mvp-seed-ensemble-strategy.md` -> `.planning/todos/completed/058-concept-registry-mvp-seed-ensemble-strategy.md`
- Modify: `.planning/todos/PRIORITIES.md` (remove/strike the 058 entry, matching how other completed todos are handled there)

**Interfaces:**
- Consumes: everything above.
- Produces: merged main.

- [ ] **Step 1: Lint and format**

```bash
cd /home/bg/dev/indicagent
.venv/bin/ruff check src/intelligence/concept_registry_service.py \
  scripts/ops/alpha/ops_ensemble_weight_compare.py \
  tests/unit/test_concept_registry_service.py \
  tests/unit/test_ensemble_weight_compare.py --fix
.venv/bin/black src/intelligence/concept_registry_service.py \
  scripts/ops/alpha/ops_ensemble_weight_compare.py \
  tests/unit/test_concept_registry_service.py \
  tests/unit/test_ensemble_weight_compare.py
```
Expected: no remaining ruff errors; black reformats or leaves unchanged. If black reformatted, re-run the Task 3-5 test commands and amend the last commit (`git add -u && git commit --amend --no-edit`).

- [ ] **Step 2: Full unit suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: green, same pass count as `main` plus the new tests (the pre-existing unrelated `test_no_smooth_or_backward_in_factory` failure, if still present on main, is not a regression from this work).

- [ ] **Step 3: Done-Coding SOP steps 1-2**

Run the code-simplifier agent over the changed files, then `/review`. Apply any fixes as additional commits on this branch and re-run Step 2.

- [ ] **Step 4: Close todo 058**

```bash
cd /home/bg/dev/indicagent
git mv .planning/todos/pending/058-concept-registry-mvp-seed-ensemble-strategy.md \
       .planning/todos/completed/058-concept-registry-mvp-seed-ensemble-strategy.md
```
Then open `.planning/todos/PRIORITIES.md`, find the 058 line, and remove it (match the file's existing convention for completed items). Also grep for gated references per the close-referenced-concept-docs rule:
```bash
grep -rn "todo 058\|todo-058" docs/foundation docs/research docs/intelligence .planning/todos/pending
```
Task 6 already updated the two registry docs; if this grep surfaces any OTHER doc stating 058 as pending/unbuilt, update its status wording in place (state the corrected fact plainly, no review-narrative annotation).

```bash
git status --short
git add -A .planning/todos docs/
git commit -m "chore(todos): close todo 058 - Concept Registry MVP shipped"
```

- [ ] **Step 5: Merge per SOP**

```bash
cd /home/bg/dev/indicagent
git checkout main
git merge --ff-only feature/todo-058-concept-registry-mvp
git branch -d feature/todo-058-concept-registry-mvp
git worktree prune
git push origin main
```
If `--ff-only` fails because main advanced (concurrent sessions), rebase the feature branch onto main, re-run Step 2, then merge.

---

## Spec Coverage Map (todo 058's seven scope items)

| Scope item | Where |
|---|---|
| 1. Four-table migration, `corpus_build_ref` on transition log (F3), no `concept_gate_template` (F7) | Task 1 (migration 231; scope guards in Global Constraints) |
| 2. Seed `domain='ensemble_strategy'` from CURRENT live state (todo's 2026-07-04 snapshot superseded) | Task 2 (migration 232) + "Verified Live State" section |
| 3. Name the invariant-1 deterministic status-flipper | Tasks 3-5: `ConceptRegistryService.record_comparison_outcome()`, called by `ops_ensemble_weight_compare.py`; concept identity supplied via `--challenger-concept` because `weight_version` is a data-scoping epoch tag |
| 4. `baseline_metric` winner's-curse guard (F8) | Task 3 (`decide_comparison_action`: baseline = mean of `promotion_eval_metrics`) + `concept_gate.promotion_eval_metrics` column (Task 1) + dedicated test |
| 5. Per-stratum status resolution (F2) | Task 1 table comment, Task 2 status assignments (redundancy_group NULL, displacement disabled), Task 3 `record_win`-on-active test, Task 5's champion-never-written note |
| 6. Invariant-6 exception documentation | Task 6 Step 1 (canonical doc), Task 2 migration header, Task 5 transition `notes` |
| 7. Do NOT migrate feature_registry; note sequencing | Global Constraints scope guard; `domain` CHECK includes `'feature'` with zero rows; Task 6 Step 4 files todo 109 recording that Phase 143 (the original blocker) completed 2026-07-10 |

Judgment calls made beyond the todo/hub text, recorded for the executor: (a) `min_promotion_consecutive` seeded at 2, not the canonical doc's generic 3, because this domain's per-round bar (non-overlapping CI + walk-forward veto + BH-FDR) is far stronger than a scalar p-gate - APR-tunable, provenance `[initial_estimate]`; (b) `e1_shrunk_ic` seeds `candidate` despite being the deployed champion-by-default, because no formal A/B win exists and status = evidence, not deployment; (c) the F3 evidence-mass delta is approximated as `eval_n - last_eval_n` (summed `n_independent` growth between evals), documented in the gate table comment; (d) `metadata->'recipe'` stores the definitional `ic_input`/`weight_method` pair - recipe identity like the 5 in `momentum_z_5`, not a tunable-value copy, so it does not violate the pointer-not-values metadata convention.




