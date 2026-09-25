"""Unit tests: ClassificationService (Phase 182, Security Classification Hierarchy, todo 384).

Pure-Python, no-DB style (mirrors tests/unit/test_vocabulary_service.py): builds a
ClassificationService, populates `_nodes`/`_assignments` caches directly (bypassing
initialize()/DB entirely), and asserts the synchronous hot-path readers plus the shared
module-level constants/helpers every wave-2 plan imports.
"""

from __future__ import annotations

import inspect
import sys
from datetime import date
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.config.classification_service import (
    ALLOWED_SOURCE_REFS,
    DEFAULT_SCHEME,
    SECTOR_LEVEL,
    SOURCE_REF_CONTRACT_SPEC,
    SOURCE_REF_FUND_MANDATE,
    SOURCE_REF_IBKR_REVIEWED,
    AssignmentRow,
    ClassificationAssignment,
    ClassificationNode,
    ClassificationService,
    _build_caches,
    current_level_name_sql,
    label_or_unclassified,
    unclassified_code,
)


def _node(
    code: str, parent_code: str | None, level: int, name: str, path: list[str]
) -> ClassificationNode:
    return ClassificationNode(
        scheme=DEFAULT_SCHEME,
        code=code,
        parent_code=parent_code,
        level=level,
        name=name,
        path=tuple(path),
    )


def _assignment(
    symbol: str,
    code: str,
    valid_from: date,
    valid_to: date | None,
    source_ref: str = SOURCE_REF_IBKR_REVIEWED,
) -> AssignmentRow:
    return AssignmentRow(
        symbol=symbol,
        scheme=DEFAULT_SCHEME,
        code=code,
        valid_from=valid_from,
        valid_to=valid_to,
        source_ref=source_ref,
    )


def _service_with_fixture() -> ClassificationService:
    service = ClassificationService("postgresql://unused")
    nodes = [
        _node("EQ", None, 1, "Equity", ["EQ"]),
        _node("EQ.IT", "EQ", 2, "Information Technology", ["EQ", "EQ.IT"]),
        _node(
            "EQ.IT.SEMI",
            "EQ.IT",
            3,
            "Semiconductors & Semiconductor Equipment",
            ["EQ", "EQ.IT", "EQ.IT.SEMI"],
        ),
        _node(
            "EQ.IT.SEMI.EQUIP",
            "EQ.IT.SEMI",
            4,
            "Semiconductor Equipment",
            ["EQ", "EQ.IT", "EQ.IT.SEMI", "EQ.IT.SEMI.EQUIP"],
        ),
        _node("EQ.BROAD", "EQ", 2, "Broad Market", ["EQ", "EQ.BROAD"]),
        _node("FI", None, 1, "Fixed Income", ["FI"]),
        _node("FI.RATES", "FI", 2, "Rates", ["FI", "FI.RATES"]),
    ]
    service._nodes = {(n.scheme, n.code): n for n in nodes}
    service._assignments = {
        (DEFAULT_SCHEME, "NVDA"): [
            _assignment("NVDA", "EQ.IT.SEMI.EQUIP", date(2026, 9, 25), None)
        ],
        (DEFAULT_SCHEME, "SPY"): [
            _assignment(
                "SPY", "EQ.BROAD", date(2026, 9, 25), None, source_ref=SOURCE_REF_FUND_MANDATE
            )
        ],
        (DEFAULT_SCHEME, "TLT"): [
            _assignment(
                "TLT", "FI.RATES", date(2026, 9, 25), None, source_ref=SOURCE_REF_FUND_MANDATE
            )
        ],
        (DEFAULT_SCHEME, "XYZ"): [
            _assignment(
                "XYZ",
                "EQ.BROAD",
                date(2026, 9, 25),
                date(2026, 10, 10),
                source_ref=SOURCE_REF_FUND_MANDATE,
            ),
            _assignment("XYZ", "EQ.IT.SEMI.EQUIP", date(2026, 10, 10), None),
        ],
    }
    return service


