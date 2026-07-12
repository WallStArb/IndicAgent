---
**Created:** 2026-07-10
**Completed:** 2026-07-12
**Area:** infrastructure
**Type:** correctness
**Priority:** P1 (real fresh-install risk, not just doc drift)
**Effort:** S-M — mostly documentation correction + a handful of file/script changes
**Benefit:** Fixes a genuine "fresh install may fail" risk, and closes a naming-convention doc
that has been silently wrong for over a month
**Risk:** low to fix (once the right direction is chosen); the current state is what carries risk
---

## Resolution (2026-07-12)

Fixed per the recommended plan below, with one scope adjustment:

1. **Docs corrected** — `naming-system.md` §11, `naming-conventions.md`, `development/setup.md`
   now state `production/migrations/` is the sole canonical home. Also found and fixed the same
   `db/migrations/` mislabeling in 6 more docs (`signal-ledger-architecture.md`,
   `extrinsic-confidence-layer.md`, `adaptive-parameter-registry.md`, `signals-schema.md`,
   `signals-ecl.md`, `signals-foundation.md`, `operations-database.md`) — their `src:` provenance
   comments pointed at `db/migrations/NNN_*.sql` for files that actually live in
   `production/migrations/NNN_*.sql` under the same number. `docs/plans/archive/*.md` and the
   `.planning/phases/142.5-*` plan files were left untouched — they're historical records
   describing a past mistake and its fix accurately, not a live wrong convention.
2. **`db/migrations/` resolved, not just deleted** — verified before deleting (per this project's
   "verify then delete, don't flag" convention): `001_baseline.sql` was confirmed abandoned/never
   applied (production/migrations already independently built the schema from 001 onward) and
   removed. `120_instrument_tag_vocabulary.sql` and `121_instrument_tag_vocabulary_v2.sql` were
   confirmed genuinely applied (their tables — `instrument_tags`, `tag_vocabulary` — exist live,
   with no duplicate content anywhere in `production/migrations/`), so they were renamed/moved
   into `production/migrations/` as `227_instrument_tag_vocabulary.sql` and
   `228_instrument_tag_vocabulary_v2.sql` rather than deleted, preserving real applied history.
   The now-empty `db/migrations/` directory was removed.
3. **`infrastructure_db_setup.sh` fixed** — dropped the `db/migrations/` glob entirely; also
   fixed the sort key while in there (`sort -t/ -k1,1` was comparing only the common path prefix
   across two directories, not actually sorting by migration number — moot now with one
   directory, but was a latent bug).
4. **Scope adjustment on the `001` duplicate:** confirming both `001_*` files and renumbering one,
   as originally scoped, uncovered that `production/migrations/` actually has **13** duplicate-
   number groups (001, 031, 038, 050, 051, 052, 064, 138, 152, 168, 178, 214, 215 — several with
   3 files), not just the one this todo knew about. Renumbering already-applied migrations at
   that scale is a materially different risk profile than todo 095's original 3-doc-correction
   scope — deliberately NOT attempted inline. Filed as its own scoped follow-up:
   [todo 101](../pending/101-migration-duplicate-number-sweep.md).

# 095 — `db/migrations/` vs `production/migrations/` split: stale docs, real number collisions,
likely-broken fresh install

**Found:** 2026-07-10, during a naming/conventions review prompted by the project owner
("review names to make sure they follow our Renaissance conventions") — checking
`docs/foundation/naming-system.md` §11 (Operational Files) against actual repo state.

## What the docs claim vs. what's actually true

Three docs consistently state the same claim:

- `docs/foundation/naming-system.md` §11: `db/migrations/` = "Canonical home for all migrations
  Phase 104+"; `production/migrations/` = "Legacy home, frozen... No new files."
- `docs/reference/naming-conventions.md:232`: same claim.
- `docs/development/setup.md:81,212`: same claim, plus states the setup script applies
  `production/migrations/` (legacy, 001-103) *then* `db/migrations/` (canonical, Phase 104+).

**Actual repo state contradicts all three:**

