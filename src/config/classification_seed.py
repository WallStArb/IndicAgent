"""Seed validator and SQL renderer for the indicagent_v1 classification scheme.

Phase 182 (security classification hierarchy, todo 384). Renders the build-date seed held in
`src/config/classification_seed_data.py` into a numbered migration. The migration file is
generated, never hand-edited: regenerate with

    .venv/bin/python -m src.config.classification_seed --write <migration path>

and `--check <migration path>` exits 1 when the committed file differs from the render
(`tests/unit/test_classification_seed_shape.py` asserts the same equality in CI).

The data module is a build-date snapshot (D-07: every `valid_from` is the apply date, no
history before it). Reclassifications after the build date are separate close-and-insert
migrations, never edits to the data module: reclassification never overwrites (design doc,
`docs/research/stratification-security-classification-hierarchy.md`).

Guards rendered into the SQL:
- D-01 node immutability: a staged node whose code exists in `classification_node` with a
  different `parent_code` or `level` aborts the migration. Only `name` updates in place. Any
  future node-adding migration must reuse `render_node_guard_sql` so this guard is never
  skipped.
- Assignment disagreement: a staged symbol whose current assignment has a different code
  aborts the migration (a change after the build date is a close-and-insert migration).
- D-09 seed-time coverage: the migration aborts if any active instrument is left without a
  current assignment in the scheme.

Basis text and override reasons are review metadata; they live only in the data module and
never reach the rendered SQL.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.config.classification_service import ALLOWED_SOURCE_REFS, check_scheme_identifier

_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(\.[A-Z][A-Z0-9]*){0,3}$")
_REQUIRED_AUTHORITY = "IndicAgent"
_EQUITY_ROOT = "EQ"
_EQUITY_LEAF_LEVEL = 4
_APPLY_DATE_SQL = "(now() AT TIME ZONE 'UTC')::date"
_NODE_STAGE = "_seed_classification_node"
_ASSIGNMENT_STAGE = "_seed_instrument_classification"


@dataclass(frozen=True)
class SchemeSeed:
    scheme: str
    name: str
    authority: str
    source_ref: str


@dataclass(frozen=True)
class NodeSeed:
    code: str
    parent_code: str | None
    level: int
    name: str


@dataclass(frozen=True)
class AssignmentSeed:
    symbol: str
    code: str
    source_ref: str
    basis: str
    override_reason: str = ""


def _root(code: str) -> str:
    return code.split(".", 1)[0]


def validate_seed(
    scheme: SchemeSeed, nodes: Sequence[NodeSeed], assignments: Sequence[AssignmentSeed]
) -> None:
    """Raises ValueError listing every problem found; returns None when the seed is valid."""
    problems: list[str] = []

    try:
        check_scheme_identifier(scheme.scheme)
    except ValueError as error:
        problems.append(str(error))
    for field in ("scheme", "name", "authority", "source_ref"):
        if "gics" in getattr(scheme, field).lower():
            problems.append(f"scheme {field} {getattr(scheme, field)!r} mentions GICS (D-03)")
    if scheme.authority != _REQUIRED_AUTHORITY:
        problems.append(f"scheme authority {scheme.authority!r} is not {_REQUIRED_AUTHORITY!r}")

    codes: set[str] = set()
    for node in nodes:
        if node.code in codes:
            problems.append(f"duplicate node code {node.code!r}")
        codes.add(node.code)
    for node in nodes:
        if not _CODE_PATTERN.match(node.code):
            problems.append(f"node code {node.code!r} violates the code convention (D-02)")
            continue
        segments = node.code.split(".")
        if node.level != len(segments):
            problems.append(
                f"node {node.code!r} level {node.level} != segment count {len(segments)}"
            )
        expected_parent = ".".join(segments[:-1]) or None
        if node.parent_code != expected_parent:
            problems.append(
                f"node {node.code!r} parent_code {node.parent_code!r} != {expected_parent!r}"
            )
        elif expected_parent is not None and expected_parent not in codes:
            problems.append(
                f"node {node.code!r} parent {expected_parent!r} is not in the node list"
            )
        if not node.name.strip():
            problems.append(f"node {node.code!r} has an empty name")

    # Names must be unique within a level: consumers read the level-2 name as the sector
    # label (D-10), so two same-named nodes would silently merge strata keyed by name.
    seen_names: dict[tuple[int, str], str] = {}
    for node in nodes:
        key = (node.level, node.name.strip().lower())
        if key in seen_names:
            problems.append(
                f"node {node.code!r} name {node.name!r} duplicates {seen_names[key]!r} "
                f"at level {node.level}"
            )
        else:
            seen_names[key] = node.code

    symbols: set[str] = set()
    used: set[str] = set()
    for assignment in assignments:
        if assignment.symbol in symbols:
            problems.append(f"duplicate assignment symbol {assignment.symbol!r}")
        symbols.add(assignment.symbol)
        if assignment.code not in codes:
            problems.append(
                f"assignment {assignment.symbol!r} code {assignment.code!r} is not in the node list"
            )
        if assignment.source_ref not in ALLOWED_SOURCE_REFS:
            problems.append(
                f"assignment {assignment.symbol!r} source_ref {assignment.source_ref!r} "
                f"is not one of {sorted(ALLOWED_SOURCE_REFS)}"
            )
        if not assignment.basis.strip():
            problems.append(f"assignment {assignment.symbol!r} has an empty basis")
        segments = assignment.code.split(".")
        used.update(".".join(segments[: i + 1]) for i in range(len(segments)))

    for node in nodes:
        if node.code in used or not _CODE_PATTERN.match(node.code):
            continue
        if _root(node.code) != _EQUITY_ROOT:
            problems.append(f"non-equity node {node.code!r} has no assignment at or below it")
        elif node.level == _EQUITY_LEAF_LEVEL:
            problems.append(f"equity level-4 node {node.code!r} has no assignment")

    if problems:
        raise ValueError("invalid classification seed:\n  " + "\n  ".join(problems))


def _lit(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sorted_nodes(nodes: Sequence[NodeSeed]) -> list[NodeSeed]:
    return sorted(nodes, key=lambda n: (n.level, n.code))


def render_node_guard_sql(scheme: str, nodes: Sequence[NodeSeed]) -> str:
    """The node staging temp table plus the D-01 immutability guard, nothing else.

    Does not call validate_seed, so an integration test can feed it a deliberately
    inconsistent node and watch the guard raise.
    """
    check_scheme_identifier(scheme)
    values = ",\n".join(
        f"    ({_lit(n.code)}, {_lit(n.parent_code)}, {int(n.level)}, {_lit(n.name)})"
        for n in _sorted_nodes(nodes)
    )
    return f"""-- Node staging and immutability guard (D-01): parent_code and level never change for a code.
