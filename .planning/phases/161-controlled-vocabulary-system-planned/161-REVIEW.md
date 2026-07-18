---
phase: 161-controlled-vocabulary-system-planned
reviewed: 2026-07-18T00:50:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - production/migrations/239_controlled_vocabulary_schema.sql
  - production/migrations/240_controlled_vocabulary_seed_namespaces.sql
  - production/migrations/241_vocabulary_drift_window_apr_key.sql
  - src/config/vocabulary_service.py
  - tests/unit/test_vocabulary_service.py
  - src/config/vocabulary_drift.py
  - tests/unit/test_vocabulary_drift_audit.py
  - scripts/ops/corpus/ops_corpus_pipeline_run.sh
  - src/api/routes/vocabulary.py
  - tests/unit/api/test_vocabulary_api.py
  - src/api/main.py
findings:
  critical: 0
  warning: 6
  info: 2
  total: 8
status: issues_found
---

# Phase 161: Code Review Report

**Reviewed:** 2026-07-18T00:50:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the Controlled Vocabulary System (three-table schema, `VocabularyService` cache,
column-backed `vocabulary_drift` audit oneshot, and the read-only `/api/vocabulary/{namespace}`
route) after the `/simplify` pass already cleaned up dead code, query dedup, pool creation, and
concurrent API queries.

I applied migrations 239-241 against the live DB (already applied), ran
`python -m src.config.vocabulary_drift` against the live schema (clean pass, 7
`integrity_monitor` rows written correctly), cross-checked every seeded `(namespace, code)`
against the actual label-emitting code in `regime_writer.py`, `breadth_vol.py`, and
`curve_credit.py` (all match exactly), verified the FK-crossed group-membership seed data
programmatically (no typos), imported `src.api.main` and confirmed `/api/vocabulary/{namespace}`
registers correctly, and ran the full unit suite for the three new test files (25/25 green).
No blockers found — the SQL, migrations, and seed data are all correct and independently
verified against the live database. The issues below are real robustness/completeness gaps,
not currently-manifesting breakage: a startup crash mode that requires a precondition the
codebase doesn't currently create, information-disclosure-by-design tradeoffs in the API's
error handling, and a data-completeness gap around vocabulary group metadata that undermines
the module's own stated purpose.

## Warnings

### WR-01: `VocabularyService._load_all()` can raise an unguarded `KeyError` on startup if group tables are ever written concurrently with a read

**File:** `src/config/vocabulary_service.py:84-113`
**Issue:** `_load_all()` issues three separate `SELECT`s over the same acquired connection
with no explicit transaction/consistent snapshot:
```python
async with self._db_pool.acquire() as conn:
    entry_rows = await conn.fetch(...)
    group_rows = await conn.fetch("SELECT namespace, group_name FROM vocabulary_group")
    member_rows = await conn.fetch(
        "SELECT namespace, group_name, code FROM vocabulary_group_member"
    )
```
`group_members` is then seeded only from `group_rows`, and the `member_rows` loop indexes into
it unconditionally:
```python
group_members: dict[tuple[str, str], set[str]] = {
    (row["namespace"], row["group_name"]): set() for row in group_rows
}
for row in member_rows:
    key = (row["namespace"], row["group_name"])
    group_members[key].add(row["code"])  # KeyError if key not in group_members
```
Under READ COMMITTED (asyncpg/Postgres default), each `await conn.fetch()` sees its own latest
committed snapshot at execution time. If a `vocabulary_group` + `vocabulary_group_member` pair
is inserted and committed *between* the `group_rows` fetch and the `member_rows` fetch, the new
member row's `(namespace, group_name)` key won't be in `group_members` yet, and
`group_members[key].add(...)` raises `KeyError`, crashing `initialize()` (and thus the calling
daemon's startup, since this mirrors `ConfigService`'s "must succeed at boot" pattern). The
`/simplify` commit (`e00b19ed`) removed a `setdefault` here on the reasoning "FK guarantees the
key already exists" — true for a single transactional snapshot, not across three sequential
reads on one connection. Today no code path performs runtime INSERTs into these tables (they're
documented as migration-time-only writers), so this is latent, not currently triggered — but
it's a real crash mode with no defensive handling, unlike the entries loop just above it
(`entries.setdefault(namespace, {})[...]`) which does still guard against a missing key.
**Fix:** Either wrap the three fetches in a single explicit transaction (`async with
conn.transaction():` at minimum `REPEATABLE READ`) to guarantee one consistent snapshot, or
restore the defensive `group_members.setdefault(key, set()).add(row["code"])` in the member-row
loop — cheap insurance against a table-write invariant that's convention-enforced, not
DB-enforced (no immutability constraint on `vocabulary_group`/`vocabulary_group_member`).

