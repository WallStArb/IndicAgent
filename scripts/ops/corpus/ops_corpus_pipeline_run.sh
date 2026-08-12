#!/usr/bin/env bash
#
# ops_corpus_pipeline_run.sh — v3.0 corpus pipeline orchestrator
#
# Runs feature_factory → regime_writer → forward_return_writer → equity_regime_model →
# ic_engine → ic_shrinkage → ensemble_trainer → alpha_publisher sequence for corpus generation.
# Use for initial population or incremental updates.
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

# Durable, append-only, non-timestamped-filename record of every step's wall-clock
# cost across every invocation of this script (including --from-step resumes) --
# distinct from the per-run $LOG_DIR/*.log/.out files, which get a fresh timestamped
# name each invocation and therefore can't answer "which step actually dominates
# runtime" without manually reconstructing history across however many files a
# restarted run produced (todo 217).
STEP_TIMINGS_LOG="$LOG_DIR/step_timings.jsonl"

log_step_timing() {
    local step=$1 name=$2 start_epoch=$3 end_epoch=$4 status=$5 logfile=$6
    printf '{"run_start":"%s","step":%d,"name":"%s","start":"%s","end":"%s","duration_s":%d,"status":"%s","logfile":"%s"}\n' \
        "$(date -u -d "@$RUN_START" +%Y-%m-%dT%H:%M:%SZ)" \
        "$step" "$name" \
        "$(date -u -d "@$start_epoch" +%Y-%m-%dT%H:%M:%SZ)" \
        "$(date -u -d "@$end_epoch" +%Y-%m-%dT%H:%M:%SZ)" \
        "$(( end_epoch - start_epoch ))" "$status" "$logfile" \
        >> "$STEP_TIMINGS_LOG"
}

banner() {
    local step=$1
    local name=$2
    local status=$3
    echo
    echo "======================================"
    printf " Step %d/8 — %s\n" "$step" "$name"
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
    if (( FROM_STEP > 5 )); then
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

check_canary_integrity() {
    # Skip once resuming from a step past ic_shrinkage (6) or later -- mirrors
    # check_regime_consistency's pattern: if we're that far into a resumed run,
    # ic_engine (5, this check's dependency) already completed in a prior
    # invocation and this gate already evaluated its output then.
    if (( FROM_STEP > 6 )); then
        return 0
    fi

    echo
    echo "======================================"
    echo " Canary Integrity Gate (Component D, todo 068, Phase 143.1-02)"
    echo " Expectation-aware, false-halt-aware assertion over the 5 canary/"
    echo " control predictors (concept_registry domain='feature', is_control=true rows)"
    echo " $(date)"
    echo "======================================"

    if ! "$PYTHON" scripts/ops/alpha/ops_canary_integrity_assert.py; then
        echo
        echo "  FATAL: canary integrity gate failed -- see output above."
        echo "  This means either a negative-control canary cleared the IC"
        echo "  significance gate in the POOLED stratum (broken measurement"
        echo "  pipeline -- one config flip from weighting a control feature"
        echo "  into the live ensemble), the acausal-placebo positive control"
        echo "  failed to clear it (pipeline cannot detect genuine look-ahead"
        echo "  leakage), or per-symbol false clears exceeded the"
        echo "  pre-committed Binomial tail bound."
        echo
        echo "  Pipeline halted. Do not proceed to ic_shrinkage/ensemble_trainer"
        echo "  with unverified measurement integrity."
        echo
        exit 1
    fi
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
        log_step_timing "$step" "$name" "$t0" "$(date +%s)" "done" "$logfile"
    else
        local rc=$?
        echo "  FAILED (exit $rc) after $(elapsed_since "$t0")"
        echo "  Last 20 lines of $logfile:"
        tail -20 "$logfile" | sed 's/^/    /'
        STEP_ERRORS+=("step $step ($name)")
        log_step_timing "$step" "$name" "$t0" "$(date +%s)" "failed" "$logfile"
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
#
# OOS holdout enforcement (alpha.validation.oos_start): TRAINING_WINDOW_END must never cross
# the pre-committed OOS boundary, or training/IC/ensemble would see held-out data — the exact
# leakage this clamp exists to prevent. Reversing this clamp back to a bare MAX(bar_ts) query
# is a protocol violation (see docs/plans/OOS-EVAL-PROTOCOL.md).
RAW_MAX_BAR_TS=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -tAc "SELECT MAX(bar_ts) FROM feature_vectors")

if [[ -z "$RAW_MAX_BAR_TS" ]]; then
    echo
    echo "  FATAL: feature_vectors is empty — MAX(bar_ts) returned NULL."
    echo "  Run step 1 (feature_factory) to populate feature_vectors before deriving"
    echo "  TRAINING_WINDOW_END. Refusing to proceed with a NULL freeze point."
    echo
    exit 1
fi

OOS_START=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -tAc "SELECT NULLIF(config_value,'') FROM config_state WHERE config_key='alpha.validation.oos_start'")

