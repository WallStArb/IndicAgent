"""Feature Validation Agent — systemd oneshot entrypoint (Phase 82 D-05).

Invoked daily by indicagent-feature-validation.timer (02:00 ET).
Type=oneshot: runs once, exits.

Mirrors services/ml_training_agent.py main() pattern.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.settings import Settings
from src.intelligence.services.feature_validation_compute_agent import (
    FeatureValidationComputeAgent,
)


def main() -> None:
    """Create agent, run, exit.

    FeatureValidationComputeAgent.start() swallows all exceptions and logs them,
    so asyncio.run() always completes cleanly (systemd oneshot exit code 0).
    """
    settings = Settings()
    agent = FeatureValidationComputeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
