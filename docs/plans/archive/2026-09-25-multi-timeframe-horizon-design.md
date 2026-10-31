# Multiple timeframes and horizons in the research layer: one clock, one target, measured decay

Original: 2026-09-25 (status proposed; superseded by the unified design).
Archived 2026-10-31: pre-unified design, kept for the measurement ideas.

Ideas worth keeping:
- Horizon is a property of a signal, recorded as its IC term structure by lag, not a grid
  dimension to search; the tf x horizon grid is what produced the phase 148 failure.
- Cumulative-horizon ladders share days between rungs and carry no overlap correction. The
  descriptive object is the lag IC curve read as a whole against a joint shift-null band,
  never lag by lag (slow signals have smooth curves by construction, autocorrelation about
  0.99 for a 52-week feature).
- One clock and one target per book (daily: next-next-open residual; intraday: next-slot
  open-to-open, never crossing a session).
- Corpus evidence cited: IC over sqrt(horizon) flat to 10 days for slow price-position
  features, so 1h at 60 bars matches 1d at 10 bars.

Live successor: docs/plans/2026-09-26-unified-research-to-production-design.md.
Full text in git history at docs/plans/2026-09-25-multi-timeframe-horizon-design.md as of 708f3fe09.
