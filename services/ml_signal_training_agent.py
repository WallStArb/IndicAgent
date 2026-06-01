"""ML Signal Training Materialize Agent — systemd oneshot entrypoint (Phase 104).

Invoked nightly by indicagent-ml-signal-training-materialize.timer (02:00 UTC).
Type=oneshot: runs once, exits.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401

from src.config.settings import Settings
from src.intelligence.services.ml_signal_training_materializer import (
    MLSignalTrainingMaterializer,
)
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

_JOB = "ml-signal-training-materialize"


def main() -> None:
    """Create agent, run materialization, exit cleanly.

    MLSignalTrainingMaterializer catches all exceptions and logs them,
    so asyncio.run() always completes cleanly (systemd oneshot exit code 0).
    """
    settings = Settings()
    agent = MLSignalTrainingMaterializer(settings)
    try:
        asyncio.run(agent.start())
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "success"})
    except Exception:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": "failure"})
        raise
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
