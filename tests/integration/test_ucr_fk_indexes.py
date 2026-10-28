"""Every foreign key in the UCR and research tables has a covering index (plan 187-11).

Runs against indicagent_test (migrations replayed by tests/integration/conftest.py).
"""

import asyncpg

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_TABLES = (
    "concept_registry",
    "concept_parent",
    "concept_recipe",
    "concept_gate",
    "concept_transition_log",
    "concept_evaluation",
    "concept_annotation",
    "research_run",
    "research_run_series",
    "instrument_classification",
)
_UNCOVERED = """
SELECT c.conrelid::regclass::text AS tbl, c.conname
FROM pg_constraint c
WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY($1::text[])
  AND NOT EXISTS (
      SELECT 1 FROM pg_index i
      WHERE i.indrelid = c.conrelid
        AND (i.indkey::int2[])[0:cardinality(c.conkey) - 1] = c.conkey
  )
ORDER BY 1, 2
"""


async def test_every_foreign_key_has_a_covering_index():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        rows = await conn.fetch(_UNCOVERED, list(_TABLES))
    finally:
        await conn.close()
    assert [(r["tbl"], r["conname"]) for r in rows] == []
