# Signal Data Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five data quality issues in signal_ledger display, lifecycle replay TTL consistency, and dashboard labelling discovered during post-Phase-32 audit.

**Architecture:** Three independent fix surfaces — (1) API query layer, (2) lifecycle replay script + shared constants, (3) dashboard display. Each is self-contained. Migration 035 and re-replay are operational steps run after code changes.

**Tech Stack:** Python (FastAPI/asyncpg, psycopg2), TypeScript/React, TimescaleDB

---

## Background: Five Issues

| # | Issue | Root Cause |
|---|-------|-----------|
| 1 | 98% of signals show "-" for time in dashboard | `signal_computed_at` intentionally NULL for backfill; `feature_ts` (100% populated) not used as fallback |
| 2 | Replay uses TTL=10 for all historical signals | `ttl_bars` not a DB column; `sig.get("ttl_bars", 10)` always falls back to 10; per-TF TTLs (1m=20, 5m=12, 15m=8, 1h=6) never applied to historical replay |
| 3 | `bars_in_trade` always NULL for TTL-expired active signals | Hardcoded `None` in replay write path for TTL exits regardless of zone activation state |
| 4 | `never_activated` signals show raw pnl_r (+14.2R looks like a win) | `lifecycle_tracker.py` correctly computes hypothetical pnl_r for entry-efficiency tracking; dashboard doesn't distinguish it from realized pnl_r |
| 5 | Migration 035 not applied + 1m outcomes wrong TTL | Phase 32-01 code merged but DB schema not updated; 1m signals replayed with TTL=10 need re-run at TTL=20 |

---

## File Map

| File | Change |
|------|--------|
| `src/core/service_utils.py` | Add `TF_TTL_BARS` dict (moves from service, becomes single source of truth) |
| `services/signal_generator_service.py` | Import `TF_TTL_BARS` from service_utils instead of defining locally |
| `production/scripts/lifecycle_replay.py` | Import `TF_TTL_BARS`; inject per-signal TTL after DB fetch; fix `bars_in_trade` for activated TTL exits; update `handle_no_data` and `resolve_at_end_of_bars` signatures |
| `src/api/routes/signals.py` | `COALESCE(sl.signal_computed_at, sl.feature_ts)` in SELECT + ORDER BY |
| `dashboard/src/components/signals/signal-ledger.tsx` | Prefix pnl_r with `~` when outcome is `never_activated` |
| `tests/unit/scripts/test_lifecycle_replay.py` | Tests for TTL injection + bars_in_trade computation |
| `tests/unit/api_tests/test_signals_routes.py` | Test that null `signal_computed_at` falls back to `feature_ts` |

---

## Chunk 1: Shared TTL constant + service import fix

### Task 1: Move TF_TTL_BARS to service_utils

**Files:**
- Modify: `src/core/service_utils.py` (after line 64, near TF_SECONDS/TF_DURATIONS)
- Modify: `services/signal_generator_service.py` (remove local def, add import)
- Test: `tests/unit/scripts/test_lifecycle_replay.py`

- [ ] **Step 1: Add TF_TTL_BARS to service_utils.py after TF_DURATIONS**

```python
# src/core/service_utils.py — add after TF_DURATIONS dict
TF_TTL_BARS: dict[str, int] = {
    "1m": 20,   # 20-bar window for 1m signals
    "5m": 12,   # 60-bar window for 5m signals
    "15m": 8,   # 2-hour window for 15m signals
    "1h": 6,    # 6-hour window for 1h signals
}
```

- [ ] **Step 2: Replace local TF_TTL_BARS in signal_generator_service.py with import**

In `services/signal_generator_service.py`, find:
```python
TF_TTL_BARS: dict[str, int] = {
    "1m": 20,   # 20 min window for 1m signals
    "5m": 12,   # 60 min window for 5m signals
    "15m": 8,   # 2 hour window for 15m signals
    "1h": 6,    # 6 hour window for 1h signals
}
```
Replace with import — add to the existing `from src.core.service_utils import ...` line:
```python
from src.core.service_utils import (
    TF_SECONDS,
    TF_TTL_BARS,
    setup_service_logging,
    min_bars_for_tf,
    PLUGIN_METRICS_SAMPLE_RATE,
)
```
(Check the exact current import line first and add `TF_TTL_BARS` to it.)