CREATE TEMP TABLE {_NODE_STAGE} (
    code        TEXT PRIMARY KEY,
    parent_code TEXT,
    level       SMALLINT NOT NULL,
    name        TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO {_NODE_STAGE} (code, parent_code, level, name) VALUES
{values};

DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(
        format('%s (seed parent %s level %s, existing parent %s level %s)',
               s.code, s.parent_code, s.level, n.parent_code, n.level),
        ', ' ORDER BY s.code) INTO bad
    FROM {_NODE_STAGE} s
    JOIN classification_node n ON n.scheme = {_lit(scheme)} AND n.code = s.code
    WHERE n.parent_code IS DISTINCT FROM s.parent_code OR n.level <> s.level;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'classification_node immutability violated in {scheme} (D-01): %', bad;
    END IF;
END $$;"""


def render_seed_sql(
    scheme: SchemeSeed,
    nodes: Sequence[NodeSeed],
    assignments: Sequence[AssignmentSeed],
    *,
    transaction: bool = True,
) -> str:
    """Renders the full seed migration. Validates first; output is deterministic."""
    validate_seed(scheme, nodes, assignments)
    s = scheme.scheme
    s_lit = _lit(s)

    header = f"""-- Migration: {s} classification seed (Phase 182, todo 384). GENERATED FILE, DO NOT EDIT.
--
-- Rendered from src/config/classification_seed_data.py by src/config/classification_seed.py.
-- Regenerate: .venv/bin/python -m src.config.classification_seed --write <this file>
-- Verify:     .venv/bin/python -m src.config.classification_seed --check <this file>
--
-- D-01: node parent_code/level are immutable per code; the seed aborts on disagreement and
--       only node names update in place. instrument_classification is append-only.
-- D-07: valid_from is the apply date (the build date); no history before it.
-- D-09: the seed aborts if any active instrument lacks a current {s} assignment.
-- D-11: numbered migration, applied and committed together.
-- This scheme is project-owned and is not GICS (D-03)."""

    scheme_sql = f"""INSERT INTO classification_scheme (scheme, name, authority, source_ref)
VALUES ({s_lit}, {_lit(scheme.name)}, {_lit(scheme.authority)}, {_lit(scheme.source_ref)})
ON CONFLICT (scheme) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM classification_scheme
        WHERE scheme = {s_lit} AND authority IS DISTINCT FROM {_lit(scheme.authority)}
    ) THEN
        RAISE EXCEPTION 'classification_scheme {s} exists with a different authority';
    END IF;