def test_node_at_level_nvda_walks_full_depth():
    service = _service_with_fixture()
    assert service.node_at_level("NVDA", 1) == "EQ"
    assert service.node_at_level("NVDA", 2) == "EQ.IT"
    assert service.node_at_level("NVDA", 3) == "EQ.IT.SEMI"
    assert service.node_at_level("NVDA", 4) == "EQ.IT.SEMI.EQUIP"


def test_node_at_level_above_assignment_depth_returns_unclassified():
    service = _service_with_fixture()
    assert service.node_at_level("SPY", 4) == "indicagent_v1:unclassified"


def test_node_at_level_unknown_symbol_returns_unclassified_never_none():
    service = _service_with_fixture()
    assert service.node_at_level("NOSUCH", 2) == "indicagent_v1:unclassified"


def test_node_at_level_before_build_date_returns_unclassified():
    service = _service_with_fixture()
    assert service.node_at_level("NVDA", 2, as_of=date(2026, 9, 24)) == "indicagent_v1:unclassified"


def test_node_at_level_xyz_as_of_before_reclassification():
    service = _service_with_fixture()
    assert service.node_at_level("XYZ", 2, as_of=date(2026, 10, 1)) == "EQ.BROAD"


def test_node_at_level_xyz_valid_to_is_exclusive():
    service = _service_with_fixture()
    assert service.node_at_level("XYZ", 2, as_of=date(2026, 10, 10)) == "EQ.IT"


def test_node_at_level_resolves_to_a_named_node():
    service = _service_with_fixture()
    assert service.node(service.node_at_level("NVDA", 2)).name == "Information Technology"


def test_max_level():
    service = _service_with_fixture()
    assert service.max_level() == 4


def test_max_level_unseeded_scheme_returns_zero():
    service = _service_with_fixture()
    assert service.max_level("no_such_scheme") == 0


def test_classification_service_no_db_calls_after_init():
    """All hot-path readers are synchronous and touch no DB pool after caches are
    populated -- hot-path reads must be zero-I/O per D-08."""
    service = _service_with_fixture()
    assert service._db_pool is None
    for method_name in ("node", "assignment_as_of", "node_at_level", "max_level"):
        method = getattr(service, method_name)
        assert not inspect.iscoroutinefunction(method)
    assert service.node_at_level("NVDA", 1) == "EQ"


def test_unclassified_code():
    assert unclassified_code("indicagent_v1") == "indicagent_v1:unclassified"
    assert unclassified_code() == "indicagent_v1:unclassified"


def test_label_or_unclassified_none_and_empty_fall_back():
    assert label_or_unclassified(None) == unclassified_code()
    assert label_or_unclassified("") == unclassified_code()


def test_label_or_unclassified_passes_through_real_label():
    assert label_or_unclassified("Rates") == "Rates"


def test_classification_assignment_rejects_unknown_source_ref():
    with pytest.raises(ValueError):
        ClassificationAssignment("EQ", "made_up")


def test_classification_assignment_rejects_empty_code():
    with pytest.raises(ValueError):
        ClassificationAssignment("", "fund_mandate")


def test_classification_assignment_accepts_every_allowed_source_ref():
    for source_ref in (SOURCE_REF_IBKR_REVIEWED, SOURCE_REF_FUND_MANDATE, SOURCE_REF_CONTRACT_SPEC):
        assert ClassificationAssignment("EQ", source_ref).source_ref == source_ref
    assert ALLOWED_SOURCE_REFS == frozenset(
        {SOURCE_REF_IBKR_REVIEWED, SOURCE_REF_FUND_MANDATE, SOURCE_REF_CONTRACT_SPEC}
    )


def test_current_level_name_sql_default_shape():
    sql = current_level_name_sql("i")
    assert "i.symbol" in sql
    assert "valid_to IS NULL" in sql
    assert f"path[{SECTOR_LEVEL}]" in sql
    assert f"'{DEFAULT_SCHEME}'" in sql


