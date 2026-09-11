# Strategic plans — features, ensemble, trade construction (2026-09-11)

**Live status:** item #1 (bucketed `alpha_score_residual` retest) resolved same day —
FAST-KILL. Item #2 (regime-gated `bars_since_high_fast`) also resolved same day — CLOSED;
the "regime-stratified IC" premise below decomposed into an artifact of averaging across
4 incompatible regime taxonomies, dominated by a 52-day event-clustered commodity cell (not
a real regime-conditional equity signal). Current verdicts tracked in
`docs/research/construction-verdict-ledger.md`, not here — this doc is a frozen
design/priority record as of 2026-09-11.

**Author:** Fable, two independent dispatches by Claude (Sonnet 5), interactive session,
2026-09-11.
**Provenance, load-bearing:** dispatch 1 asked for new proposals across features/ensemble/
construction and pre-identified specific "gaps" before asking (purely-linear ensemble,
untested single-stock pairs, unbuilt interaction layer) — a priming risk the user flagged
immediately. Dispatch 2 was a deliberate correction: presented the six graveyard constructions
as neutral facts only (exact mechanism, exact numbers, any refinement already tried), explicitly
told NOT to treat proposing a refinement as the expected answer, and asked to independently
judge each as fundamentally settled or genuinely reconsiderable. This doc merges both,
reconciling overlaps in favor of dispatch 2's more specific, fact-grounded verdicts wherever
the two touch the same construction.
**Origin:** User asked for a Fable pass improving concepts from features → ensemble → trade
thesis, then separately pushed that several "disproven" ideas might be valid given refinement
and this week's corpus improvements (migration 331 coverage expansion + recompute, todo 372's
null-shift fix) — prompting dispatch 2.

---

## Overall priority ranking (merged)

