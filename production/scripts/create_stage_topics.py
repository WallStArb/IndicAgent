#!/usr/bin/env python3
"""Create Redpanda topics for DAG pipeline stages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config.settings import Settings
from src.core.stream_keys import (
    topic_attribution,
    topic_calibrated,
    topic_data_quality,
    topic_quality_gated,
    topic_ranked,
    topic_regime_gated,
    topic_tod_adjusted,
    topic_winner,
)

# 7-day retention in milliseconds
RETENTION_MS = 604800000

# All stage topics (name, topic_builder)
STAGE_TOPICS = [
    ("quality_gated", topic_quality_gated),
    ("regime_gated", topic_regime_gated),
    ("tod_adjusted", topic_tod_adjusted),
    ("calibrated", topic_calibrated),
    ("ranked", topic_ranked),
    ("winner", topic_winner),
    ("attribution", topic_attribution),
    ("data_quality", topic_data_quality),
]


def create_topic(topic_name: str) -> bool:
    """Create a single Redpanda topic with 7-day retention.

    rpk topic create uses -c key=value for config (not --set).
    """
    cmd = [
        "docker",
        "exec",
        "redpanda",
        "rpk",
        "topic",
        "create",
        topic_name,
        "-c",
        f"retention.ms={RETENTION_MS}",
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"  Created topic: {topic_name}")
        return True

    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "already exists" in stderr or "TOPIC_ALREADY_EXISTS" in stderr:
            print(f"  Topic already exists: {topic_name}")
            return True
        else:
            print(f"  Failed to create topic {topic_name}: {stderr}")
            return False


def set_retention(topic_name: str) -> bool:
    """Set retention on an existing topic (idempotent alter).

    rpk topic alter-config uses --set key=value flags.
    """
    cmd = [
        "docker",
        "exec",
        "redpanda",
        "rpk",
        "topic",
        "alter-config",
        topic_name,
        "--set",
        f"retention.ms={RETENTION_MS}",
        "--no-confirm",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Warning: could not alter retention for {topic_name}: {e.stderr}")
        return False


def main() -> None:
    """Create all stage topics."""
    settings = Settings()

    print("Creating DAG pipeline stage topics...")
    print(f"Environment prefix: {settings.env_name!r}")
    print(f"Retention: {RETENTION_MS}ms (7 days)")
    print()

    success_count = 0
    for name, topic_builder in STAGE_TOPICS:
        topic_name = topic_builder(settings.env_name)
        if create_topic(topic_name):
            # Ensure retention is applied even if topic already existed
            set_retention(topic_name)
            success_count += 1

    print()
    print(f"Created/verified {success_count}/{len(STAGE_TOPICS)} topics")

    if success_count != len(STAGE_TOPICS):
        sys.exit(1)


if __name__ == "__main__":
    main()