def test_current_level_name_sql_rejects_injection_shaped_alias():
    with pytest.raises(ValueError):
        current_level_name_sql("i; drop table instruments;--")


def test_current_level_name_sql_rejects_bad_scheme():
    with pytest.raises(ValueError):
        current_level_name_sql("i", scheme="bad scheme")


def test_current_level_name_sql_rejects_level_below_one():
    with pytest.raises(ValueError):
        current_level_name_sql("i", level=0)


def test_build_caches_raises_on_unknown_assignment_code():
    node_rows = [
        {
            "scheme": DEFAULT_SCHEME,
            "code": "EQ",
            "parent_code": None,
            "level": 1,
            "name": "Equity",
            "path": ["EQ"],
        }
    ]
    assignment_rows = [
        {
            "symbol": "NVDA",
            "scheme": DEFAULT_SCHEME,
            "code": "NOPE",
            "valid_from": date(2026, 9, 25),
            "valid_to": None,
            "source_ref": SOURCE_REF_IBKR_REVIEWED,
        }
    ]
    with pytest.raises(RuntimeError):
        _build_caches(node_rows, assignment_rows)


def test_build_caches_raises_on_overlapping_windows():
    node_rows = [
        {
            "scheme": DEFAULT_SCHEME,
            "code": "EQ",
            "parent_code": None,
            "level": 1,
            "name": "Equity",
            "path": ["EQ"],
        }
    ]
    assignment_rows = [
        {
            "symbol": "NVDA",
            "scheme": DEFAULT_SCHEME,
            "code": "EQ",
            "valid_from": date(2026, 9, 25),
            "valid_to": date(2026, 10, 15),
            "source_ref": SOURCE_REF_IBKR_REVIEWED,
        },
        {
            "symbol": "NVDA",
            "scheme": DEFAULT_SCHEME,
            "code": "EQ",
            "valid_from": date(2026, 10, 10),
            "valid_to": None,
            "source_ref": SOURCE_REF_IBKR_REVIEWED,
        },
    ]
    with pytest.raises(RuntimeError):
        _build_caches(node_rows, assignment_rows)


def test_build_caches_accepts_adjacent_non_overlapping_windows():
    node_rows = [
        {
            "scheme": DEFAULT_SCHEME,
            "code": "EQ",
            "parent_code": None,
            "level": 1,
            "name": "Equity",
            "path": ["EQ"],
        }
    ]
    assignment_rows = [
        {
            "symbol": "NVDA",
            "scheme": DEFAULT_SCHEME,
            "code": "EQ",
            "valid_from": date(2026, 9, 25),
            "valid_to": date(2026, 10, 10),
            "source_ref": SOURCE_REF_IBKR_REVIEWED,
        },
        {
            "symbol": "NVDA",
            "scheme": DEFAULT_SCHEME,
            "code": "EQ",
            "valid_from": date(2026, 10, 10),
            "valid_to": None,
            "source_ref": SOURCE_REF_IBKR_REVIEWED,
        },
    ]
    nodes, assignments = _build_caches(node_rows, assignment_rows)
    assert len(assignments[(DEFAULT_SCHEME, "NVDA")]) == 2


def test_level_below_one_raises() -> None:
    """A level <= 0 would index the path from the end and return a real node."""
    service = _service_with_fixture()
    with pytest.raises(ValueError, match="must be an int >= 1"):
        service.node_at_level("NVDA", 0)
    with pytest.raises(ValueError, match="must be an int >= 1"):
        service.node_at_level("NVDA", -1)


def test_node_path_not_extending_parent_raises() -> None:
    nodes = [
        {
            "scheme": "s",
            "code": "EQ",
            "parent_code": None,
            "level": 1,
            "name": "Equity",
            "path": ["EQ"],
        },
        {
            "scheme": "s",
            "code": "EQ.IT",
            "parent_code": "EQ",
            "level": 2,
            "name": "IT",
            "path": ["EQ", "EQ.FIN"],
        },
    ]
    with pytest.raises(RuntimeError, match="wrong branch"):
        _build_caches(nodes, [])
