"""Unit tests: ensemble_trainer's concept_registry alignment gate (Phase 170 Plan 06).

Behavioural proof of _assert_concept_registry_alignment -- a source-text assertion
that the file no longer contains "feature_registry" proves the EDIT happened; it
does not prove the gate still GATES, and this gate is the only thing standing
between a silently drifted registry and a trainer that weights features it cannot
explain.

Pure Python -- no real DB. A hand-rolled fake asyncpg connection (the same
`_FakeConn.fetch(sql, *args) -> list` idiom as tests/unit/services/test_hmm_trainer.py)
stubs the one query the gate issues, driven via asyncio.run (no pytest-asyncio
dependency needed for a single coroutine call per test).
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ensemble_trainer import _assert_concept_registry_alignment
from src.intelligence.schemas import FeatureVector

_DATACLASS_NAMES = {f.name for f in dataclasses.fields(FeatureVector)}


class _FakeConn:
    """Records the query text issued and returns caller-supplied name rows."""

    def __init__(self, names: set[str]):
        self._names = names
        self.captured_sql: str | None = None

    async def fetch(self, sql: str, *args):
        self.captured_sql = sql
        return [{"name": n} for n in self._names]


def test_alignment_gate_passes_on_exact_match():
    """Stub returns exactly FeatureVector's field names -- the call returns
    without raising."""
    conn = _FakeConn(set(_DATACLASS_NAMES))

    result = asyncio.run(_assert_concept_registry_alignment(conn))

    assert result == _DATACLASS_NAMES


def test_alignment_gate_raises_on_drift():
    """Stub omits one real name and adds one unknown name -- must raise
    RuntimeError with BOTH symmetric-difference names in the message, so the
    reader isn't left hunting the wrong direction."""
    real_names = sorted(_DATACLASS_NAMES)
    omitted = real_names[0]
    drifted_names = set(_DATACLASS_NAMES) - {omitted} | {"totally_unknown_field"}
    conn = _FakeConn(drifted_names)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(_assert_concept_registry_alignment(conn))

    message = str(excinfo.value)
    assert omitted in message
    assert "totally_unknown_field" in message


def test_alignment_gate_query_checks_schema_completeness_not_lifecycle_state():
    """Pins the 'schema completeness, not lifecycle state' property the gate's
    docstring/comment claims: the query scopes to domain='feature' but must
    NOT filter on status -- a status filter here would make the gate fail the
    moment any feature is deprecated, which is correct lifecycle behavior, not
    registry drift."""
    conn = _FakeConn(set(_DATACLASS_NAMES))

    asyncio.run(_assert_concept_registry_alignment(conn))

    assert conn.captured_sql is not None
    assert "domain = 'feature'" in conn.captured_sql
    assert "status" not in conn.captured_sql
