# Fix A: intelligence_features TOAST Bloat — Cache-and-Fold

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-27
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the follow-up JSONB UPDATE path on `intelligence_features` that causes 17 GB of TOAST bloat on the current week's chunk.

**Architecture:** `FeatureWriterAgent` caches the latest cross-asset snapshot per-timeframe in memory. On bar INSERT, the cached snapshot is merged into `market_context` at param-build time — no follow-up UPDATE. The roll boundary UPDATE is retargeted from `trading_signals` (TOAST'd, 3.4 kB avg) to `market_context` (on-heap, 764 bytes avg) to prevent future TOAST churn on that rare code path too.

**Tech Stack:** Python asyncio, asyncpg, TimescaleDB, Kafka (aiokafka). Tests use pytest + unittest.mock.

---

### Task 1: Write failing tests for cache-and-fold behaviour

**Files:**
- Modify: `tests/unit/services/test_feature_writer_agent.py`

- [ ] **Step 1: Add three failing tests at the end of the test file**

```python
# ── Cache-and-fold tests ──────────────────────────────────────────────────────

def test_record_to_insert_params_folds_cross_asset_into_market_context():
    """cross_asset_snapshot dict is merged into the market_context param."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    snapshot = {"cross_asset": {"es_nq_spread_z": 1.23, "corr_z": -0.5}}
    params = _record_to_insert_params(record, cross_asset_snapshot=snapshot)

    # $9 is market_context — confirm cross_asset key present
    market_ctx = params[8]  # 0-indexed position 8 = $9
    assert "cross_asset" in market_ctx
    assert market_ctx["cross_asset"]["es_nq_spread_z"] == pytest.approx(1.23)


def test_record_to_insert_params_empty_snapshot_leaves_market_context_unchanged():
    """Empty cross_asset_snapshot does not corrupt market_context."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    params_without = _record_to_insert_params(record, cross_asset_snapshot=None)
    params_with = _record_to_insert_params(record, cross_asset_snapshot={})

    assert params_without[8] == params_with[8]


def test_process_cross_asset_message_updates_cache_not_db():
    """_process_cross_asset_message must update _cross_asset_cache, never call execute_batch."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from services.feature_writer_agent import FeatureWriterAgent

    agent = FeatureWriterAgent.__new__(FeatureWriterAgent)
    agent._cross_asset_cache = {}
    agent.db_manager = MagicMock()
    agent.db_manager.execute_batch = AsyncMock()
    agent.logger = MagicMock()

    payload = {
        "tf": "5m",
        "ts": "2026-05-24T10:00:00Z",
        "ready": True,
        "es_nq_spread_z": 0.75,
        "corr_z": -0.3,
        "eq_corr_break": False,
        "eq_vol_imbalance": 0.1,
        "active_pair": "ES-NQ",
        "pairs_confirming": 2,
        "data_quality_score": 0.95,
        "low_vol_flag": False,
    }

    asyncio.get_event_loop().run_until_complete(
        agent._process_cross_asset_message(payload)
    )

    # Cache updated
    assert "5m" in agent._cross_asset_cache
    assert agent._cross_asset_cache["5m"]["cross_asset"]["es_nq_spread_z"] == pytest.approx(0.75)
    # DB never touched
    agent.db_manager.execute_batch.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/services/test_feature_writer_agent.py::test_record_to_insert_params_folds_cross_asset_into_market_context tests/unit/services/test_feature_writer_agent.py::test_record_to_insert_params_empty_snapshot_leaves_market_context_unchanged tests/unit/services/test_feature_writer_agent.py::test_process_cross_asset_message_updates_cache_not_db -v
```

Expected: 3 FAILED (TypeError or AttributeError — `cross_asset_snapshot` param does not exist yet)

---

### Task 2: Add `_cross_asset_cache` to `FeatureWriterAgent.__init__`

**Files:**
- Modify: `services/feature_writer_agent.py` (line ~281, after `self._expiry_map` init)

- [ ] **Step 1: Add cache field after `self._expiry_map`**

In `__init__`, after line `self._expiry_map: dict[str, date] = {}`, add:

```python
        # Per-timeframe cross-asset snapshot cache. Updated by _process_cross_asset_message;
        # folded into market_context at INSERT time. Never written to DB directly.
        self._cross_asset_cache: dict[str, dict] = {}
```

---

### Task 3: Update `_record_to_insert_params` to accept and fold cross-asset snapshot

**Files:**
- Modify: `services/feature_writer_agent.py` (function `_record_to_insert_params`, line ~166)

- [ ] **Step 1: Add `cross_asset_snapshot` parameter and merge into market_context**

Replace the function signature and the market_context param line:

```python
def _record_to_insert_params(
    record: BarIntelligenceRecord,
    expiry_map: dict[str, date] | None = None,
    cross_asset_snapshot: dict | None = None,
) -> tuple:
    """Build a 31-element tuple of INSERT parameters for _INSERT_FEATURE_SQL."""
    event = record.intelligence
    days = _compute_days_to_expiry(event.symbol, event.ts, expiry_map or {})
    winner_dir = str(record.winner_direction) if record.winner_direction is not None else None
    session_type_val = normalize_session_type(record.session_type)

    market_ctx = {
        **event.i2.model_dump(exclude_none=True),
        **(cross_asset_snapshot or {}),
    }

    return (
        event.ts,                                       # $1 ts
        event.symbol,                                   # $2 symbol
        event.tf,                                       # $3 tf
        event.platform,                                 # $4 platform
        event.source,                                   # $5 source
        record.schema_version,                          # $6 schema_version
        event.bar.model_dump(),                         # $7 bar
        event.i1.model_dump(),                          # $8 technical_indicators
        market_ctx,                                     # $9 market_context (+ cross_asset)
        event.i3.model_dump(exclude_none=True),         # $10 pattern_detections
        event.i4.model_dump(exclude_none=True),         # $11 regime_features
        event.i5.model_dump(exclude_none=True),         # $12 confluence_scores
        event.smc.model_dump(exclude_none=True),        # $13 smc
        event.i6.model_dump(exclude_none=True),         # $14 cross_timeframe_context
        [s.model_dump() for s in record.ranked_signals],# $15 trading_signals
        event.bar_close_ts,                             # $16 bar_close_ts
        event.i1_computed_at,                           # $17 i1_computed_at
        event.computed_at,                              # $18 computed_at
        record.winner_plugin,                           # $19 winner_plugin
        record.winner_confidence,                       # $20 winner_confidence
        winner_dir,                                     # $21 winner_direction
        record.signals_evaluated,                       # $22 signals_evaluated
        record.signals_after_quality,                   # $23 signals_after_quality
        record.signals_after_regime,                    # $24 signals_after_regime
        record.signals_after_tod,                       # $25 signals_after_tod
        record.signals_after_calibration,               # $26 signals_after_calibration
        record.ledger_written,                          # $27 ledger_written
        record.pipeline_latency_ms,                     # $28 pipeline_latency_ms
        record.i7_computed_at,                          # $29 i7_computed_at
        session_type_val,                               # $30 session_type
        days,                                           # $31 days_to_expiry
    )
```

---

### Task 4: Wire cache into `_parse_payload`

**Files:**
- Modify: `services/feature_writer_agent.py` (`_parse_payload`, line ~306)

- [ ] **Step 1: Pass cross-asset snapshot when building params**

Replace the `params = _record_to_insert_params(record, self._expiry_map)` line:

```python
        cross_asset = self._cross_asset_cache.get(record.intelligence.tf, {})
        params = _record_to_insert_params(record, self._expiry_map, cross_asset)
```

---

### Task 5: Rewrite `_process_cross_asset_message` — cache only, no DB

**Files:**
- Modify: `services/feature_writer_agent.py` (`_process_cross_asset_message`, line ~623)

- [ ] **Step 1: Replace method body — update cache, remove execute_batch call**

```python
    async def _process_cross_asset_message(self, payload: dict) -> None:
        """Cache cross-asset snapshot for folding into next bar INSERT.

        Cross-asset features are group-level market context (spread z-scores,
        correlation flags). They are merged into market_context at INSERT time
        via _record_to_insert_params — no follow-up UPDATE to intelligence_features.
        """
        try:
            tf = payload.get("tf", "")
            if not tf or not payload.get("ready"):
                return
            self._cross_asset_cache[tf] = {
                "cross_asset": {
                    "es_nq_spread_z": payload.get("es_nq_spread_z"),
                    "es_rty_spread_z": payload.get("es_rty_spread_z"),
                    "eq_corr_break": payload.get("eq_corr_break"),
                    "eq_vol_imbalance": payload.get("eq_vol_imbalance"),
                    "active_pair": payload.get("active_pair"),
                    "pairs_confirming": payload.get("pairs_confirming"),
                    "data_quality_score": payload.get("data_quality_score"),
                    "low_vol_flag": payload.get("low_vol_flag"),
                    "corr_z": payload.get("corr_z"),
                }
            }
        except Exception as e:
            self.logger.warning("cross_asset_cache_update_failed", error=str(e))
            self.error_count_total.add(1)
```

---

### Task 6: Retarget roll boundary UPDATE from `trading_signals` to `market_context`

**Files:**
- Modify: `services/feature_writer_agent.py` (`_UPDATE_I7_MERGE_SQL`, line ~99)

- [ ] **Step 1: Change UPDATE target column**

Replace:

```python
_UPDATE_I7_MERGE_SQL = """
UPDATE intelligence_features
SET trading_signals = COALESCE(trading_signals, '{}'::jsonb) || $4::jsonb
WHERE ts = $1::timestamptz AND symbol = $2 AND tf = $3
"""
```

With:

```python
_UPDATE_MARKET_CTX_SQL = """
UPDATE intelligence_features
SET market_context = COALESCE(market_context, '{}'::jsonb) || $4::jsonb
WHERE ts = $1::timestamptz AND symbol = $2 AND tf = $3
"""
```

- [ ] **Step 2: Update `_handle_roll_event` to use the new constant name**

In `_handle_roll_event` (line ~591), change both references from `_UPDATE_I7_MERGE_SQL` to `_UPDATE_MARKET_CTX_SQL`. There are two calls: the roll boundary marker and the roll_premium_pct UPDATE. The roll_premium_pct UPDATE has its own SQL inline — leave it unchanged. Only the `_UPDATE_I7_MERGE_SQL` call changes:

```python
            await self.db_manager.execute_batch(
                _UPDATE_MARKET_CTX_SQL,
                [(detected_at, new_symbol, _ROLL_BOUNDARY_TF, marker)],
            )
```

---

### Task 7: Run all tests and verify

- [ ] **Step 1: Run the three new tests**

```bash
.venv/bin/pytest tests/unit/services/test_feature_writer_agent.py::test_record_to_insert_params_folds_cross_asset_into_market_context tests/unit/services/test_feature_writer_agent.py::test_record_to_insert_params_empty_snapshot_leaves_market_context_unchanged tests/unit/services/test_feature_writer_agent.py::test_process_cross_asset_message_updates_cache_not_db -v
```

Expected: 3 PASSED

- [ ] **Step 2: Run full feature writer test suite**

```bash
.venv/bin/pytest tests/unit/services/test_feature_writer_agent.py -v
```

Expected: all PASSED

- [ ] **Step 3: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: pre-existing failures only (none introduced by this change)

---

### Task 8: VACUUM FULL to reclaim TOAST bloat

- [ ] **Step 1: Stop feature-writer service**

```bash
sudo systemctl stop indicagent-feature-writer
```

- [ ] **Step 2: Run VACUUM FULL**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "VACUUM FULL intelligence_features;"
```

Expected: completes in 5–15 minutes. Releases ~15 GB back to OS.

- [ ] **Step 3: Verify reclaim**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT hypertable_name, pg_size_pretty(hypertable_size(format('%I.%I', hypertable_schema, hypertable_name)::regclass)) as size
FROM timescaledb_information.hypertables WHERE hypertable_name = 'intelligence_features';"
```

Expected: size < 5 GB (was 19 GB)

- [ ] **Step 4: Restart feature-writer**

```bash
sudo systemctl start indicagent-feature-writer
```

---

### Task 9: Commit

- [ ] **Step 1: Stage and commit**

```bash
git add services/feature_writer_agent.py tests/unit/services/test_feature_writer_agent.py
git commit -m "$(cat <<'EOF'
fix(feature-writer): cache-and-fold cross-asset data — eliminate TOAST-churn UPDATE path

Cross-asset market context (spread z-scores, correlation flags) is now cached
per-timeframe in FeatureWriterAgent._cross_asset_cache and folded into the
market_context JSONB at INSERT time. Removes the follow-up UPDATE on
trading_signals that caused 17 GB of TOAST bloat on the current week's chunk.

Roll boundary UPDATE retargeted from trading_signals to market_context (on-heap,
764 bytes avg) to prevent TOAST churn on that rare path too.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