# LEAST() is Postgres-NULL-aware: it ignores a NULL argument and returns the smallest
# non-null value, so an empty/unset oos_start degrades gracefully to RAW_MAX_BAR_TS (no
# holdout). A malformed NON-empty oos_start raises "invalid input syntax for type
# timestamp" at the ::timestamptz cast — under `set -euo pipefail` that non-zero psql
# exit aborts the run loudly rather than silently mis-clamping.
TRAINING_WINDOW_END=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -tAc "SELECT LEAST(
            (SELECT MAX(bar_ts) FROM feature_vectors),
            (SELECT NULLIF(config_value,'')::timestamptz FROM config_state WHERE config_key='alpha.validation.oos_start')
          )")

echo
echo "======================================"
echo " OOS holdout enforcement"
echo " Raw MAX(bar_ts):        $RAW_MAX_BAR_TS"
echo " alpha.validation.oos_start: ${OOS_START:-<unset>}"
echo " Effective TRAINING_WINDOW_END: $TRAINING_WINDOW_END"
if [[ -z "$OOS_START" ]]; then
    echo " WARNING: alpha.validation.oos_start is unset — NO holdout is in effect."
    echo " Training/IC/ensemble will see the full corpus, including any data that"
    echo " should have been reserved for out-of-sample evaluation."
fi
echo "======================================"
echo

# WEIGHT_EPOCH — per-run weight epoch derived from the (clamped) freeze point.
# Boundary identity, not a globally unique per-run ID: two runs sharing the same
# TRAINING_WINDOW_END share one epoch by design — ensemble_trainer's DO UPDATE upsert
# makes a same-epoch re-run idempotent (overwrite, not collide). Threaded to BOTH
# ensemble_trainer (step 5, producer) and alpha_publisher (step 6, consumer) so they
# always agree on the same weight_version — closing the silent-staleness trap at both
# the training write and the emission event_id.
#
# Pure digit extraction of the freeze timestamp — deterministic, filesystem/PK-safe,
# no arithmetic (no off-by-one surface).
WEIGHT_EPOCH="run_$(echo "$TRAINING_WINDOW_END" | tr -cd '0-9')"

if [ -z "$TRAINING_WINDOW_END" ] || [ "$WEIGHT_EPOCH" = "run_" ]; then
    echo "FATAL: WEIGHT_EPOCH is empty/malformed (TRAINING_WINDOW_END='$TRAINING_WINDOW_END') — refusing to run trainer/publisher with a degenerate epoch" >&2
    exit 1
fi

echo "======================================"
echo " Weight epoch"
echo " WEIGHT_EPOCH: $WEIGHT_EPOCH"
echo "======================================"
echo

# Step 2 — Regime Writer (feature_vectors → regime_label column)
run_step 2 "regime_writer" \
    "$PYTHON" services/regime_writer.py \
    "${SPACE_SYMBOLS[@]}"