### WR-02: API route masks all DB/backend errors as "unknown namespace" 404s, indistinguishable from genuine invalid input

**File:** `src/api/routes/vocabulary.py:56-66`
**Issue:**
```python
if isinstance(code_result, BaseException):
    logger.warning(...)
    raise HTTPException(status_code=404, detail=f"Unknown namespace: {namespace}") from code_result
```
Any exception from the `controlled_vocabulary` query — connection pool exhaustion, DB
unreachable, query timeout, a genuine bug — is reported to the client as `404 Unknown
namespace: {namespace}`, identical to the case where the namespace genuinely doesn't exist.
This is a deliberate T-161-07 information-disclosure mitigation per the plan, but it has a real
operational cost: external consumers/monitors cannot distinguish "this namespace was never
registered" (a client-side error, don't retry) from "the backend is currently broken" (a
server-side error, retry / page someone). A transient DB blip during a namespace lookup for a
namespace that genuinely exists will incorrectly read as a permanent 404 to any caller, with no
signal to retry.
**Fix:** Keep the redacted client-facing message, but use a distinct status for the two cases —
e.g. `503`/`502` for `isinstance(code_result, BaseException)` (backend failure) vs `404` only
for the genuinely-empty-rows case. The `logger.warning` already captures the real error
server-side; the client-visible status code should carry the same distinction.

### WR-03: Group-fetch failure silently degrades to `groups: {}` instead of surfacing a partial-failure signal

**File:** `src/api/routes/vocabulary.py:68-76`
**Issue:**
```python
if isinstance(group_result, BaseException):
    logger.warning(...)
    group_rows = []
else:
    group_rows = group_result
```
If the `vocabulary_group_member` query fails (pool exhaustion, timeout) while the
`controlled_vocabulary` query succeeds, the endpoint returns a `200` with `"groups": {}` —
indistinguishable from a namespace that genuinely has no groups (e.g. `timeframe`,
`asset_class`, `tier`). A caller has no way to tell "this namespace has no groups" from "the
groups query happened to fail this request." The failure is logged server-side but invisible to
the client.
**Fix:** Either propagate a `5xx` on a genuine group-query failure (fail closed, matching the
`code_result` branch's philosophy) or add an explicit `"groups_available": false` flag to the
response body when `group_result` was an exception, so callers can distinguish the two states.

### WR-04: `vocabulary_group.label`/`.description`/`.sort_order` are seeded but never read by any consumer

**File:** `src/config/vocabulary_service.py:90`, `src/api/routes/vocabulary.py:49-52`
**Issue:** Migration 240 seeds real, human-readable content into
`vocabulary_group(label, description, sort_order)` for all 3 seeded groupings (e.g.
`('regime_cross_sectional_equity', 'low_vol', 'Low Volatility', 'Low cross-sectional volatility
tier (all directions)', 1)`). Neither `VocabularyService._load_all()`'s group query
(`SELECT namespace, group_name FROM vocabulary_group` — only 2 of 5 columns) nor the API
route's group query (`SELECT group_name, code FROM vocabulary_group_member` — doesn't touch
`vocabulary_group` at all) ever reads those 3 columns back. `group_codes()` returns a bare
`frozenset[str]` with no label/description accessor, and the API's `groups` field is a raw
`{group_name: [codes]}` map with no human-readable label. This directly undercuts the module's
own stated purpose — the file header docstring for `vocabulary.py` says the endpoint "[l]ets any
external consumer enumerate a namespace's codes/labels/groups over HTTP without importing Python
or hardcoding labels" — but a group's own label (e.g. "Low Volatility" for `low_vol`) is
unreachable through either code path; only the flat code labels are exposed.
**Fix:** Add `group_label(namespace, group_name) -> str` to `VocabularyService` (mirroring
`label()`), extend `_load_all()`'s group query to select `label, description, sort_order`, and
extend the API response to include per-group metadata (e.g. `groups: {group_name: {label,
description, codes: [...]}}` instead of a bare code list) — otherwise drop the unused columns
from the schema rather than carrying dead seed data.

### WR-05: API's group listing silently omits any group with zero members, inconsistent with `VocabularyService.group_codes()`'s explicit handling of that case

