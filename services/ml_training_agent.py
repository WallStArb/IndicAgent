"""ML Training Agent — systemd oneshot entrypoint (Phase 070).

Invoked nightly by indicagent-ml-training.timer (03:00 UTC).
Type=oneshot: runs once, exits.

Mirrors services/ml_orchestrator_agent.py main() pattern.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.settings import Settings
from src.intelligence.services.ml_training_compute_agent import MLTrainingComputeAgent


def main() -> None:
    """Create agent, run, exit.

    MLTrainingComputeAgent._run() swallows all exceptions and logs them,
    so asyncio.run() always completes cleanly (systemd oneshot exit code 0).
    """
    settings = Settings()
    agent = MLTrainingComputeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
