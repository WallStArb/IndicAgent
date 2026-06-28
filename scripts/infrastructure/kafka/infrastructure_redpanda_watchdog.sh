#!/usr/bin/env bash
#
# infrastructure_redpanda_watchdog.sh — Redpanda health check and auto-restart
#
# Monitors Redpanda health via Kafka API and restarts container if unresponsive.
# Run via systemd timer (indicagent-redpanda-watchdog.timer) every 2 minutes.
# Requires Docker and Redpanda container installed.
#

set -euo pipefail

TIMEOUT=5
MAX_RESTART_ATTEMPTS=2

log() {
    logger -t "redpanda-watchdog" "$@"
}

# Check: can Redpanda respond to a Kafka API request?
if timeout "$TIMEOUT" docker exec redpanda rpk topic list >/dev/null 2>&1; then
    exit 0
fi

log "WARN: Redpanda unresponsive (timeout=${TIMEOUT}s) — attempting restart"

attempt=0
while [ $attempt -lt $MAX_RESTART_ATTEMPTS ]; do
    attempt=$((attempt + 1))
    log "INFO: Restart attempt $attempt/$MAX_RESTART_ATTEMPTS"

    if docker restart redpanda >/dev/null 2>&1; then
        # Wait for Redpanda to become responsive
        sleep 15
        if timeout "$TIMEOUT" docker exec redpanda rpk topic list >/dev/null 2>&1; then
            log "INFO: Redpanda recovered after restart attempt $attempt"
            exit 0
        fi
        log "WARN: Redpanda still unresponsive after restart attempt $attempt"
    else
        log "ERROR: docker restart redpanda failed (attempt $attempt)"
    fi
done

log "ERROR: Redpanda failed to recover after $MAX_RESTART_ATTEMPTS restart attempts"
exit 1
