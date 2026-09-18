---
status: pending
priority: P1
filed: 2026-09-18
source: session discussion starting from a data-integrity audit (todos 382/383) that
  drifted into a cointegrated-pairs methodology question (NVDA/AMD/INTC semiconductor
  example) -- surfaced that no industry/sub-industry classification exists anywhere in
  this codebase, and that a complete design for exactly this already exists and its own
  build trigger already fired
---

# Security classification hierarchy (GICS-style): a complete, reviewed design already exists and its own stated build trigger already fired -- nobody flagged it

## What

There is currently no industry/sub-industry classification anywhere in this codebase.
Verified live: `instruments.contract_details->>'sector'` (168 single-name equities) has 24
distinct ad hoc values mixing inconsistent granularity (`technology` alongside
`materials_mining_uranium`), is **completely empty for 40/168 (24%) of single-name
equities**, and its sibling `sub_sector`/`industry` JSON keys are populated for **zero**
symbols. There is no controlled vocabulary namespace for sector/industry at all (checked
live: `controlled_vocabulary` has 7 namespaces today -- `asset_class`, 4 regime namespaces,
`tier`, `timeframe` -- none industry-related).

This gap surfaced concretely this session while discussing whether a same-sector
cointegration screen was fairly powered for semiconductor names (NVDA/AMD/AVGO/QCOM/ASML/TSM):
the finest grouping available for that test was a flat `sector='technology'` bucket of 13
names mixing real chip companies with unrelated software/internet names, because nothing
finer exists.

**The real finding: this isn't a new gap to design around -- a complete, twice-reviewed
design for exactly this already exists, unbuilt.** `docs/research/stratification-security-
classification-hierarchy.md` (Fable 5, 558 lines, `status: draft`, reviewed 2026-07-04 and
again 2026-07-06):

- Deliberately **not** built into CVR (`controlled_vocabulary`) -- an earlier proposal to add
  a `parent_code` column there was explicitly retracted after a full design pass:
  classification's load-bearing half is *membership* (which security belongs to which node,
  effective-dated, single-scheme), and CVR is designed to be a platform-wide,
  instrument-agnostic code registry -- the wrong shape for per-instrument, point-in-time
  assignment.
- Split architecture instead: **Layer 1**, a small purpose-built system (three tables, one
  seed migration, a `ClassificationService` read layer) for the authoritative GICS-style
  layer -- external reference data (S&P/MSCI assign it, single-valued, not falsifiable by
  us, only revisable by them -- "a fact to sync, not a hypothesis to calibrate"). **Layer 2**,
  a one-column extension of the *existing* `instrument_tags`/ITR system for finer custom
  classification below GICS (e.g. therapeutic-area-style sub-classification) -- because that
  IS a legitimate hypothesis (multi-valued, testable), matching ITR's existing epistemic
  model exactly.
- GICS itself is licensed (S&P/MSCI) -- not currently sourced anywhere in this project.
  **Sourcing question resolved this session, live-verified 2026-09-18**: IBKR's
  `ContractDetails.industry`/`.category`/`.subcategory` fields (`ib_async`, confirmed via a
  real `reqContractDetailsAsync` call against the running gateway) already return a genuine
  3-level hierarchy for free, on every contract lookup, with real discriminating power --
  `NVDA`/`AMD` both land on `industry='Technology', category='Semiconductors',
  subcategory='Electronic Compo-Semicon'`, while `AAPL` (same flat `sector='technology'`
  bucket today) correctly separates to `category='Computers'`, and `JNJ` lands in an
  entirely different tree (`Consumer, Non-cyclical' -> 'Pharmaceuticals' -> 'Medical-Drugs'`).
  `src/providers/ibkr.py` doesn't currently request or store any of these three fields.
  **Not official licensed GICS** -- IBKR's own proprietary scheme, no S&P/MSCI numeric
  codes, unaudited against the real taxonomy -- but free, already-authorized via the
  existing IBKR relationship, and demonstrably solves the actual problem at this project's
  scale. Recommended sourcing path for Layer 1: this, not a paid vendor feed -- a real
  GICS license would be disproportionate for a personal-scale project. SEC SIC codes remain
  the documented free fallback if IBKR coverage turns out patchy for some symbols.

**The build trigger already fired.** The doc's own staging section says, verbatim: "the
current universe is ETFs, funds have no GICS... Building ahead of real candidates would
violate this project's promotion discipline" and defines the trigger as **"the first phase
that onboards individual equities into `instruments`"**, with an explicit warning that
Layer 1 "must not lag the universe expansion" because **point-in-time correctness cannot be
retrofitted** -- months of single-snapshot classification data already sitting in the
corpus by the time anyone notices is the doc's own named silent-bias failure mode. This
project onboarded 168 single-name equities weeks ago (migrations 287, 296, and the whole
personal-scale program's single-name track). That trigger condition has been true for a
while and nobody flagged it until this session.

## What to do

This is a prioritization decision, not a design task -- the design is already done and
reviewed twice. Needs an explicit owner call:

1. **Build now** (Layer 1 at minimum): sourcing path is resolved -- IBKR's
   `industry`/`category`/`subcategory` contract-detail fields, verified live this session
   (see above). **Coverage confirmed 2026-09-18 across all 168 single-name equities:
   100% (168/168), zero errors, zero empty-classification results.** 46 distinct `category`
   values with real discriminating power (Biotechnology 12, Transportation 9, Internet 8,
   Semiconductors 7, Retail 7, Mining 6, Banks 6, Pharmaceuticals 6, plus 38 more) --
   NVDA/AMD's shared `Semiconductors` category sits alongside `Computers`, `Software`,
   `Internet` etc. as genuinely separate buckets, not lumped into one flat `technology`
   tag. No coverage-gap risk remains; this is a straightforward backfill against data
   already fully available. Execute the small schema (three tables + seed migration +
   `ClassificationService`) per the existing design.
2. **Formally defer with a real re-trigger check**, explicitly acknowledging the
   point-in-time-correctness cost of waiting (every day since the equity onboarding is
   another day of un-captured classification history that can't be reconstructed later)
   is an accepted cost, not an overlooked one.
3. Either way, this doc's own `status: draft` and "unscheduled, no ROADMAP phase" framing
   needs updating once a decision is made -- don't leave it looking like it's still waiting
   on a trigger that already fired.

## References

- `docs/research/stratification-security-classification-hierarchy.md` -- the full design,
  read this first
- `docs/research/concept-controlled-vocabulary.md` -- "Out of Scope: Hierarchical Instrument
  Classification" section, the CVR-retraction rationale
- `docs/research/construction-verdict-ledger.md` -- `cointegrated_pairs_residual` DEAD
  verdict (0/471 same-sector single-equity pairs), the session thread that surfaced this
- `src/providers/ibkr.py` -- confirmed does not currently request/store IBKR's
  `industry`/`category`/`subcategory` contract-detail fields
