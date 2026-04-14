"""MLOrchestratorComputeAgent -- LangGraph orchestrator for weekly ML pipeline.

Timer-triggered: indicagent-ml-orchestrator.timer (Monday 04:00 UTC).
One-shot: runs LangGraph StateGraph, then exits.

Graph:
  DataQualityNode -> [gate] -> DiscoveryNode -> TrainingNode (stub) -> MonitorNode (stub)
                               | (quality low)
                            -> AlertNode -> END

DataQualityNode: triggers indicagent-ml-data-quality.service and reads score.
DiscoveryNode:   triggers indicagent-ml-discovery.service and waits for completion.
TrainingNode:    STUB -- logs "awaiting Phase 67", returns state unchanged.
MonitorNode:     STUB -- logs "awaiting Phase 67", returns state unchanged.

Phase 67 adds TrainingNode and MonitorNode implementations -- no architecture changes needed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TypedDict

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_ml_orchestrator_dlq
from src.observability.metrics import PERSISTENCE_CONSUMER_LAG

logger = structlog.get_logger(__name__)

try:
    import langgraph.graph as _lg  # availability probe only

    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _lg = None  # type: ignore[assignment]
    logger.warning("ml_orchestrator.langgraph_not_installed", msg="pip install langgraph")
    _LANGGRAPH_AVAILABLE = False


class MLOrchestrationState(TypedDict):
    """Immutable state passed between LangGraph nodes."""

    data_quality_score: float | None
    last_discovery_run_id: str | None
    model_status: str  # 'none' | 'training' | 'shadow' | 'production'
    last_error: str | None


class MLOrchestratorComputeAgent(BaseAgent):
    """Weekly ML pipeline orchestrator using LangGraph StateGraph."""

    def __init__(self, settings: Settings) -> None:
        setup_service_logging("logs/ml_orchestrator_agent.log")
        super().__init__("MLOrchestratorComputeAgent")
        self._settings = settings
        self._pool: asyncpg.Pool | None = None
        self._producer = KafkaProducerClient(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )

    async def _setup(self) -> None:
        self._pool = await asyncpg.create_pool(self._settings.database_url)

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag until stop event. One-shot orchestrator — no buffer accumulation."""
        while not self._stop_event.is_set():
            PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(0)
            await asyncio.sleep(15)

    async def _teardown(self) -> None:
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        """One-shot entry point: run LangGraph pipeline and exit."""
        self.logger.info("ml_orchestrator.starting")
        try:
            initial_state: MLOrchestrationState = {
                "data_quality_score": None,
                "last_discovery_run_id": None,
                "model_status": "none",
                "last_error": None,
            }
            final_state = await self._run_graph(initial_state)
            self.logger.info(
                "ml_orchestrator.complete",
                data_quality_score=final_state.get("data_quality_score"),
                discovery_run_id=final_state.get("last_discovery_run_id"),
                model_status=final_state.get("model_status"),
            )
        except Exception as exc:
            self.logger.exception("ml_orchestrator.error", error=str(exc))
            await self._producer.publish(
                topic_ml_orchestrator_dlq(self._settings.env_name),
                {"error": str(exc)},
            )

    async def _run_graph(self, initial_state: MLOrchestrationState) -> MLOrchestrationState:
        """Run LangGraph pipeline or sequential fallback if langgraph unavailable."""
        if not _LANGGRAPH_AVAILABLE:
            return await self._run_sequential(initial_state)

        from langgraph.graph import END, StateGraph

        graph = StateGraph(MLOrchestrationState)
        graph.add_node("data_quality", self._data_quality_node)
        graph.add_node("discovery", self._discovery_node)
        graph.add_node("training", self._training_node)
        graph.add_node("monitor", self._monitor_node)

        graph.set_entry_point("data_quality")
        graph.add_conditional_edges(
            "data_quality",
            self._quality_gate,
            {"pass": "discovery", "fail": END},
        )
        graph.add_edge("discovery", "training")
        graph.add_edge("training", "monitor")
        graph.add_edge("monitor", END)

        compiled = graph.compile()
        result = await compiled.ainvoke(initial_state)
        return result

    async def _run_sequential(self, state: MLOrchestrationState) -> MLOrchestrationState:
        """Fallback sequential execution when langgraph is not installed."""
        state = await self._data_quality_node(state)
        if self._quality_gate(state) == "fail":
            return state
        state = await self._discovery_node(state)
        state = await self._training_node(state)
        state = await self._monitor_node(state)
        return state

    def _quality_gate(self, state: MLOrchestrationState) -> str:
        min_score = self._settings.DATA_QUALITY_MIN_SCORE
        score = state.get("data_quality_score") or 0.0
        if score < min_score:
            self.logger.warning(
                "ml_orchestrator.quality_gate_fail",
                score=score,
                threshold=min_score,
            )
            return "fail"
        return "pass"

    async def _data_quality_node(self, state: MLOrchestrationState) -> MLOrchestrationState:
        """Trigger data quality service and read the resulting score."""
        self.logger.info("ml_orchestrator.data_quality_node.starting")
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "systemctl", "start", "--wait", "indicagent-ml-data-quality.service",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            except TimeoutError as exc:
                proc.kill()
                await proc.wait()
                raise RuntimeError("data quality service timed out after 600s") from exc
            if proc.returncode != 0:
                raise RuntimeError(f"data quality service failed: {stderr.decode()[:200]}")

            async with self._pool.acquire() as conn:
                score = await conn.fetchval(
                    "SELECT score FROM ml_data_quality_runs ORDER BY ts DESC LIMIT 1"
                )
            score = float(score) if score is not None else 0.0
            self.logger.info("ml_orchestrator.data_quality_score", score=score)
            return {**state, "data_quality_score": score}

        except Exception as exc:
            self.logger.exception("ml_orchestrator.data_quality_node.error", error=str(exc))
            return {**state, "data_quality_score": 0.0, "last_error": str(exc)}

    async def _discovery_node(self, state: MLOrchestrationState) -> MLOrchestrationState:
        """Trigger discovery service and capture run_id."""
        self.logger.info("ml_orchestrator.discovery_node.starting")
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "systemctl", "start", "--wait", "indicagent-ml-discovery.service",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                # 30 min max for tsfresh
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)
            except TimeoutError as exc:
                proc.kill()
                await proc.wait()
                raise RuntimeError("discovery service timed out after 1800s") from exc
            if proc.returncode != 0:
                raise RuntimeError(f"discovery service failed: {stderr.decode()[:200]}")

            async with self._pool.acquire() as conn:
                run_id = await conn.fetchval(
                    "SELECT run_id::text FROM ml_discovery_runs ORDER BY ts DESC LIMIT 1"
                )
            self.logger.info("ml_orchestrator.discovery_complete", run_id=run_id)
            return {**state, "last_discovery_run_id": run_id}

        except Exception as exc:
            self.logger.exception("ml_orchestrator.discovery_node.error", error=str(exc))
            return {**state, "last_error": str(exc)}

    async def _training_node(self, state: MLOrchestrationState) -> MLOrchestrationState:
        """STUB -- Phase 67 implements LightGBM training here."""
        self.logger.info(
            "ml_orchestrator.training_node.stub",
            msg="awaiting Phase 67 -- no training today",
        )
        return state  # pass through unchanged

    async def _monitor_node(self, state: MLOrchestrationState) -> MLOrchestrationState:
        """STUB -- Phase 67 implements model performance monitoring here."""
        self.logger.info(
            "ml_orchestrator.monitor_node.stub",
            msg="awaiting Phase 67 -- no monitoring today",
        )
        return state  # pass through unchanged


def main() -> None:
    settings = Settings()
    agent = MLOrchestratorComputeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
