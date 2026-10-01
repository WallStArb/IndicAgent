---
status: pending
priority: P3
filed: 2026-10-01
source: interactive session, 2026-10-01 reboot recovery (AGL/APH silent pauses)
---

# Rate-limiter waits in ibkr.py are silent and read as hangs

## What

`src/providers/ibkr.py`'s per-timeframe sliding-window limiter
(`_hist_limiter_for(tf).acquire()`, ~line 1140 in the chunk walk) logs nothing while a
request waits for pacing budget (`infra.ibkr.rate_limit_max_requests`, 58 per 10 min
shared). When the budget is saturated - which is the normal state during a backfill
lane's rescan section, where per-name probes (D1 capture, head timestamps) compete
with gap fetches - the lane goes silent for minutes at a time.

On 2026-10-01 this ambiguity caused two wrong reads in one afternoon: an ~8-10 min
silent pause on AGL/1h was treated as a wedge (it self-resolved right as a kill
landed), and a later identical pause on APH/15m was only diagnosed as throttling by
watching it resolve. The 25-min lane watchdog is the designed backstop, but treating a
normal throttle as a fault invites premature kills, and each kill restarts the
per-attempt rescan walk (todo 449's known defect), so the misread compounds.

## Change

One log line when the limiter actually blocks: measure the wait inside the `acquire()`
path (or around it at the call site) and emit a single
`ibkr.hist_pacing_wait`-style warning per blocked request with the waited seconds,
instead of silence. Keep it out of any per-row loop (log the wait, not a poll). The
lane log then distinguishes "waiting on budget" (benign, expected during rescan) from
"request sent, no answer" (the HOOD class: timeout lines fire within ~60s) at a glance.

## Related

- Todo 453 (limiter concurrency measurement - this makes the limiter's behavior
  observable in production logs, which that probe work can reuse).
- Todo 449 memory entry (2026-10-01): the pauses are bursts-then-silence at the
  58/10-min ceiling; ~6 min/name real-fetch pace is exactly chunk budget.
