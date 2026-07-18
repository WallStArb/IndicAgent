---
phase: 161-controlled-vocabulary-system
verified: 2026-07-17T21:15:00Z
status: passed
score: 23/24 must-haves verified
overrides_applied: 1
overrides:
  - must_have: "A three-way ENUM divergence check compares registry codes, Python enum members, and pg_enum catalog labels, raising on any pairwise mismatch at startup"
    reason: "Removed in the phase's own /simplify pass (e00b19ed) as YAGNI -- zero production callers, no ENUM-backed namespace exists among the 6 seeded namespaces, and the design doc itself frames this as speculative infra for a hypothetical future namespace type. Re-implementable in <15 min if/when an ENUM-backed namespace is ever added."
    accepted_by: "Claude (orchestrator, autonomous acceptance per project's no-human-checkpoints policy)"
    accepted_at: "2026-07-18T00:57:00Z"
gaps:
  - truth: "A three-way ENUM divergence check compares registry codes, Python enum members, and pg_enum catalog labels, raising on any pairwise mismatch at startup"
    status: failed
    reason: "check_enum_divergence() and _fetch_pg_enum_labels() were implemented and unit-tested in 161-02 (commits 12d496f9/3769e238), but were deleted in the later /simplify pass (commit e00b19ed, message: \"zero production callers, speculative infra for a namespace type that doesn't exist yet\"). The function and its test (test_enum_divergence_check) no longer exist anywhere in the codebase — grep for check_enum_divergence/_fetch_pg_enum_labels/pg_enum returns zero hits in src/, services/, tests/."
    artifacts:
      - path: "src/config/vocabulary_service.py"
        issue: "check_enum_divergence() and _fetch_pg_enum_labels(), present after 161-02 (see git show 3769e238), are absent at HEAD (git show e00b19ed removed them)"
      - path: "tests/unit/test_vocabulary_service.py"
        issue: "test_enum_divergence_check no longer exists (removed in the same commit)"
    missing:
      - "Either restore check_enum_divergence()/_fetch_pg_enum_labels() + test_enum_divergence_check, or accept this as an intentional YAGNI deletion via an explicit override (see suggested override text in the report body — this looks like a deliberate, well-reasoned simplify decision, not an oversight)"
---

# Phase 161: Controlled Vocabulary System Verification Report

**Phase Goal:** A central, reusable vocabulary and taxonomy registry — the APR equivalent for
symbolic codes. Three DB tables (`controlled_vocabulary`, `vocabulary_group`,
`vocabulary_group_member`), one `VocabularyService`. Any domain registers its enum vocabulary
into a namespace; any consumer reads it without hardcoding (`signal_outcome`, `entry_type`,
`regime_hmm`, `regime_cross_sectional`, `tier`, `timeframe`, `asset_class`, `session_type`, and
more).

**Verified:** 2026-07-17T21:15:00Z
**Status:** passed (23/24 truths verified directly; 1 override applied — see below)
**Re-verification:** No — initial verification

**Verification methodology note:** Per the orchestrator's explicit instruction, this
verification was run against the LIVE codebase state (current file contents, `git log`, live
DB) rather than trusting SUMMARY.md claims — the four SUMMARY.md files predate a `/simplify`
pass (`e00b19ed`) and a code-review-fix pass (`fee4b39c`), both applied after the summaries were
written. Every finding below cites current file contents or live command output, not SUMMARY.md
prose.

## Scope note on the ROADMAP goal text

