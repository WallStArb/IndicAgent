"""ML Signal Training Materialize Agent — systemd oneshot entrypoint (Phase 104).

Invoked nightly by indicagent-ml-signal-training-materialize.timer (02:00 UTC).
Type=oneshot: runs once, exits.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401

from src.config.settings import Settings
from src.intelligence.services.ml_signal_training_materialize_agent import (
    MLSignalTrainingMaterializeAgent,
)


def main() -> None:
    """Create agent, run materialization, exit cleanly.

    MLSignalTrainingMaterializeAgent catches all exceptions and logs them,
    so asyncio.run() always completes cleanly (systemd oneshot exit code 0).
    """
    settings = Settings()
    agent = MLSignalTrainingMaterializeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
