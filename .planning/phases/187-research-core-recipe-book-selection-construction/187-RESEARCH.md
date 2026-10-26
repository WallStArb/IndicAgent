# Phase 187 research: recipe book, selection, construction

Author: indicagent-5b research lane, 2026-10-26 (written inline; the researcher agent hit a session
limit before writing)
Informed by: `docs/plans/2026-09-26-unified-research-to-production-design.md` (sections 3.2, 4, 7,
10, 13, 14.6, 16), `.planning/ROADMAP.md` phase 187, todos 448, 459, 430, 442, 432, the live DB
(read-only, 2026-10-26) and `src/intelligence/research/` at `317d61b69`.

Status: input to `/gsd-plan-phase 187`. No CONTEXT.md: the adopted design (E18) is the decided
input; nothing here re-opens it.

## Owner decision that shapes the plan (2026-10-26)

Build-first is lifted for exactly one family 2 evidence run
(`scripts/research/run_spec.py --spec research/specs/family2_overnight_intraday.yaml`), after phase
191 plan 25 lands, so it reads final canonical 1d after the Tradier deletion; it may run in
parallel with the 186-26 rebuild. E18 counts every run as a look and plan 20 changes the 1d data
its panel reads.

Consequence: the ROADMAP gate "187 depends on family 2 finished" is a gate on the research
package being free, not on the run's outcome. No plan below needs family 2's statistic. Two
rules follow:

- Plans that edit `runner.py`, `spec.py`, `evidence.py`, `ledger.py` or the families must keep
  `repro_frozen` bit-identical and must not change family 2's spec hash, so the one run can go
  whenever 191-25 lands, before or after them.
- The family 2 run is the first attempt recorded under the new attempt schema if wave 1 has
  landed by then, otherwise it is backfilled like the family 1 runs (R-187-04).

## Requirements (derived; stable IDs)

| ID | Requirement | Design |
|---|---|---|
| R-187-01 | `concept_recipe`: append-only, versioned per concept, UPDATE/DELETE refused by trigger; recipe_hash, code pointer and commit, pinned params, APR values at pin time, inputs, universe selector, CVR codes validated, mechanism, sources, author | 10.2.2 |
| R-187-02 | Typed concept domains: feature, family, member, combiner, construction_rule, book, method; `ensemble_strategy` retired | 10.2.1 |
| R-187-03 | `research_run` becomes the attempt table: `recipe_hash`, `informed_by`, `mode` gains `exploration`, kind gains `pod_book` and `legacy_verdict`, typed headline columns | 10.2.3, 7.2 |
| R-187-04 | Full per-session D_s series stored for every counted attempt; the 21 existing runs backfilled by deterministic replay from their stored snapshot, accepted only when the replay reproduces the recorded statistic exactly | 7.2, 7.3.2 |
| R-187-05 | Runner `exploration` mode: cheap, recorded, counted, series stored | 7.2 |
| R-187-06 | Romano-Wolf StepM over the selection universe at FWER 0.05: one joint stationary-bootstrap index draw, common session calendar, per-series studentization, mean block above the longest holding horizon | 7.3.2 |
| R-187-07 | StepM validated through the E17 H0 battery (gating and diagnostic cells) before any selection uses it | todo 448 item 4, todo 432 |
| R-187-08 | E18 switch: the M = 30 per-screen Bonferroni budget (`alpha.research.budget_m`, `ledger.charged_book_tests`) is replaced by recorded attempts plus StepM selection; methodology-change-ledger entry | 7.4 |
| R-187-09 | Research stage derived by a view (idea -> specified -> registered -> tested -> refused, frozen or confirmed), never stored | 10.2.4 |
| R-187-10 | Legacy verdict import: about 20-25 summary cards (`kind = 'legacy_verdict'`), not reproducible, never re-scored | 10.2.3 |
| R-187-11 | Generated `docs/research/research-ledger.md` (do-not-edit header) rendered by a nightly job; the hand ledger retires | 10.2.6 |
| R-187-12 | `ConstructionRule` protocol over `portfolio.py` (R1, vol_normalized, ic_proportional, mean_variance, fixed_sign) | 4.3 |
| R-187-13 | Pod books: session-level sum of member books' E17 D_s, its own book type and attempt | 4.1, todo 442 |
| R-187-14 | Horizon rule (kappa partial trading), pinned in spec, with `reach` (weight below 1e-3) | 4.4 |
| R-187-15 | One `book_memory()`: member memory + combiner training reach + horizon reach; nobody types L | 4.5, todo 448 item 2, todo 442 |
| R-187-16 | Missing-member combining rule: average over available standardized members, pinned minimum count, coverage in evidence | 4.2 |
| R-187-17 | In-fold signs (EqualWeight sign from expanding training-fold IC for prior-less families) | 4.2 |
| R-187-18 | Calendar-anchored refits (`combiner.refit_positions` anchors to row 0 today) | 4.1 |
| R-187-19 | Contribution accounting: forecast-level attribution, leave-one-family-out, Shapley at 4+ families, uniqueness, breadth, accounting groups; headline numbers as typed columns | 13 |
| R-187-20 | `generated_family` grammar support in spec | 6.1 |
| R-187-21 | YAML DAG manifest; CI checks one writer per table and no cycle; `service_auditor` and the corpus orchestrator read it; `_DAG_ORDER` deleted; auditor inventory | 3.2, 14.6 item 7 |
| R-187-22 | One login role per writer with grants only on its own tables, read-only roles for readers, generated from the manifest | ROADMAP |
| R-187-23 | Research package split behind the three protocols; `runner.py` split into loading, execution, recording; renames with todo 430 step 4 (`SignalSource` -> `Predictor`) | 14.6 item 8 |
| R-187-24 | Indexes on every FK in the UCR schema (`concept_registry.parent_concept_id`, `research_run.concept_id`, `instrument_classification.scheme`) | ROADMAP |
| R-187-25 | Todo 459: composition key replaces the `tier` taxonomy; 11 HMM columns get recipe rows | ROADMAP |

