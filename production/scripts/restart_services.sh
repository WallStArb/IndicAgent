#!/usr/bin/env bash
# Restart all IndicAgent systemd services in pipeline order.
# Usage: sudo bash production/scripts/restart_services.sh

set -euo pipefail

SERVICES=(
    indicagent-data-provider
    indicagent-bar-aggregator-compute
    indicagent-feature-compute
    indicagent-feature-writer
    indicagent-signal-generator
    indicagent-signal-tracker
    indicagent-ai-narrative
    indicagent-llm-writer
    indicagent-api
)

echo "=== Restarting IndicAgent services ==="
for svc in "${SERVICES[@]}"; do
    echo -n "  $svc ... "
    systemctl restart "$svc"
    echo "ok"
done

echo ""
echo "=== Status ==="
systemctl status "${SERVICES[@]}" --no-pager -l