1. **Bucketed retest of `alpha_score_residual` via ITR tags** (graveyard #3, verdict B) —
   cheapest item in the whole set, pure re-aggregation of already-computed scores, directly
   resolves the single most interesting open question in this program: a real (p=0.002,
   19-year-stable) effect that is diffuse across all 231 symbols under per-symbol testing,
   never re-tested at a coarser grouping.
2. **Regime-gated `bars_since_high_fast`/`bars_since_low_fast`** (graveyard #4, verdict B) —
   the specific missing construction is named directly in the original data: stratified IC
   was positive in specific regimes (0.11 avg, 46+/187 symbols significant) but only the
   always-on, regime-agnostic version was ever built and tested (net-negative, low beta —
   ruling out a beta-contamination explanation).
3. **Same-sector single-name pairs screen** (graveyard #5, verdict B at the construction-type
   level) — the 6/6-failed test was broad ETF pairs only; single equities were never screened
   at any scale, and there's a real structural reason to expect a difference (ETF creation/
   redemption arbitrage smooths away exactly the dislocations a stat-arb strategy needs; broad
   ETFs also don't have same-sector single-name stocks' tighter fundamental linkage).
4. **Reuse `cross_sectional_spread_tracker.py`'s production infra with a different ranking
   feature** (graveyard #6, split verdict — feature dead, construction type alive) — the
   expensive part (shadow tracking + Gate 1/2 evaluation harness, proven to actually catch a
   real bug) already exists; only `ctf_momentum` specifically is dead post-lookahead-fix.
5. **Build the curated interaction layer** (new, dispatch 1) — already evidenced (22.2% of
   piloted cells cleared BH-FDR in the todo-037 pilot), already decided (Phase 150), never
   executed.
6. **Shallow tree/GBM pilot on the 7 MP axes** (new, dispatch 1) — sequenced after 1-4, since
   it should be motivated by their results, not built speculatively.
7. **Time-series (absolute) momentum, multi-asset-class** (new, dispatch 1) — plausible, but
   gated on a backfill the corpus doesn't have yet (confirmed live: the 22 registered futures/
   FX instruments have zero rows anywhere).

**Settled, not reopening:**
- **`range_pct_fast` cross-sectional long-short** (graveyard #1, verdict A) — the natural
  refinement (strip the beta, trade the residual) was already the actual test performed, and
  it lost money at every one of 9 cost combinations, including the most favorable. No untried
  lever plausibly flips this; wider universe coverage doesn't fix a beta-contamination finding.
- **`alpha_score` / Phase 148** (graveyard #2, verdict A) — the apparent Gate-1 pass was
  selection-inflated (140 cells chosen from 640 by the same FDR procedure claiming
  significance), and 100% sign co-firing across cells means there was never real breadth to
  average over — one directional bet in 640 cell-shaped costumes, with negative gross P&L.
- **`ctf_momentum` specifically** (the feature, not the construction type, within graveyard
  #6) — post-lookahead-fix point-IC collapsed from +0.0746 to +0.0047 with a CI crossing
  zero. This is the corrected measurement, not an artifact of one; no refinement of this
  feature survives it.
- Further undirected atomic feature engineering beyond the interaction layer; the full
  combinatorial interaction generator (FDR-power already ruled it out); options/vol-premium
  strategies (no evidence of options data in this corpus); more hand-picked ETF pairs (fix the
  sample-size/screening problem via the single-name screen above, don't pick six more by hand).

---

## Graveyard reconsideration (dispatch 2 — neutral framing)

### #3 `alpha_score_residual` — B: bucketed retest is genuinely untried
The failure that actually bites is condition (d): 0 of 231 symbols individually clear their
own per-symbol BY-FDR null, despite the family-level statistic clearing every other gate
(CI lower bound > 0, panel-synchronous shuffled-null p=0.0020, point estimate at the
pre-registered floor, stable across three ~6.3-year temporal thirds). **No bucketed
(coarser-than-per-symbol) version of condition (d) has ever been run** — only the strict
231-way test. A small, uniformly-diffuse residual is exactly the signature of an effect real
enough to survive a family-level test but too weak to survive per-symbol multiple-testing
correction while potentially surviving a much smaller number of pre-registered group tests.

- **Refinement:** use ITR `equity_beta`/sector tags to partition symbols into ~5-10 ex-ante
  groups, pool each group's residual-IC, re-run BY-FDR condition (d) across that much smaller
  hypothesis count. Pre-register the bucket definitions before looking at results — no
  post-hoc search over boundaries.
- **On the null-shift bug (todo 372):** reasoned to plausibly have LOW impact on this
  construction's recorded p=0.0020 specifically — the residual is cross-sectionally demeaned
  per bar *before* the null even runs, so the common/contemporaneous component
  panel-synchronicity exists to protect against has already been surgically removed by
  construction. Combined with this being a dense, near-daily single-security panel (low
  variance in active-date-count across symbols — unlike a sparse event-based panel), the bug's
  effect here should be small. Flag it, don't block on it; proceed with the bucketed retest
  without waiting for the fix's adversarial review.
- **Fast-kill:** if the bucketed retest still shows 0-1 of ~10 buckets clearing BY-FDR, or the
  null-shift fix's eventual review shows p=0.0020 was substantially inflated (corrected p >
  0.05), abandon immediately — don't chase finer bucket granularities afterward.
- **Effort:** 1-2 days, pure re-aggregation of already-computed scores.

### #4 `bars_since_high_fast`/`bars_since_low_fast` — B: the untried construction is named in the original data
Regime-stratified IC (0.11 avg, 46+/187 symbols significant) and the unconditional net-negative
result aren't contradictory — they answer different questions, and only the always-on version
was ever turned into a tradeable construction. 74.9% per-symbol sign consistency (a quarter of
symbols disagree) is exactly what you'd expect if the true relationship is regime-conditional,
not universal. Low beta/R² (0.19/0.085) rules out a beta-contamination explanation — this needs
regime-gating, not neutralization.

- **Refinement:** hold positions only during the regime label(s) where stratified IC measured
  positive, flat otherwise. Re-run the identical quintile-spread design used for the
  unconditional test, restricted to those dates, same 2007-2025 window.
- **Caveat:** the regime label used must independently clear (or already have) a null-arm
  scrambled-data control per this project's standing rule, AND must be usable without
  look-ahead (known at position-open time, not a smoothed/backward-looking label) — if either
  fails, the apparent stratified IC could itself be a look-ahead artifact the gating can't
  capture live.
- **Fast-kill:** if the regime-gated backtest is still net-negative/noise-indistinguishable, or
  a causally-valid version of the regime label collapses the stratified IC, kill it — don't try
  progressively finer regime slicing.
- **Effort:** not separately estimated by Fable; comparable to graveyard #3 (re-aggregation +
  a bounded backtest), likely 2-4 days including the look-ahead check on the regime label.

### #5 `cointegrated_pairs_residual` — B at the construction-type level only
The tested claim (6 broad sector/asset-class ETF pairs cointegrate) is dead and shouldn't be
revisited — 0/6 at Stage 1, unambiguous. But this is the *only* search done: 6 macro-basket
pairs, never any screen of the 182 individual equities at any scale. Classical pairs-trading's
actual sweet spot is same-industry single names (tight fundamental linkage), not broad ETFs
(ETF creation/redemption arbitrage smooths away exactly the dislocations a stat-arb strategy
needs; EEM/VWO and IEF/TLT failing says something about ETF-level market structure, not about
single-name relationships).

- **Refinement:** use ITR sector tags to generate candidate same-sector single-name pairs
  among the 182 equities (economically motivated, not a blind ~16,500-pair fishing
  expedition — keeps multiple-testing correction tractable). Run Stage 1 (Engle-Granger) only,
  FDR-corrected, plus a split-sample check (cointegrates in both halves, not just pooled)
  before any signal construction.
- **Fast-kill:** if the same-sector single-name screen also returns a cointegration rate
  indistinguishable from the false-positive rate under proper correction, that's a much
  stronger, structural conclusion — cointegration is genuinely rare in this corpus/era
  regardless of granularity — and the construction type should close for good, not narrow
  further (e.g., to sub-industry).
- **Effort:** 2-3 days for the screen; 1-1.5 weeks more only if a healthy surviving set emerges.

### #6 `cross_sectional_relative_value`/`ctf_momentum` — split: A (feature) / B (construction type)
As literally specified (ranked on `ctf_momentum`), this is fundamentally dead: post-lookahead-
fix point-IC collapsed from +0.0746 to +0.0047 (CI crossing zero) — the corrected measurement,
not an artifact. But the construction TYPE — basket cross-sectional long-short using the
already-built, already-proven production tracking and gate-evaluation infrastructure
(`cross_sectional_spread_tracker.py`, which caught this exact leak) — has never been tested
with any other ranking feature. That's a real, unexploited asset: the expensive part already
exists and works.

- **Refinement:** re-run the same infrastructure with a different, independently-vetted
  ranking feature. **Explicit trap flagged, not glossed over:** neither of the other two
  reconsidered graveyard features is a safe drop-in. `range_pct_fast` is real but R²=0.75
  against market beta — Gate 2's attribution-honesty check would likely flag the same
  contamination that killed its own neutralized version. `bars_since_high_fast` has low beta
  but its *unconditional* version is itself net-negative — only usable here if paired with
  graveyard #4's own regime-gating refinement first. Whatever feature gets substituted must
  independently clear standalone significance and low-beta checks before being fed into this
  infra.
- **Fast-kill:** if Gate 1 fails under the corrected join with the substituted feature too, or
  no feature in the current corpus passes the prerequisite standalone checks at all, the
  construction type has no current candidate — wait rather than force an unvetted feature in.
- **Effort:** not separately estimated; gated entirely on graveyard #3/#4 producing a
  standalone-clean feature to substitute in, so sequence this after those two land.

---

## New proposals (dispatch 1 — not graveyard reconsiderations)

### Features: build the curated interaction layer
- **Mechanism:** extend `feature_vectors` with ~20-30 theory-motivated pairwise interaction
  terms, prioritizing pairs crossing the two *confirmed independent* MP axes (momentum ×
  range/vol) over within-axis pairs (likely redundant).
- **Why plausible:** the specific, evidenced gap this project already identified (todo 037
  pilot: 22.2% of 864 cells cleared BH-FDR, broad-based across all 8 piloted features) and
  explicitly declined to build at full combinatorial scale only for FDR-power reasons
  (Phase 150). The curated ≤50-feature resolution was chosen but never executed.
- **Cheap-first falsification:** re-run the exact `partial_spearman_ic` pilot methodology on
  15-20 new candidate interactions using data that already exists. Require a similarly
  broad-based clearance (~15-25% of cells, spread across features) before committing to the
  full build.
- **Watch item:** any interaction touching an HTF join must be explicitly audited against the
  lookahead-leak bug class that killed graveyard #6.
- **Effort:** cheap check 1-2 days; full build ~1-1.5 weeks.

### Features (informational): label the 5 unidentified MP axes
- Inspect the already-computed MP eigenvector loadings; find which features load heavily on
  each unlabeled axis, propose economic interpretations. Descriptive, not falsifiable in the
  usual sense — the check is whether loadings cohere into an interpretable story. Informs
  which interactions/conditioning variables to prioritize next. Effort: 2-3 days.

### Ensemble: shallow tree/GBM pilot on the 7 MP axes
- Train a shallow, heavily regularized GBM (or decision-tree bucketing) on one representative
  feature per MP axis, predict forward returns, compare IC/Sharpe against the existing linear
  IC-proportional benchmark on identical data/period.
- **Why plausible:** the ensemble combination layer (`ensemble_trainer.py::resolve_stratum_
  weights`) is confirmed purely linear in both modes — `ic_proportional` and `mean_variance`
  are both `score = Σ w_i·feature_i`, no interaction terms, no conditioning. 7 known axes is
  small enough that a shallow tree doesn't immediately drown.
- **Why it should wait:** more expensive and overfitting-prone than the graveyard
  reconsiderations above; its natural evidence base (the interaction pilot) is feature-level,
  not ensemble-level — sequence after the interaction layer and the two bucketed/regime-gated
  retests have validated motivations, not speculatively.
- **Falsification:** purged/embargoed walk-forward CV, require OOS IC/Sharpe to beat the
  linear benchmark by a margin clearing a shuffled-null control — small numeric edges over
  small N are the classic overfitting signature.
- **Effort:** ~1 week for a disciplined first pilot.

### Construction: time-series (absolute) momentum, multi-asset-class
- Classic TSMOM (Moskowitz/Ooi/Pedersen-style): each instrument sized off its own trailing-
  return sign, vol-scaled, aggregated across asset classes rather than ranked cross-sectionally.
  Structurally distinct from everything tried — doesn't need cross-sectional dispersion or
  concentration across correlated names, sidestepping the concentration failure mode that
  recurred in graveyard #1/#3/#6.
- **Why plausible:** momentum is the one MP axis already confirmed real and independent, only
  ever tried in a cross-sectional framing.
- **Near-free check:** `ic_engine.py` already runs per-symbol (not just cross-sectional) IC
  passes — query existing momentum features' per-symbol IC broken out by asset_class before
  building anything new.
- **Blocking caveat, confirmed live this session:** the 22 registered futures/FX instruments
  (ES, NQ, CL, GC, VX, the Treasury/grain complex, 4 FX pairs) have **zero rows** in
  `market_data_ohlcv` and `feature_vectors` — never actually backfilled, despite being
  registered as instrument metadata. TSMOM's classic edge comes from diversifying trend across
  genuinely uncorrelated asset classes; without this data, the idea is data-constrained, not
  design-flawed. A full backfill (raw OHLCV + feature/IC pipeline from zero) is a prerequisite,
  not a footnote, and hasn't been scoped or estimated.
- **Effort:** free IC re-read <1 day; a real pilot 3-5 days IF instrument coverage is backfilled
  first (currently is not).

**Other standard theses considered and set aside (dispatch 1):** options/vol-premium (no
evidence this corpus ingests options data); futures curve/carry (roll infrastructure exists but
unclear if multi-tenor curve data is retained — needs a one-line data-availability check before
scoping).
