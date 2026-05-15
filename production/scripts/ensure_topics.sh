#!/usr/bin/env bash
# ensure_topics.sh — Idempotent DLQ topic provisioning with 7-day retention.
#
# Creates all 15 active DLQ topics if they do not exist and sets
# retention.ms=604800000 (7 days) on each. Safe to run repeatedly.
#
# Usage: bash production/scripts/ensure_topics.sh
set -euo pipefail

DLQ_TOPICS=(
  market.events.roll.dlq
  intelligence.signal.dlq
  bar.aggregator.dlq
  bar.writer.dlq
  feature.writer.dlq
  intelligence.signal.writer.dlq
  lifecycle.writer.dlq
  intelligence.pipeline.dlq
  signal.tracker.dlq
  llm.writer.dlq
  intelligence.transform.graduation.dlq
  intelligence.signal_lineage.dlq
  ml.orchestrator.dlq
  gap_fill.dlq
  intelligence.service_auditor.journal.dlq
)

echo "Provisioning ${#DLQ_TOPICS[@]} DLQ topics with retention.ms=604800000 (7 days)..."

for topic in "${DLQ_TOPICS[@]}"; do
  # Create topic if it does not exist (ignore error if already present)
  docker exec redpanda rpk topic create "$topic" --replicas 1 \
    -c retention.ms=604800000 2>/dev/null || true

  # Set retention regardless (idempotent alter-config)
  docker exec redpanda rpk topic alter-config "$topic" \
    --set retention.ms=604800000

  echo "  OK $topic"
done

echo "Done."
