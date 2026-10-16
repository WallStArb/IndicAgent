#!/usr/bin/env bash
# IBKR 1d raw deepening: gate check, launcher, retry and completion watcher (todo 537).
#
# Scheduled from bg's crontab (11,41 * * * *) so it runs with no Claude session open. Each
# fire: kill the deepening run if a cutover window opened under it (fingerprint rule), watch
# completion, and when every gate is clear launch one scoped full-scan fetcher run:
#   ohlcv_history_fetcher.py --dimension compute_1d --timeframes 1d --full-scan
# A run that dies (gateway loss, crash) is simply relaunched on a later fire; the fetcher is
# resumable by design. Two consecutive launched runs that land zero pre-2015 1d bars mean the
# cohort is exhausted (remaining names are no_data-confirmed floors); the script then removes
# its own crontab line and stops. Runbook: docs/plans/2026-10-16-ibkr-1d-raw-deepening.md.
set -u
cd /home/bg/dev/indicagent || exit 1

PY=/home/bg/dev/indicagent/.venv/bin/python
LOG=logs/ibkr_1d_deepening_gate.log
STATE=logs/ibkr_1d_deepening.state
RUN_LOG=logs/ibkr_1d_deepening_run.log
RUN_PATTERN="ohlcv_history_fetcher.py.*--full-scan"
PSQL_BIN=$(command -v psql || echo /usr/bin/psql)

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG"; }

psql_q() {
  env PGPASSWORD=postgres "$PSQL_BIN" -U postgres -h localhost -d indicagent -tAq -c "$1"
}

cohort_names() {
  psql_q "WITH own AS (SELECT symbol, min(timestamp) AS s FROM ohlcv_raw WHERE timeframe='1d' AND vendor='ibkr' AND kind <> 'smart_adjusted' GROUP BY symbol), fl AS (SELECT symbol, head_ts FROM ohlcv_provider_head WHERE provider='ibkr' AND timeframe='1d') SELECT count(*) FROM own o JOIN fl f ON f.symbol = o.symbol WHERE o.s > f.head_ts + interval '7 days';"
}

state_get() { sed -n "s/^$1=//p" "$STATE" 2>/dev/null; }
state_set() { printf '%s=%s\n' "$1" "$2" >>"$STATE"; }
state_clear_key() { sed -i "/^$1=/d" "$STATE" 2>/dev/null; }

# --- 1. interlock: a cutover window open under an in-flight run -> kill it before edits land
WINDOW_OUT=$($PY scripts/ops/bars/ops_raw_cutover_window.py status 2>/dev/null || true)
WINDOW_OPEN=0
grep -q "^window opened" <<<"$WINDOW_OUT" && WINDOW_OPEN=1

if pgrep -f "$RUN_PATTERN" >/dev/null 2>&1; then
  if [ "$WINDOW_OPEN" = 1 ]; then
    pkill -f "$RUN_PATTERN"
    log "interlock: cutover window open, killed the in-flight deepening run"
  else
    log "run in flight, nothing to do this cycle"
  fi
  exit 0
fi

# --- 2. completion bookkeeping for the run we launched last (it has finished by now)
STARTED=$(state_get run_started)
if [ -n "$STARTED" ]; then
  BARS=$(psql_q "SELECT count(*) FROM ohlcv_request WHERE timeframe='1d' AND source='ibkr' AND outcome='bars' AND window_start < '2015-01-01' AND answered_at > '$STARTED';")
  NO_BARS=$(state_get no_bars_runs)
  NO_BARS=${NO_BARS:-0}
  if [ "$BARS" = "0" ]; then
    NO_BARS=$((NO_BARS + 1))
  else
    NO_BARS=0
  fi
  state_clear_key no_bars_runs
  state_set no_bars_runs "$NO_BARS"
  state_clear_key run_started
  log "run finished: $BARS pre-2015 bars landed, consecutive no-bars runs: $NO_BARS"
  if [ "$NO_BARS" -ge 2 ]; then
    log "complete: cohort exhausted, cohort names remaining $(cohort_names), removing crontab entry"
    crontab -l 2>/dev/null | grep -v "ops_ibkr_1d_deepening_gate.sh" | crontab -
    exit 0
  fi
fi

# --- 3. gates
if [ "$WINDOW_OPEN" = 1 ]; then
  log "gate: cutover window open, waiting"
  exit 0
fi
if ! systemctl is-active --quiet indicagent-ibkr-history-fetcher.timer; then
  log "gate: fetcher timer not active (window resume pending), waiting"
  exit 0
fi
if pgrep -f "ohlcv_history_fetcher.py" >/dev/null 2>&1; then
  log "gate: another fetcher run holds the stream, waiting"
  exit 0
fi
if [ -n "$(git status --porcelain -- scripts/infrastructure/backfill scripts/ops/bars src/intelligence/bars src/providers 2>/dev/null)" ]; then
  log "gate: fetcher import surface dirty (fingerprint rule), waiting"
  exit 0
fi

# --- 4. launch one run
NOW=$(date -u +%FT%TZ)
COHORT=$(cohort_names)
log "launching full-scan 1d deepening run, cohort names above floor: $COHORT"
state_clear_key run_started
state_set run_started "$NOW"
nohup "$PY" scripts/infrastructure/backfill/ohlcv_history_fetcher.py \
  --dimension compute_1d --timeframes 1d --full-scan >>"$RUN_LOG" 2>&1 &
exit 0
