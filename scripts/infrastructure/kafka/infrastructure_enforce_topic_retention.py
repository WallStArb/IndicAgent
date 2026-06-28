#!/usr/bin/env python3
"""
infrastructure_enforce_topic_retention.py — enforce Redpanda topic retention from canonical spec

Idempotently sets broker-level and per-topic retention.ms to match canonical spec without
deleting or recreating topics; safe to run against live cluster at any time.
Run to correct topic retention drift or after infrastructure_init_kafka_topics.py changes.
Requires Redpanda container accessible via docker exec; rpk CLI installed in container.
"""

import argparse
import subprocess
import sys
from typing import NamedTuple

from scripts.infrastructure.setup.infrastructure_init_kafka_topics import (
    _BUFFER_MS,
    _COMPACTED_TOPICS,
    get_topic_specs,
)

# Broker-level default — protects any topic not in the spec.
# All non-compacted topics in the spec are already >= this value; this just
# ensures organically-created topics don't silently accumulate 7 days of data.
_BROKER_DEFAULT_MS: int = _BUFFER_MS  # 1 day

# Providers whose raw topics may exist in the live cluster.
_KNOWN_PROVIDERS: list[str] = ["ibkr"]


class TopicResult(NamedTuple):
    topic: str
    expected_ms: int
    actual_ms: int
    changed: bool
    skipped: bool  # compacted — no time-based retention


def _rpk(*args: str, broker: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["docker", "exec", "redpanda", "rpk", "--brokers", broker, *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _get_actual_retention(topic: str, broker: str) -> int | None:
    """Return the effective retention.ms for a topic, or None if topic missing."""
    result = _rpk("topic", "describe", topic, broker=broker, check=False)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if "retention.ms" in line and "delete.retention" not in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass
    return None


def _set_topic_retention(topic: str, retention_ms: int, broker: str, dry_run: bool) -> None:
    if dry_run:
        return
    _rpk(
        "topic",
        "alter-config",
        topic,
        "--set",
        f"retention.ms={retention_ms}",
        broker=broker,
    )


def _set_broker_default(retention_ms: int, broker: str, dry_run: bool) -> bool:
    current_result = subprocess.run(
        ["docker", "exec", "redpanda", "rpk", "cluster", "config", "get", "log_retention_ms"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        current = int(current_result.stdout.strip())
    except ValueError:
        current = -1

    if current == retention_ms:
        return False

    print(f"  broker default: {current}ms → {retention_ms}ms")
    if not dry_run:
        subprocess.run(
            [
                "docker",
                "exec",
                "redpanda",
                "rpk",
                "cluster",
                "config",
                "set",
                "log_retention_ms",
                str(retention_ms),
            ],
            check=True,
        )
    return True


def run(broker: str = "localhost:9092", dry_run: bool = False) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}Enforcing Redpanda topic retention\n")

    # 1. Broker-level default
    print("── Broker default ──")
    broker_changed = _set_broker_default(_BROKER_DEFAULT_MS, broker, dry_run)
    if not broker_changed:
        print(f"  broker default already {_BROKER_DEFAULT_MS}ms ✓")

    # 2. Per-topic overrides
    print("\n── Per-topic overrides ──")
    topic_specs = get_topic_specs(_KNOWN_PROVIDERS)

    compacted_names = {s for s, _ in _COMPACTED_TOPICS}

    results: list[TopicResult] = []
    for suffix, _partitions, retention_ms, _policy in topic_specs:
        # Topic names in live cluster include env prefix; try bare name (dev/test
        # clusters typically use the suffix directly since env_prefix is empty or "dev.")
        topic = suffix

        if topic in compacted_names:
            results.append(TopicResult(topic, retention_ms, -1, changed=False, skipped=True))
            continue

        actual = _get_actual_retention(topic, broker)
        if actual is None:
            print(f"  MISSING  {topic} (not in cluster — skip)")
            continue

        if actual == retention_ms:
            results.append(TopicResult(topic, retention_ms, actual, changed=False, skipped=False))
        else:
            print(f"  {prefix}ALTER  {topic}: {actual}ms → {retention_ms}ms")
            _set_topic_retention(topic, retention_ms, broker, dry_run)
            results.append(TopicResult(topic, retention_ms, actual, changed=True, skipped=False))

    # Summary
    changed = [r for r in results if r.changed]
    correct = [r for r in results if not r.changed and not r.skipped]
    skipped = [r for r in results if r.skipped]

    print("\n── Summary ──")
    print(f"  altered : {len(changed)}")
    print(f"  correct : {len(correct)}")
    print(f"  skipped (compacted): {len(skipped)}")

    if changed:
        print("\nNote: Redpanda enforces new retention on the next log segment roll.")
        print("Existing segments older than the new limit will be deleted within minutes.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--broker", default="localhost:9092", help="Redpanda broker address")
    args = parser.parse_args()
    run(broker=args.broker, dry_run=args.dry_run)
    sys.exit(0)


if __name__ == "__main__":
    main()