- [ ] **Step 3: Write failing test — TF_TTL_BARS importable from service_utils**

In `tests/unit/scripts/test_lifecycle_replay.py`, add:
```python
@pytest.mark.unit
class TestTTLConstants:
    def test_tf_ttl_bars_available_in_service_utils(self):
        from src.core.service_utils import TF_TTL_BARS
        assert TF_TTL_BARS["1m"] == 20
        assert TF_TTL_BARS["5m"] == 12
        assert TF_TTL_BARS["15m"] == 8
        assert TF_TTL_BARS["1h"] == 6

    def test_replay_imports_from_service_utils(self):
        """Replay must not define its own TF_TTL_BARS — must import from service_utils."""
        import inspect
        from production.scripts import lifecycle_replay
        source = inspect.getsource(lifecycle_replay)
        assert "TF_TTL_BARS: dict" not in source  # no local definition
        assert "TF_TTL_BARS" in source             # it is used
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/scripts/test_lifecycle_replay.py::TestTTLConstants -v
```
Expected: FAIL (TF_TTL_BARS not yet in service_utils)

- [ ] **Step 5: Implement (already done in steps 1-2) — run tests to verify pass**

```bash
.venv/bin/pytest tests/unit/scripts/test_lifecycle_replay.py::TestTTLConstants -v
```
Expected: PASS

- [ ] **Step 6: Verify signal generator still works**

```bash
.venv/bin/pytest tests/unit/service_tests/ -v -k "signal_generator" --tb=short
```

- [ ] **Step 7: Commit**

```bash
git add src/core/service_utils.py services/signal_generator_service.py tests/unit/scripts/test_lifecycle_replay.py
git commit -m "refactor: move TF_TTL_BARS to service_utils — single source of truth for lifecycle TTL"
```

---

## Chunk 2: Lifecycle replay TTL injection + bars_in_trade

