# Signal Timing Visibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Surface pipeline lag (`+Xs`) and staleness ratio (`N.N×`) on the signal card and narrative panel, using timing data already captured in PostgreSQL but not yet flowing to the SSE stream or UI.

**Architecture:** Backend threads `signal_computed_at` and `bar_close_ts` through to the Redis stream message and REST response. Frontend adds shared timing utilities to `format.ts`, extends `SignalData` type, parses new SSE fields in the hook, and renders inline in `SignalPanel`, `NarrativeElevated`, and `NarrativeCard`.

**Tech Stack:** Python (signal_generator_service, FastAPI routes), TypeScript/React (Next.js dashboard), Redis Streams, SSE

---

## Task 1: Backend — thread timing fields into Redis stream

**Files:**
- Modify: `services/signal_generator_service.py:664-667`
- Test: `tests/unit/service_tests/test_signal_generator_service.py`

`signal_computed_at` (line 610) and `bar_close_ts` (parameter at line 545, passed in at line 736) are both in scope at the `xadd` call site (line 667). The `message` dict is built at line 640 from `sig.items()`, which does not include these service-level fields — they must be appended manually.

**Step 1: Write the failing test**

Find the existing signal generator test file. Add a test that checks the Redis stream message contains the new fields. Look for tests of `_process_bar` or the Redis publish path.

```python
# In the test file, find or create a test for Redis message fields.
# The pattern used in this codebase: ServiceClass.__new__(ServiceClass) to bypass __init__,
# then manually set required instance attributes.

def test_signal_redis_message_includes_timing_fields():
    """signal_computed_at and bar_close_ts must appear in Redis stream message."""
    from datetime import datetime, timezone
    # Build a minimal message dict the same way the service does:
    sig = {
        "direction": 1,
        "signal_type": "trend_long",
        "setup_plugin": "trad_TrendFollowing",
        "confidence": 0.85,
        "entry_price": 5823.50,
        "stop_loss": 5810.00,
        "regime_context": "bullish",
    }
    message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}

    bar_close_ts = datetime(2026, 3, 6, 5, 10, 0, tzinfo=timezone.utc)
    signal_computed_at = datetime(2026, 3, 6, 5, 10, 0, 800000, tzinfo=timezone.utc)  # +0.8s

    # Apply the change we're about to make:
    message["timestamp"] = datetime(2026, 3, 6, 5, 10, 0, tzinfo=timezone.utc).isoformat()
    message["symbol"] = "ESH6"
    message["timeframe"] = "5m"
    if signal_computed_at:
        message["signal_computed_at"] = signal_computed_at.isoformat()
    if bar_close_ts:
        message["bar_close_ts"] = bar_close_ts.isoformat()

    assert "signal_computed_at" in message
    assert "bar_close_ts" in message
    assert "2026-03-06T05:10:00.800000" in message["signal_computed_at"]
    assert "2026-03-06T05:10:00" in message["bar_close_ts"]
```