# Step 2 (volatility) — Regime Writer, regime_volatility family (Phase 172).
# One regime_writer.py invocation writes exactly one column family (--regime-column
# defaults to "regime"; "regime_volatility" is a second, separate pass) -- this
# script previously only ran the legacy-family pass, which left
# feature_vectors.regime_volatility all-NULL going into step 5. ic_engine.py's
# startup gate hard-fails on that ("IC Engine startup gate FAILED:
# feature_vectors.regime_volatility is all-NULL") -- found 2026-08-12 reading the
# gate before launching a full-corpus run, previously undocumented (see todo 285).
# Reuses step number 2 (not a new numbered step) so --from-step semantics and
# existing operator muscle memory for resuming at a specific step are unaffected.
run_step 2 "regime_writer_volatility" \
    "$PYTHON" services/regime_writer.py \
    --regime-column regime_volatility \
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

# Step 4 — Cross-Sectional Regime Model (market_data_ohlcv → market_regimes, one
# cross-sectional regime label per enabled alpha.regime.groups entry — equity via
# breadth_vol, rates via curve_credit; commodity/fx ship disabled). Generalizes the
# prior equity-only equity_regime_model.py (Phase 144 — see
# services/equity_regime_model.py's deprecation header for the rollback path).
# Independent of feature_vectors/regime_writer — reads raw bars only — but must land
# before ic_engine, whose startup gate FAILs immediately if market_regimes is empty
# and alpha.regime.equity_model_enabled=true. No --symbols arg: always computes
# across the full active-instrument universe per TF.
run_step 4 "cross_sectional_regime_model" \
    "$PYTHON" services/cross_sectional_regime_model.py

# Step 5 — IC Engine (feature_vectors + forward_returns → feature_ic_scores)
run_step 5 "ic_engine" \
    "$PYTHON" services/ic_engine.py \
    "${SPACE_SYMBOLS[@]}" \
    --training-window-end "$TRAINING_WINDOW_END"

# Canary integrity gate — abort if a control feature proves the measurement
# pipeline is broken (see check_canary_integrity() for the full rule).
check_canary_integrity

# Step 6 — IC Shrinkage (E1): shrink feature_ic_scores IC estimates toward a
# leave-one-out peer-group prior; the out-of-fold acceptance gate flips
# alpha.ensemble.ic_input to 'ic_shrunk' only on empirical PASS (D-04/D-05). A gate
# FAIL is a valid, expected report (exit 0) -- it must not halt the pipeline; step 7
# always proceeds using whichever ic_input is currently configured.
run_step 6 "ic_shrinkage" \
    "$PYTHON" scripts/ops/alpha/ops_ic_shrinkage.py

# Step 7 — Ensemble Trainer (feature_ic_scores + feature_vectors → ensemble_weights + ensemble_alpha)
run_step 7 "ensemble_trainer" \
    "$PYTHON" services/ensemble_trainer.py \
    --weight-version "$WEIGHT_EPOCH"

# Step 8 — Alpha Publisher (ensemble_alpha → alpha_events + Kafka)
run_step 8 "alpha_publisher" \
    "$PYTHON" services/alpha_publisher.py \
    --weight-version "$WEIGHT_EPOCH"

# Vocabulary Drift Audit (Phase 161, Controlled Vocabulary System) — observability-only
# (D-09): writes a loud integrity_monitor row (monitor_type='vocabulary_drift') + OTel
# counter + logger.error per namespace/guard carrying an unregistered live code. Never
# gates the pipeline — not wrapped in run_step (halts on non-zero) and not modeled on
# check_canary_integrity (a hard gate); `|| true` swallows a non-zero exit so a drift-
# audit failure never blocks alpha_publisher's already-committed completion. Backgrounded
# (subshell + &) since nothing downstream waits on it — no reason to hold the pipeline's
# wall-clock completion on a step that can't fail it. PID logged so an unexpectedly-killed
# run (e.g. a supervising wrapper tearing down the process group) leaves a trace instead
# of vanishing silently.
( "$PYTHON" -m src.config.vocabulary_drift \
    2>&1 | tee -a "$LOG_DIR/vocabulary_drift_$(date +%Y%m%d_%H%M%S).log" || true ) &
echo "Vocabulary drift audit backgrounded (PID: $!)"

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