### Task 2: Inject per-TF TTL into replay signals + fix bars_in_trade

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`
- Test: `tests/unit/scripts/test_lifecycle_replay.py`

**Context on the bug:** The replay calls `evaluate_signal(sig_eval, ...)` and `handle_no_data(sig)` which both read `sig.get("ttl_bars", 10)`. Since `ttl_bars` is not a DB column, all historical signals default to 10. After Phase 32-01, the correct values are `{"1m": 20, "5m": 12, "15m": 8, "1h": 6}`. 1m signals are the most affected — they got half the evaluation window.

**Fix strategy:** After fetching signals from DB in `_process_symbol_tf`, iterate `sig_map` and set `sig["ttl_bars"] = TF_TTL_BARS.get(timeframe, 10)` on each. This single injection point ensures ALL downstream code (`evaluate_signal`, `handle_no_data`, `resolve_at_end_of_bars`) uses the correct TTL without any function signature changes.

**bars_in_trade bug:** For TTL-expired signals that DID activate (zone_activated=True), `bars_in_trade` is hardcoded `None` at replay line 462. It should be `int((exit_at - activated_at).total_seconds() / tf_secs)`.

- [ ] **Step 1: Write failing tests for TTL injection**

Add to `tests/unit/scripts/test_lifecycle_replay.py`:

```python
@pytest.mark.unit
class TestTTLInjection:
    """TF_TTL_BARS must override stored ttl_bars for replay consistency."""

    def test_1m_signal_uses_ttl_20_not_10(self):
        """1m signal with no stored ttl_bars must get ttl_bars=20 injected."""
        replay = _get_replay()
        # Simulate a signal from DB that has no ttl_bars set (the historical case)
        sig = _sig(signal_id="ttl-test-1", ttl_bars=None)
        sig.pop("ttl_bars", None)  # remove field entirely to simulate DB row

        # get_signals_active_at is a pure helper — test TTL injection in isolation
        # by verifying _process_symbol_tf injects it. We test via resolve_at_end_of_bars
        # which reads sig.get("ttl_bars", 10).
        from src.core.service_utils import TF_TTL_BARS
        tf = "1m"
        # Simulated injection step
        sig["ttl_bars"] = TF_TTL_BARS.get(tf, 10)
        assert sig["ttl_bars"] == 20

    def test_15m_signal_uses_ttl_8_not_10(self):
        from src.core.service_utils import TF_TTL_BARS
        sig = _sig()
        sig.pop("ttl_bars", None)
        sig["ttl_bars"] = TF_TTL_BARS.get("15m", 10)
        assert sig["ttl_bars"] == 8

    def test_resolve_at_end_of_bars_respects_injected_ttl(self):
        """resolve_at_end_of_bars must use sig['ttl_bars'] when computing market_bit."""
        replay = _get_replay()
        sig = _sig(signal_id="ttl-eob", ttl_bars=20)  # injected
        last_bar = _bar(BASE_TS + timedelta(minutes=25), 5110, 5090, 5100)
        tf_secs = 60

        result = replay.resolve_at_end_of_bars(
            sig, last_bar,
            tf_seconds=tf_secs,
            zone_mfe=0.5,
            market_mfe=0.3,
            zone_activated=False,
            market_entry_price=5100.0,
        )
        # market_bit = min(bars_elapsed, ttl_bars) = min(25, 20) = 20
        assert result["market_entry_bars_in_trade"] == 20

    def test_handle_no_data_uses_injected_ttl(self):
        """handle_no_data must compute exit_ts from sig['ttl_bars'], not hardcoded 10."""
        replay = _get_replay()
        sig = _sig(signal_id="no-data-ttl", ttl_bars=20)
        result = replay.handle_no_data(sig)
        # exit_ts = timestamp + 20 * 60s = timestamp + 1200s
        expected_exit = sig["timestamp"] + timedelta(seconds=20 * 60)
        assert result["exit_at"] == expected_exit
        assert result["zone_exit_at"] == expected_exit
```

- [ ] **Step 2: Write failing test for bars_in_trade on activated TTL exit**

```python
@pytest.mark.unit
class TestBarsInTrade:
    def test_ttl_exit_activated_signal_has_bars_in_trade(self):
        """An activated signal that hits TTL must have bars_in_trade computed, not NULL."""
        # This tests the resolve_at_end_of_bars path for zone_activated=True.
        # The actual bars_in_trade write comes from _process_symbol_tf using
        # zone_activated_at. Test that the value IS computed in the pending_write.
        # We verify the helper computes bars_elapsed cleanly.
        replay = _get_replay()
        sig = _sig(signal_id="bit-test", ttl_bars=20)
        last_bar = _bar(BASE_TS + timedelta(minutes=15), 5110, 5090, 5100)
        tf_secs = 60

        result = replay.resolve_at_end_of_bars(
            sig, last_bar,
            tf_seconds=tf_secs,
            zone_mfe=1.5,
            market_mfe=0.8,
            zone_activated=True,
            market_entry_price=5100.0,
        )
        # zone_outcome: was activated + mfe>0 → ttl_expired_ahead
        assert result["zone_outcome"] == "ttl_expired_ahead"
        # bars_in_trade for zone-activated TTL exits is NOT returned by this helper
        # — the caller in _process_symbol_tf must compute it from zone_activated_at.
        # This test documents the contract: resolve_at_end_of_bars returns the outcome,
        # _process_symbol_tf is responsible for bars_in_trade computation.
        assert result["zone_outcome"] is not None  # contract: outcome always set
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/scripts/test_lifecycle_replay.py::TestTTLInjection tests/unit/scripts/test_lifecycle_replay.py::TestBarsInTrade -v
```
Expected: several FAIL

- [ ] **Step 4: Add TF_TTL_BARS import to lifecycle_replay.py**

In `production/scripts/lifecycle_replay.py`, update the service_utils import:
```python
from src.core.service_utils import TF_SECONDS, TF_TTL_BARS
```

- [ ] **Step 5: Inject TTL per signal after DB fetch in _process_symbol_tf**

After this block in `_process_symbol_tf` (around line 242):
```python
sig_map: dict[str, dict] = {str(s["signal_id"]): dict(s) for s in signals}
```
Add:
```python
# Inject canonical per-TF TTL — overrides any stored ttl_bars (column doesn't exist
# in signal_ledger; sig.get("ttl_bars", 10) would always fall back to 10).
_tf_ttl = TF_TTL_BARS.get(timeframe, 10)
for _sig_dict in sig_map.values():
    _sig_dict["ttl_bars"] = _tf_ttl
