#!/bin/bash
# provision_dlq_topics.sh — Create all DLQ topics in Redpanda
# Phase 067-07 Task 5: DLQ Topic Provisioning
#
# Usage: ./provision_dlq_topics.sh [env]
#   env: Environment name (default: dev)

set -e

ENV_NAME=${1:-dev}
RETENTION_MS=604800000  # 7 days

echo "Creating DLQ topics for environment: $ENV_NAME"
echo "Retention: $RETENTION_MS ms (7 days)"

# Writer agent DLQs
docker exec redpanda rpk topic create ${ENV_NAME}.bar.writer.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.feature.writer.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.signal.writer.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.lifecycle.writer.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.swarm.writer.dlq --config retention.ms=${RETENTION_MS}

# Auditor agent DLQs
docker exec redpanda rpk topic create ${ENV_NAME}.bar.audit.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.signal.audit.dlq --config retention.ms=${RETENTION_MS}

# Compute agent DLQs
docker exec redpanda rpk topic create ${ENV_NAME}.intelligence.pipeline.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.signal.tracker.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.cross.asset.dlq --config retention.ms=${RETENTION_MS}

# LLM writer DLQ
docker exec redpanda rpk topic create ${ENV_NAME}.llm.writer.dlq --config retention.ms=${RETENTION_MS}

# Compute agent DLQs (additional)
docker exec redpanda rpk topic create ${ENV_NAME}.intelligence.signal.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.swarm.orchestrator.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.market.events.roll.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.intelligence.service_auditor.journal.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.ml.orchestrator.dlq --config retention.ms=${RETENTION_MS}
docker exec redpanda rpk topic create ${ENV_NAME}.gap_fill.dlq --config retention.ms=${RETENTION_MS}

echo ""
echo "Verifying DLQ topics:"
docker exec redpanda rpk topic list | grep "${ENV_NAME}.*\.dlq"

echo ""
echo "DLQ topic provisioning complete!"
