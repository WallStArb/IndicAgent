# Vendor adjustment basis study: IBKR SMART vs Tradier 1d

**Author:** Claude (Opus 5.5), 2026-10-07, at Brandon's request (plan 185-37)
**Status:** in progress (decision rule committed before any result is computed)
**Informed by:** docs/plans/2026-10-06-data-layer-integrity-design.md (sections 2, 6, 7, open
risks; spec step 5); summaries of plans 185-33 (vendor_basis_run verdict, 46 blockers), 185-38
(74 IBKR-primary exception rows, 113 names routed here, VMRK) and 185-46
(docs/research/1d-primary-swap-evidence.md: the swap to IBKR primary from D = 2026-10-07)

## Question

Where the two 1d vendors disagree for a run of sessions (an adjustment-basis disagreement: a
split, spin-off or dividend applied by one vendor and not the other, or applied differently),
which vendor's own series is continuous across the run, and does the canonical 1d series follow
it? A canonical series built from the stepping vendor carries a false return at each boundary.
The design lists the vendor treatment of IBM, BDX and LEN as unverified; this study verifies it
against the public record.

Scope: history before D (2026-10-07). The 185-46/185-47 swap decides who owns bars from D on and
does not edit any bar dated before D; this study decides bars before D only.

## Decision rule

Pre-registered (plan 185-37 objective, verbatim). Committed alone before the study script runs
against the data.

1. A run is a span of at least `threshold.bar_integrity.vendor_ratio_run_min_sessions` sessions
   where the IBKR/Tradier close ratio leaves `threshold.bar_integrity.fallback_basis_tolerance_bp`.
2. At each run boundary, the continuous vendor is the one whose own close-to-close move at the
   boundary is within the name's ordinary range (|log return| below the name's 99th percentile
   daily move over the surrounding 250 sessions) while the other vendor's move is not; a recorded
   corporate_action on the boundary date explains a step on the vendor that applies it.
3. Tradier stays primary unless Tradier is the discontinuous side with no corporate action
   explaining it and IBKR is continuous; then an exception row sets primary_source ibkr for the
   run's date range (valid_from and valid_to bound the range), evidence = the run (dates, median
   ratio, both boundary moves).
4. Spin-offs: the canonical series should not show a false return at the ex-date. If Tradier
   adjusts history for the spin-off and IBKR does not, Tradier is already right and no row is
   written; if the reverse, an exception row applies. Undecided runs get no row and are listed by
   name.

The 99th percentile and 250 sessions are study parameters recorded here, not APR keys (the study
is a one-off measurement; the daily rule's thresholds are the APR keys above).

### Operational definitions (fixed with the rule, before any result)

- Closes. Per name and date, each vendor's latest current-scale close (`current_closes` in
  `src/intelligence/bars/daily_rule.py`, the input D7's vendor_basis_run verdict reads; TRADIER
  route for Tradier, SMART TRADES for IBKR, LEGACY_IMPORT excluded). Common sessions are dates
  where both closes are positive. Runs come from `find_basis_runs` over those pairs with the two
  APR values read at run time.
- Ordinary range. For each vendor, the absolute log close-to-close moves between consecutive
  common sessions. The sample for a boundary is the 125 moves before the boundary's earlier
  session and the 125 moves after its later session (250 surrounding sessions; fewer at the ends
  of the history), excluding both boundary moves of the run. The 99th percentile is numpy's
  linear-interpolation percentile. A boundary move is in range when it is strictly below that
  percentile.
- Boundaries. Before: (last common session before the run, the run's first session). After:
  (the run's last session, first common session after it). A run touching the first or last
  common session has one boundary.
- Boundary votes. A boundary whose window (prev, cur] contains the effective_date of a recorded
  corporate_action casts no vote (explained). Otherwise it votes for the vendor that is in range
  when the other is not; both in range (a gradual drift) or both out (a common shock) cast no
  vote.
- Run verdict. ibkr or tradier when at least one boundary votes and every vote names the same
  vendor; otherwise undecided. The D7 detector's own classification (`classify_run`) is recorded
  next to it for every run, and disagreements are listed; the rule above decides rows.
- Proposed row (rule 3). For a run decided ibkr whose dates are canonical under a Tradier-primary
  policy (stored 1d source tradier on at least one run date, and no open IBKR symbol row): one
  symbol row, primary ibkr, no fallback (d2-v2 refuses an IBKR-primary row with a Tradier
  fallback), valid_from = the run's first session, valid_to = the day after the run's last session
  (the table's range is [valid_from, valid_to)). Its evidence holds the run's dates, n_sessions,
  median ratio, every boundary's dates and both vendors' log moves and percentiles, and the D7
  classification. A run decided tradier on a name whose run dates are stored from IBKR is listed;
  rule 3 writes no Tradier row.
- Spin-off cases (rule 4). For IBM, BDX and LEN, the ex-date and distribution are taken from the
  public record (SEC EDGAR filings or the company's investor relations pages), retrieved with
  WebFetch and cited with URL and retrieval date. The vendor that adjusts is the one whose
  pre-ex-date closes sit below the other's by about the distribution's value share with the ratio
  returning to 1 at the ex-date. A failed fetch or an ambiguous record leaves the case undecided:
  no row, listed by name. No date is filled from memory.
- Decomposition of the disagreement. Re-measure the spec's figure first: name-dates where both
  vendors' latest raw closes (no scale correction) differ by more than 1%. Each such name-date is
  then: inside a run (its date is inside a basis run found on current-scale closes), isolated
  (current-scale out of tolerance in a stretch shorter than the run minimum), or other (on the
  current scale it is within tolerance or not comparable, a scale artifact such as a pre-split
  answer). The same split is reported for the current-scale count.

Study parameters: percentile 99, surrounding window 250 sessions (125 each side), disagreement
threshold 1% for the decomposition.

## Results

## Known cases

## Proposed exception rows

## Undecided runs
