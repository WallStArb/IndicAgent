# Phase 74, Plan 1: BarNormalizerAgent - State Checkpointing for BarAggregator

## Summary

Added state checkpointing to BarAggregatorComputeAgent following the IntelligencePipelineComputeAgent pattern. This eliminates two critical vulnerabilities: (M3) data loss on outage when restart exceeds 3-day HTF retention, and (H5) stale state corruption causing HTF bar duplication/suppression.

## What Was Built

### 1. State Topic Infrastructure
- **src/core/stream_keys.py**: Added `topic_bar_aggregator_state()` function
  - Returns compacted topic name: `{env}.bar.aggregator.state`
  - Key format: `{version}:{symbol}:{tf}` (e.g., "1:ESM6:5m")
  - Value: msgpack-encoded BarAccumulator state

- **production/scripts/kafka_init_topics.py**: Added compacted topic configuration
  - Entry: `("bar.aggregator.state", 1)`
  - Partition count: 1 (correct for compacted topics)
  - Cleanup policy: compact, min.cleanable.dirty.ratio=0.1

### 2. State Checkpointing Implementation
- **services/bar_aggregator_agent.py**: Full state checkpointing system
  - Imported StateSerializer and msgpack
  - Added `_AGENT_VERSION = "1"` constant for future-proofing
  - Prometheus metrics: `_state_checkpoint_restored_total`, `_state_checkpoint_failures_total`
  - Degradation tracking: `_checkpoint_failure_timestamps` list

### 3. Core Methods
- **`_track_checkpoint_failure()`**: Sliding window degradation detection
  - Tracks failures in 60-second window
  - Returns True (degraded) if ≥3 failures in 60s
  - Logs critical error and stops processing when degraded

- **`_restore_state_checkpoint()`**: State restoration on startup
  - Consumes compacted state topic with 5-second timeout
  - Skips keys with wrong version prefix
  - Restores `_accumulators` and `_last_session_boundary_log` to BarAccumulator
  - Returns True if any state restored, False on miss/failure

- **`_checkpoint_state(bar)`**: State persistence after each bar
  - Extracts `_accumulators` and `_last_session_boundary_log` from BarAccumulator
  - Encodes with StateSerializer
  - Publishes to compacted state topic with versioned key

### 4. Integration Points
- **`_setup()` method**: Calls `_restore_state_checkpoint()` after Kafka setup
  - Logs "checkpoint_miss — starting fresh" when no state available
  - Executes before consumer starts processing bars

- **`_run()` method**: Calls `_checkpoint_state(bar)` after each bar processed
  - Wrapped in try/except with degradation detection
  - Clears failure timestamps on successful checkpoint
  - Raises exception (stops agent) if degraded (3+ failures in 60s)
  - systemd will restart the agent automatically

## Key Files Created/Modified

### Created
- None (infrastructure only, no new files)

### Modified
- `src/core/stream_keys.py`: Added topic_bar_aggregator_state() function
- `production/scripts/kafka_init_topics.py`: Added compacted topic entry
- `services/bar_aggregator_agent.py`: Full state checkpointing implementation (157 lines added)

## Deviations from Plan

None. All tasks completed exactly as specified.

## Verification

### Automated Checks
✓ Function `topic_bar_aggregator_state()` exists with correct signature
✓ Entry `("bar.aggregator.state", 1)` exists in _COMPACTED_TOPICS
✓ StateSerializer import present
✓ topic_bar_aggregator_state imported
✓ Metrics declared in __init__
✓ Degradation tracking list initialized
✓ `_track_checkpoint_failure()` method exists
✓ `_restore_state_checkpoint()` method exists
✓ `_checkpoint_state()` method exists
✓ Restore called in _setup()
✓ Checkpoint called in _run() with degradation detection

### Manual Verification Needed
1. **Topic creation**: Run `production/scripts/kafka_init_topics.py` to create the compacted topic
   ```bash
   sudo -H -u postgres bash production/scripts/kafka_init_topics.py
   ```

2. **Service restart**: Restart bar_aggregator_agent to pick up changes
   ```bash
   sudo systemctl restart indicagent-bar-aggregator
   ```

3. **Checkpoint validation**: Monitor logs for successful checkpoint operations
   ```bash
   tail -f logs/bar_aggregator_agent.log | grep -E "state\.restored|checkpoint_miss|checkpoint_failed"
   ```

4. **Metrics verification**: Check Prometheus metrics are exported
   ```bash
   curl http://localhost:9120/metrics | grep bar_aggregator_state_checkpoint
   ```

## Integration Testing

### Test 1: Fresh Start (No Checkpoint)
1. Delete any existing state topic data: `docker exec redpanda rkb topic delete bar.aggregator.state`
2. Restart agent: `sudo systemctl restart indicagent-bar-aggregator`
3. Expected log: `"bar_aggregator.state.checkpoint_miss — starting fresh"`
4. Verify agent processes bars normally

### Test 2: State Persistence
1. Let agent run for 5 minutes (accumulate HTF bars)
2. Restart agent: `sudo systemctl restart indicagent-bar-aggregator`
3. Expected log: `"bar_aggregator.state.restored"` with accumulator count
4. Verify HTF bars continue without duplication/suppression

### Test 3: Degradation Detection
1. Manually corrupt state topic (invalid msgpack data)
2. Monitor logs for: `"bar_aggregator.checkpoint_degraded"` (3 failures in 60s)
3. Expected: Agent stops processing and systemd restarts it
4. After restart: `"bar_aggregator.state.checkpoint_miss — starting fresh"`

## Threat Mitigation

| Threat ID | Category | Mitigation |
|-----------|----------|------------|
| T-74-01 | Tampering | State structure validation (only recognized keys) |
| T-74-02 | Spoofing | Version prefix prevents future structure breakage |
| T-74-03 | DoS | 5-second timeout prevents indefinite hang |
| T-74-05 | DoS | Degradation detection stops agent on 3+ failures |

## Next Steps

1. **Deploy to production**: Run kafka_init_topics.py to create the compacted topic
2. **Monitor checkpoint success**: Set up Prometheus alerts for `bar_aggregator_state_checkpoint_failures_total`
3. **Validate data integrity**: Verify HTF bar continuity across restarts
4. **Performance testing**: Confirm checkpoint overhead doesn't impact bar processing latency

## Implementation Notes

- Checkpoint topic is compacted: only latest state per (version, symbol, tf) retained
- Version prefix allows future BarAccumulator structure changes without data corruption
- Degradation detection prevents silent data loss when checkpointing is broken
- Agent stops processing on degradation → systemd restart → fresh start on unrecoverable failure
- State restoration happens before consumer starts → no race condition with new bars
