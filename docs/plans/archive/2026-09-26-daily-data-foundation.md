# Daily data foundation (phase 185 proposal)

Original: 2026-09-26 (accepted 2026-09-26; landed as phase 185).
Archived 2026-10-31: landed design, kept for the owner decisions and rationale.

Decisions worth keeping: derived 1d bars write into market_data_ohlcv with the derivation as
their only writer; scrubbing is flag-never-delete with rules validated on known answers;
revisions propagate through content-digest keys and every snapshot records the rule version;
daily attempts wait on a minimum data bar; Yahoo dividend history stays as reference data
(todo 428) because total-return research depends on it and it is not a price source; D8
(forward survivorship capture: delisting records, holdings snapshots) descoped, few
delistings ahead and the past cannot be fixed from IBKR; stage V (second source) stayed
closed at the time.

Full text in git history at docs/plans/2026-09-26-daily-data-foundation.md as of 708f3fe09.
