#!/usr/bin/env bash
#
# ops_corpus_pipeline_run.sh — v3.0 corpus pipeline orchestrator
#
# Runs feature_factory → regime_writer → ic_engine → ensemble_trainer → alpha_publisher sequence
# for corpus generation. Use for initial population or incremental updates.
# Requires market_data_ohlcv populated and Redpanda + TimescaleDB running.
#

set -euo pipefail

PYTHON=".venv/bin/python"
LOG_DIR="logs/corpus_pipeline"
mkdir -p "$LOG_DIR"

FROM_STEP=1
SYMBOLS_ARG=""
SYMBOLS_FLAG=""

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-step)
            FROM_STEP="$2"
            shift 2
            ;;
        --symbols)
            SYMBOLS_ARG="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--from-step N] [--symbols SYM1,SYM2]"
            exit 1
            ;;
    esac
done

if [[ -n "$SYMBOLS_ARG" ]]; then
    # backfill_feature_factory uses comma-separated --symbols; others use space-separated
    SYMBOLS_FLAG="$SYMBOLS_ARG"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RUN_START=$(date +%s)
STEP_ERRORS=()

banner() {
    local step=$1
    local name=$2
    local status=$3
    echo
    echo "======================================"
    printf " Step %d/6 — %s\n" "$step" "$name"
    echo " Status: $status"
    echo " $(date)"
    echo "======================================"
}

elapsed_since() {
    local start=$1
    local end
    end=$(date +%s)
    echo $(( end - start ))s
}

check_regime_consistency() {
    if (( FROM_STEP > 4 )); then
        return 0
    fi

    echo
    echo "======================================"
    echo " Corpus Consistency Gate"
    echo " Checking regime label uniformity across symbols"
    echo " $(date)"
    echo "======================================"

    local distinct_sets
    distinct_sets=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
        -tAc "SELECT COUNT(DISTINCT regime_set) FROM (SELECT symbol, ARRAY_AGG(DISTINCT regime ORDER BY regime)::text AS regime_set FROM feature_vectors WHERE regime IS NOT NULL GROUP BY symbol) sub")

    if [[ -z "$distinct_sets" || "$distinct_sets" == "0" ]]; then
        echo
        echo "  ERROR: No regime labels found in feature_vectors."
        echo "  Run regime_writer (step 2) before proceeding."
        echo
        exit 1
    fi

    if (( distinct_sets > 1 )); then
        echo
        echo "  ERROR: Inconsistent regime label sets detected across symbols."
        echo "  distinct_sets = $distinct_sets"
        echo
        echo "  Breakdown by regime label set:"
        PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
            "SELECT regime_set, COUNT(*) AS num_symbols, ARRAY_AGG(symbol ORDER BY symbol)::text AS symbols FROM (SELECT symbol, ARRAY_AGG(DISTINCT regime ORDER BY regime)::text AS regime_set FROM feature_vectors WHERE regime IS NOT NULL GROUP BY symbol) sub GROUP BY regime_set ORDER BY num_symbols DESC" \
            | sed 's/^/  /'
        echo
        echo "  This typically means K (feature.hmm.n_components) changed mid-run."
        echo "  Truncate feature_vectors regime columns and re-run from step 2:"
        echo "    bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 2${SYMBOLS_ARG:+ --symbols $SYMBOLS_ARG}"
        echo
        exit 1
    fi

    # distinct_sets == 1: all symbols share the same label set
    local label_set symbol_count
    label_set=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
        -tAc "SELECT ARRAY_AGG(DISTINCT regime ORDER BY regime)::text FROM feature_vectors WHERE regime IS NOT NULL")
    symbol_count=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
        -tAc "SELECT COUNT(DISTINCT symbol) FROM feature_vectors WHERE regime IS NOT NULL")

    echo "  OK: All $symbol_count symbols share the same regime label set."
    echo "  Labels: $label_set"
    echo
}