## Current state (verified 2026-10-26)

| Area | State | Evidence |
|---|---|---|
| `concept_recipe` | absent | `to_regclass('concept_recipe')` null |
| `concept_registry` domains | `feature` 302, `construction` 11 split by `metadata->>'kind'` (member 4, family 1, book_version 1, unkinded 5) plus `ensemble_strategy` 5 | live query |
| `research_run` | 21 rows (20 family 1 evidence completed, 1 book_v1 refused), `mode` CHECK = 'real' only, `kind` CHECK evidence/book_test, append-only triggers, `evidence` jsonb has statistics only, no series, no recipe_hash, no informed_by | `\d research_run` |
| S6 sole writer | `ledger.PostgresLedger` (280 lines) writes `concept_registry` identity rows, `concept_parent` and `research_run`; guarded by `test_ledger_sole_writer.py` | `ledger.py:136-276` |
| M = 30 accounting | `charged_book_tests` counts book_test rows not in UNCHARGED_STATUSES; APR `alpha.research.budget_m = 30`, `screen_alpha = 0.05`, `vintage_id = vintage_1` | `ledger.py:118-133` |
| StepM | absent; `evaluate.py:378` has the Politis-Romano stationary bootstrap of Sharpe (reusable index draw) | grep |
| Runner modes | `real` and `synthetic` only | `runner.py` |
| Combiner protocol | exists: `EqualWeight`, `RidgeSpec` with `training_rows`; `refit_positions` anchored to row 0 | `combiner.py:48-167` |
| Construction | free functions in `portfolio.py` (R1 rank_vol_neutral, arm_returns/weights, mean_variance matrix, fixed_sign_returns); no protocol | `portfolio.py` |
| Book memory | runner sets `memory_sessions = max(slot_histories)`; `book.book_memory_rows` exists | `runner.py`, `book.py` |
| Snapshots | family 1 panel `logs/research/snapshots/panel_81fa9178ca4ad603` retained; per-member run JSONs in `logs/research/runs` (682 MB total) | ls |
| Specs | `book_v1`, family1 h2/h4/h8/h26, `family1_intraday_periodicity`, `family2_overnight_intraday` | `research/specs/` |
| Optional spec fields | `_OPTIONAL_PANEL_FIELDS`, `_OPTIONAL_SCORING_FIELDS`, `_OPTIONAL_COMBINER_FIELDS` | `spec.py:355-385` |
| `_DAG_ORDER` | hand-kept dict in `services/service_auditor.py:57`, used at 366, 678 | grep |
| DB roles | `postgres`, plus stale `ohlcv_observation_writer` (its table was dropped in 191-16) and `bar_derivation_writer` | `pg_roles` |
| `SignalSource` | still the research identifier (`signals.py`, `guards.py:37`) | grep |
| Hand ledger | `docs/research/construction-verdict-ledger.md`, 278 lines | wc |
| E17 battery | `scripts/research/e17_null_battery.py`, scenario cells per battery module, `--cells` filter | file |
| Next migration | 514 at research time (511-513 landed today from another session); goes stale, re-check at execution | `ls production/migrations` |

