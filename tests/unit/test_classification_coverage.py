"""Unit tests: classification coverage audit (Phase 182 Plan 06, D-09 point 3).

Pure-Python, no-DB style (mirrors tests/unit/test_classification_service.py): a real
ClassificationService whose `_nodes`/`_assignments` caches are populated directly, so the
coverage functions are measured through the same as-of read layer production uses.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.config.classification_coverage import (
    ClassificationCoverageAuditor,
    unclassified_counts_by_level,
    uncovered_symbols,
)
from src.config.classification_service import (
    DEFAULT_SCHEME,
    SOURCE_REF_FUND_MANDATE,
    SOURCE_REF_IBKR_REVIEWED,
    AssignmentRow,
    ClassificationNode,
    ClassificationService,
)

_AS_OF = date(2026, 9, 25)


def _node(code: str, level: int, path: list[str]) -> ClassificationNode:
    return ClassificationNode(
        scheme=DEFAULT_SCHEME,
        code=code,
        parent_code=path[-2] if len(path) > 1 else None,
        level=level,
        name=code,
        path=tuple(path),
    )


def _assignment(
    symbol: str,
    code: str,
    valid_from: date,
    valid_to: date | None = None,
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


def _service() -> ClassificationService:
    service = ClassificationService("postgresql://unused")
    nodes = [
        _node("EQ", 1, ["EQ"]),
        _node("EQ.IT", 2, ["EQ", "EQ.IT"]),
        _node("EQ.IT.SEMI", 3, ["EQ", "EQ.IT", "EQ.IT.SEMI"]),
        _node("EQ.IT.SEMI.CHIPS", 4, ["EQ", "EQ.IT", "EQ.IT.SEMI", "EQ.IT.SEMI.CHIPS"]),
        _node("EQ.BROAD", 2, ["EQ", "EQ.BROAD"]),
        _node("FI", 1, ["FI"]),
        _node("FI.RATES", 2, ["FI", "FI.RATES"]),
    ]
    service._nodes = {(n.scheme, n.code): n for n in nodes}
    start = date(2026, 1, 1)
    service._assignments = {
        (DEFAULT_SCHEME, "NVDA"): [_assignment("NVDA", "EQ.IT.SEMI.CHIPS", start)],
        (DEFAULT_SCHEME, "SPY"): [
            _assignment("SPY", "EQ.BROAD", start, source_ref=SOURCE_REF_FUND_MANDATE)
        ],
        (DEFAULT_SCHEME, "TLT"): [
            _assignment("TLT", "FI.RATES", start, source_ref=SOURCE_REF_FUND_MANDATE)
        ],
        (DEFAULT_SCHEME, "OLDCO"): [_assignment("OLDCO", "EQ.IT", start, date(2026, 6, 1))],
    }
    return service


def test_uncovered_symbols_reports_symbols_without_assignment():
    assert uncovered_symbols(["NVDA", "SPY", "NEWCO"], _service(), _AS_OF) == ["NEWCO"]


def test_uncovered_symbols_sorted():
    result = uncovered_symbols(["ZZZ", "NVDA", "AAA"], _service(), _AS_OF)
    assert result == ["AAA", "ZZZ"]


def test_symbol_with_only_closed_row_is_uncovered():
    assert uncovered_symbols(["OLDCO", "NVDA"], _service(), _AS_OF) == ["OLDCO"]


def test_closed_row_is_covered_inside_its_window():
    assert uncovered_symbols(["OLDCO"], _service(), date(2026, 3, 1)) == []


def test_unclassified_counts_by_level():
    counts = unclassified_counts_by_level(["NVDA", "SPY", "TLT"], _service(), _AS_OF)
    assert counts == {1: 0, 2: 0, 3: 2, 4: 2}


def test_empty_input():
    service = _service()
    assert uncovered_symbols([], service, _AS_OF) == []
    assert unclassified_counts_by_level([], service, _AS_OF) == {1: 0, 2: 0, 3: 0, 4: 0}


def test_empty_registry_reports_every_symbol_uncovered():
    service = ClassificationService("postgresql://unused")
    assert uncovered_symbols(["SPY", "NVDA"], service, _AS_OF) == ["NVDA", "SPY"]
    assert unclassified_counts_by_level(["SPY"], service, _AS_OF) == {}


def test_job_name():
    assert ClassificationCoverageAuditor.job_name == "classification-coverage-audit"
