---
created: 2026-03-06T21:29:41.323Z
title: Capture and thread market price at signal computation time
area: intelligence
files:
  - services/signal_generator_service.py:610-671
  - src/api/routes/signals.py:72-75
  - dashboard/src/lib/types.ts:206-209
  - dashboard/src/components/landing/signal-card.tsx:125-134
---

## Problem

When a signal fires at e.g. 16:01:07, the market may already be at 6753 — 3 points away from the bar close of 6750 at 16:00:00. We currently capture `bar_close_price` (the bar's close price) and `signal_computed_at` (the timestamp of computation), but we do NOT capture the market price at the moment the signal was computed.

This gap matters: the difference between `bar_close_price` and `computed_price` is implicit slippage — how far the market has moved in the pipeline lag window before you even see the signal.

## Solution

1. **Backend** (`signal_generator_service.py`): At the time `signal_computed_at = datetime.now()` is taken, capture the last known price from the most recently processed bar. The generator processes bars sequentially — the bar currently being processed has a `close` price which approximates the market price at computation time. Thread this as `computed_price` into the Redis stream message alongside `signal_computed_at`.

2. **API** (`src/api/routes/signals.py`): If `computed_price` is stored in `signal_ledger` or the stream, expose it in the REST response.

3. **Types** (`dashboard/src/lib/types.ts`): Add `computed_price?: number` to `SignalData`.

4. **SSE hook** (`use-market-stream.ts`): Parse `computed_price` from stream payload.

5. **UI** (`signal-card.tsx`, `signal-panel.tsx`): Display as `bar 16:00:00 @ 6750 → calc 16:01:07 @ 6753`.

Note: If the signal generator doesn't have access to a live tick feed, `computed_price` will be the same as the next bar's open rather than a true mid-market price. This is still more useful than showing nothing.