**File:** `src/api/routes/vocabulary.py:49-52, 89-91`
**Issue:** The API route builds its `groups` dict purely from `vocabulary_group_member` rows:
```python
db_manager.fetch(
    "SELECT group_name, code FROM vocabulary_group_member WHERE namespace = $1", namespace
)
...
groups: dict[str, list[str]] = {}
for row in group_rows:
    groups.setdefault(row["group_name"], []).append(row["code"])
```
A `vocabulary_group` row that currently has zero `vocabulary_group_member` rows (a legitimate,
FK-valid state — nothing prevents defining a group before assigning members to it) would never
appear as a key in this dict at all — not even with an empty list. Compare
`VocabularyService.group_codes()` (`src/config/vocabulary_service.py:131-133`), which explicitly
pre-seeds every registered `(namespace, group_name)` with an empty `frozenset()` precisely so a
real-but-empty group is distinguishable from an unknown one (per that file's own comment at
lines 106-107). The API route has no equivalent handling and doesn't even query
`vocabulary_group` — the two consumers of the same underlying data model disagree on how a
zero-member group is represented. Currently moot (every seeded group has ≥2 members), but a
future group added without members yet would be invisible via the API despite existing.
**Fix:** Have the API route also query `vocabulary_group` for the namespace and seed `groups`
with an empty list for every group row before folding in member rows, matching
`VocabularyService`'s pattern.

### WR-06: Backgrounded vocabulary-drift step in the corpus pipeline has no supervision — a killed process group silently drops it with zero signal

**File:** `scripts/ops/corpus/ops_corpus_pipeline_run.sh:358-367`
**Issue:**
```bash
( "$PYTHON" -m src.config.vocabulary_drift \
    2>&1 | tee -a "$LOG_DIR/vocabulary_drift_$(date +%Y%m%d_%H%M%S).log" || true ) &
```
The audit is launched as a detached background job with no `wait`, no captured PID, and no
`disown`/`setsid`. Under a plain `bash script.sh` invocation this is harmless (background jobs
survive the parent's normal exit, reparented to init). But if this script is ever invoked in a
context that tears down the whole process group on completion — a supervising wrapper, a CI
runner, an SSH one-liner (`ssh host 'bash script.sh'`, which under some SSH server
configurations sends SIGHUP to the whole session's process group on disconnect), or a future
systemd unit with `KillMode=control-group` — the backgrounded subshell is killed mid-run along
with the parent, and the pipeline's own output has already printed "Pipeline complete" with no
indication the drift audit didn't finish. Since `D-09` deliberately makes this observability-only
and non-gating, a silently-dropped run means taxonomy drift goes undetected for a full pipeline
cycle with zero operator-visible signal (the only trace is a truncated/missing log file under
`$LOG_DIR`, which nothing checks).
**Fix:** At minimum, capture the PID and log a one-line note with it (`echo "drift audit PID:
$!"`), or use `disown` to explicitly detach it from job control, or run it via `nohup` up front.
None of these change the non-blocking design; they just make an unexpectedly-killed run visible
after the fact instead of leaving no trace.

## Info

### IN-01: Migration 239 shares its number with an unrelated migration (`239_ic_engine_cross_sectional_bootstrap_threads.sql`)

**File:** `production/migrations/239_controlled_vocabulary_schema.sql:1-8`
**Issue:** Both `239_controlled_vocabulary_schema.sql` and
`239_ic_engine_cross_sectional_bootstrap_threads.sql` exist simultaneously in
`production/migrations/`. The migration's own header comment acknowledges this as a genuine,
pre-existing collision "out of scope for this plan to fix." I independently verified this is
functionally harmless: `scripts/infrastructure/setup/infrastructure_db_setup.sh` applies every
`[0-9][0-9][0-9]_*.sql` file by filename glob + sort (not by tracking a numeric migration
version in a `schema_migrations` table — that table doesn't exist anywhere in this codebase
despite being referenced in `docs/operations/operations-database.md`), and each file is
independently idempotent (`CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO NOTHING`), so both `239_`
files apply in full regardless of the shared number. Purely a naming-hygiene issue for future
readers/tooling that might assume migration numbers are unique identifiers, not a deployment
risk today.
**Fix:** No action required for correctness. If migration numbering is ever formalized with an
actual version-tracking table, renumber one of the two `239_` files first.

### IN-02: `VocabularyService.codes()`/`namespace()` return deprecated codes with no filtered accessor

**File:** `src/config/vocabulary_service.py:122-137`
**Issue:** `codes(namespace)` and `namespace(namespace)` return every cached entry regardless of
`is_deprecated`. No seeded row currently has `is_deprecated=true`, so this doesn't manifest today,
but the schema clearly anticipates deprecation (`is_deprecated BOOLEAN NOT NULL DEFAULT FALSE` in
migration 239), and there's no `active_codes()`/`active_only=True` convenience the way many
enumeration APIs provide. Every caller that wants "codes valid for new use" must remember to
filter on `.is_deprecated` themselves (the API route does expose the flag per-code, so a client
technically can filter — but `VocabularyService`'s own synchronous readers, used by any Python
consumer, cannot).
**Fix:** Consider an `active_codes(namespace) -> list[str]` convenience method, or document on
`codes()`/`namespace()` that deprecated entries are included by design and callers must filter.

---

_Reviewed: 2026-07-18T00:50:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
