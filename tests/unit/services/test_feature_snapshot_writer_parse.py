"""Tests for FeatureSnapshotWriterAgent._parse_record dict/bytes/str routing.

snapshot_writer_parse_failed flooded logs (16k/day) because _run() called
str(payload) on a dict, producing Python repr instead of JSON.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent
from src.intelligence.schemas import BarIntelligenceRecord


def _make_agent() -> FeatureSnapshotWriterAgent:
    """Return a FeatureSnapshotWriterAgent shell with mocked I/O attributes."""
    agent = object.__new__(FeatureSnapshotWriterAgent)
    agent.logger = MagicMock()
    agent._parse_errors = MagicMock()
    agent._parse_errors.inc = MagicMock()
    return agent


VALID_DICT = {"schema_version": "1.0", "some_field": "value"}
VALID_JSON_STR = json.dumps(VALID_DICT)
VALID_JSON_BYTES = VALID_JSON_STR.encode()
FAKE_RECORD = MagicMock(spec=BarIntelligenceRecord)


class TestParseRecord:
    @pytest.mark.unit
    def test_dict_routes_to_model_validate(self):
        """dict payload calls model_validate (not model_validate_json)."""
        agent = _make_agent()
        with (
            patch.object(BarIntelligenceRecord, "model_validate", return_value=FAKE_RECORD) as mv,
            patch.object(BarIntelligenceRecord, "model_validate_json") as mvj,
        ):
            result = agent._parse_record(VALID_DICT)
        mv.assert_called_once_with(VALID_DICT)
        mvj.assert_not_called()
        assert result is FAKE_RECORD

    @pytest.mark.unit
    def test_bytes_routes_to_model_validate_json(self):
        """bytes payload calls model_validate_json."""
        agent = _make_agent()
        with (
            patch.object(
                BarIntelligenceRecord, "model_validate_json", return_value=FAKE_RECORD
            ) as mvj,
            patch.object(BarIntelligenceRecord, "model_validate") as mv,
        ):
            result = agent._parse_record(VALID_JSON_BYTES)
        mvj.assert_called_once_with(VALID_JSON_BYTES)
        mv.assert_not_called()
        assert result is FAKE_RECORD

    @pytest.mark.unit
    def test_str_routes_to_model_validate_json(self):
        """str payload calls model_validate_json."""
        agent = _make_agent()
        with patch.object(
            BarIntelligenceRecord, "model_validate_json", return_value=FAKE_RECORD
        ) as mvj:
            result = agent._parse_record(VALID_JSON_STR)
        mvj.assert_called_once_with(VALID_JSON_STR)
        assert result is FAKE_RECORD

    @pytest.mark.unit
    def test_validation_error_returns_none_and_increments_counter(self):
        """ValidationError → returns None and increments _parse_errors."""
        agent = _make_agent()
        with patch.object(
            BarIntelligenceRecord, "model_validate_json", side_effect=ValueError("bad")
        ):
            result = agent._parse_record("bad json")
        assert result is None
        agent._parse_errors.add.assert_called_once()
