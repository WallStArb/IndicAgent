#!/usr/bin/env bash
# Install and enable all IndicAgent systemd services.
# Run from the production/systemd/ directory or any path — uses script-relative paths.
# Usage: sudo ./install.sh
#
# Current service inventory (v2.2 DAG architecture):
#   Data layer:   data-provider, bar-aggregator-compute, feature-compute, feature-writer
#   Bar audit:    bar-writer (Phase 53.1), bar-auditor (Phase 53.1)
#   Intelligence: intelligence-compute, signal-generator, signal-tracker
#   Persistence:  feature-snapshot-writer, parity-auditor, llm-writer
#   Analytics:    cross-asset, ai-narrative
#   API:          api
#   Timers:       weight-updater, data-quality

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

SERVICES=(
    indicagent-data-provider.service
    indicagent-bar-aggregator-compute.service
    indicagent-feature-compute.service
    indicagent-feature-writer.service
    indicagent-feature-snapshot-writer.service
    indicagent-intelligence-compute.service
    indicagent-signal-generator.service
    indicagent-signal-tracker.service
    indicagent-parity-auditor.service
    indicagent-cross-asset.service
    indicagent-ai-narrative.service
    indicagent-llm-writer.service
    indicagent-api.service
    indicagent-weight-updater.service
)

TIMERS=(
    indicagent-weight-updater.timer
    indicagent-data-quality.timer
)

echo "==> Removing legacy services (renamed or retired)"
for legacy in \
    indicagent-tws.service \
    indicagent-indicator.service \
    indicagent-market-analysis.service \
    indicagent-signal-lifecycle.service \
    indicagent-feature-pipeline.service \
    indicagent-timeframes.service; do
    if systemctl is-enabled "$legacy" &>/dev/null; then
        systemctl disable "$legacy"
        echo "    disabled $legacy"
    fi
    if [[ -f "$SYSTEMD_DIR/$legacy" ]]; then
        rm "$SYSTEMD_DIR/$legacy"
        echo "    removed $legacy"
    fi
done

echo "==> Copying service files to $SYSTEMD_DIR"
for svc in "${SERVICES[@]}"; do
    if [[ -f "$SCRIPT_DIR/$svc" ]]; then
        cp "$SCRIPT_DIR/$svc" "$SYSTEMD_DIR/$svc"
        echo "    $svc"
    else
        echo "    SKIP (no template): $svc"
    fi
done

echo "==> Copying timers"
for timer in "${TIMERS[@]}"; do
    if [[ -f "$SCRIPT_DIR/$timer" ]]; then
        cp "$SCRIPT_DIR/$timer" "$SYSTEMD_DIR/$timer"
        echo "    $timer"
    fi
done

echo "==> Reloading systemd"
systemctl daemon-reload

echo "==> Enabling services"
for svc in "${SERVICES[@]}"; do
    if [[ -f "$SYSTEMD_DIR/$svc" ]]; then
        systemctl enable "$svc"
        echo "    enabled $svc"
    fi
done

for timer in "${TIMERS[@]}"; do
    if [[ -f "$SYSTEMD_DIR/$timer" ]]; then
        systemctl enable "$timer"
        echo "    enabled $timer"
    fi
done

echo ""
echo "Done. Start all services with:"
echo "  sudo systemctl start indicagent-data-provider indicagent-bar-aggregator-compute indicagent-feature-compute indicagent-feature-writer indicagent-signal-generator indicagent-signal-tracker indicagent-ai-narrative indicagent-llm-writer indicagent-api"
