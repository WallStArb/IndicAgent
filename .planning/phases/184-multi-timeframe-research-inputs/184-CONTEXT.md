# Phase 184: Multi-timeframe research inputs - Context

**Gathered:** 2026-10-27
**Status:** Ready for planning
**Source:** ROADMAP phase 184 section, design revision 3, todo 435, owner reorder 2026-10-27, lane coordination with session indicagent-5b

<domain>
## Phase boundary

Predictors computed on any timeframe enter a book on one clock without a lookahead, a filled
value or a second implementation of a feature. Scope is section 7 of
`docs/plans/2026-09-25-multi-timeframe-horizon-design.md` (revision 3), items B1-B8, plus the
`feature_vectors` S0 read of todo 435 (B1). This phase is the gate for every feature, factor and
regime family.

</domain>

<decisions>
## Implementation decisions

### Scope and order (owner 2026-10-27)
- Plan now, in parallel with 191 and 186. Execution runs on the rebuilt `feature_vectors` after
  186-27 swaps it in; planning and the align node's code need no rebuilt data.
- `feature_vectors` is the basis of the research layer (owner 2026-09-26, todo 435). Features
  enter books as members of pre-registered families at 5m, 15m, 1h and 1d. No parallel feature
  implementation in research; design D5 revision 3 already says this.
- Todo 435's gap closures are in scope for B1: pin APR window values in the spec at freeze and
  refuse on mismatch; mask warmup to NaN by declared memory; refuse a feature below a pinned
  populated-symbol coverage floor; feature columns as `[t, i]` arrays content-hashed in the
  snapshot; the S3 causality probe covers them.
- HMM-derived columns (`hmm_*`, regime labels) may not enter any family until the 186-26
  rebuild produces clean walk-forward columns (todo 248).
- B8 (economic series through the same causal alignment) needs todo 482 first; todo 482 is
  pending and deferred behind its consumers. B8 is planned as its own plan that names 482 as a
  prerequisite, not silently dropped.

### Coordination with the research lane (indicagent-5b, 2026-10-27)
- Plans only edit `.planning/phases/184-*` during planning. Code touching
  `src/intelligence/research/` executes only after 5b's go.
- Construction goes through `src/intelligence/research/construction.py`
  `resolve_rule(spec, bars_per_session)`; the runner refuses non-R1 rules for now.
- Attempts record series through S6 (`research_run_series`); selection is `select_books.py`
  with its gates. Build against these, not around them.
- 187-08 adds `HorizonRule` and `book_memory()`; 187-09 adds in-fold signs and calendar refits.
  Both change `book`/`combiner`/`spec.py`. Any 184 plan that touches spec.py's canonical form
  or the combiner is sequenced after 187-09.
- New spec fields go through spec.py's `_OPTIONAL_*_FIELDS`;
  `tests/unit/research/test_spec_hashes_pinned.py` gates the seven recorded hashes.
- 187-15 (`generated_family`) adds point-in-time sector lookups from
  `instrument_classification`. If the align node builds sector or classification inputs, it
  shares that one reader.

### Project invariants that bind every plan
- `repro_frozen.py` bit-identical after each item (B7, design D7 guard 8).
- Executable targets from `panel.forward_returns` only; compute reads
  `market_data_ohlcv_tradeable`, never the raw table.
- APR for every tunable number; UTC only; no fill (missing is NaN).

### Claude's discretion
- Plan granularity, wave layout, and test design, within the constraints above.

</decisions>

<canonical_refs>
## Canonical references

Downstream agents MUST read these before planning or implementing.

- `docs/plans/2026-09-25-multi-timeframe-horizon-design.md` - the phase spec (revision 3); sections 3 (D1-D7), 4 (DAG), 7 (build items)
- `docs/plans/2026-09-26-unified-research-to-production-design.md` - adopted design; UD-25, sections 12 and 14.7
- `docs/plans/2026-09-25-alpha-research-architecture.md` - S0 to S8
- `docs/plans/2026-09-24-evidence-framework.md` - E15-E18 rules
- `.planning/todos/pending/435-wire-feature-vectors-into-research-panel-all-timeframes.md` - B1 requirements
- `.planning/todos/deferred/482-economic-series-point-in-time-by-alfred-release-records.md` - B8 prerequisite
- `docs/ideas/signal-macro-context-layer.md` - B8 shift test
- `.planning/phases/187-*/` plans 08, 09, 15 and `187-REVIEWS.md` - sequencing constraints above
- `src/intelligence/research/` - panel.py, snapshot, spec.py, construction.py, runner, S8 book test

</canonical_refs>

<deferred>
## Deferred ideas

- First feature family pre-registration (todo 435 step 4) follows this phase; it is a research
  run, not a phase 184 build item.

</deferred>

---

*Phase: 184-multi-timeframe-research-inputs*
*Context gathered: 2026-10-27*
