"""Integration test for AlphaSwarm graduation loop.

Requires live TimescaleDB. Inserts signal_lineage + signal_ledger rows with
rank-correlated prediction/pnl_r, runs one evaluation cycle, asserts state='live'.

Run with: .venv/bin/pytest tests/integration/test_swarm_graduation_loop.py -v
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skip(reason="v2.x Signal Ledger Architecture, archived, no live consumer (CLAUDE.md)")
async def test_graduation_loop_promotes_skeptic_end_to_end() -> None:
    """Insert 100 lineage + ledger rows with positive correlation → promote to live.

    End-to-end test:
    1. Ensure skeptic is enrolled in shadow_registry
    2. Insert 100 signal_lineage rows (agent_prediction) + signal_ledger rows (positive pnl_r)
    3. Run one graduation cycle
    4. Assert shadow_registry.is_shadow=FALSE for skeptic

    Cleans up inserted rows after the test.
    """
    import numpy as np
    from scipy.stats import spearmanr

    from services.alpha_swarm import AlphaSwarm
    from src.config.settings import Settings
    from src.core.database_manager import create_pool as create_db_pool

    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=1, max_size=3)

    # Ensure skeptic enrolled (idempotent)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO shadow_registry (component_name, component_type, is_shadow)
            VALUES ('skeptic', 'swarm_agent', TRUE)
            ON CONFLICT (component_name) DO NOTHING
            """,
        )
        # Force back to shadow for this test
        await conn.execute(
            "UPDATE shadow_registry SET is_shadow=TRUE WHERE component_name='skeptic'",
        )

    # Generate 100 strongly correlated (prediction, pnl_r) pairs
    rng = np.random.default_rng(2026_04_30)
    predictions = np.linspace(0.1, 1.0, 100)
    pnl_rs = predictions + rng.normal(0, 0.05, 100)

    # Verify Spearman passes gate before inserting
    rho, p = spearmanr(predictions, pnl_rs)
    assert rho > 0 and p < 0.05, f"Test data does not meet promotion gate: rho={rho}, p={p}"

    # Insert test signal_ledger rows first (FK target)
    signal_ids: list[str] = []
    now = datetime.now(UTC)

    async with pool.acquire() as conn:
        for i, pnl_r in enumerate(pnl_rs):
            sig_id = str(uuid.uuid4())
            signal_ids.append(sig_id)
            await conn.execute(
                """
                INSERT INTO signal_ledger
                    (signal_id, symbol, setup_plugin, direction, status, outcome, pnl_r,
                     signal_computed_at, timestamp)
                VALUES ($1, 'ESM6', 'integration_test', 1, 'resolved', 'target_1', $2,
                        $3, $3)
                """,
                uuid.UUID(sig_id),
                float(pnl_r),
                now,
            )

    # Insert signal_lineage rows (agent_prediction) — multiplier is the column
    # _evaluate_agent queries (sl.multiplier IS NOT NULL); prediction is not queried.
    async with pool.acquire() as conn:
        for sig_id, pred_score in zip(signal_ids, predictions):
            await conn.execute(
                """
                INSERT INTO signal_lineage
                    (ts, signal_id, event_type, source, multiplier, symbol, tf)
                VALUES ($1, $2, 'agent_prediction', 'skeptic', $3, 'ESM6', '5m')
                """,
                now,
                uuid.UUID(sig_id),
                float(pred_score),
            )

    # Build agent with the live pool — __new__ bypasses __init__ so set required attrs.
    agent = AlphaSwarm.__new__(AlphaSwarm)
    agent.settings = MagicMock()
    agent.settings.swarm_graduation_interval_s = 0
    agent.settings.SWARM_WEIGHT_MIN_SAMPLES = 10
    agent.settings.SWARM_WEIGHT_FLOOR = 0.05
    agent.logger = MagicMock()
    agent._pool = pool
    agent._demotion_streak = 0
    agent._agents = [MagicMock(agent_id="skeptic")]
    agent._agent_weights = {}

    try:
        # Run a single evaluation cycle
        await agent._run_graduation_cycle()

        # Assert weight was learned — graduation writes swarm_agent_weights, not
        # shadow_registry (is_shadow is shadow_auditor's responsibility).
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT weight, sample_size FROM swarm_agent_weights "
                "WHERE agent_id='skeptic' AND timeframe='5m'"
            )

        assert row is not None, "swarm_agent_weights not populated for skeptic/5m"
        assert row["sample_size"] >= 10, f"Expected >=10 samples, got {row['sample_size']}"
        assert (
            row["weight"] > 0.5
        ), f"Expected weight > 0.5 for positively correlated agent, got {row['weight']}"

    finally:
        async with pool.acquire() as conn:
            for sig_id in signal_ids:
                await conn.execute(
                    "DELETE FROM signal_lineage WHERE signal_id=$1", uuid.UUID(sig_id)
                )
                await conn.execute(
                    "DELETE FROM signal_ledger WHERE signal_id=$1", uuid.UUID(sig_id)
                )
            await conn.execute(
                "DELETE FROM swarm_agent_weights WHERE agent_id='skeptic' AND timeframe='5m'"
            )
        await pool.close()
