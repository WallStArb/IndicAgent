from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.core.schemas.intelligence_journal import IntelligenceJournal, ProvenanceChain
from src.persistence.writer.data_writer_agent import DataWriterAgent


@pytest.mark.asyncio
async def test_data_writer_agent_persistence_flow():
    """Simulate the persistence flow for a DataWriterAgent with a mocked repository."""

    # 1. Setup Mock Repository and dependencies
    mock_repo = AsyncMock()
    # Mock topic builder: env_name -> topic string
    mock_topic_builder = lambda env: f"{env}.intelligence.feature.processed"

    agent = DataWriterAgent(
        repository=mock_repo,
        topic_builder=mock_topic_builder,
        env_name="dev",
        kafka_bootstrap="localhost:9092",
        group_id="test_group"
    )

    # 2. Construct a "Golden Payload"
    journal = IntelligenceJournal(
        ts=datetime.now(UTC),
        sid="feat_ES_1m",
        payload={"entries": [{"feature_a": 1.0, "feature_b": 0.5}], "selected_count": 1},
        provenance=ProvenanceChain(
            origin_ts=datetime.now(UTC),
            pipeline_id="gen_ES_1m",
            plugin_stack=["test_pipeline"],
            compute_budget_ms=0.5,
        ),
    )

    # 3. Simulate persistence
    await agent._persist(journal.model_dump_json())

    # 4. Verify Repository contract
    # Ensure insertBatch was called with expected payload
    assert mock_repo.insertBatch.called
    args, _ = mock_repo.insertBatch.call_args
    assert args[0] == journal.payload

    print("\n✅ DataWriterAgent persistence contract verified via Simulation-First test.")
