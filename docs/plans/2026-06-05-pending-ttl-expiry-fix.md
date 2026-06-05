# Pending Signal TTL Expiry Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two structural bugs that cause pending signals to accumulate indefinitely, remediate ~937k stuck signals in the DB, and correct the misleading "Active" dashboard label.

**Architecture:** (1) `evaluate_signal()` currently hard-returns for PENDING signals before the TTL block — change to conditional fall-through. (2) `_bootstrap_active_signals()` bypasses the ingest fast-path TTL check — apply the same routing logic at bootstrap. (3) Direct SQL update to close all non-backfill signals whose `expires_at` has passed. (4) Dashboard label rename.

**Tech Stack:** Python 3.11, pytest, asyncpg (TimescaleDB), TypeScript/React dashboard

**Spec:** `docs/plans/2026-06-05-pending-ttl-expiry-fix-design.md`

---

## Files

| Action | Path | What changes |
|--------|------|-------------|
| Modify | `src/intelligence/trading/lifecycle_tracker.py:238-249` | Pending branch: conditional return instead of hard return |
| Modify | `tests/unit/intelligence/test_lifecycle_tracker.py` | Add `test_pending_expires_at_ttl_no_zone_overlap` test; update stale comment |
| Modify | `services/signal_tracker.py:1149-1156` | Bootstrap loop: apply ingest fast-path TTL check before `_add_to_active_index` |
| Modify | `tests/unit/services/test_signal_tracker_backfill_fast_path.py` | Add bootstrap TTL fast-path tests |
| Run once | SQL (psql command) | Write exits for 937k stuck non-backfill signals |
| Modify | `dashboard/src/hooks/use-observability-stream.ts:265` | `"Active"` → `"Tracked"` |
| Modify | `dashboard/src/components/observability-panel.tsx:152` | `"Active Signals"` → `"Tracked Signals"` |

---

## Task 1 — Fix `evaluate_signal` pending TTL fall-through

**Files:**
- Modify: `src/intelligence/trading/lifecycle_tracker.py:238-249`
- Modify: `tests/unit/intelligence/test_lifecycle_tracker.py`

- [ ] **Step 1.1: Write the failing test**

Add this test to `tests/unit/intelligence/test_lifecycle_tracker.py` inside the existing `TestTTLExpiry` class, after `test_active_expires_after_ttl`:

```python
@pytest.mark.unit
def test_pending_expires_at_ttl_no_zone_overlap(self):
    """Pending signal: bar_time >= expires_at, bar does NOT overlap zone -> ttl_expired/never_activated.

    This is the safety-valve case: signal generated, zone never touched, TTL elapsed.
    After the fix, evaluate_signal falls through from the pending branch to the TTL
    block when _check_zone_activation returns None.
    """
    sig = _pending_signal(direction=1, entry=5100.0, stop=5085.0)
    sig["expires_at"] = _T0 + timedelta(minutes=10)
    bar_time = _T0 + timedelta(minutes=11)

    # Bar range 5040-5050 does NOT overlap zone (entry_zone defaults to entry ±0 → 5100).
    # No entry_zone_low/entry_zone_high in _pending_signal() → zone_low = zone_high = entry = 5100.
    # 5050 < 5100 → no overlap.
    t = evaluate_signal(
        sig,
        high=5050.0,
        low=5040.0,
        close=5045.0,
        bar_time=bar_time,
        signal_timestamp=_T0,
    )

    assert t is not None, "Expected TTL-expired Transition, got None"
    assert t.exit_reason == "ttl_expired"
    assert t.new_status == "expired"
    assert t.outcome == "never_activated"
```

- [ ] **Step 1.2: Run test to confirm it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_lifecycle_tracker.py::TestTTLExpiry::test_pending_expires_at_ttl_no_zone_overlap -v
```

Expected: `FAILED` — `assert t is not None` fails because the current code returns `None` for pending signals regardless of TTL.

- [ ] **Step 1.3: Apply the fix**

In `src/intelligence/trading/lifecycle_tracker.py`, replace lines 237-249:

```python
# BEFORE
    # --- Pending: zone activation check (first) ---
    if status == SignalStatus.PENDING:
        return _check_zone_activation(
            sid,
            direction,
            zone_low,
            zone_high,
            high,
            low,
            bars,
            signal_timestamp=signal_timestamp,
            bar_time=bar_time,
        )
