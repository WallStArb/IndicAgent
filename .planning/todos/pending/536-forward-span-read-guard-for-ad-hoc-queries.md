---
status: pending
priority: P2
filed: 2026-10-14
source: evidence framework section 7 amendment (forward span reads)
owner: research
---

# Mechanical guard on ad hoc reads of the forward span

The snapshot builder, target kernel and `ic_measure` refuse any `end_exclusive` past
`alpha.validation.oos_start` before fetching. A direct SQL read of `market_data_ohlcv_tradeable`
by date is not restricted, and `tests/unit/test_market_data_ohlcv_boundary.py` only covers the raw
table. An ad hoc look at the forward span is therefore unlogged and can void the one-spend claim
without anyone knowing.

## Open

1. Decide the mechanism: a read-only DB role or view that caps `timestamp` at `oos_start` for
   research sessions, versus a logged-access approach (pg audit of reads past the cutoff).
2. Decide the sink for recorded looks. S6 is the sole writer of `research_run`, so non-run looks
   probably need their own table or log; do not widen `research_run`.
3. The role or view must move with the vintage roll (`oos_start` is write-once, so the roll path
   needs a defined update).
4. Allow-list the forward runner and the confirmation test explicitly.

## Done when

An ad hoc query past the cutoff from a research session either fails or leaves a record, and a
test proves both the refusal and the allow-listed paths.
