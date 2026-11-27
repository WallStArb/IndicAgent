#!/usr/bin/env bash
# Alert rule gate: promtool check rules on production/alertmanager-rules.yml, then every
# production/alertmanager-rules*.test.yml. Runs the Prometheus image that production/docker-compose.yml
# pins, so CI, a local run and production use the same promtool. Fails loud: no test file, a missing image tag,
# a failed pull or any failed promtool call exits non-zero.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

IMAGE=$(sed -n 's|^ *image: *\(prom/prometheus:[^ ]*\).*|\1|p;T;q' "$ROOT/production/docker-compose.yml")
[[ -n $IMAGE ]] || { echo "check_alert_rules: no prom/prometheus image in production/docker-compose.yml" >&2; exit 1; }

shopt -s nullglob
tests=("$ROOT"/production/alertmanager-rules*.test.yml)
(( ${#tests[@]} > 0 )) || { echo "check_alert_rules: no alertmanager-rules*.test.yml found" >&2; exit 1; }

# Docker Hub answers anonymous pulls with 429 or a timeout now and then: retry before calling it a failure.
for attempt in 1 2 3; do
  docker pull -q "$IMAGE" >/dev/null && break
  (( attempt < 3 )) || { echo "check_alert_rules: cannot pull $IMAGE" >&2; exit 1; }
  sleep $((attempt * 5))
done

promtool() { docker run --rm --entrypoint /bin/promtool -v "$ROOT/production:/p:ro" -w /p "$IMAGE" "$@"; }

promtool check rules alertmanager-rules.yml
for file in "${tests[@]}"; do
  promtool test rules "$(basename "$file")"
done