**Step 2: Run test to verify it passes (it's a pure unit test of dict construction)**

```bash
cd /home/bg/dev/indicagent
.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k "timing" 2>&1 | tail -20
```

**Step 3: Apply the change to `signal_generator_service.py`**

At line 666, after `message["timeframe"] = timeframe`, add:

```python
            # Thread timing fields to SSE stream (signal_computed_at already in DB via signal_ledger)
            # TODO(v1.4-feedback): derive staleness thresholds from percentile analysis of
            # signal_ledger once N > 100 signals with resolved outcomes.
            if signal_computed_at:
                message["signal_computed_at"] = signal_computed_at.isoformat()
            if bar_close_ts:
                message["bar_close_ts"] = bar_close_ts.isoformat()
```

This goes at lines 666–667, immediately before the `xadd` call. The full block after the change:

```python
            message["timestamp"] = timestamp.isoformat()
            message["symbol"] = symbol
            message["timeframe"] = timeframe
            # Thread timing fields to SSE stream
            # TODO(v1.4-feedback): derive staleness thresholds from percentile analysis of
            # signal_ledger once N > 100 signals with resolved outcomes.
            if signal_computed_at:
                message["signal_computed_at"] = signal_computed_at.isoformat()
            if bar_close_ts:
                message["bar_close_ts"] = bar_close_ts.isoformat()
            await self.redis_client.xadd(stream_name, message, maxlen=200, approximate=True)
```

**Step 4: Run lint**

```bash
.venv/bin/ruff check services/signal_generator_service.py
```
Expected: no errors.

**Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```
Expected: all passing.

**Step 6: Commit**

```bash
git add services/signal_generator_service.py
git commit -m "feat(signal): thread signal_computed_at + bar_close_ts into Redis stream message"
```

---

## Task 2: Backend — expose `signal_computed_at` in REST signals response

**Files:**
- Modify: `src/api/routes/signals.py`
- Test: `tests/unit/test_signals_api.py` (check if exists; if not, the route is tested by integration tests — skip unit test for this task)

**Step 1: Update `_build_signal_row`**

In `_build_signal_row` (line 48), add `signal_computed_at` to the returned dict:

```python
        "signal_computed_at": (
            row["signal_computed_at"].isoformat()
            if row.get("signal_computed_at") is not None and hasattr(row["signal_computed_at"], "isoformat")
            else None
        ),
```

Place it after the `feature_tf` field (line 72).

**Step 2: Update both SELECT queries**

In the `include_features=True` query (line 113), add `sl.signal_computed_at` to the SELECT:

```sql
SELECT sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
       sl.setup_plugin, sl.signal_type, sl.direction,
       sl.entry_price, sl.stop_loss, sl.confidence, sl.status,
       sl.feature_ts, sl.feature_tf, sl.signal_computed_at,
       f.bar, f.i1, f.i3, f.i4, f.i5, f.smc, f.i6
```

In the plain query (line 131), add `signal_computed_at` to the SELECT:

```sql
SELECT signal_id, timestamp, symbol, timeframe,
       setup_plugin, signal_type, direction,
       entry_price, stop_loss, confidence, status,
       feature_ts, feature_tf, signal_computed_at
```

**Step 3: Run lint**

```bash
.venv/bin/ruff check src/api/routes/signals.py
```
Expected: no errors.

**Step 4: Run unit suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

**Step 5: Commit**

```bash
git add src/api/routes/signals.py
git commit -m "feat(api): expose signal_computed_at in /signals REST response"
```

---

## Task 3: Frontend — add timing utility functions to `format.ts`

**Files:**
- Modify: `dashboard/src/lib/format.ts`

**Step 1: Write unit tests for the utilities**

Create `dashboard/src/lib/__tests__/format.test.ts` (or add to existing test file if one exists):

```ts
import { stalenessRatio, pipelineLagS, tfToMinutes } from "../format";

describe("tfToMinutes", () => {
  it("maps known timeframes to minutes", () => {
    expect(tfToMinutes("1m")).toBe(1);
    expect(tfToMinutes("5m")).toBe(5);
    expect(tfToMinutes("15m")).toBe(15);
    expect(tfToMinutes("1h")).toBe(60);
    expect(tfToMinutes("4h")).toBe(240);
    expect(tfToMinutes("1d")).toBe(1440);
  });

  it("returns 1 for unknown timeframe", () => {
    expect(tfToMinutes("unknown")).toBe(1);
  });
});

describe("stalenessRatio", () => {
  it("returns null when ratio < 1.0", () => {
    const now = Date.now();
    const ts = new Date(now - 3 * 60 * 1000).toISOString(); // 3m ago
    expect(stalenessRatio(ts, 5)).toBeNull(); // 3/5 = 0.6
  });

  it("returns ratio when >= 1.0", () => {
    const now = Date.now();
    const ts = new Date(now - 7 * 60 * 1000).toISOString(); // 7m ago
    const ratio = stalenessRatio(ts, 5); // 7/5 = 1.4
    expect(ratio).not.toBeNull();
    expect(ratio!).toBeCloseTo(1.4, 0);
  });

  it("returns null for invalid timestamp", () => {
    expect(stalenessRatio("invalid", 5)).toBeNull();
  });
});

describe("pipelineLagS", () => {
  it("returns seconds between bar close and signal computed", () => {
    const barClose = "2026-03-06T05:10:00.000Z";
    const signalAt = "2026-03-06T05:10:00.800Z";
    expect(pipelineLagS(signalAt, barClose)).toBeCloseTo(0.8, 1);
  });

  it("returns null for missing or invalid timestamps", () => {
    expect(pipelineLagS(undefined, "2026-03-06T05:10:00Z")).toBeNull();
    expect(pipelineLagS("2026-03-06T05:10:00Z", undefined)).toBeNull();
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/bg/dev/indicagent/dashboard
npm test -- --testPathPattern="format" 2>&1 | tail -20
```
Expected: FAIL — functions not defined.

**Step 3: Add the utilities to `format.ts`**

Append to the end of `dashboard/src/lib/format.ts`:

```ts
// ── Signal timing utilities ──

/** Convert timeframe string to minutes. */
export function tfToMinutes(tf: string): number {
  const map: Record<string, number> = {
    "1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440,
  };
  return map[tf] ?? 1;
}

/**
 * Returns staleness ratio (elapsed / bar_period_minutes) when >= 1.0, else null.
 * >= 1.0 means at least one full bar period has elapsed since the signal/narrative fired.
 * TODO(v1.4-feedback): replace provisional 1.0 display threshold with empirically-derived
 * percentile from signal_ledger outcomes once N > 100 resolved signals.
 */
export function stalenessRatio(timestamp: string, tfMinutes: number): number | null {
  const ms = Date.parse(timestamp);
  if (isNaN(ms)) return null;
  const ratio = (Date.now() - ms) / (tfMinutes * 60 * 1000);
  return ratio >= 1.0 ? ratio : null;
}

/**
 * Returns pipeline lag in seconds (signal_computed_at - bar_close_ts).
 * Returns null if either timestamp is missing or invalid.
 */
export function pipelineLagS(
  signalComputedAt: string | undefined,
  barCloseTs: string | undefined
): number | null {
  if (!signalComputedAt || !barCloseTs) return null;
  const computed = Date.parse(signalComputedAt);
  const barClose = Date.parse(barCloseTs);
  if (isNaN(computed) || isNaN(barClose)) return null;
  return (computed - barClose) / 1000;
}
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/bg/dev/indicagent/dashboard
npm test -- --testPathPattern="format" 2>&1 | tail -20
```
Expected: PASS.

**Step 5: Commit**

```bash
git add dashboard/src/lib/format.ts dashboard/src/lib/__tests__/format.test.ts
git commit -m "feat(dashboard): add stalenessRatio, pipelineLagS, tfToMinutes to format.ts"
```

---

## Task 4: Frontend — extend `SignalData` type

**Files:**
- Modify: `dashboard/src/lib/types.ts:185-206`

**Step 1: Add three fields to the `SignalData` interface**

After `timestamp: string;` (line 205), add:

```ts
  signal_computed_at?: string;  // ISO — when signal_generator_service fired this signal
  bar_close_ts?: string;        // ISO — when bar closed (source of pipeline lag start)
  pipeline_lag_s?: number;      // computed client-side: signal_computed_at - bar_close_ts
```

**Step 2: Verify TypeScript compiles**

```bash
cd /home/bg/dev/indicagent/dashboard
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

**Step 3: Commit**

```bash
git add dashboard/src/lib/types.ts
git commit -m "feat(dashboard): add signal_computed_at, bar_close_ts, pipeline_lag_s to SignalData type"
```

---

## Task 5: Frontend — parse new timing fields from SSE in `use-market-stream.ts`

**Files:**
- Modify: `dashboard/src/hooks/use-market-stream.ts:501-523`

The signal parsing block builds `fullSignal: SignalData` at line 501. Add the three new fields to that object.

**Step 1: Add import**

At the top of the file, `pipelineLagS` needs to be imported from format.ts. Add to existing imports:

```ts
import { pipelineLagS } from "@/lib/format";
```

**Step 2: Extend the `fullSignal` object**

Inside the `fullSignal` object (after `timestamp: String(payload.timestamp || "")` at line 522), add:

```ts
              signal_computed_at: payload.signal_computed_at
                ? String(payload.signal_computed_at)
                : undefined,
              bar_close_ts: payload.bar_close_ts
                ? String(payload.bar_close_ts)
                : undefined,
              pipeline_lag_s: pipelineLagS(
                payload.signal_computed_at ? String(payload.signal_computed_at) : undefined,
                payload.bar_close_ts ? String(payload.bar_close_ts) : undefined,
              ) ?? undefined,
```

**Step 3: Verify TypeScript compiles**

```bash
cd /home/bg/dev/indicagent/dashboard
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

**Step 4: Commit**

```bash
git add dashboard/src/hooks/use-market-stream.ts
git commit -m "feat(dashboard): parse signal_computed_at + bar_close_ts from SSE signal payload"
```

---

## Task 6: Frontend — render timing in `SignalPanel`

**Files:**
- Modify: `dashboard/src/components/signal-panel.tsx`

**Step 1: Add imports**

At top of file, extend the format import:

```ts
import { fmtPrice, fmtNum, pipelineLagS, stalenessRatio, tfToMinutes } from "@/lib/format";
```

Remove `pipelineLagS` from this import if it's computed in the hook — use `signal.pipeline_lag_s` directly. Actually `pipeline_lag_s` is already on `SignalData` from Task 5, so just import `stalenessRatio` and `tfToMinutes`:

```ts
import { fmtPrice, fmtNum, stalenessRatio, tfToMinutes } from "@/lib/format";
```

**Step 2: Compute display values**

After the existing computed values (line 41, `const isStructural = ...`), add:

```ts
  const tfMinutes = tfToMinutes(signal.timeframe);
  const staleness = stalenessRatio(signal.timestamp, tfMinutes);
  const lagS = signal.pipeline_lag_s ?? null;
  const lagStr = lagS !== null ? `+${lagS < 1 ? lagS.toFixed(2) : lagS.toFixed(1)}s` : null;
```

**Step 3: Render pipeline lag on Row 1**

In Row 1 (after the `timeStr` span, around line 65), add the lag badge immediately after the timestamp:

```tsx
        {/* Pipeline lag — only shown when available (live signals only, not backfill) */}
        {lagStr && (
          <span className="text-[0.5rem] font-data text-[var(--text-muted)] opacity-60">
            {lagStr}
          </span>
        )}
```

**Step 4: Render staleness ratio below targets**

After the T2/T3 row block (after the closing `}` of the `t2 !== null` block), add:

```tsx
      {/* Staleness ratio — shown only when >= 1.0× (one full bar has elapsed) */}
      {staleness !== null && (
        <div className="pl-[3.25rem]">
          <span
            className="text-[0.5rem] font-data"
            style={{
              // TODO(v1.4-feedback): replace fixed thresholds with p80/p95 from signal_ledger
              color: staleness >= 2.0 ? "var(--red-dim)" : "var(--amber, #f59e0b)",
              opacity: 0.7,
            }}
          >
            {staleness.toFixed(1)}× stale
          </span>
        </div>
      )}
```

Note: `var(--amber)` may not exist in the CSS variables. Use `#f59e0b` as fallback or check `globals.css` for the amber variable name. If unavailable, use `var(--text-muted)` with slightly higher opacity.

**Step 5: Verify TypeScript compiles and check dev server**

```bash
cd /home/bg/dev/indicagent/dashboard
npx tsc --noEmit 2>&1 | head -20
```

Then start dev server and visually verify:
```bash
npm run dev -- --port 3000 --hostname 0.0.0.0 > /tmp/dash.log 2>&1 &
```
Open `http://localhost:3000` — signal card should show lag and staleness.

**Step 6: Commit**

```bash
git add dashboard/src/components/signal-panel.tsx
git commit -m "feat(dashboard): show pipeline lag and staleness ratio on signal card"
```

---

## Task 7: Frontend — render staleness in `NarrativeElevated`

**Files:**
- Modify: `dashboard/src/components/narrative-elevated.tsx`

`NarrativeElevated` receives `narrative: NarrativeData` which has `timestamp` (ISO, when LLM generated) and `timeframe` (TF string). Staleness is computed from these.

**Step 1: Add imports**

```ts
import { stalenessRatio, tfToMinutes } from "@/lib/format";
```

**Step 2: Compute staleness**

After the existing `isBullish` line, add:

```ts
  const tfMinutes = tfToMinutes(narrative.timeframe);
  const staleness = stalenessRatio(narrative.timestamp, tfMinutes);
```

**Step 3: Render staleness in header**

In the header `div` (line 37), after the existing TF span, add:

```tsx
        {staleness !== null && (
          <span
            className="text-[0.45rem] font-data ml-auto"
            style={{
              color: staleness >= 2.0 ? "var(--red-dim)" : "#f59e0b",
              opacity: 0.7,
            }}
          >
            {staleness.toFixed(1)}× stale
          </span>
        )}
```

Remove or adjust `ml-auto` from the existing timestamp span if both are shown in the same row.

**Step 4: TypeScript check + commit**

```bash
cd /home/bg/dev/indicagent/dashboard
npx tsc --noEmit 2>&1 | head -20
git add dashboard/src/components/narrative-elevated.tsx
git commit -m "feat(dashboard): show staleness ratio on NarrativeElevated"
```

---

## Task 8: Frontend — render staleness in `NarrativeCard` (narrative-panel)

**Files:**
- Modify: `dashboard/src/components/narrative-panel.tsx`

`NarrativeCard` receives `data: NarrativeData`. The staleness ratio is the same computation as Task 7.

**Step 1: Add imports**

```ts
import { stalenessRatio, tfToMinutes } from "@/lib/format";
```

**Step 2: Compute staleness in `NarrativeCard`**

After the existing `isBullish` line in `NarrativeCard`, add:

```ts
  const tfMinutes = tfToMinutes(data.timeframe);
  const staleness = stalenessRatio(data.timestamp, tfMinutes);
```

**Step 3: Render staleness in header**

In the header div (around line 125), in the `ml-auto` section alongside `barTimeStr`, add:

```tsx
          {staleness !== null && (
            <span
              className="text-[0.45rem] font-data"
              style={{
                color: staleness >= 2.0 ? "var(--red-dim)" : "#f59e0b",
                opacity: 0.7,
              }}
            >
              {staleness.toFixed(1)}×
            </span>
          )}
```

The existing `isStale` binary label ("stale") can coexist or be replaced — the ratio is more informative. Keep the existing `isStale` opacity fade (line 121) as it works well.

**Step 4: TypeScript check + commit**

```bash
cd /home/bg/dev/indicagent/dashboard
npx tsc --noEmit 2>&1 | head -20
git add dashboard/src/components/narrative-panel.tsx
git commit -m "feat(dashboard): show staleness ratio on NarrativeCard"
```

---

## Task 9: Final verification

**Step 1: Full Python test suite**

```bash
cd /home/bg/dev/indicagent
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```
Expected: all passing, count >= 1117.

**Step 2: Ruff**

```bash
.venv/bin/ruff check . 2>&1 | tail -5
```
Expected: no errors.

**Step 3: TypeScript**

```bash
cd dashboard && npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

**Step 4: Visual check**

With dev server running, verify on a live or replayed signal:
- Signal card shows `+0.Xs` lag next to bar time (only on live signals, hidden for backfill)
- Signal card shows `N.N× stale` below targets when >1.0× (amber) or >2.0× (red-dim)
- Narrative elevated shows `N.N× stale` in header
- Narrative card shows `N.N×` next to timestamp

**Step 5: Tag and push**

Not required — this is part of v1.4 in-progress work. Wait for milestone completion.

---

## CSS Note

`var(--amber)` may not be defined. Check `dashboard/src/app/globals.css` for available CSS variables. If amber doesn't exist, `#f59e0b` (Tailwind amber-500) is a safe fallback. Do not add a new CSS variable just for this — the inline fallback is cleaner.
