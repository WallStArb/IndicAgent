# Phase 143: Feature Lifecycle Routing (merged with Phase 149B) - Research

**Researched:** 2026-07-05
**Domain:** Feature governance state machine (feature_registry) + IC-engine post-run hook + HMM regime label quality gate
**Confidence:** HIGH (all core claims verified directly against live DB, live code, and applied migrations)

## Summary

This phase is a routing decision, not new-subsystem construction, and the codebase confirms the
ROADMAP's framing on every checkable point. `feature_registry` (migration 172, live, 61 rows, all
currently `status='active'`) already implements the `candidate -> active -> shadow_only ->
deprecated` state machine with a cascade trigger for tier-1 children. `ic_engine.py` already
stamps `feature_status_at_eval` on every `feature_ic_scores` row from registry state at eval time
(verified: `_INSERT_BODY` includes the column, `registry_svc.get_status()` feeds it). `ensemble_trainer.py`
already filters `WHERE feature_status_at_eval = 'active'` in `_process_stratum()` (line 544) -
LIFECYCLE-02 requires zero new code. The three legacy `is_decaying`/`decay_detected_at`/
`recovery_eligible_at` columns on `feature_ic_scores` (migration 160) are confirmed dead in
production code: they appear nowhere in `_INSERT_BODY`, so every row has them at their SQL
`DEFAULT` (`false`/`NULL`) forever - D3's "drop, don't wire" instruction is correct and safe.

The one load-bearing gap this research surfaces that neither the ROADMAP nor the intel-14 doc
states explicitly: **`FeatureRegistryService.record_transition()` is async-only** (`asyncio.create_task`
fire-and-forget against an `asyncpg.Pool`) and **is currently called from nowhere in the codebase**
- not ic_engine, not ensemble_trainer, despite the docstring's claim. `ic_engine.py` is a fully
synchronous `psycopg2` script (no event loop, no asyncpg) chosen specifically so its
`ProcessPoolExecutor` workers can pickle connections cleanly. The transition-writer hook this
phase adds cannot reuse `record_transition()` as-is; it needs a new **synchronous** method on
`FeatureRegistryService` (a `psycopg2`-based counterpart to `_write_transition_record`), called as
a plain blocking function call from `ic_engine.main()` after the corpus write completes - not
scheduled as a fire-and-forget task. This is also the more correct design for a batch job: the
existing async fire-and-forget pattern in `record_transition()` risks a transition write being
silently dropped if the event loop tears down before the scheduled task runs, which is the exact
"silent wrong answer" failure mode the project's design mandate forbids. Flag this as a real bug
in the existing (unused) async path, worth fixing if that path is ever wired up elsewhere, but out
of this phase's direct scope since ic_engine needs its own sync method regardless.

Two APR keys the phase's requirements reference already exist under migration 161, seeded and
live: `alpha.decay.materiality_threshold` (0.005) and `alpha.decay.regime_shift_fraction` (0.60) -
match ROADMAP's stated defaults exactly. A third, `alpha.decay.recovery_min_observations` (2000),
also already exists - but under a **different key name** than the phase description's requested
`alpha.ic.decay_recovery_min_observations`. Same value, same concept, different namespace prefix
chosen by whoever wrote migration 161 vs. whoever wrote the later ROADMAP text. **Do not create a
duplicate key** - reuse `alpha.decay.recovery_min_observations`. Only `alpha.ic.staleness_alert_days`
and its associated `ic_engine_last_run_age_days` gauge are genuinely new (verified absent from
every migration and from `src/observability/metrics.py`).

`integrity_monitor` does not exist as a table anywhere in the migrations directory or the live DB
(`\d integrity_monitor` returns no relation) - this is a real gap LIFECYCLE-03/04 must cover with a
new migration, not an existing table to write into.

LIFECYCLE-00's remaining scope is narrower than a first read of `docs/plans/2026-06-28-hmm-regime-audit-optimization.md`
suggests: P0, P1a, P2a are DONE; P1b is NOT DONE but explicitly out of this phase's stated
remaining scope; only **P2b** (degenerate-model occupation-fraction gate - zero references
anywhere in the codebase, confirmed), **P2c** (`hmm_churn` column - zero references, confirmed;
`feature_vectors` has no such column today), and **P3** (empirical threshold calibration - APR
keys exist at migration-182-seeded defaults, never recalibrated) are open. Todo 034's Step 1
baseline-separation query has **already been run** (documented inline in todo 026, 2026-07-02,
per-symbol not pooled) - LIFECYCLE-00 does not need to re-derive this, only confirm it against
the current corpus if todo 033's 4 features are re-evaluated.

**Primary recommendation:** Build LIFECYCLE-00 (P2b/P2c/P3 only) first as it's a hard prerequisite
for trusting LIFECYCLE-04's regime-shift guard; then LIFECYCLE-01 (registry migration: new
columns, no CHECK-constraint change needed since `shadow_only` is already a valid status value);
then the ic_engine post-run hook (new sync `FeatureRegistryService` method + new `integrity_monitor`
table + gate-evaluation logic), landing LIFECYCLE-02/03/04/05 together since they share the same
hook and per-run view. LIFECYCLE-06 is SQL-only, no build dependency.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Feature status state machine (candidate/active/shadow_only/deprecated) | Database / Storage | — | `feature_registry` table + CHECK constraints + cascade trigger own this; no application-layer state |
| Transition decision logic (promote/demote/regime-shift-hold) | API / Backend (batch) | — | Runs inside `ic_engine.py`'s post-run hook, a batch/oneshot process, not a request-serving tier |
| Transition write (status flip + audit row) | API / Backend (batch) | Database / Storage | New sync method on `FeatureRegistryService`, invoked from `ic_engine.main()`; DB enforces via cascade trigger |
| Ensemble consumption of active features | API / Backend (batch) | — | `ensemble_trainer.py` already filters `WHERE feature_status_at_eval = 'active'` - no phase 143 work needed here |
| Gate-evaluation fact logging | Database / Storage | API / Backend (batch) | New `integrity_monitor` table, written by the same ic_engine hook; observability only, not authoritative state |
| IC staleness alerting | API / Backend (batch) | — | Gauge check inside the same end-of-run hook; no new daemon |
| HMM regime label quality (LIFECYCLE-00) | API / Backend (batch) | Database / Storage | `regime_writer.py` batch job computes; `feature_vectors.hmm_churn` new column persists |