## Recommended decomposition

The scope is two phases' worth. The path to a selectable candidate book needs R-187-01..18. The
platform items (R-187-21..24) are independent of research outcomes and touch services and DB
roles, not the research package. Recommendation: keep one phase (the ROADMAP already owns the
list) but order waves so the selection path lands first and the E18 switch (R-187-08) is
recorded when wave 2 lands, not at phase close. The platform wave may later move to its own
phase without re-planning the others.

**Wave 1: attempt schema and series (unblocks everything)**
- 187-01 Migration: `concept_recipe` (append-only triggers, SCH pattern 367/368), typed domains
  (CHECK or CVR namespace), `research_run` columns `recipe_hash`, `informed_by` (FK, indexed),
  headline columns, `mode` adds `exploration`, `kind` adds `pod_book` and `legacy_verdict`;
  new `research_run_series` (run_id FK, session date array or one row per session; decide by
  size: 21 runs x ~4,000 sessions is small, thousands of exploration attempts x 4,000 is still
  under 1e8 doubles; one `float8[]` plus `date[]` per run is simplest and bit-exact); FK indexes
  (R-187-24, the three named). Ledger writes recipes and series; `test_ledger_sole_writer.py`
  allow-list extends only to the new S6-owned tables.
- 187-02 Evidence records carry the D_s series to the ledger (E17 `timing_test` already
  computes D_s per session); recorded through S6 only. Repro_frozen bit-identical; spec hashes
  unchanged.
- 187-03 Backfill: deterministic replay of the 20 family 1 evidence runs (and book_v1 if it
  produced a statistic; it was refused, so it is not counted) from `panel_81fa9178ca4ad603` at
  current code, accepted only if each replay reproduces the stored decision statistic
  bit-exactly; otherwise the run gets a disclosed `series_unavailable` flag and the gap is
  reported (never silently dropped from the universe). Writes through S6.

**Wave 2: selection (E18)**
- 187-04 StepM in `src/intelligence/statistics/stepm.py`: pure, joint index draw over a common
  session calendar, per-series studentization, block length APR key
  (`alpha.selection.stepm.*`), FWER APR key. Tests: known-answer cases, size under global null,
  monotonicity, determinism under seed.
- 187-05 StepM through the E17 H0 battery (todo 448 item 4, 432): gating and diagnostic cells;
  sized FWER at or below 0.05 before 187-06 enables it.
- 187-06 E18 switch: `exploration` mode in the runner; selection command reading the universe
  from `research_run_series`; the M = 30 budget retired (APR keys deprecated in a migration,
  `charged_book_tests` removed or kept as a disclosure count), methodology-change-ledger E18
  entry dated at landing.

**Wave 3: the book's four parts (construction that will trade)**
- 187-07 `ConstructionRule` protocol wrapping `portfolio.py` arms; R1 output byte-identical.
- 187-08 Horizon rule (kappa, `reach`), `book_memory()` summing member, combiner and horizon
  reach (todo 448 item 2, todo 442 L rule); E17 battery gains ridge and kappa cells first.
