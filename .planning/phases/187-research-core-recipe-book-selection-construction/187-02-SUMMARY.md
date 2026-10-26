---
phase: 187-research-core-recipe-book-selection-construction
plan: 02
status: complete
completed: 2026-10-26
commits: [bdac96116]
requirements: [R-187-03, R-187-04]
---

# 187-02 summary: attempt series and headline numbers through S6

- `TimingResult.series` keeps the per-session D_s that `timing_series` already computed
  (`compare=False`, `repr=False`; no number changes).
- `ledger.AttemptSeries` holds the tested sessions (finite D_s) as `datetime64[D]` plus
  values; `finish_run(..., series=)` writes the headline columns (t, p, gross Sharpe, mean
  session P&L, turnover, n sessions, span) and, for completed or failed runs, the
  `research_run_series` row in the same transaction as the terminal update.
- `run_family` and `run_book` pass the series for every completed attempt.
- `test_ledger_sole_writer.py` now also guards writes to `research_run_series` and
  `concept_recipe` (ledger only).

Verification: unit suite green; `tests/integration/test_research_ledger.py` 13/13 on
`indicagent_test` (migration 515 applied there; the teardown clears series rows first; the
TRUNCATE assertion now proves both the FK refusal and the CASCADE path reaching the
append-only triggers); a recorded series reproduces each member's HAC t and n exactly
(`test_recorded_series_reproduces_the_decision_statistic`); `repro_frozen` bit-identical.

Deviation: evidence JSON gained no keys (the series lives in its own table, as planned).