```

```python
# AFTER
    # --- Pending: zone activation check (first) ---
    if status == SignalStatus.PENDING:
        activation = _check_zone_activation(
            sid,
            direction,
            zone_low,
            zone_high,
            high,
            low,
            bars,
            signal_timestamp=signal_timestamp,
            bar_time=bar_time,
        )
        if activation is not None:
            return activation
        # No activation — fall through to TTL check below
```

- [ ] **Step 1.4: Run test to confirm it passes**

```bash
.venv/bin/pytest tests/unit/intelligence/test_lifecycle_tracker.py::TestTTLExpiry::test_pending_expires_at_ttl_no_zone_overlap -v
```

Expected: `PASSED`

- [ ] **Step 1.5: Update the stale comment in the D02 test**

In `tests/unit/services/test_lifecycle_tracker_d02.py`, find the class docstring for `TestD02ViolationCounter` (around line 42) and update this sentence:

```python
# BEFORE (in class docstring)
    """D-02 labeling violation counter fires in the TTL block, which is only
    reached for ACTIVE signals after the TTL reorder. PENDING signals short-circuit
    to zone activation check and never reach the TTL block.
```

```python
# AFTER
    """D-02 labeling violation counter fires in the TTL block, which is
    reached for ACTIVE signals and for PENDING signals that miss zone activation.
    PENDING signals fall through to TTL after _check_zone_activation returns None.
```

- [ ] **Step 1.6: Run the full lifecycle test suite to confirm no regressions**

```bash
.venv/bin/pytest tests/unit/intelligence/test_lifecycle_tracker.py tests/unit/services/test_lifecycle_tracker_d02.py -v
```

Expected: all green.

- [ ] **Step 1.7: Commit**

```bash
git add src/intelligence/trading/lifecycle_tracker.py \
        tests/unit/intelligence/test_lifecycle_tracker.py \
        tests/unit/services/test_lifecycle_tracker_d02.py