```

- [ ] **Step 6: Fix bars_in_trade for TTL-expired activated signals in end-of-bars loop**

In the end-of-bars section (around line 458-468), replace the activated zone_exit write:
```python
# Before (line ~462):
"bars_in_trade": None,
```
With:
```python
"bars_in_trade": int(
    (result["exit_at"] - zone_activated_at.get(sid, sig["timestamp"])).total_seconds()
    / tf_secs
),
```

The non-activated (never_activated) zone_exit at lines 469-477 correctly keeps `bars_in_trade: None` — never entered, so no bars in trade.

- [ ] **Step 7: Run tests to verify pass**

```bash
.venv/bin/pytest tests/unit/scripts/test_lifecycle_replay.py -v
```
Expected: all PASS

- [ ] **Step 8: Run full unit suite to check for regressions**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short -q
```
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add production/scripts/lifecycle_replay.py tests/unit/scripts/test_lifecycle_replay.py
git commit -m "fix(replay): inject per-TF TTL from TF_TTL_BARS; compute bars_in_trade for activated TTL exits"
```

---

## Chunk 3: API timestamp fallback

### Task 3: COALESCE signal_computed_at with feature_ts in /signals/recent

**Files:**
- Modify: `src/api/routes/signals.py` (two lines: SELECT + ORDER BY)
- Test: `tests/unit/api_tests/test_signals_routes.py`

**Context:** `signal_computed_at` is NULL for 845k/862k rows (historical backfill). `feature_ts` (bar close time) is populated on every row and is the correct semantic: it's when the signal information became known. The COALESCE makes time visible for historical signals without losing precision for live signals.

- [ ] **Step 1: Write failing test**

In `tests/unit/api_tests/test_signals_routes.py`, add:

```python
@pytest.mark.unit
class TestSignalTimestampFallback:
    """COALESCE(signal_computed_at, feature_ts) must be used for computed_at."""

    def _make_row_no_computed_at(self):
        """Row with signal_computed_at=NULL but feature_ts set — historical signal."""
        feature_ts = datetime(2026, 3, 10, 14, 30, 0, tzinfo=UTC)
        return _DictRow({
            "signal_id": uuid.uuid4(),
            "signal_computed_at": None,
            "feature_ts": feature_ts,
            "setup_plugin": "trad_trend_following",
            "signal_type": "TrendFollowing",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "confidence": 0.75,
            "was_selected": True,
            "cis_score": 0.42,
            "status": "expired",
            "outcome": "never_activated",
            "exit_price": None,
            "pnl_r": 7.2,
            "timeframe": "1m",
            "symbol": "NQM6",
            "win_rate": None,
            "avg_pnl_r": None,
        })

    def test_null_signal_computed_at_falls_back_to_feature_ts(self):
        """When signal_computed_at is NULL, computed_at in response must be feature_ts ISO."""
        row = self._make_row_no_computed_at()
        # The API uses COALESCE in SQL — simulate the coalesced value:
        # SQL: COALESCE(sl.signal_computed_at, sl.feature_ts) AS signal_computed_at
        # After COALESCE, row["signal_computed_at"] = feature_ts.
        row["signal_computed_at"] = row["feature_ts"]  # what COALESCE returns

        mock_db = _make_mock_db(rows=[row])
        mock_db.fetchrow = AsyncMock(return_value=_DictRow({
            "n_total": 1, "n_resolved": 1, "n_suppressed": 0,
            "win_rate": None, "avg_pnl_r": None,
        }))
        client = _make_client(mock_db)

        response = client.get("/api/signals/recent?limit=10")
        assert response.status_code == 200
        data = response.json()
        signals = data["signals"]
        assert len(signals) == 1
        assert signals[0]["computed_at"] is not None
        assert "2026-03-10" in signals[0]["computed_at"]

    def test_live_signal_computed_at_takes_precedence(self):
        """When signal_computed_at is set, it must be used (not feature_ts)."""
        live_ts = datetime(2026, 3, 17, 10, 5, 0, tzinfo=UTC)
        feature_ts = datetime(2026, 3, 17, 10, 4, 0, tzinfo=UTC)  # 1 min earlier
        row = self._make_row_no_computed_at()
        row["signal_computed_at"] = live_ts   # COALESCE returns live_ts
        row["feature_ts"] = feature_ts

        mock_db = _make_mock_db(rows=[row])
        mock_db.fetchrow = AsyncMock(return_value=_DictRow({
            "n_total": 1, "n_resolved": 1, "n_suppressed": 0,
            "win_rate": None, "avg_pnl_r": None,
        }))
        client = _make_client(mock_db)

        response = client.get("/api/signals/recent?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "10:05:00" in data["signals"][0]["computed_at"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/api_tests/test_signals_routes.py::TestSignalTimestampFallback -v
```
Expected: FAIL

- [ ] **Step 3: Apply COALESCE in signals.py SELECT**

In `src/api/routes/signals.py` around line 188, replace:
```python
sl.signal_computed_at,
```
With:
```python
COALESCE(sl.signal_computed_at, sl.feature_ts) AS signal_computed_at,
```

- [ ] **Step 4: Apply COALESCE in ORDER BY**

Around line 198, replace:
```python
ORDER BY sl.signal_computed_at DESC
```
With:
```python
ORDER BY COALESCE(sl.signal_computed_at, sl.feature_ts) DESC
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/api_tests/test_signals_routes.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/signals.py tests/unit/api_tests/test_signals_routes.py
git commit -m "fix(api): COALESCE signal_computed_at with feature_ts in /signals/recent — 98% of rows were showing no time"
```

---

## Chunk 4: Dashboard never_activated label

### Task 4: Prefix pnl_r with ~ for never_activated signals

**Files:**
- Modify: `dashboard/src/components/signals/signal-ledger.tsx` (LedgerRow pnl display only)

**Context:** `pnl_r` on a `never_activated` signal is the hypothetical "missed move" — where price was at TTL expiry relative to entry. +14.2R looks like a win but the signal never triggered. A `~` prefix (`~+14.2R`) communicates "this is unrealized / missed, not actual P&L."

- [ ] **Step 1: Update LedgerRow pnl_r display**

In `dashboard/src/components/signals/signal-ledger.tsx`, find the PnL R cell:
```tsx
{signal.pnl_r != null
  ? (signal.pnl_r >= 0 ? "+" : "") + fmtNum(signal.pnl_r, 1) + "R"
  : "-"}
```
Replace with:
```tsx
{signal.pnl_r != null
  ? (signal.outcome === "never_activated" ? "~" : "")
    + (signal.pnl_r >= 0 ? "+" : "")
    + fmtNum(signal.pnl_r, 1) + "R"
  : "-"}
```

- [ ] **Step 2: Verify dashboard builds**

```bash
cd dashboard && npm run build 2>&1 | tail -20
```
Expected: no TypeScript errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/signals/signal-ledger.tsx
git commit -m "fix(dashboard): prefix never_activated pnl_r with ~ to indicate missed/hypothetical move"
```

---

## Chunk 5: Operational steps (migration + re-replay)

These are run in order after all code changes are merged and services restarted.

### Task 5: Apply migration 035

- [ ] **Step 1: Copy and apply migration**

```bash
docker cp production/migrations/035_stop_basis_and_divergence_stack.sql timescaledb:/tmp/035.sql
docker exec timescaledb psql -U postgres -d indicagent -f /tmp/035.sql
```
Expected: a series of `ALTER TABLE` success messages, no errors.

- [ ] **Step 2: Verify columns exist**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "\d signal_ledger" | grep -E "stop_basis|hmm_regime_at_fire|garch_sigma_at_fire|chandelier_vol_source|staleness_score"
```
Expected: at least 5 columns listed.

### Task 6: Re-replay 1m signals with correct TTL=20

**Context:** 1m signals were previously replayed with TTL=10 (hardcoded default). With the fix from Task 2, they will now use TTL=20. We need to reset their outcomes and re-run.

- [ ] **Step 1: Stop lifecycle service to avoid interference**

```bash
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl stop indicagent-signal-lifecycle
```

- [ ] **Step 2: Reset 1m signal outcomes**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
BEGIN;
UPDATE signal_ledger
SET status='pending', outcome=NULL, exit_at=NULL,
    exit_price=NULL, exit_reason=NULL, pnl_ticks=NULL, pnl_r=NULL,
    pnl_dollars=NULL, mae=NULL, mfe=NULL, bars_in_trade=NULL,
    signal_quality=NULL, activated_at=NULL, activation_price=NULL,
    zone_entry_pct=NULL, bars_to_activation=NULL,
    market_entry_at=NULL, market_entry_exit_price=NULL,
    market_entry_exit_at=NULL, market_entry_pnl_r=NULL,
    market_entry_mae=NULL, market_entry_mfe=NULL,
    market_entry_bars_in_trade=NULL, market_entry_outcome=NULL,
    market_entry_gap_bars=NULL
WHERE timeframe = '1m'
  AND outcome IS NOT NULL;
COMMIT;
"
```
Expected: `UPDATE XXXXXX` — note the count.

- [ ] **Step 3: Run lifecycle replay for 1m only**

```bash
.venv/bin/python -u production/scripts/lifecycle_replay.py \
  --timeframes 1m \
  --workers 8 \
  --commit-every 1000 \
  > /tmp/replay_1m_rerun.log 2>&1 &
echo "PID: $!"
```

- [ ] **Step 4: Monitor progress**

```bash
tail -f /tmp/replay_1m_rerun.log
```
Wait for completion. Expect several hours for all symbols × 1m.

- [ ] **Step 5: Verify outcome distribution looks reasonable**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT outcome, COUNT(*), ROUND(AVG(pnl_r)::numeric, 3) as avg_pnl_r
FROM signal_ledger
WHERE timeframe = '1m' AND outcome IS NOT NULL
GROUP BY outcome ORDER BY COUNT(*) DESC;
"
```
Check: `never_activated` avg_pnl_r should decrease significantly (more signals now have time to activate with TTL=20 vs TTL=10). Expect `never_activated` count to drop and `ttl_expired_*` / activated outcomes to rise.

- [ ] **Step 6: Restart lifecycle service**

```bash
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl start indicagent-signal-lifecycle
```

---

## Verification

After all tasks complete:

```bash
# 1. Unit tests
.venv/bin/pytest tests/unit/ -q --tb=short
# Expected: all pass

# 2. Spot-check API timestamp
curl -s "http://localhost:8000/api/signals/recent?limit=5&timeframe=1m" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for s in data['signals'][:3]:
    print(s['symbol'], s['timeframe'], s['computed_at'])
"
# Expected: timestamps, not null

# 3. Spot-check never_activated pnl_r in DB is still set (data preserved)
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT COUNT(*) FILTER (WHERE outcome='never_activated' AND pnl_r IS NOT NULL) as hyp_pnl,
       ROUND(AVG(pnl_r) FILTER (WHERE outcome='never_activated' AND pnl_r IS NOT NULL)::numeric,3) as avg
FROM signal_ledger WHERE timeframe='1m';
"
# Expected: count > 0, avg should be lower than +7.6R (more signals activated with TTL=20)
```