run_step() {
    local step=$1
    local name=$2
    shift 2
    local cmd=("$@")

    if (( step < FROM_STEP )); then
        echo "  [skipped — --from-step $FROM_STEP]"
        return 0
    fi

    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    local logfile="$LOG_DIR/step${step}_${name}_${ts}.log"
    local t0
    t0=$(date +%s)

    banner "$step" "$name" "RUNNING"
    echo "  Command: ${cmd[*]}"
    echo "  Log:     $logfile"
    echo

    if PYTHONUNBUFFERED=1 "${cmd[@]}" > "$logfile" 2>&1; then
        echo "  DONE in $(elapsed_since "$t0")"
        tail -5 "$logfile" | sed 's/^/  /'
    else
        local rc=$?
        echo "  FAILED (exit $rc) after $(elapsed_since "$t0")"
        echo "  Last 20 lines of $logfile:"
        tail -20 "$logfile" | sed 's/^/    /'
        STEP_ERRORS+=("step $step ($name)")
        echo
        echo "  Pipeline halted. Fix the error then resume with:"
        echo "    bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step $step${SYMBOLS_ARG:+ --symbols $SYMBOLS_ARG}"
        exit "$rc"
    fi
}

# ---------------------------------------------------------------------------
# Build per-step symbol args (scripts differ: comma-sep vs space-sep vs none)
# ---------------------------------------------------------------------------
# backfill_feature_factory: --symbols SPY,TLT  (comma, single arg)
FF_SYMBOLS=()
if [[ -n "$SYMBOLS_FLAG" ]]; then
    FF_SYMBOLS=(--symbols "$SYMBOLS_FLAG")
fi

# regime_writer / forward_return_writer / ic_engine: --symbols SPY TLT  (space-sep, nargs=*)
SPACE_SYMBOLS=()
if [[ -n "$SYMBOLS_FLAG" ]]; then
    IFS=',' read -ra _syms <<< "$SYMBOLS_FLAG"
    SPACE_SYMBOLS=(--symbols "${_syms[@]}")
fi

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
echo "======================================"
echo " v3.0 Full Corpus Pipeline"
echo " $(date)"
[[ -n "$SYMBOLS_FLAG" ]] && echo " Scope: $SYMBOLS_FLAG" || echo " Scope: all active ETFs"
[[ "$FROM_STEP" -gt 1 ]] && echo " Resuming from step $FROM_STEP"
echo "======================================"

# Step 1 — Feature Factory (OHLCV → feature_vectors)
run_step 1 "feature_factory" \
    "$PYTHON" services/backfill_feature_factory.py \
    --compute-only \
    "${FF_SYMBOLS[@]}"

# Capture freeze point after step 1 — always executed so --from-step N resumes still lock it.
# This value is passed explicitly to forward_return_writer and ic_engine to stabilize PKs
# across multi-run builds (avoids training_window_end drift if new bars arrive mid-pipeline).
TRAINING_WINDOW_END=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -tAc "SELECT MAX(bar_ts) FROM feature_vectors")

# Step 2 — Regime Writer (feature_vectors → regime_label column)
run_step 2 "regime_writer" \
    "$PYTHON" services/regime_writer.py \
    "${SPACE_SYMBOLS[@]}"

# Corpus consistency gate — abort if symbols have divergent regime label sets
check_regime_consistency

# Step 3 — Forward Return Writer (feature_vectors → forward_returns)
# forward_returns must be truncated and re-run after the ET session-boundary fix
# (complete_{scale} flags changed for intraday TFs — 5m, 15m, 1h).
run_step 3 "forward_return_writer" \
    "$PYTHON" services/forward_return_writer.py \
    "${SPACE_SYMBOLS[@]}" \
    --training-window-end "$TRAINING_WINDOW_END"

# Step 4 — IC Engine (feature_vectors + forward_returns → feature_ic_scores)
run_step 4 "ic_engine" \
    "$PYTHON" services/ic_engine.py \
    "${SPACE_SYMBOLS[@]}" \
    --training-window-end "$TRAINING_WINDOW_END"

# Step 5 — Ensemble Trainer (feature_ic_scores + feature_vectors → ensemble_weights + ensemble_alpha)
run_step 5 "ensemble_trainer" \
    "$PYTHON" services/ensemble_trainer.py

# Step 6 — Alpha Publisher (ensemble_alpha → alpha_events + Kafka)
run_step 6 "alpha_publisher" \
    "$PYTHON" services/alpha_publisher.py

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "======================================"
echo " Pipeline complete"
echo " Total elapsed: $(elapsed_since "$RUN_START")"
echo " Logs: $LOG_DIR/"
echo " $(date)"
echo "======================================"
