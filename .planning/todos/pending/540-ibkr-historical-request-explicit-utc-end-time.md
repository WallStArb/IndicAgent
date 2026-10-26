---
status: pending
priority: P2
filed: 2026-10-26
source: fetcher run 2026-10-26 09:03Z, IBKR warning 2174
owner: 2026-10-26
---

# IBKR windowed history requests send endDateTime without a time zone

## What

`src/providers/ibkr.py` (the windowed `reqHistoricalDataAsync` call, about line 1213) sends
`endDateTime=chunk_end.strftime("%Y%m%d %H:%M:%S")` with no zone. IBKR answers every such request
with warning 2174: implied time zone support will be removed in the next API release. Today the
gateway container runs `TZ=Etc/UTC`, so the implied zone is UTC and request windows are correct.

## Why it matters

When IBKR removes implied zones, every windowed request fails (loud), and if the gateway's zone
ever changes before that, every window shifts silently by the offset (the worse failure). Fix:
send `chunk_end.strftime("%Y%m%d-%H:%M:%S")` with an explicit UTC suffix in the form IBKR
documents (`yyyymmdd-hh:mm:ss` is UTC), plus a unit test pinning the format.

## Constraint

The fetcher imports this module; edit it only between fetcher runs (no fetcher process, timer
fire not imminent), never while a run is live or resumable.
