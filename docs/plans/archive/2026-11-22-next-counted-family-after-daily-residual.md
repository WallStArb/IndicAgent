# Next counted family after the daily residual run (archived)

Date: 2026-11-22. Archived 2026-11-25.
Outcome: the lead accepted the order H-C seasonality, family 9, family 10 and confirmed H-C under the E21 lift. All three have run and are recorded (ledger 2026-11-22f, 2026-11-23i, 2026-11-25b); the outcomes and the order that follows are in `docs/plans/2026-11-24-family-order-after-1d-corpus.md`. Todo 635 closed; family 9's kernel and close member input are todo 653; family 10 is todo 663.

Ideas kept:
- Eligibility rule: a family is counted now only if it is price-derived 1d, reads canonical 1d and `universe_membership` through the panel, and is covered by the E21 lift; feature-vector and intraday families need their own gate.
- Rank by build cost first: the cheapest counted test (a bound battery pass, no new code) goes first; a family that needs a new member input or a runner edit waits until no live run imports the modules it edits, because a battery pass binds to the import closure of the battery, family and runner statistic functions.
- Looks are series (members times horizons times panels), so a family's cost is the series it adds to the StepM universe; check that cost before a family is built.
- Parked, not retired: industry momentum (needs the point-in-time classification joined to dead names, a registration, a kernel and a battery; 3 looks) and H-A information discreteness (dropped by amendment A4 after failing the pooled battery; re-adding it edits the daily residual closure and stales the daily residual and seasonality passes).

Full text: git history, `docs/plans/2026-11-22-next-counted-family-after-daily-residual.md` as of `fc638a645`.
