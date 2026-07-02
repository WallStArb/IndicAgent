"""Unit tests for alpha_publisher event_id distinctness across weight_version epochs.

Covers Task 3 of Phase 141.1 Plan 04: the alpha_events event_id must fold in
weight_version so a new weight epoch produces a DISTINCT event_id instead of being
silently swallowed by ON CONFLICT (event_id, bar_ts) DO NOTHING.

Uses the pure static BaseBatch.content_key directly — isolates the hash contract
without requiring a live DB or alpha_publisher import.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.agent.base_batch import BaseBatch


class TestEventIdDistinctnessAcrossWeightVersion:
    """A differing weight_version must yield a distinct event_id (5-arg content_key)."""

    def test_differing_weight_version_yields_distinct_event_id(self) -> None:
        id_a = BaseBatch.content_key("SPY", "5m", "123", "v1.0.0", "run_A")
        id_b = BaseBatch.content_key("SPY", "5m", "123", "v1.0.0", "run_B")
        assert id_a != id_b

    def test_including_weight_version_changes_id_vs_old_4arg_form(self) -> None:
        old_4arg_id = BaseBatch.content_key("SPY", "5m", "123", "v1.0.0")
        new_5arg_id = BaseBatch.content_key("SPY", "5m", "123", "v1.0.0", "run_A")
        assert old_4arg_id != new_5arg_id

    def test_same_inputs_are_stable(self) -> None:
        id_1 = BaseBatch.content_key("SPY", "5m", "123", "v1.0.0", "run_A")
        id_2 = BaseBatch.content_key("SPY", "5m", "123", "v1.0.0", "run_A")
        assert id_1 == id_2


class TestAlphaPublisherEventIdConstruction:
    """alpha_publisher.py source must construct event_id with the 5-arg content_key form."""

    def _source(self) -> str:
        import services.alpha_publisher as m

        return inspect.getsource(m)

    def test_five_arg_content_key_form_present(self) -> None:
        source = self._source()
        assert "content_key(symbol, tf, bar_ts_ns, self.ensemble_version, weight_version)" in source

    def test_no_bare_four_arg_form_remains(self) -> None:
        source = self._source()
        assert "content_key(symbol, tf, bar_ts_ns, self.ensemble_version)" not in source


class TestAlphaPublisherWeightVersionOverride:
    """AlphaPublisher accepts --weight-version and threads it into __init__."""

    def test_init_accepts_weight_version_override(self) -> None:
        import services.alpha_publisher as m

        assert "weight_version_override" in inspect.signature(m.AlphaPublisher.__init__).parameters

    def test_effective_resolution_prefers_override(self) -> None:
        source = inspect.getsource(
            __import__("services.alpha_publisher", fromlist=["AlphaPublisher"])
        )
        assert "self._weight_version_override or _cfg_str(" in source