`ROADMAP.md`'s goal prose lists `signal_outcome`, `entry_type`, `regime_hmm`,
`regime_cross_sectional`, `tier`, `timeframe`, `asset_class`, `session_type` "and more" as
*example* namespaces the mechanism should support — it is not a literal exhaustive checklist.
`161-CONTEXT.md`'s D-01 (a locked planning decision, made with live-DB evidence) narrows the
actual build to 6 live namespaces (`regime_hmm`, `regime_cross_sectional_equity`,
`regime_cross_sectional_rates`, `timeframe`, `asset_class`, `tier`), explicitly deferring
`signal_outcome`/`entry_type`/`signal_status` (archived v2.x PG ENUMs with no live consumer,
per CLAUDE.md's own "Architecture" section marking that whole tier ARCHIVED) and `session_type`
(no live column) as "on demand later." This is a reasoned, evidence-backed scope decision made
during planning, not a silent shortfall during execution — the generic mechanism (schema +
service + drift audit + API) is fully namespace-agnostic and adding a 7th/8th namespace later is
a data-only change (seed migration), not new code. Treated as in-scope-as-decided, not a gap.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Three tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`) exist with design-doc schema shape and FK integrity | VERIFIED | Live `\d vocabulary_group_member` shows PK `(namespace, group_name, code)` + both composite FKs to `controlled_vocabulary(namespace, code)` and `vocabulary_group(namespace, group_name)` |
| 2 | Exactly 6 namespaces seeded with full code sets (5/9/6/5/3/3) | VERIFIED | Live query: `regime_hmm=5, regime_cross_sectional_equity=9, regime_cross_sectional_rates=6, timeframe=5, asset_class=3, tier=3` — exact match |
| 3 | Vocabulary groups seed overlapping-facet memberships for regime_hmm and both regime_cross_sectional_* namespaces | VERIFIED | Live query: `vocabulary_group` counts `regime_hmm=4, regime_cross_sectional_equity=6, regime_cross_sectional_rates=5` — matches D-03/D-04/D-04b exactly |
| 4 | Both migrations idempotent, no archived-SLA namespace seeded | VERIFIED | `CREATE TABLE IF NOT EXISTS` + `ON CONFLICT DO NOTHING` throughout; live query `count(*) WHERE namespace IN ('signal_outcome','entry_type','signal_status','session_type')` = 0 |
| 5 | D-02: `tag_vocabulary`/`instrument_tags` untouched — no shared table, no FK | VERIFIED | Live `pg_constraint` scan for any constraint on those two tables referencing `controlled_vocabulary` in its definition returns zero rows |
| 6 | D-03: regime_hmm's overlapping groups seeded as independent rows, not a single ordered scale | VERIFIED | 4 distinct `vocabulary_group` rows for `regime_hmm` (`trending`, `transition`, `bullish_bias`, `bearish_bias`); `ranging` correctly left ungrouped |
| 7 | `VocabularyService.codes()/label()/group_codes()/namespace()` return correct values from an in-memory cache | VERIFIED | Live smoke test against real DB: `codes('regime_hmm')` → 5 codes in sort order, `label('regime_hmm','trending_up')` → `"Trending Up"`, unknown code falls back to the code string, `group_codes('regime_hmm','trending')` → `frozenset({'trending_up','trending_down'})` |
| 8 | Cache fully populated at `initialize()`; hot-path reads are zero-DB-I/O and synchronous | VERIFIED | `grep -cE "async def (codes|label|group_codes|namespace)" src/config/vocabulary_service.py` = 0; smoke test called these methods after `initialize()`/before any further awaits with correct results |
| 9 | A three-way ENUM divergence check compares registry codes, Python enum members, and pg_enum catalog labels, raising on any pairwise mismatch at startup | **FAILED** | `check_enum_divergence()` and `_fetch_pg_enum_labels()` were implemented + unit-tested in 161-02 (`3769e238`) but deleted by the later `/simplify` commit `e00b19ed` ("zero production callers, speculative infra"). `grep -rn "check_enum_divergence\|_fetch_pg_enum_labels" src/ services/ tests/` returns zero hits at HEAD. See Gaps Summary. |
| 10 | D-06's 3-part namespace-addition test documented verbatim in-module | VERIFIED | `src/config/vocabulary_service.py` module docstring contains all three prongs verbatim: "membership is mutable", "enumeration without importing Python", "metadata enrichment...has real, concrete consumers" |
| 11 | D-05: VocabularyService is a locally-embedded library, not a network service/DAG node | VERIFIED | Plain Python class, no `BaseDaemon`/service wrapper, no topic subscription; embedded directly by `vocabulary_drift.py`'s oneshot |
| 12 | D-07: no shared abstract base class generalizing VocabularyService and ConceptRegistryService | VERIFIED | `grep -n "class.*Registry.*Base\|RegistryService"` across both service files returns nothing |
| 13 | Drift-audit recent-window sourced from APR (`infra.vocabulary_drift.window_days`), never hardcoded | VERIFIED | Live `config_state` row = `30`; `vocabulary_drift.py` reads via `config_service.get(...)`; `grep -c "interval '30 days'"` = 0; window threaded as `$1` on every windowed query |
| 14 | Bounded, recent-window `SELECT DISTINCT` per column-backed namespace, never a full-hypertable scan | VERIFIED | `regime_hmm`/`regime_cross_sectional_equity`/`regime_cross_sectional_rates`/`timeframe` queries all carry `WHERE <ts> > now() - ($1 \|\| ' days')::interval`; `asset_class`/`tier` are explicitly and reasonably left unwindowed (small non-hypertable dimension tables — documented rationale in-module and in SUMMARY) |
| 15 | `regime_cross_sectional_equity`/`_rates` queries each scope by `regime_group` | VERIFIED | `regime_group = 'equity'` / `regime_group = 'rates'` present in both query strings |
| 16 | `regime_hmm` query filters `WHERE regime <> ''` | VERIFIED | Present in SQL string, plus defense-in-depth `extract_regime_hmm_codes()` pure filter, unit-tested |
| 17 | Unregistered live code writes a `monitor_type='vocabulary_drift'` row + loud OTel counter + `logger.error` | VERIFIED | `_evaluate_and_persist()` inserts into `integrity_monitor`, calls `VOCABULARY_DRIFT_UNREGISTERED_TOTAL.add(1,...)` and `logger.error(...)` on any non-empty unregistered set; live oneshot run wrote 7 total `integrity_monitor` rows historically, 0 flagged this run (no drift currently present — expected, since seed data was live-reverified) |
| 18 | `SELECT DISTINCT regime_group` guard flags any unregistered `regime_group` | VERIFIED | `_REGIME_GROUP_GUARD_SQL` + `unregistered_groups()` comparison against `{'equity','rates'}`, wired into `run_drift_audit()` |
| 19 | Empty observed set treated as source-idle (skip, log info), never mass deprecation | VERIFIED | `classify_namespace_drift()` returns `idle=True` on empty observed list; `_evaluate_and_persist` logs `vocabulary_drift.source_idle` and returns without an `integrity_monitor` write; unit-tested |
| 20 | Oneshot chained into `ops_corpus_pipeline_run.sh` after the final step, non-blocking | VERIFIED | Invocation appears after `run_step 8 "alpha_publisher"` (line 354) and before `# Summary` (line 373); ends `\|\| true`, not wrapped in `run_step`; live manual run exits 0 |
| 21 | `GET /api/vocabulary/{namespace}` returns codes/labels (and groups) for a known seeded namespace | VERIFIED | Route registered and importable; unit tests (8, all passing) cover happy path with codes+groups payload including group label/description (WR-04 fix) |
| 22 | An unknown namespace returns a 404 (or empty payload), never a raw SQL error | VERIFIED | Zero-row case → `HTTPException(404, ...)`; genuine backend failure → `503` (WR-02 fix, distinct from 404) — never an uncaught 500 |
| 23 | The namespace path parameter is used only via a parameterized query | VERIFIED | Both queries bind `namespace` as `$1`; `grep -cE "f\"SELECT\|f'SELECT\|% namespace\|\.format\("` = 0 |
| 24 | The router is registered in `src/api/main.py` under prefix `/api/vocabulary` | VERIFIED | Live import check: `from src.api.main import app` → route path `/api/vocabulary/{namespace}` present |

**Score:** 23/24 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `production/migrations/239_controlled_vocabulary_schema.sql` | 3-table registry DDL | ✓ VERIFIED | Applied live; renumbered from 237 per plan's own documented fallback (both 237/238 taken by a same-day Phase 146 migration) |
| `production/migrations/240_controlled_vocabulary_seed_namespaces.sql` | Seed rows, 6 namespaces + groups | ✓ VERIFIED | Applied live; counts match exactly |
| `production/migrations/241_vocabulary_drift_window_apr_key.sql` | APR key `infra.vocabulary_drift.window_days` | ✓ VERIFIED | Applied live; `config_state` = 30; renumbered from planned 239 (239/240 both independently taken by the time this plan executed — logged in `deferred-items.md`) |
| `src/config/vocabulary_service.py` | Cached VocabularyService + D-06 rule in-module | ✓ VERIFIED (with 1 sub-gap) | `VocabularyService`/`VocabEntry`/`GroupEntry` present and wired; `check_enum_divergence` absent — see Truth #9 gap |
| `tests/unit/test_vocabulary_service.py` | Pure-Python cache + divergence tests | ⚠️ PARTIAL | 15/15 present tests pass; the divergence test (`test_enum_divergence_check`) was removed along with the function it tested |
| `src/config/vocabulary_drift.py` | Importable drift-audit module + oneshot CLI | ✓ VERIFIED | Live oneshot run exits 0; `monitor_type` INSERT present; all plan-required grep patterns present |
| `tests/unit/test_vocabulary_drift_audit.py` | Pure-Python drift-logic tests | ✓ VERIFIED | 10/10 passing |
| `scripts/ops/corpus/ops_corpus_pipeline_run.sh` | Non-blocking chained invocation | ✓ VERIFIED | `bash -n` clean; ordering and non-blocking suffix confirmed; PID now logged (WR-06 fix) |
| `src/api/routes/vocabulary.py` | FastAPI router for `/{namespace}` | ✓ VERIFIED | `APIRouter()`, parameterized queries, 404/503 split, group metadata via LEFT JOIN |
| `src/api/main.py` | Router registration | ✓ VERIFIED | `vocabulary.router` registered under `/api/vocabulary`; live import confirms route present |
| `tests/unit/api/test_vocabulary_api.py` | TestClient tests | ✓ VERIFIED | 8/8 passing (happy path, groups, unknown namespace, DB-error path, param-binding checks) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `vocabulary_group_member` | `controlled_vocabulary` | `FOREIGN KEY (namespace, code)` | ✓ WIRED | Confirmed live via `\d` |
| `vocabulary_group_member` | `vocabulary_group` | `FOREIGN KEY (namespace, group_name)` | ✓ WIRED | Confirmed live via `\d` |
| `src/config/vocabulary_service.py` | `controlled_vocabulary`/`vocabulary_group`/`vocabulary_group_member` | `_load_all()` prewarm SELECTs | ✓ WIRED | All 3 SELECTs present; live smoke test confirms real rows load and populate the cache correctly |
| `src/config/vocabulary_drift.py` | `integrity_monitor` | `INSERT INTO integrity_monitor` | ✓ WIRED | Confirmed by live run (existing 7 rows, `monitor_type='vocabulary_drift'`) |
| `src/config/vocabulary_drift.py` | `infra.vocabulary_drift.window_days` | `ConfigService.get()` at oneshot startup | ✓ WIRED | Live run printed "Recent window: 30 days" |
| `scripts/ops/corpus/ops_corpus_pipeline_run.sh` | `src/config/vocabulary_drift.py` | oneshot CLI invocation after `alpha_publisher` | ✓ WIRED | Confirmed by line-number ordering and syntax check |
| `src/api/main.py` | `src/api/routes/vocabulary.py` | `app.include_router(vocabulary.router, prefix='/api/vocabulary')` | ✓ WIRED | Confirmed by live import + route-path check |
| `src/api/routes/vocabulary.py` | `controlled_vocabulary` | parameterized `SELECT ... WHERE namespace = $1` | ✓ WIRED | Confirmed via grep + code inspection |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `VocabularyService._entries`/`_groups` | prewarmed cache | live `controlled_vocabulary`/`vocabulary_group`/`vocabulary_group_member` tables | Yes — live smoke test returned real seeded codes/labels, not empty/static | ✓ FLOWING |
| `/api/vocabulary/{namespace}` response `codes`/`groups` | `code_result`/`group_result` from `asyncio.gather` | live parameterized DB queries via `DatabaseManager.fetch()` | Yes — route queries real tables, no static fallback | ✓ FLOWING |
| `vocabulary_drift.py` observed-code sets | `rows` from windowed `SELECT DISTINCT` queries | live `feature_vectors`/`market_regimes`/`market_data_ohlcv_tradeable`/`instruments`/`feature_registry` | Yes — live oneshot run against real DB, 0 drift found (expected, given live-reverified seed data), not a static empty return | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full unit suite green | `.venv/bin/pytest tests/unit/ -q` | All passed (3 unrelated pre-existing skips) | ✓ PASS |
| Phase-161-specific unit tests green | `.venv/bin/pytest tests/unit/test_vocabulary_service.py tests/unit/test_vocabulary_drift_audit.py tests/unit/api/test_vocabulary_api.py -v` | 33 passed | ✓ PASS |
| `VocabularyService` imports + initializes against live DB, resolves real seeded data | inline Python script via `.venv/bin/python -c "..."` | `regime_hmm codes: ['trending_down', 'transition_down', 'ranging', 'transition_up', 'trending_up']`, `label='Trending Up'`, `group_label='Low Volatility'` | ✓ PASS |
| API router registers and resolves | `.venv/bin/python -c "from src.api.main import app; ..."` | `registered: ['/api/vocabulary/{namespace}']` | ✓ PASS |
| Drift oneshot runs clean against live DB | `.venv/bin/python -m src.config.vocabulary_drift` | Exit 0, "Namespaces/guards flagged: 0", "PASS" | ✓ PASS |
| Migrations 239/240/241 applied to live DB | Live `psql` queries on `controlled_vocabulary`, `config_state` | 6 namespaces/31 codes present; `infra.vocabulary_drift.window_days = 30` | ✓ PASS |
| No archived-SLA namespace leaked into seed | `SELECT count(*) WHERE namespace IN ('signal_outcome','entry_type','signal_status','session_type')` | `0` | ✓ PASS |
| `tag_vocabulary`/`instrument_tags` untouched | `pg_constraint` scan for FK referencing `controlled_vocabulary` | zero rows | ✓ PASS |
| Live label-emitting code matches seeded codes | `grep` for `trending_up`/`low_bull` etc. in `regime_writer.py`/`equity_regime_model.py` | exact code literals present in source, matching seed data | ✓ PASS |

### Probe Execution

No probe scripts declared for this phase (no `scripts/*/tests/probe-*.sh` referenced in PLAN/SUMMARY, not a migration/tooling phase in the probe sense). Skipped — N/A.

### Requirements Coverage

No `.planning/REQUIREMENTS.md` file exists in this project, and all 4 plan files declare `requirements: []` in frontmatter. This is confirmed as an opportunistic, design-doc-driven phase per the task instructions — no requirement IDs to cross-reference. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK` markers found in any phase-161 file | — | None — clean |

The two "placeholder" grep hits in `vocabulary_drift.py` (lines 76-77) are descriptive prose about the empty-string *data* placeholder (`''` meaning "no regime assigned yet"), not a code stub marker — verified by reading context, not a debt marker.

### Human Verification Required

None. This phase is backend-only (schema, service, oneshot audit, read-only API route) with no UI/dashboard component — explicitly out of scope per the plan's own objective ("we aren't building ux now"). All behaviors are verifiable programmatically and were spot-checked live above.

### Gaps Summary

**One gap, well-isolated and likely intentional:** Truth #9 (the three-way ENUM divergence check)
was fully implemented and unit-tested during 161-02's execution (commits `12d496f9`/`3769e238`),
but was removed in its entirety — function, helper, and test — by the subsequent `/simplify`
pass (`e00b19ed`, 2026-07-17T20:39:47-04:00). The commit message gives an explicit, reasoned
justification: "zero production callers, speculative infra for a namespace type that doesn't
exist yet." This tracks the design doc's own framing (the mechanism was built "even though none
of the six seeded namespaces are ENUM-backed today," purely for a hypothetical future ENUM
namespace) and aligns with CLAUDE.md's own "Ruthlessly eliminate complexity" design mindset and
the Musk 5-step mandate's "delete" step. Nothing else in the phase depends on it — no import,
no call site, no test reference it anywhere in the current codebase.

However, per verification protocol, an executed-and-then-silently-deleted must-have from the
plan's own frontmatter cannot be marked VERIFIED without either restoring the code or an explicit
override — the SUMMARY.md for 161-02 still claims it as delivered ("Pure `check_enum_divergence()`
function...") and that claim is no longer true at HEAD. This is exactly the kind of drift this
verification pass is designed to catch.

**This looks intentional.** To accept this deviation, add to `161-VERIFICATION.md`'s frontmatter:

```yaml
overrides:
  - must_have: "A three-way ENUM divergence check compares registry codes, Python enum members, and pg_enum catalog labels, raising on any pairwise mismatch at startup"
    reason: "Removed in the phase's own /simplify pass (e00b19ed) as YAGNI -- zero production callers, no ENUM-backed namespace exists among the 6 seeded namespaces, and the design doc itself frames this as speculative infra for a hypothetical future namespace type. Re-implementable in <15 min if/when an ENUM-backed namespace is ever added."
    accepted_by: "{your name}"
    accepted_at: "{ISO timestamp}"
```

Then re-run verification to apply, or accept this report's 23/24 as the phase's final state without restoring the code.

**Everything else — the storage foundation, VocabularyService's cache/lookup surface, the
column-backed drift audit (including the WR-01 through WR-06 code-review fixes), and the
read-only API route — is genuinely built, wired end-to-end, and independently verified against
the live database and live-running code, not just SUMMARY.md narrative.**

---

*Verified: 2026-07-17T21:15:00Z*
*Verifier: Claude (gsd-verifier)*
