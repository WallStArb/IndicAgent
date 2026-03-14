#!/usr/bin/env bash
# Install and enable all IndicAgent systemd services.
# Run from the production/systemd/ directory or any path — uses script-relative paths.
# Usage: sudo ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

SERVICES=(
    indicagent-tws.service
    indicagent-indicator.service
    indicagent-market-analysis.service
    indicagent-signal-generator.service
    indicagent-signal-lifecycle.service
    indicagent-feature-writer.service
    indicagent-ai-narrative.service
    indicagent-llm-writer.service
    indicagent-api.service
    indicagent-weight-updater.service
)

TIMER="indicagent-weight-updater.timer"

echo "==> Copying service files to $SYSTEMD_DIR"
for svc in "${SERVICES[@]}"; do
    cp "$SCRIPT_DIR/$svc" "$SYSTEMD_DIR/$svc"
    echo "    $svc"
done

echo "==> Copying timer"
if [[ -f "$SCRIPT_DIR/$TIMER" ]]; then
    cp "$SCRIPT_DIR/$TIMER" "$SYSTEMD_DIR/$TIMER"
    echo "    $TIMER"
fi

echo "==> Removing legacy services"
for legacy in indicagent-signal-tracker.service indicagent-timeframes.service; do
    if systemctl is-enabled "$legacy" &>/dev/null; then
        systemctl disable "$legacy"
        echo "    disabled $legacy"
    fi
    if [[ -f "$SYSTEMD_DIR/$legacy" ]]; then
        rm "$SYSTEMD_DIR/$legacy"
        echo "    removed $legacy"
    fi
done

echo "==> Reloading systemd"
systemctl daemon-reload

echo "==> Enabling services"
for svc in "${SERVICES[@]}"; do
    systemctl enable "$svc"
    echo "    enabled $svc"
done

if [[ -f "$SYSTEMD_DIR/$TIMER" ]]; then
    systemctl enable "$TIMER"
    echo "    enabled $TIMER"
fi

echo ""
echo "Done. Start all services with:"
echo "  sudo systemctl start indicagent-tws indicagent-indicator indicagent-market-analysis indicagent-signal-generator indicagent-signal-lifecycle indicagent-feature-writer indicagent-ai-narrative indicagent-llm-writer indicagent-api"
