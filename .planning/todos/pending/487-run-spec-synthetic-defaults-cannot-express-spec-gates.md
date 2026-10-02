---
status: pending
priority: P3
filed: 2026-10-02
source: interactive session, phase 183 UAT recovery 2026-10-01/02
---

# run_spec synthetic defaults cannot express the spec's gates

## What

`scripts/research/run_spec.py`'s synthetic-mode defaults are unusable against real specs, and
both failures are quiet or cryptic:

1. `--synthetic-names` defaults to 30, but the plant's participation ratio comes from the
   family's measured value (family 1: 60, on the real 233-name panel).
   `synthetic.loading_scale_for_pr` raises
   `ValueError: participation ratio 60.0 not attainable with m=30, k=10` (attainability needs
   k <= p <= m), so the default invocation crashes in the generator.
2. `--synthetic-sessions` defaults to 400, and `_synthetic_panel` hardcodes
   `start="2006-07-03"`, so the panel ends 2008-01-11. `static_sizes.measure` only measures
   sessions from `scoring.trading_start` (family 1: 2010-01-04), leaving zero sessions, and the
   E17 precondition refuses every member as "not measurable: a cell has too little
   cross-section". The reason is not printed anywhere: the RESULT lines carry only
   `status: refused`, and the evidence dict with the message is not shown by the CLI.

Both surfaced during the 183 UAT (2026-10-01) and cost hours of diagnosis, including a session
loss mid-investigation. Working invocation recorded in
`.planning/phases/183-research-layer-runner-ledger-combiner-book-test/183-UAT.md` test 10:
`--synthetic-names 233 --synthetic-sessions 1500` (ends 2012-03-30, 585 scored sessions).

## Change

Loud validation instead of silent defaults: before building the panel, check that (a) names
can express the plant's participation ratio and (b) the panel span covers `trading_start`
with a sane minimum of scored sessions; on violation exit 2 with a message that names both
constraints and the computed minimal `--synthetic-names` / `--synthetic-sessions` values.
Additionally, print the refusal reason for member-level refusals (the `_static_refusal`
message currently lands only in the evidence dict). No default behavior change beyond the
error path: deriving spans automatically would silently change panel content.

## Related

- `src/intelligence/research/static_sizes.py` (`measure`'s `trading_start` filter, the
  coverage-floor "not measurable" refusal).
- `src/intelligence/research/synthetic.py` (`loading_scale_for_pr` attainability).
- 183-UAT.md test 10 note (both root causes reproduced offline 2026-10-02).
