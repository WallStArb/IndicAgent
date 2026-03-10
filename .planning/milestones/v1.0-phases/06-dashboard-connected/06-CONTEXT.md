# Phase 6: Dashboard Connected - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire every dashboard panel to live SSE data so the dashboard reflects what's actually flowing through the I1–I8 pipeline. No stubs, no empty panels, no simulated data. Success = every panel shows real values when services are running.

This phase does NOT include new features (signal history browser, charting, alerts) — those are Phase 7+.

</domain>

<decisions>
## Implementation Decisions

### Sequencing (critical)
- Fix the API "internal server error" FIRST — can't audit what we can't see
- Then diagnose what data IS flowing (inspect Redis streams + service logs) before fixing field mappings
- Only then fix UI wiring gaps — otherwise we're guessing at missing fields
- Plan order: 06-01 fix API + get SSE flowing → 06-02 stream audit + field mapping fixes → 06-03 full verification

### Price Hero redesign
- Show: **bid, ask, last** price (full spread — futures spread matters)
- **Flash animation** on tick: green flash when price goes up, red when down
- Show **H/L of current bar** alongside the live price
- **Colour the last price** green (above prev close) or red (below prev close)
- Show **+/- and % change** from BOTH:
  - Prev close (daily change — standard settlement reference)
  - Session open (intraday move)
- Show **dual range bars**:
  - Current bar H/L range (where price sits within the current bar)
  - Daily session H/L range (where price sits within today's full range)
- **Empty state**: show dashes "—" for all fields when no tick data has arrived yet (not zeros)

### Panel audit approach
- Some panels are **entirely absent from the UI** (e.g. HMM regime, liquidity zones have no component)
- Other panels **exist but fields are empty/zero** (data not arriving or field names mismatched)
- Root cause unknown — could be pipeline not computing it, or UI mapping wrong — needs diagnosis
- Wire existing panel components where possible; only create new components for features with no UI at all
- HMM regime and liquidity zone placement: Claude's discretion (inline in relevant tier panel vs dedicated section — let the audit reveal the right fit)

### Missing data known from prior sessions
- HMM regime (I6 SMC) — not visible in dashboard
- Liquidity zones — not visible
- Several I1 indicator fields (simpler indicators like stoch, williams_r, CCI) may not be populating correctly
- I3 structure fields partially populated
- I8 AI narratives: service is running but narratives are not appearing in the narrative panel

### Claude's Discretion
- Exact staleness thresholds for showing data as stale vs fresh
- Whether to show a "stale" badge on panels when data is old
- HMM and liquidity zone panel placement (inline vs own section)
- Skeleton/shimmer vs dashes for panels still waiting on first data

</decisions>

<specifics>
## Specific Ideas

- Price hero should feel like a real trading terminal — bid/ask spread is essential for futures
- Range bars give immediate visual context of where price is in its current move
- The dual % change (vs prev close AND vs session open) was explicitly requested

</specifics>

<deferred>
## Deferred Ideas

- I8 narrative panel behavior (TF-specific vs show newest) — was not discussed; Claude should default to showing the freshest narrative regardless of TF for now
- Empty/loading state design for intelligence panels — Claude's discretion (dashes pattern from price hero applies)

</deferred>

---

*Phase: 06-dashboard-connected*
*Context gathered: 2026-02-24*