END $$;"""

    node_insert = f"""INSERT INTO classification_node (scheme, code, parent_code, level, name, path, valid_from)
WITH RECURSIVE tree AS (
    SELECT code, parent_code, level, name, ARRAY[code] AS path
    FROM {_NODE_STAGE}
    WHERE parent_code IS NULL
    UNION ALL
    SELECT c.code, c.parent_code, c.level, c.name, t.path || c.code
    FROM {_NODE_STAGE} c
    JOIN tree t ON c.parent_code = t.code
)
SELECT {s_lit}, code, parent_code, level, name, path, {_APPLY_DATE_SQL}
FROM tree
ORDER BY level, code
ON CONFLICT (scheme, code) DO UPDATE SET name = EXCLUDED.name;"""

    assignment_values = ",\n".join(
        f"    ({_lit(a.symbol)}, {_lit(a.code)}, {_lit(a.source_ref)})"
        for a in sorted(assignments, key=lambda a: a.symbol)
    )
    assignment_sql = f"""-- Assignment staging. A symbol already holding a different current code aborts the seed.
CREATE TEMP TABLE {_ASSIGNMENT_STAGE} (
    symbol     TEXT PRIMARY KEY,
    code       TEXT NOT NULL,
    source_ref TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO {_ASSIGNMENT_STAGE} (symbol, code, source_ref) VALUES
{assignment_values};

DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(format('%s (seed %s, current %s)', s.symbol, s.code, c.code),
                      ', ' ORDER BY s.symbol) INTO bad
    FROM {_ASSIGNMENT_STAGE} s
    JOIN instrument_classification c
      ON c.symbol = s.symbol AND c.scheme = {s_lit} AND c.valid_to IS NULL
    WHERE c.code <> s.code;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'seed disagrees with current {s} assignments: %', bad;
    END IF;
END $$;

INSERT INTO instrument_classification (symbol, scheme, code, valid_from, source_ref)
SELECT s.symbol, {s_lit}, s.code, {_APPLY_DATE_SQL}, s.source_ref
FROM {_ASSIGNMENT_STAGE} s
JOIN instruments i ON i.symbol = s.symbol
WHERE NOT EXISTS (
    SELECT 1 FROM instrument_classification c
    WHERE c.symbol = s.symbol AND c.scheme = {s_lit} AND c.valid_to IS NULL
)
ORDER BY s.symbol;

DO $$
DECLARE
    n_absent INTEGER;
    absent TEXT;
BEGIN
    SELECT count(*), string_agg(s.symbol, ', ' ORDER BY s.symbol) INTO n_absent, absent
    FROM {_ASSIGNMENT_STAGE} s
    WHERE NOT EXISTS (SELECT 1 FROM instruments i WHERE i.symbol = s.symbol);
    RAISE NOTICE 'seed symbols absent from instruments (skipped): % %', n_absent, coalesce(absent, '');
END $$;

-- D-09 seed-time coverage guard.
DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(i.symbol, ', ' ORDER BY i.symbol) INTO bad
    FROM instruments i
    WHERE i.is_active
      AND NOT EXISTS (
          SELECT 1 FROM instrument_classification c
          WHERE c.symbol = i.symbol AND c.scheme = {s_lit} AND c.valid_to IS NULL
      );
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'active instruments without a current {s} assignment: %', bad;
    END IF;
END $$;"""

    sections = [
        scheme_sql,
        render_node_guard_sql(s, nodes),
        node_insert,
        assignment_sql,
    ]
    if transaction:
        sections = ["BEGIN;", *sections, "COMMIT;"]
    return header + "\n\n" + "\n\n".join(sections) + "\n"


def _load_data() -> tuple[SchemeSeed, Sequence[NodeSeed], Sequence[AssignmentSeed]]:
    from src.config import classification_seed_data as data

    return data.SCHEME, data.NODES, data.ASSIGNMENTS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", metavar="PATH", help="render the seed migration to PATH")
    mode.add_argument("--check", metavar="PATH", help="exit 1 if PATH differs from the render")
    args = parser.parse_args(argv)

    rendered = render_seed_sql(*_load_data())
    if args.write:
        Path(args.write).write_text(rendered)
        return 0
    target = Path(args.check)
    if not target.exists() or target.read_text() != rendered:
        print(f"{target} differs from the rendered seed; regenerate with --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
