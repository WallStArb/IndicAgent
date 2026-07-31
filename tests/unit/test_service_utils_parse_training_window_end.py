"""Unit tests for parse_training_window_end (todo 009 Part D Item 1).

Extracted from an identical 8-line block duplicated in services/ic_engine.py and
services/forward_return_writer.py's main() functions.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.core.service_utils import parse_training_window_end


def test_parse_training_window_end_utc_offset() -> None:
    result = parse_training_window_end("2025-12-24T05:15:00+00:00")

    assert result == datetime(2025, 12, 24, 5, 15, 0, tzinfo=UTC)


def test_parse_training_window_end_non_utc_offset_converted() -> None:
    result = parse_training_window_end("2025-12-24T00:15:00-05:00")

    assert result == datetime(2025, 12, 24, 5, 15, 0, tzinfo=UTC)
    assert result.tzinfo == UTC


def test_parse_training_window_end_naive_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_training_window_end("2025-12-24T05:15:00")


def test_parse_training_window_end_z_suffix() -> None:
    result = parse_training_window_end("2025-12-24T05:15:00Z")

    assert result == datetime(2025, 12, 24, 5, 15, 0, tzinfo=UTC)