- 187-09 Combining rules: missing-member average with pinned minimum count (spec optional field),
  in-fold signs, calendar-anchored refits. Each a behavior change in its own commit with
  parity proof for existing specs (default values reproduce today's output).
- 187-10 Pod books (spec kind, runner path, attempt kind) per todo 442.

**Wave 4: recipe book content and ledger**
- 187-11 `ConceptRegistryService` on the clean schema; recipe registration at spec registration;
  research-stage view; todo 459 (composition key, CVR namespace swap, `vocabulary_drift.py`, 11
  HMM recipe rows, checked against todo 248's column names).
- 187-12 Legacy summary cards (about 20-25, from the hand ledger and the old-chain gates) and the
  generated `research-ledger.md` with its nightly render job (service registry rules: `_DAG_ORDER`
  until 187-14 lands, APR lag key, `job_completed_total`).

**Wave 5: accounting and grammar (needs a multi-family book to be useful)**
- 187-13 Contribution accounting as an S8 extension (forecast-level attribution, LOFO, Shapley
  at 4+ families, uniqueness, breadth, accounting groups) with typed headline columns.
- 187-13b `generated_family` grammar in spec (optional field) with its loader tests.

**Wave 6: platform (independent; may move to its own phase)**
- 187-14 YAML DAG manifest + CI single-writer/no-cycle check + `service_auditor` and
  `ops_corpus_pipeline_run.sh` read it; `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` hand copies deleted;
  auditor inventory; systemd timers validated against it.
- 187-15 Per-writer login roles generated from the manifest; services move off `postgres`;
  stale `ohlcv_observation_writer` role dropped. High blast radius: every daemon's DSN changes;
  stage behind a dry-run grant diff and roll service by service.
- 187-16 Research package split behind the three protocols, `runner.py` split, todo 430 step 4
  renames (`SignalSource` -> `Predictor`); last, so earlier waves do not rebase across a rename.

## Risks and rules every plan must carry

- `repro_frozen` bit-identical after any edit under `src/intelligence/research/` or
  `statistics/`; new spec fields only through `_OPTIONAL_*_FIELDS` (family 2 and family 1 spec
  hashes must not move).
- S6 stays the sole writer of `research_run` and the new attempt tables.
- Determinism of StepM: one seeded index draw; series stored bit-exact (`float8`), never
  re-derived at selection time.
- Counting: a replay for backfill (187-03) is not a new look (same snapshot, same statistic,
  verified equal); it must not create a new `research_run` row.
- Migration numbers go stale (another session is adding 511+ today); each plan re-checks at
  execution. `research_run` is not a hypertable (no compressed-column rule).
- APR: every new threshold (FWER, block length, minimum member count, kappa reach cutoff 1e-3 is
  a definition, document it as such) is a seeded key.
- Glossary: new terms (attempt, selection universe, pod book, recipe) checked against
  `docs/foundation/glossary.md`; retired terms banned.
- The 186-26 rebuild and phase 191 plans 20-25 are running in other sessions: no plan here edits
  `src/intelligence/bars/`, the fetcher or feature writers.

## Validation architecture

| Requirement | Proof |
|---|---|
| R-187-01, 03 | migration contract tests (append-only triggers refuse UPDATE/DELETE; CHECKs) |
| R-187-02 | CVR/CHECK test on domain values |
| R-187-04 | replay equality test on the family 1 snapshot (integration, DB) and a unit test of the accept/flag rule |
| R-187-05 | runner test: exploration mode records a counted attempt with series through a fake ledger |
| R-187-06, 07 | unit known-answer tests; battery run report committed in the phase dir |
| R-187-08 | ledger test: no budget refusal; E18 entry present |
| R-187-09 | view test over fixture rows |
| R-187-12..18 | byte-identical parity on existing specs plus unit tests per rule |
| R-187-19 | attribution sums to forecast covariance (exact identity test); Shapley efficiency |
| R-187-21 | CI test: one writer per table, acyclic; service_auditor reads manifest |
| R-187-22 | grant diff test (generated vs live) |
| R-187-23 | full unit suite + repro_frozen |
| R-187-24 | catalog query test for FK indexes |
| R-187-25 | vocabulary drift test, 311 numeric columns all registered |

## RESEARCH COMPLETE
