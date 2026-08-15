"""CI guard: a migration that decompresses+recompresses a hypertable must VACUUM after.

compress_chunk() doesn't synchronously reclaim the decompressed heap pages a prior
decompress_chunk() populated -- any migration doing decompress_chunk() -> DDL (ALTER
COLUMN TYPE / DROP COLUMN) -> compress_chunk() on a compressed hypertable without a
trailing bare `VACUUM <table>;` leaves the full pre-migration footprint on disk under
the new compressed data. Confirmed three separate times on feature_vectors alone:
migration 201, migration 312 (turned into a 768GB disk-full incident, see
project_disk_full_incident_2026_08_13 memory and
docs/foundation/timescaledb-compressed-column-migration.md), and migration 202. The
remediation before this guard existed was human copy-paste discipline ("the next one of
these migrations will copy from 201 or 312 as a template") -- the same mechanism that
let 312 repeat 201's omission, and let 202 slip through despite predating both
chronologically. Todo 305.

Detection: a migration file "does the round trip" if it contains an uncommented
decompress_chunk( call AND an uncommented compress_chunk( call (this repo's own
established idiom is always PERFORM/SELECT decompress_chunk(...) in a loop over every
chunk, once per migration -- not a per-column repeated pattern; see 201/312's own
`DO $$ ... PERFORM decompress_chunk(c.chunk) ... $$` shape). Table-scoped, matching
todo 305's own spec ("a decompress_chunk( call followed by a compress_chunk( call ON
THE SAME TABLE without an intervening VACUUM"): the repo's established idiom always
selects the target chunks via `WHERE hypertable_name = '<name>'` inside the SAME
`DO $$ ... $$;` block as the decompress_chunk(/compress_chunk( call, so table names are
extracted per-DO-block, not from the file as a whole -- an unrelated `hypertable_name =
'other_table'` diagnostic query living outside any decompress/compress block is not
picked up (would otherwise false-positive a fully compliant migration that merely
mentions another table elsewhere), and a table round-tripped via a different
chunk-selection idiom entirely (no `hypertable_name` literal anywhere near the call)
isn't masked by an unrelated table's own compliant VACUUM elsewhere in the file (would
otherwise false-negative). Every name extracted this way must have its own matching
`VACUUM <name>;` -- a migration that round-trips two different hypertables and VACUUMs
only one is still a violation, not silently passed because *some* VACUUM exists in the
file. If no `DO` block contains BOTH a `hypertable_name = '...'` literal AND a
decompress_chunk(/compress_chunk( call (a future migration using a different
chunk-selection idiom entirely), falls back to the weaker "some bare VACUUM exists
anywhere" check rather than passing silently with no check at all.

It must also contain a bare top-level `VACUUM <table>;` statement (compress_chunk()
moves rows into the compressed columnar store but does not synchronously reclaim the
decompressed heap pages -- only a VACUUM does, and it cannot run inside the migration's
own transaction block, so it must be a bare statement, never wrapped in BEGIN/COMMIT).

A migration that only decompresses without a matching compress_chunk (e.g. leaves
compression to a later policy pass instead of recompressing synchronously -- migration
005's shape) is not this guard's concern: no synchronous recompress happens in that
file, so it leaves no decompressed-heap-page bloat behind for that migration to answer
for.

Swept the full repo history for this pattern while filing this guard (not just the 3
known instances): 10 migrations mention decompress_chunk at all; 6 are either a false
match with no matching compress_chunk (005) or the pattern discussed only in a comment,
never executed (146, 242, and the ADD-COLUMN-only 255/266/267, which mention the
206-pattern in their own headers for context). Only 201/202/312 do the real round trip,
each against a single table (feature_vectors), and all three already carry a matching
VACUUM -- zero live violations as of writing; this guard exists to keep it that way.

No allow-list (unlike this file's model, test_market_data_ohlcv_boundary.py): that guard
has ~13 genuinely legitimate raw-table readers to carve out. This one doesn't -- the
missing-VACUUM step has no legitimate exception (CLAUDE.md states it as mandatory, full
stop), so there's nothing for an escape hatch to serve. A direct `assert not hits` is the
whole check; add the escape hatch back only if a real, concrete exception ever shows up.

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "production" / "migrations"

# Discussed-but-never-executed mentions of this pattern (a migration's own comment
# showing the decompress/compress idiom for documentation purposes, e.g. migrations
# 146/242) must not false-positive as a real call -- stripped before matching. Doesn't
# handle `/* */` block comments; none of this repo's migrations use them for this
# pattern as of writing, and a false negative here just means this test's next run
# (against whatever migration triggered it) still catches it -- not a silent permanent
# gap.
_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_DECOMPRESS_CALL_RE = re.compile(r"\bdecompress_chunk\s*\(")
_COMPRESS_CALL_RE = re.compile(r"\bcompress_chunk\s*\(")
_HYPERTABLE_NAME_RE = re.compile(r"hypertable_name\s*=\s*'(\w+)'")
_DO_BLOCK_RE = re.compile(r"DO\s*\$\$.*?\$\$\s*;", re.DOTALL)
_BARE_VACUUM_ANY_RE = re.compile(r"(?m)^\s*VACUUM\s+\w+\s*;")


def _bare_vacuum_re(table: str) -> re.Pattern[str]:
    return re.compile(rf"(?m)^\s*VACUUM\s+{re.escape(table)}\s*;")


def _round_tripped_tables(sql: str) -> set[str]:
    """Hypertable names selected via `WHERE hypertable_name = '<name>'` inside a DO
    block that also calls decompress_chunk(/compress_chunk( -- i.e. tables this file
    actually round-trips, not every table the file happens to mention anywhere."""
    tables: set[str] = set()
    for block in _DO_BLOCK_RE.findall(sql):
        if _DECOMPRESS_CALL_RE.search(block) or _COMPRESS_CALL_RE.search(block):
            tables.update(_HYPERTABLE_NAME_RE.findall(block))
    return tables


@functools.lru_cache(maxsize=1)
def _migrations_missing_a_required_vacuum() -> list[str]:
    """Relative paths of every migration that decompresses AND recompresses a
    hypertable's chunks (the specific round trip that leaves decompressed-page bloat
    behind) without a matching bare VACUUM statement for each such table."""
    violations: list[str] = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        sql = _SQL_LINE_COMMENT_RE.sub("", path.read_text(encoding="utf-8", errors="ignore"))
        does_round_trip = _DECOMPRESS_CALL_RE.search(sql) and _COMPRESS_CALL_RE.search(sql)
        if not does_round_trip:
            continue
        tables = _round_tripped_tables(sql)
        if tables:
            missing = [t for t in sorted(tables) if not _bare_vacuum_re(t).search(sql)]
            if missing:
                violations.append(str(path.relative_to(_REPO_ROOT)))
        elif not _BARE_VACUUM_ANY_RE.search(sql):
            # Fallback: round trip detected but no DO block ties a `hypertable_name =
            # '...'` literal to the actual decompress_chunk(/compress_chunk( call (a
            # future migration using a different chunk-selection idiom) -- degrade to
            # "some bare VACUUM exists" rather than pass silently with no check at all.
            violations.append(str(path.relative_to(_REPO_ROOT)))
    return violations


def test_every_compress_decompress_round_trip_migration_has_a_trailing_vacuum():
    violations = _migrations_missing_a_required_vacuum()
    assert not violations, (
        f"Migration(s) decompress+recompress a hypertable without a trailing VACUUM: "
        f"{violations}. Add a bare `VACUUM <table>;` statement after the "
        "compress_chunk() sweep, outside any BEGIN/COMMIT block (see migration 312 for "
        "the exact template, and docs/foundation/timescaledb-compressed-column-"
        "migration.md)."
    )