git commit -m "fix(lifecycle): pending signals fall through to TTL check when zone not hit"
```

---

## Task 2 — Fix bootstrap TTL fast-path

**Files:**
- Modify: `services/signal_tracker.py:1149-1156`
- Modify: `tests/unit/services/test_signal_tracker_backfill_fast_path.py`

- [ ] **Step 2.1: Write two failing tests**

Add a new test class at the end of `tests/unit/services/test_signal_tracker_backfill_fast_path.py`:

```python
class TestBootstrapTTLFastPath:
    """Bootstrap loads signals from DB; signals with elapsed TTL must be fast-pathed,
    not loaded into the active index."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_expired_non_backfill_publishes_ttl_and_skips_index(self):
        """Non-backfill signal with elapsed TTL at bootstrap: TTL transition published,
        signal NOT added to active index."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        canonical = _make_backfill_canonical("bootstrap-expired-live-001", signal_ts, ttl_bars=10)
        canonical["is_backfill"] = False  # live signal

        with patch.object(
            agent, "_publish_ttl_expired_transition", new_callable=AsyncMock, return_value=True
        ) as mock_ttl, patch.object(
            agent, "_add_to_active_index"
        ) as mock_add:
            await agent._bootstrap_apply_signal(canonical)

            mock_ttl.assert_called_once()
            mock_add.assert_not_called()
        assert "bootstrap-expired-live-001" in agent._signal_ids

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_expired_backfill_dedup_only_skips_index(self):
        """Backfill signal with elapsed TTL at bootstrap: dedup-only, no EXIT published,
        NOT added to active index."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=20)
        canonical = _make_backfill_canonical("bootstrap-expired-backfill-001", signal_ts, ttl_bars=10)
        # is_backfill = True (default from _make_backfill_canonical)

        with patch.object(
            agent, "_publish_ttl_expired_transition", new_callable=AsyncMock
        ) as mock_ttl, patch.object(
            agent, "_add_to_active_index"
        ) as mock_add:
            await agent._bootstrap_apply_signal(canonical)

            mock_ttl.assert_not_called()
            mock_add.assert_not_called()
        assert "bootstrap-expired-backfill-001" in agent._signal_ids

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_valid_signal_enters_active_index(self):
        """Signal with future expires_at enters active index normally."""
        agent = _make_agent()

        signal_ts = datetime.now(UTC) - timedelta(minutes=2)
        canonical = _make_backfill_canonical("bootstrap-valid-001", signal_ts, ttl_bars=10)
        canonical["is_backfill"] = False
        canonical["expires_at"] = datetime.now(UTC) + timedelta(minutes=8)

        with patch.object(
            agent, "_publish_ttl_expired_transition", new_callable=AsyncMock
        ) as mock_ttl, patch.object(
            agent, "_add_to_active_index"
        ) as mock_add:
            await agent._bootstrap_apply_signal(canonical)

            mock_ttl.assert_not_called()
            mock_add.assert_called_once_with(canonical)
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/services/test_signal_tracker_backfill_fast_path.py::TestBootstrapTTLFastPath -v
```

Expected: `ERROR` — `_bootstrap_apply_signal` does not exist yet.

- [ ] **Step 2.3: Extract `_bootstrap_apply_signal` helper and apply fix**

In `services/signal_tracker.py`, first extract the bootstrap loop body into a new method. Insert after `_add_to_active_index` (around line 535):

```python
async def _bootstrap_apply_signal(self, canonical: dict) -> None:
    """Apply one signal loaded from DB during bootstrap.

    Mirrors _ingest_signal fast-path logic: signals with elapsed TTL are
    fast-pathed (publish TTL exit or dedup-only for backfill) rather than
    loaded into the active index. This prevents reloading stale piles on restart.
    """
    now_utc = datetime.now(UTC)
    expires_at = canonical.get("expires_at")

    if expires_at is not None and now_utc >= expires_at:
        if canonical.get("is_backfill") is True:
            self._signal_ids.add(canonical["signal_id"])
            SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL.add(
                1, {"symbol": canonical["symbol"]}
            )
            self.logger.debug(
                "bootstrap_ttl_elapsed_backfill_skip",
                signal_id=canonical["signal_id"],
            )
        else:
            tf_secs = TF_SECONDS.get(canonical["timeframe"], 60)
            bars_elapsed = int(
                (now_utc - canonical["timestamp"]).total_seconds() / tf_secs
            )
            published = await self._publish_ttl_expired_transition(canonical, bars_elapsed)
            if published:
                self._signal_ids.add(canonical["signal_id"])
        return

    self._add_to_active_index(canonical)
    self._signal_ids.add(canonical["signal_id"])
```

Then in `_bootstrap_active_signals`, replace lines 1149-1156:

```python
# BEFORE
                        canonical = self._load_signal(raw)
                        if canonical is None:
                            continue

                        # Bootstrap path: route directly to _add_to_active_index — do NOT run
                        # backfill fast-path or dedup check (signal_ids not set yet).
                        self._add_to_active_index(canonical)
                        self._signal_ids.add(canonical["signal_id"])
```

```python
# AFTER
                        canonical = self._load_signal(raw)
                        if canonical is None:
                            continue

                        await self._bootstrap_apply_signal(canonical)
```

- [ ] **Step 2.4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/services/test_signal_tracker_backfill_fast_path.py -v
```

Expected: all green including the three new `TestBootstrapTTLFastPath` tests.

- [ ] **Step 2.5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 2.6: Commit**

```bash
git add services/signal_tracker.py \
        tests/unit/services/test_signal_tracker_backfill_fast_path.py
git commit -m "fix(signal_tracker): apply TTL fast-path at bootstrap to prevent stale signal reload"
```

---

## Task 3 — Data remediation: close 937k stuck signals

**Files:** Direct psql (no code change)

- [ ] **Step 3.1: Count affected rows before running**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT COUNT(*) as will_update
FROM signal_outcomes so
JOIN signal_ledger sl ON so.signal_id = sl.signal_id
WHERE sl.is_backfill = false
  AND sl.expires_at < NOW()
  AND so.exit_at IS NULL
  AND so.status IN ('pending', 'active', 'regime_suppressed');"
```

Expected: approximately 700,000 rows.

- [ ] **Step 3.2: Run the remediation update**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
UPDATE signal_outcomes so
SET
    status      = 'expired',
    exit_at     = sl.expires_at,
    exit_reason = 'ttl_expired',
    outcome     = 'never_activated'
FROM signal_ledger sl
WHERE so.signal_id = sl.signal_id
  AND sl.is_backfill = false
  AND sl.expires_at < NOW()
  AND so.exit_at IS NULL
  AND so.status IN ('pending', 'active', 'regime_suppressed');"
```

Expected output: `UPDATE <N>` where N ≈ 700,000.

- [ ] **Step 3.3: Verify counts are now near zero**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT status, COUNT(*)
FROM signal_ledger_full
WHERE is_backfill = false
  AND expires_at < NOW()
  AND exit_at IS NULL
GROUP BY status;"
```

Expected: empty result or only rows with `expires_at` that passed in the last few seconds (race window). The 937k should be gone.

- [ ] **Step 3.4: Verify signal counts by status look sane**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT status, COUNT(*)
FROM signal_ledger_full
WHERE is_backfill = false
GROUP BY status
ORDER BY COUNT(*) DESC
LIMIT 8;"
```

Expected: `expired` will be the largest bucket (now includes the remediated signals). `pending` count drops dramatically to only truly-open signals.

- [ ] **Step 3.5: Commit remediation note**

```bash
git commit --allow-empty -m "fix(data): close 937k stuck pending signals with ttl_expired/never_activated via direct SQL"
```

---

## Task 4 — Fix dashboard labels

**Files:**
- Modify: `dashboard/src/hooks/use-observability-stream.ts:265`
- Modify: `dashboard/src/components/observability-panel.tsx:152`

- [ ] **Step 4.1: Update the pipeline node label in `use-observability-stream.ts`**

In `dashboard/src/hooks/use-observability-stream.ts` at line 265, change:

```typescript
// BEFORE
            { label: "Active",  value: activeSignals !== null ? activeSignals.toLocaleString() : "—" },
```

```typescript
// AFTER
            { label: "Tracked", value: activeSignals !== null ? activeSignals.toLocaleString() : "—" },
```

- [ ] **Step 4.2: Update the KPI card label in `observability-panel.tsx`**

In `dashboard/src/components/observability-panel.tsx` at line 152, change:

```typescript
// BEFORE
            label="Active Signals"
```

```typescript
// AFTER
            label="Tracked Signals"
```

- [ ] **Step 4.3: Build the dashboard to confirm no TypeScript errors**

```bash
cd dashboard && npm run build 2>&1 | tail -10
```

Expected: build completes with no errors.

- [ ] **Step 4.4: Commit**

```bash
git add dashboard/src/hooks/use-observability-stream.ts \
        dashboard/src/components/observability-panel.tsx
git commit -m "fix(dashboard): rename 'Active Signals' to 'Tracked Signals' — gauge counts all in-memory signals"
```

---

## Task 5 — Restart signal_tracker and verify

- [ ] **Step 5.1: Restart the service**

```bash
sudo systemctl restart indicagent-signal-tracker
```

- [ ] **Step 5.2: Watch bootstrap log to confirm fast-path firing**

```bash
tail -30 logs/signal_tracker.log
```

Expected: `bootstrap_complete` log with `signals=<N>` where N is much smaller than before (should reflect only genuinely open signals, not the 482k stale pile). Also look for `bootstrap_ttl_elapsed_backfill_skip` or `backfill_ttl_fast_path` entries confirming the fast-path is running.

- [ ] **Step 5.3: Check Prometheus gauge after 30 seconds**

```bash
curl -s 'http://localhost:9090/api/v1/query?query=signal_tracker_compute_active_signals' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['result'][0]['value'][1])"
```

Expected: a number close to the count of signals with `expires_at > NOW()` and `exit_at IS NULL` — should be well under 10,000 rather than 488,000.

- [ ] **Step 5.4: Final full unit run**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.
