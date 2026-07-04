# ibkr.py — Error 162 "no data" heuristic risks silent backfill truncation

**Found:** 2026-07-02, during `/simplify` pass on Phase 142A (`src/providers/ibkr.py`).
Flagged as an altitude/correctness concern, not a pure cleanup item — surfacing for review
rather than auto-fixing.

`fetch_historical_bars` (`src/providers/ibkr.py:665-788`) walks a backfill window backward in
chunks. When a chunk comes back empty and the "no data" callback fires (`hit_definitive_no_data`,
set from IBKR Error 162 via `_no_data_req_ids`), the walk breaks immediately (line 779-786),
on the reasoning that an empty chunk while walking backward means the instrument's launch date
has been passed — see the comment there and the recent perf commit that added this early exit
(this is itself a Phase 142A change, `perf(ibkr): stop walking pre-listing date range once
IBKR confirms no data`).

**The risk:** Error 162 is IBKR's generic "no data for this window" error. It fires for a
pre-IPO/pre-listing window, but also for extended trading halts, thin back-month futures
windows, and permission hiccups — none of which mean "we've passed the launch date." Because
`ibkr.py` is the shared entry point for equities, futures, and FX alike
(`src/providers/CLAUDE.md`), a single transient empty chunk for any of those reasons now
silently truncates the backward walk and stops collecting older bars for that
`(symbol, timeframe)` — the "silent wrong answer" failure mode the project's principles
explicitly flag as worse than a loud crash, and in tension with "never drop data that could
contain signal."

Note the blast radius is bounded: this only affects how far back a single backfill run walks
for one symbol/tf; it does not corrupt or misdate bars already collected. But a spurious
162 mid-run would go unnoticed — the run just ends up with fewer years of history than
requested, with no error surfaced.

**Action:** Gate the early-exit on stronger evidence than one empty chunk — e.g. require N
consecutive empty chunks before treating it as terminal, and/or cross-check against
`instruments.contract_details` listing/inception metadata (already tracked per-instrument)
before accepting "no data" as "past launch date." Scope any heuristic by asset class rather
than applying it blanket across equities/futures/FX.

**Blocked on:** nothing — safe to fix anytime, low urgency in the sense that nothing is
actively burning today (real-time `indicagent-ibkr-provider` is currently inactive; this path
is exercised by the batch historical backfill script per root CLAUDE.md). Worth fixing before
the next large multi-year backfill run, since a truncated corpus would look like a normal
successful run with no error logged.