| | `production/migrations/` | `db/migrations/` |
|---|---|---|
| File count | 213 | 3 |
| Highest number | 220 (added today, todo 061) | 121 |
| Last modified | 2026-07-10 (today) | 2026-06-06 (34 days stale) |
| Referenced by other docs | Dozens (grep count much higher) | Handful |

`production/migrations/` has been the sole actively-used directory this entire time, well past
migration 103. `db/migrations/` was a real, deliberate consolidation attempt — commit `33f4630e`
("db(migrations): add baseline schema dump — 51 tables, captures full schema pre-092") squashed
migrations 1-91 into a single `001_baseline.sql` pg_dump snapshot, and `e9468c7f` removed
migrations 92-96 as "absorbed into 001_baseline" — but the cutover was never completed.
`production/migrations/` kept receiving new files in parallel (it's up to 220 now), and nobody
ever finished migrating tooling/docs to treat `db/migrations/` as authoritative. The attempt
stalled after 3 files and has been silently abandoned for over a month.

## Confirmed real collision (not just stale docs)

`production/migrations/` itself has a numbering collision: **two files both numbered `001_`**
(`001_create_features_intelligence.sql` and `001_timescale_schema.sql` — pre-dates this todo,
unrelated to the `db/migrations/` split). Separately, `db/migrations/120_instrument_tag_vocabulary.sql`
and `production/migrations/120_signal_probe_results.sql` are two completely different migrations
sharing number 120 — same for 121. Per naming-system.md §11 itself: "Duplicate numbers are a
violation — they are the artifact of parallel development without coordination and must be
resolved." This is that exact violation.

## Real risk, not cosmetic

`scripts/infrastructure/setup/infrastructure_db_setup.sh` applies **both** directories' globs in
sequence (`production/migrations/[0-9][0-9][0-9]_*.sql` then `db/migrations/[0-9][0-9][0-9]_*.sql`).
A genuinely fresh install today would run all 213 `production/migrations/` files (building the
full current schema incrementally), then hit `db/migrations/001_baseline.sql` — a raw `pg_dump`
snapshot of the pre-092 schema — which would very likely error trying to recreate tables that
already exist (pg_dump-generated `CREATE TABLE` is not `IF NOT EXISTS` by default). This wasn't
tested end-to-end as part of this finding (didn't want to risk the live DB or spin up a scratch
instance mid-session) — but the mechanism is clear enough to flag as a real risk, not a hypothetical
one. `db/migrations/001_baseline.sql` is also, separately, exactly the "Schema Reference File"
pattern naming-system.md §11 bans elsewhere in the same section ("No schema snapshot files... a
snapshot that is not continuously maintained diverges from reality and becomes noise") — it's
banned twice over, once as a stale snapshot and once as a migration-numbering collision.

## Recommended fix

Given 213 files already exist in `production/migrations/` (the directory actually in continuous
use, referenced everywhere) vs. 3 abandoned files in `db/migrations/`, the pragmatic and
lower-risk fix is the reverse of what the docs currently claim:

1. **Correct the three docs** (`naming-system.md` §11, `naming-conventions.md`,
   `development/setup.md`) to state `production/migrations/` is canonical, not legacy/frozen.
2. **Resolve `db/migrations/`**: either delete it outright (git history preserves the squash
   attempt) or, if the baseline-squash idea has future value, file a *separate*, deliberately
   scoped effort to actually complete a migration-history squash — don't leave a half-finished
   attempt masquerading as the current convention.
3. **Fix `infrastructure_db_setup.sh`** to stop globbing `db/migrations/` once (2) is resolved,
   so a fresh install is no longer at risk of the collision described above.
4. Resolve the pre-existing `production/migrations/001_*` duplicate-number issue while in this
   territory (two files both claim `001`) — confirm both are still needed and renumber one if so.

**Do not attempt the "complete the squash to db/migrations/" alternative without a dedicated,
scoped plan** — moving 213 files and rewriting every doc reference is a much larger, riskier
undertaking than correcting three docs to match 34-plus days of actual practice.

**Gate:** none — runs against the current repo state today. Recommend doing this before the next
fresh install/disaster-recovery scenario actually needs `infrastructure_db_setup.sh` to work
correctly, since that's exactly when this would surface as a hard failure instead of a
documentation inconsistency.