No browser/client or CDN tier involvement anywhere in this phase - it is entirely a backend batch
pipeline change plus schema migrations.

<user_constraints>
## User Constraints (from CONTEXT.md)

No CONTEXT.md exists yet for this phase (`has_context: false` per init). No locked decisions or
discretion areas have been recorded via `/gsd:discuss-phase`. The ROADMAP.md Phase 143 section
(read in full, see below) is being treated as the authoritative, already-locked design per this
research task's explicit instruction - it functions as the constraint set in place of a
CONTEXT.md. Nothing in it should be reopened or redesigned by the planner; only executed.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LIFECYCLE-00 | HMM regime label validation (todo 026 P2b/P2c/P3) | Confirmed P0/P1a/P2a DONE, P1b NOT DONE (out of scope), P2b/P2c/P3 are the only open items; todo 034 Step 1 already run per-symbol (see Common Pitfalls). Plan doc: `docs/plans/2026-06-28-hmm-regime-audit-optimization.md` |
| LIFECYCLE-01 | Registry amendments: redirect `ic_demotion`->`shadow_only`, add `shadow_only`->`active` promotion, add `pre_shadow_weight` + shadow counters as registry columns | Verified `feature_registry` CHECK constraint already permits `shadow_only` as a status value (migration 172) - no CHECK change needed, only new columns + application logic. `feature_transition_log` schema confirmed (see Standard Stack); needs new nullable `note` column per intel-14 |
| LIFECYCLE-02 | Ensemble query enforcement (`WHERE feature_status_at_eval = 'active'`) | **Already implemented** - `ensemble_trainer.py:544`, verified by direct code read. Zero new code required; this requirement is satisfied once LIFECYCLE-01 lands |
| LIFECYCLE-03 | Transition writer as ic_engine post-run hook (no daemon) | Requires new sync `FeatureRegistryService` method (async `record_transition()` cannot be called from ic_engine's psycopg2/no-event-loop context - verified). Hook insertion point identified: after `_write_cross_sectional_results()` call, before manifest recording, in `ic_engine.py` `main()` (~line 2050). `integrity_monitor` table does not exist - new migration required |
| LIFECYCLE-04 | Regime-shift guard (`alpha.decay.regime_shift_fraction >= 0.60` holds weights) | APR key already exists at correct value (migration 161). Depends on LIFECYCLE-00 |
| LIFECYCLE-05 | IC staleness alerting (`alpha.ic.staleness_alert_days`, `ic_engine_last_run_age_days` gauge) | APR key does not exist yet (genuine gap, confirmed via grep). Gauge does not exist (confirmed absent from `src/observability/metrics.py`). New APR key + new OTel gauge required |
| LIFECYCLE-06 | Decay diagnostics (ad-hoc SQL) | No code dependency; `docs/analysis/feature-decay-queries.sql` does not yet exist - net-new file, no blocking prerequisite |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **APR mandate:** any new numeric threshold/weight/period/count must be a `config_schema` +
  `config_state` migration row, loaded via `ConfigService.get_sync()`/`get()`, never a hard-coded
  constant. Applies to `alpha.ic.staleness_alert_days` (new) and any new demotion/promotion
  thresholds this phase introduces beyond the three already-seeded keys.
- **Migrate-as-you-go:** since this phase touches `ic_engine.py` and `feature_registry_service.py`,
  any hard-coded numeric literal newly introduced there must be APR-backed in the same session.
- **`except X as error:`** convention - `feature_registry_service.py` already follows this
  (`except Exception as error:`); new sync method must match.
- **structlog logging** - all new log lines follow `_logger.info("feature_registry_service.<event>", key=value)`
  dotted-event-name convention already established in the file.
- **DAG Invariant 3** ("a compute daemon never writes its own computed output... that persistence
  goes through a dedicated BaseWriter/BaseBatch subclass, never inline in the compute daemon") -
  **does not block this design**. `ic_engine.py` is a `BaseBatch`-adjacent oneshot script (though
  it predates and does not literally subclass `BaseBatch` - see Common Pitfalls) that already
  writes its own primary output (`feature_ic_scores`) directly via `_write_ic_results()`/`_write_cross_sectional_results()`.
  This established precedent (also true of `ensemble_trainer.py`, which extends `BaseBatch` and
  writes `ensemble_weights` directly) means Invariant 3 targets the *real-time, Kafka-driven*
  compute tier (`FeatureVectorPipeline` and friends), not oneshot corpus/batch jobs, which have
  always written their own output tables directly since Phase 138. Adding a second, small write
  (`feature_registry` status + `feature_transition_log` row + `integrity_monitor` fact row) to the
  same already-self-writing batch job is consistent with existing practice, not a new violation.
  State this explicitly in the plan so a future reviewer doesn't misapply Invariant 3 here.
- **`BaseWriter.__init__` / `BaseWriter._parse_payload` contracts** - not applicable; no Kafka
  topic, no `BaseWriter` subclass is created by this phase, since there is no new persistence path
  outside the existing ic_engine/`FeatureRegistryService` pairing.
- **Naming system / gradient columns** - not applicable; no gradient-scale (`fast`/`mid`/`slow`)
  columns are introduced by this phase.
- **Service registry (`_DAG_ORDER`, `_AGENT_ID_TO_UNIT`)** - not applicable; no new systemd
  service/daemon is created (this is the entire point of the ROADMAP's rejected-alternative
  framing - "no new daemon").

## Standard Stack

### Core (all already in use, no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg2 | already pinned in project | `ic_engine.py`'s sole DB driver | ic_engine is sync-only by design for ProcessPoolExecutor compatibility |
| asyncpg | already pinned in project | `ensemble_trainer.py` / `FeatureRegistryService.load()` DB driver | Existing async path, unaffected by this phase |
| structlog | already pinned in project | all logging in touched files | Project-wide convention |
| OTel SDK (`opentelemetry`) | already pinned in project | new `ic_engine_last_run_age_days` gauge, `alpha_decay_cells_flagged`/`alpha_decay_ensemble_rebuild_total` counters | `src/observability/metrics.py` factory functions (`counter()`, `gauge()`, `point_gauge()`) |

### Supporting

No new supporting libraries. This phase is pure SQL migration + Python service/script edits
against libraries already vendored in the project.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Sync `psycopg2` transition-write method on `FeatureRegistryService` | Wrap the existing async `record_transition()` in `asyncio.run()` inside `ic_engine.main()` | Rejected: would require opening a second DB connection type (asyncpg) purely for this one write inside an otherwise fully-sync psycopg2 script, adding a connection pool and event-loop bootstrap for a single blocking call. A native sync method (mirroring `_write_transition_record`'s logic with a psycopg2 cursor + explicit transaction) is simpler and avoids the fire-and-forget task-loss risk entirely. |
| New `integrity_monitor` table (plain TimescaleDB hypertable) | Reuse `feature_transition_log` for gate-evaluation facts too | Rejected per intel-14/D3: `feature_transition_log` is the authoritative *transition* record (one row per actual status change); gate-evaluation facts (metric vs. threshold, pass/fail, including runs where nothing transitioned) are a different cardinality and purpose - conflating them would mean querying "did the regime-shift guard fire this run" requires filtering out real transitions, a modeling smell. |

**Installation:** none - no `pip install` / `npm install` required for this phase.

**Version verification:** not applicable - no third-party package versions are being pinned or
upgraded by this phase.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero new external packages. All work is SQL migrations
plus edits to already-vendored files (`services/ic_engine.py`, `src/intelligence/feature_registry_service.py`,
`services/regime_writer.py`, `src/observability/metrics.py`). The Package Legitimacy Gate protocol
is skipped in its entirety - there is nothing to run slopcheck or `npm view`/`pip index versions`
against.

## Architecture Patterns

### System Architecture Diagram

```
[Corpus pipeline, unchanged upstream]
  regime_writer.py --> forward_return_writer --> ic_engine.py (per-symbol + cross-sectional IC pass)
                                                        |
                                                        | (existing) writes feature_ic_scores
                                                        | rows, stamping feature_status_at_eval
                                                        | from FeatureRegistryService.get_status()
                                                        v
                                          [NEW: post-run transition-writer hook]
                                          inside ic_engine.main(), after
                                          _write_cross_sectional_results()
                                                        |
                        +-------------------------------+--------------------------------+
                        |                                |                                |
                        v                                v                                v
        Gate eval: per (feature, tf,      Gate eval: regime-shift guard    Gate eval: IC staleness
        regime) cell vs.                  (>=60% of cells fail             (days since last successful
        materiality_threshold /            simultaneously -> hold          ic_engine run vs.
        demotion_periods /                 all weights, human review)      staleness_alert_days)
        recovery_min_observations
                        |                                |                                |
                        v                                v                                v
        FeatureRegistryService                  FeatureRegistryService          ic_engine_last_run_age_days
        .record_transition_sync()               .record_transition_sync()      gauge (point_gauge)
        (NEW sync method)                       (hold path: no transition,
                        |                         just an integrity_monitor row)
                        v
        feature_registry.status flip
        (active->shadow_only,
         shadow_only->active)
                        |
                        v
        feature_transition_log INSERT
        (trigger_reason=ic_promotion/
         ic_demotion, existing table)
                        |
                        v
        integrity_monitor INSERT
        (NEW table, monitor_type='ic_lifecycle',
         gate-evaluation fact row: metric,
         threshold, pass/fail - observability
         only, not authoritative)
                        |
                        v
        [Downstream, unchanged]
        ensemble_trainer.py reads
        feature_ic_scores WHERE
        feature_status_at_eval='active'
        (already filters correctly)
```

### Recommended Project Structure

No new files/directories beyond migrations and test files. Edits land in:

```
production/migrations/
├── 200_feature_registry_lifecycle_columns.sql   # LIFECYCLE-01: pre_shadow_weight, shadow counters, feature_transition_log.note
├── 201_integrity_monitor.sql                     # LIFECYCLE-03/04: new hypertable
├── 202_hmm_churn_column.sql                      # LIFECYCLE-00 P2c: feature_vectors.hmm_churn
├── 203_lifecycle_apr_keys.sql                    # LIFECYCLE-00/05: n_restarts (if not already covered by P2a), min_state_occupation, churn_window, staleness_alert_days
services/
├── ic_engine.py                                  # LIFECYCLE-03/04/05: post-run hook call site
├── regime_writer.py                              # LIFECYCLE-00: P2b occupation gate, P2c churn feature
src/intelligence/
├── feature_registry_service.py                   # LIFECYCLE-01/03: new sync transition-write method, promotion-eligibility logic
tests/unit/
├── intelligence/test_feature_registry_service.py # extend with sync-method tests
├── test_ic_engine_*.py                           # extend with hook tests (mocked FeatureRegistryService)
docs/analysis/
├── feature-decay-queries.sql                     # LIFECYCLE-06: new ad-hoc SQL file, no code dependency
```

Migration numbers above are illustrative placeholders (next free number after `199_ibkr_hist_request_timeout_apr.sql`
was 200 as of this research date) - the planner/executor must re-check the actual highest-numbered
file in `production/migrations/` immediately before creating new ones, since other phases may land
migrations concurrently.

### Pattern 1: Compile-time APR binding (frozen config dataclass)

**What:** `ic_engine.py`'s `ICEngineConfig` is a frozen `@dataclass` populated once via
`ICEngineConfig.from_apr(cfg)` at the top of `main()`, using `cfg.get_sync(key, default)` for every
value. No mid-run re-reads of `config_state`.
**When to use:** Any new demotion/promotion/staleness threshold this phase reads inside ic_engine's
run loop must be added as a new field on `ICEngineConfig` (or a small sibling frozen dataclass,
e.g. `LifecycleGateConfig`), not read ad hoc via `cfg.get_sync()` scattered through the hook body.
**Example:**
```python
# Source: services/ic_engine.py:302-330 (existing pattern to extend)
@classmethod
def from_apr(cls, cfg: Any) -> ICEngineConfig:
    return cls(
        min_observations=int(cfg.get_sync("alpha.ic.min_observations", 500)),
        ...
        # New fields this phase would add, e.g.:
        # decay_materiality_threshold=float(cfg.get_sync("alpha.decay.materiality_threshold", 0.005)),
        # decay_regime_shift_fraction=float(cfg.get_sync("alpha.decay.regime_shift_fraction", 0.60)),
        # decay_recovery_min_observations=int(cfg.get_sync("alpha.decay.recovery_min_observations", 2000)),
        # ic_staleness_alert_days=int(cfg.get_sync("alpha.ic.staleness_alert_days", 5)),
    )
```

### Pattern 2: FeatureRegistryService sync load (already-existing precedent for the new sync write)

**What:** `FeatureRegistryService.load_sync(conn)` already demonstrates the sync/psycopg2
counterpart to the async `load(pool)` method - same method body logic, different cursor API. This
is the direct precedent to follow for a new `record_transition_sync(conn, ...)` method.
**When to use:** Any time `ic_engine.py` needs to call into `FeatureRegistryService` for a write,
since the async `record_transition()` is unusable from a script with no running event loop.
**Example:**
```python
# Source: src/intelligence/feature_registry_service.py:100-136 (existing sync precedent)
def load_sync(self, conn: Any) -> None:
    """Load all feature_registry rows via psycopg2 connection."""
    with conn.cursor() as cur:
        cur.execute(_LOAD_QUERY)
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]
    # ... (blocking, no asyncio, mirrors the async load() body exactly)
```
A new `record_transition_sync(self, conn, feature_name, from_status, to_status, reason, ...)`
method should mirror `_write_transition_record`'s two-statement transaction (INSERT into
`feature_transition_log`, UPDATE `feature_registry.status`) using `with conn:` (psycopg2's
context-manager transaction semantics: commits on clean exit, rolls back on exception) instead of
`async with conn.transaction():`.

### Pattern 3: OTel metric factory usage

**What:** New counters/gauges are created once at module scope via the factory functions in
`src/observability/metrics.py`, not per-call.
**When to use:** `alpha_decay_cells_flagged`, `alpha_decay_ensemble_rebuild_total`,
`ic_engine_last_run_age_days`.
**Example:**
```python
# Source: src/observability/metrics.py:72-84, IC_ENGINE_RUN_LATENCY_SECONDS at line 1097 (existing precedent)
ALPHA_DECAY_CELLS_FLAGGED = counter(
    "alpha_decay_cells_flagged",
    "Feature/regime cells flagged as decaying in the ic_engine post-run hook",
)
ALPHA_DECAY_ENSEMBLE_REBUILD_TOTAL = counter(
    "alpha_decay_ensemble_rebuild_total",
    "Ensemble re-solve events triggered by materiality-gated decay",
)
IC_ENGINE_LAST_RUN_AGE_DAYS = point_gauge(
    "ic_engine_last_run_age_days",
    "Days since the last successful ic_engine run completed",
)
```

### Anti-Patterns to Avoid

- **Reintroducing a bespoke state machine or columns on `feature_ic_scores`:** the ROADMAP and
  intel-14 doc both explicitly reject this (D3). Any plan task that proposes adding
  `is_shadowed`/`shadow_corpus_runs`/similar columns to `feature_ic_scores` is a direct regression
  to the design this phase supersedes - verified those exact three legacy columns already exist,
  unread, and are slated for removal, not renaming.
- **A separate daemon or Kafka-subscribed monitor for lifecycle transitions:** explicitly rejected;
  the hook lives inside `ic_engine.main()`, full stop.
- **Calendar-gated recovery (cooldown):** explicitly rejected by Fable's reconciliation (see
  intel-14 doc's recovery-policy table) - only the evidence floor
  (`alpha.decay.recovery_min_observations` + 2 consecutive passing runs) gates promotion.
- **Duplicating the `alpha.decay.recovery_min_observations` APR key under a new name:** it already
  exists (migration 161) at the value the ROADMAP wants (2000) - reuse it, do not create
  `alpha.ic.decay_recovery_min_observations` as a second key with the same meaning.
- **Calling the existing async `record_transition()` from ic_engine:** will silently fail or raise
  `RuntimeError: no running event loop` - `asyncio.create_task()` requires an active event loop,
  which `ic_engine.main()` (plain sync `def main()`) does not have.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Feature promotion/demotion state tracking | A new state machine, table, or set of boolean columns | `feature_registry` (already exists, already has the exact 4-state machine + cascade trigger) | Building a second one is the exact anti-pattern D3 and this phase both exist to prevent |
| Corpus-run-triggered background work | A new systemd daemon or Kafka consumer | A post-run hook inside `ic_engine.main()` | Lifecycle state can only change when new IC measurements land; a daemon polling on a schedule would re-read unchanged data on 6 of 7 days (ic_engine runs weekly) with zero latency benefit and adds an event-vs-data-visibility race the hook doesn't have |
| BH-FDR / walk-forward significance testing for the gate re-evaluation | A new significance test bespoke to lifecycle routing | The existing `passes_fdr`/`passes_ci_gate`/`ic_ci_lower > 0` columns already written to `feature_ic_scores` by ic_engine every run | The IC gate this phase routes on is the same gate `ensemble_trainer` already consumes - no second statistical test needed, only a state-transition decision layered on top of numbers ic_engine already computes |

**Key insight:** every piece of machinery this phase needs to *read* (IC values, FDR pass/fail,
regime labels, registry status) already exists and is already computed correctly. The only
genuinely new code is (a) the transition-decision logic (a handful of threshold comparisons), (b)
the sync write path, and (c) two small schema additions (`integrity_monitor`, `feature_registry`
lifecycle columns). Anything larger than that is scope creep back into the design this phase
explicitly rejected.

## Common Pitfalls

### Pitfall 1: Calling `record_transition()` (async) from `ic_engine.py` (sync, no event loop)

**What goes wrong:** `asyncio.create_task()` raises `RuntimeError: no running event loop` when
called from code that never entered an `async def` context - `ic_engine.main()` is a plain `def`.
**Why it happens:** `FeatureRegistryService.record_transition()` was designed for
`ensemble_trainer.py`'s fully-async `BaseBatch.execute(pool)` context; it was never designed for
ic_engine's sync context, and the module docstring's claim ("Only ensemble_trainer calls
record_transition()") is aspirational, not descriptive - grep confirms zero call sites anywhere in
the codebase today.
**How to avoid:** Add a new synchronous method (`record_transition_sync` or similar) that takes a
psycopg2 connection and performs the INSERT + UPDATE in a single blocking transaction, following
the `load_sync()` precedent already in the same file.
**Warning signs:** Any plan task that says "call `registry_svc.record_transition(...)` from
`ic_engine.py`" without first adding a sync variant is planning to ship a runtime crash.

### Pitfall 2: Assuming `alpha.ic.decay_recovery_min_observations` needs to be created

**What goes wrong:** Creating a second APR key with a different name but the same meaning as an
existing key (`alpha.decay.recovery_min_observations`, migration 161, value 2000) causes config
drift - two keys, one concept, and no clarity about which one `ic_engine`'s hook actually reads.
**Why it happens:** The ROADMAP text (`alpha.ic.decay_recovery_min_observations`) and the actual
migrated key (`alpha.decay.recovery_min_observations`) were written by different authors/sessions
that didn't cross-reference each other's exact key string.
**How to avoid:** Grep `production/migrations/*.sql` for `recovery_min_observations` before adding
any new migration; reuse the existing key.
**Warning signs:** A migration that inserts a key containing the substring `decay_recovery_min_observations`
or `ic.decay` - almost certainly a duplicate of the existing `alpha.decay.recovery_min_observations`.

### Pitfall 3: Treating `ic_engine.py` as a `BaseBatch` subclass

**What goes wrong:** Plan tasks that say "extend `BaseBatch`" or "use `self._pool`" for ic_engine
will not compile - `ic_engine.py` has no class at all in its module-level `main()` structure; it is
a plain `argparse` + `psycopg2` script, unlike `ensemble_trainer.py` which does extend `BaseBatch`
(`class EnsembleTrainer(BaseBatch)`, asyncpg-based).
**Why it happens:** Both files sit in `services/` and are both "batch jobs" conceptually, but they
were built with different DB drivers (`ic_engine.py` predates `BaseBatch` and needs psycopg2 for
`ProcessPoolExecutor` worker pickling; `ensemble_trainer.py` is fully async and post-dates
`BaseBatch`).
**How to avoid:** Any new hook code inside `ic_engine.py` must use the existing `write_conn`
(psycopg2 connection, created via `_connect_db(settings)` inside `main()`) - not `self._pool`,
not `await`.
**Warning signs:** `await` or `async def` anywhere inside a diff to `services/ic_engine.py`.

### Pitfall 4: Assuming the 4 zero-IC features (todo 033) are ready to demote today

**What goes wrong:** Demoting `poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist`
immediately once the transition writer ships, without checking measurement freshness.
**Why it happens:** These 4 features do show `ic_value = 0` exactly at the most recent
`feature_ic_scores.training_window_end` (verified live: 2026-06-23 19:55:00+00, which is the Phase
B corpus re-run's IC pass, completed on 2026-07-01 wall-clock but using this as the data cutoff) -
so the "zero-IC" finding is current, not stale, per direct DB verification during this research.
However, todo 033 also gates on "todo 034/026's regime-label validation for any of the 4 that are
regime-stratified" before concluding a feature is dead - and 3 of these 4 features are `2_theory`
tier features whose IC is measured per-regime (`hmm_regime_prob` derives from the same HMM this
phase's LIFECYCLE-00 is auditing). Demoting on data that predates LIFECYCLE-00's P2b/P2c work
risks demoting on a mis-measured regime label, not a genuinely dead feature.
**How to avoid:** Sequence LIFECYCLE-00 before the first live transition-writer run touches these
4 features, exactly as the ROADMAP's phase-level sequencing already specifies (LIFECYCLE-00 ships
first "same phase").
**Warning signs:** A plan wave that runs the transition-writer hook against the current corpus
before LIFECYCLE-00's P2b/P2c/P3 work lands.

### Pitfall 5: Confusing `training_window_end` with wall-clock run date

**What goes wrong:** Reading `feature_ic_scores.training_window_end = '2026-06-23 19:55:00+00'`
and concluding the corpus is stale/needs re-running.
**Why it happens:** `training_window_end` is an explicit CLI argument (the OOS holdout clamp, `LEAST(MAX(bar_ts),
alpha.validation.oos_start)`) representing a *data* cutoff timestamp, not the timestamp the script
was executed. The Phase B corpus re-run executed 2026-07-01 15:52 UTC (per STATE.md) but wrote
rows with this earlier `training_window_end` value because that's the bar-data boundary it
trained through.
**How to avoid:** Cross-check `feature_vectors` row counts (10,080,038, matching STATE.md's Phase B
figure) rather than `training_window_end`'s literal value to confirm corpus freshness.
**Warning signs:** A plan or verification step that flags the corpus as stale purely because
`training_window_end` "looks old" relative to today's date.

## Code Examples

### Existing cascade trigger (LIFECYCLE-01 should NOT need to touch this)

```sql
-- Source: production/migrations/172_feature_registry.sql:100-123 (verified live, unchanged needed)
CREATE OR REPLACE FUNCTION fn_cascade_parent_deprecation()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'deprecated' AND OLD.status != 'deprecated' THEN
        UPDATE feature_registry
        SET status = 'deprecated'
        WHERE tier = '1_interaction'
          AND status != 'deprecated'
          AND NEW.feature_name = ANY(parent_features);
        INSERT INTO feature_transition_log (feature_name, from_status, to_status, trigger_reason)
        SELECT feature_name, 'active', 'deprecated', 'parent_cascade'
        FROM feature_registry
        WHERE tier = '1_interaction'
          AND NEW.feature_name = ANY(parent_features);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```
This trigger only fires on transitions *to* `deprecated`. Since LIFECYCLE-01 redirects automated
demotion to target `shadow_only` (not `deprecated`), this cascade will correctly NOT fire for
automated demotions going forward - only for the now-operator-only path to `deprecated`. No trigger
change needed; this is a side effect of the redirect worth verifying in a plan-check step, not
touching the trigger code itself.

### Existing ensemble_trainer filter (LIFECYCLE-02 - already correct, cite as evidence)

```python
# Source: services/ensemble_trainer.py:535-546 (verified live, no change needed)
ic_rows = await conn.fetch(
    f"""
    SELECT feature_name, ic_sharpe_hac, ic_shrunk, shrinkage_weight,
           ic_ci_lower, ic_ci_upper, ic_sign, lookahead_bars, training_window_end
    FROM feature_ic_scores
    WHERE symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
      AND tf = $1 AND regime = $2
      AND ic_ci_lower > 0 AND passes_fdr = true
      AND reliable = true AND ic_sharpe_hac IS NOT NULL
      AND feature_status_at_eval = 'active'
      {ic_shrunk_not_null_clause}
    """,
    tf, regime,
)
```

### ic_engine.py hook insertion point (exact location for LIFECYCLE-03/04/05)

```python
# Source: services/ic_engine.py:2047-2053 (verified live - insertion point for the new hook)
# Write all cross-sectional results (after corpus BH-FDR)
if equity_model_enabled and corpus_cs_rows:
    n_written = _write_cross_sectional_results(write_conn, corpus_cs_rows)
    total_committed += n_written

# <<< NEW: post-run transition-writer hook goes here, using write_conn >>>
# _run_lifecycle_hook(write_conn, registry_svc, config, training_window_end)

elapsed = time.monotonic() - t0
IC_ENGINE_RUN_LATENCY_SECONDS.record(elapsed)
```
`write_conn` is already open, already the connection all of this run's writes went through, and
`registry_svc` (the `FeatureRegistryService` instance loaded earlier via `load_sync(conn)`) is
already in scope in `main()`. No new connection needs to be opened for the hook.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Bespoke `AlphaDecayMonitor` daemon writing `is_decaying` to `feature_ic_scores` | Post-run hook inside `ic_engine.py` writing through `feature_registry` | ROADMAP rewritten 2026-07-03, adopting intel-14's Fable-reviewed recommendation | Zero new daemons, zero new systemd units, identical detection latency (ic_engine already runs weekly) |
| Two separate planned builds (Phase 143's `AlphaDecayMonitor` + then-separate Phase 149B's `ICLifecycleMonitor`) | One merged build (this phase) | Merged 2026-07-03 | Halves the implementation surface; single transition writer, single schema |
| Calendar cooldown for shadow-recovery | Pure evidence (2 consecutive passing runs + observation floor) | Fable's reconciliation, adopted into ROADMAP LIFECYCLE-01 | No arbitrary wait; recovery is exactly as fast as evidence accumulates |

**Deprecated/outdated:**
- `is_decaying`/`decay_detected_at`/`recovery_eligible_at` columns on `feature_ic_scores`: dead
  code paths, confirmed never written by any INSERT statement; slated for DROP, not reuse, per D3.
- `feature_deprecations` table concept (never built): superseded by `feature_registry.status = 'deprecated'`
  + a `feature_transition_log` row with `trigger_reason = 'operator_override'`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Next free migration number is 200 (highest applied is `199_ibkr_hist_request_timeout_apr.sql` as of 2026-07-05) | Recommended Project Structure | Low - trivially re-checked at execution time; migration numbering is sequential and collision-obvious |
| A2 | `feature_transition_log` should get a new nullable `note` column (per intel-14's recommendation) rather than reusing an existing text column | LIFECYCLE-01 requirements table | Low-medium - if the planner decides `notes`-style free text isn't needed, this is a one-column simplification, not a structural risk. Not explicitly stated in ROADMAP.md itself (only in the intel-14 doc it's built from), so flagged as ASSUMED, not CITED, despite intel-14 being a fairly authoritative internal design doc |
| A3 | The "deprecation candidate after `shadow_max_corpus_runs` (default 12) consecutive failing shadow runs, operator-confirmed" refinement from intel-14 is in-scope for this phase | LIFECYCLE-01 | Medium - ROADMAP.md's own LIFECYCLE-01 text does not explicitly require this event/counter; it appears only in the intel-14 doc as "kept from the source designs, once routed." Planner should treat this as an optional enhancement to confirm with the user/CONTEXT.md rather than a hard requirement, since the authoritative ROADMAP text is silent on it |

**If this table is empty:** N/A - see above; both entries are genuinely low-to-medium risk
process/scope questions, not factual claims about library behavior or existing code.

## Open Questions (RESOLVED)

1. **RESOLVED — Should the sync transition-write method live on `FeatureRegistryService` itself, or as a
   free function in `ic_engine.py`?**
   - What we know: `load_sync()` already exists as a method on `FeatureRegistryService` for the
     symmetric read-side sync/async split - a `record_transition_sync()` method on the same class
     is the more consistent placement, keeping all registry I/O (sync and async) in one file.
   - What's unclear: whether `ic_engine.py`'s existing `_write_ic_results`/`_write_cross_sectional_results`
     module-level-function style (not class-based) argues for a matching free function instead, to
     avoid mixing service-object and free-function DB-write styles in the same call site.
   - Resolution (adopted in planning): put it on `FeatureRegistryService` as a method (matches
     `load_sync()` precedent, keeps registry-table logic colocated regardless of caller), call it
     from a small free function in `ic_engine.py` (matching that file's existing style) that does
     the gate-evaluation arithmetic and then calls `registry_svc.record_transition_sync(write_conn, ...)`.
     Implemented as such in Plan 143-02 Task 2 / Plan 143-03 Task 2.

2. **RESOLVED — Does the `feature_registry -> concept_registry` migration (D9's build trigger has fired per
   intel-14, but Concept Registry itself is not yet built per todo 058) affect this phase's
   timing?**
   - What we know: intel-14 explicitly says route through `feature_registry` now and migrate later
     "for free" if Concept Registry isn't built yet by the time this phase ships.
   - What's unclear: whether todo 058 (Concept Registry MVP seed) is scheduled to land before or
     after this phase in current sequencing.
   - Resolution (adopted in planning): route through `feature_registry` unconditionally, without a
     pre-Wave-1 todo-058 status check — this is the doc's own recommended default regardless of
     todo 058's state, so gating Wave 1 start on checking it would add a step with no decision
     branch (the action is identical either way). If Concept Registry lands later, migrate then.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB | All migrations, `feature_registry`/`integrity_monitor` reads/writes | Yes (verified live via `psql` queries during this research) | — | — |
| Python venv with psycopg2, asyncpg, structlog, opentelemetry | `ic_engine.py`, `feature_registry_service.py` edits | Yes (existing project dependencies, already imported and working in the files this phase touches) | — | — |

No new external tools, services, or runtimes are required. This phase is fully covered by the
existing project environment.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 6.0+ (`pytest.ini`), `asyncio_mode = auto`, `--strict-markers` |
| Config file | `/home/bg/dev/indicagent/pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_feature_registry_service.py tests/unit/test_ic_engine_idempotency.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIFECYCLE-00 | `regime_writer.py` flags degenerate models (occupation < `feature.hmm.min_state_occupation`) | unit | `pytest tests/unit/test_regime_writer_occupation_gate.py -x` | ❌ Wave 0 |
| LIFECYCLE-00 | `hmm_churn` computed as rolling label-change rate | unit | `pytest tests/unit/test_regime_writer_churn.py -x` | ❌ Wave 0 |
| LIFECYCLE-01 | `feature_registry` accepts `shadow_only -> active` transition given 2 passing runs + observation floor | unit | `pytest tests/unit/intelligence/test_feature_registry_service.py::TestRecordTransitionSync -x` | ❌ Wave 0 (extend existing file) |
| LIFECYCLE-01 | Automated `ic_demotion` targets `shadow_only`, never `deprecated` | unit | `pytest tests/unit/intelligence/test_feature_registry_service.py::TestRecordTransitionSync -x` | ❌ Wave 0 (same file) |
| LIFECYCLE-02 | `ensemble_trainer` filters `feature_status_at_eval = 'active'` | unit (regression - already exists) | `pytest tests/unit/test_ensemble_trainer.py -x` | ✅ (verify existing test covers this filter, no new test required unless coverage gap found) |
| LIFECYCLE-03 | ic_engine post-run hook writes exactly one `feature_transition_log` row per real transition, zero for holds | unit | `pytest tests/unit/test_ic_engine_lifecycle_hook.py -x` | ❌ Wave 0 |
| LIFECYCLE-04 | Regime-shift guard holds all weights when >= 60% of cells fail simultaneously | unit | `pytest tests/unit/test_ic_engine_lifecycle_hook.py::test_regime_shift_guard -x` | ❌ Wave 0 (same new file) |
| LIFECYCLE-05 | Staleness gauge computes correct day-count and fires alert threshold | unit | `pytest tests/unit/test_ic_engine_staleness.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/ tests/unit/test_ic_engine_*.py tests/unit/test_ensemble_trainer*.py -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_regime_writer_occupation_gate.py` - covers LIFECYCLE-00 P2b
- [ ] `tests/unit/test_regime_writer_churn.py` - covers LIFECYCLE-00 P2c
- [ ] `tests/unit/test_ic_engine_lifecycle_hook.py` - covers LIFECYCLE-03/04 (new file; mock `FeatureRegistryService.record_transition_sync` and `write_conn`)
- [ ] `tests/unit/test_ic_engine_staleness.py` - covers LIFECYCLE-05
- [ ] Extend `tests/unit/intelligence/test_feature_registry_service.py` with a `TestRecordTransitionSync` class covering the new sync method (INSERT + UPDATE transaction, rollback on error)
- [ ] No framework install needed - pytest, pytest-asyncio already present and configured

## Security Domain

`security_enforcement` is absent from `.planning/config.json`'s `workflow` block, so it is treated
as enabled per the protocol default - but this phase has essentially no attack surface to assess.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surface; internal batch job |
| V3 Session Management | No | No sessions involved |
| V4 Access Control | No | No new API endpoints or user-facing controls |
| V5 Input Validation | Marginal | New APR keys get `min_value`/`max_value` bounds in `config_schema` (existing pattern, e.g. migration 161's `0.0001, 0.10` bounds on `alpha.decay.materiality_threshold`) - apply the same bounding to `alpha.ic.staleness_alert_days` |
| V6 Cryptography | No | No secrets, keys, or crypto operations introduced |

### Known Threat Patterns for this stack

Not applicable - this phase has no external input surface (no HTTP endpoint, no user-submitted
data, no file upload). The only "input" is IC values ic_engine itself already computed and
committed earlier in the same run, read back via SQL the phase's own hook issues. Standard SQL
injection concerns are already mitigated project-wide by psycopg2/asyncpg parameterized queries
(`%(name)s` / `$1` placeholders), a pattern this phase's new code must continue (verified: every
existing query in `ic_engine.py` and `feature_registry_service.py` uses parameterized placeholders,
zero string-interpolated SQL for values).

## Sources

### Primary (HIGH confidence - direct code/DB read during this research session)

- `production/migrations/172_feature_registry.sql` - `feature_registry`/`feature_transition_log` schema, cascade trigger, seed data (61 rows)
- `production/migrations/160_ic_engine_tables.sql` - confirms `is_decaying`/`decay_detected_at`/`recovery_eligible_at` columns exist on `feature_ic_scores`
- `production/migrations/161_alpha_ic_apr_keys.sql` - confirms `alpha.decay.materiality_threshold`, `alpha.decay.regime_shift_fraction`, `alpha.decay.recovery_min_observations` already seeded
- `src/intelligence/feature_registry_service.py` - full file read; confirmed `record_transition()` is async-only, fire-and-forget, called from nowhere
- `services/ic_engine.py` - confirmed sync/psycopg2 throughout, no `BaseBatch`, hook insertion point at line ~2047-2053, `_INSERT_BODY` column list (no `is_decaying` reference in any write path)
- `services/ensemble_trainer.py` - confirmed `WHERE feature_status_at_eval = 'active'` filter exists (line 544), `class EnsembleTrainer(BaseBatch)`
- `src/core/agent/base_batch.py` - confirmed `BaseBatch` is asyncpg/async-only
- `src/observability/metrics.py` - confirmed `counter()`/`gauge()`/`point_gauge()` factory pattern, confirmed no existing `alpha_decay_*` or `ic_engine_last_run_age_days` metrics
- `docs/plans/2026-06-28-hmm-regime-audit-optimization.md` - full plan doc for LIFECYCLE-00
- `.planning/todos/pending/026-hmm-regime-audit-optimization.md` - per-item status table (verified 2026-07-04)
- `.planning/todos/pending/033-zero-ic-feature-refinement.md` and `.planning/todos/completed/034-hmm-walk-forward-refit.md`
- `docs/ideas/intel-14-integrity-monitor.md` - full doc read, reconciliation history and schema recommendation
- Live DB queries (this session): `feature_registry` status distribution (61/61 active), `integrity_monitor` non-existence, `feature_ic_scores` row/training_window_end counts for the 4 zero-IC features, `feature_vectors.momentum_rank_z` still NULL (todo 013 unshipped)
- `.planning/ROADMAP.md` lines 1632-1723 - the authoritative Phase 143 spec itself
- `.planning/STATE.md` - Phase B corpus re-run figures, cross-checked against live DB counts

### Secondary (MEDIUM confidence)

- None used - all claims in this research were verified directly against the live codebase/DB
  rather than via web search, since this phase's domain is entirely internal-codebase knowledge.

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, every pattern cited is read directly from the live files this phase touches
- Architecture: HIGH - hook insertion point, sync/async mismatch, and DAG-invariant applicability all verified by direct code read, not inference
- Pitfalls: HIGH - every pitfall listed was discovered via direct grep/DB query during this session, not hypothesized

**Research date:** 2026-07-05
**Valid until:** 14 days (internal codebase research; primary risk to staleness is another
concurrent phase landing a migration that changes the "next free migration number" or touches
`feature_registry`/`ic_engine.py` before this phase's plan executes - re-verify migration numbering
and `record_transition` call sites at plan-execution time, not just at research time)
