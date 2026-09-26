# Phase 174: Universe Expansion — Single-Name Breadth Scaling + Targeted ETF Gap-Fill - Context

**Gathered:** 2026-09-14
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase scales the corpus's effective breadth beyond the current ~8.4 (measured via the
Fundamental Law of Active Management, IR ≈ IC × √breadth, against a stable IC of ~0.03-0.06)
by expanding the single-name equity universe — the only lever with enough scale to move that
number materially — and closing confirmed ETF exposure gaps (EM-FX, momentum/quality factor
tilts, vol) alongside it. It excludes futures entirely (no continuous-contract construction
work; see todo 377). It is prescribed by the personal-scale edge determination program's
kill criterion (closed 2026-09-12, reconfirmed 2026-09-13): "this corpus, at breadth ~8 and
this TF stack, cannot carry the endgame."

</domain>

<decisions>
## Implementation Decisions

### Target universe & sourcing
- **D-01:** Do not lock a target instrument count in this phase. Research determines the
  largest feasible count under whatever the todo-371 OOM fix (D-04 below) actually supports —
  committing to a number before that's resolved risks locking in a target the infra can't run.
- **D-02:** Russell 3000 is the definitional target population — systematic, no cherry-picking,
  matches the standing "maximal coverage scaled against compute" direction
  ([[project_long_term_securities_universe_scaling]]). The actual Phase 174 backfill scope is a
  **market-cap-stratified random sample** from that population, sized against D-04's supported
  scale. Rationale: hand-picking "promising" small-caps (a curated down-cap subset) is selection
  bias by construction — it smuggles in a prior about where signal lives before any measurement
  happens. A full-population definition plus unbiased stratified sampling tests the down-cap
  idiosyncratic-signal hypothesis empirically instead of assuming it. The current single-name
  book (128 names, only 1 tagged `eq_small_cap`) is almost entirely large/mega-cap — the segment
  where `alpha_score_residual_single_security_15m`'s DEAD verdict (0/231, then 0/8 sector-bucketed)
  was actually measured, so this is a genuinely untested population, not a re-run of a dead test.
- **D-03:** Survivorship bias (todo 376) does not gate this phase's pilot. Source the pilot
  sample active-only (today's Russell 3000 constituents); research delisted-constituent
  feasibility in parallel (todo 376's action item 1 — can IBKR or another source even supply
  historical bars for delisted names). Fold delisted-inclusion in later only if that research
  comes back positive. Don't block a large, already-complex phase on an unresolved
  data-availability question that may be a dead end.

### ic_engine OOM fix (todo 371)
- **D-04:** Build **(1) a pre-flight cell-size estimate** that makes `_check_cell_size`
  actually reachable before whole-cell materialization, **and (2) disk-bounded incremental
  processing** so peak memory is bounded by chunk size (`cs_chunk_ts`), not total cell size —
  this is the structural fix, not a patch. Explicitly reject silent subsampling as a default
  degrade path (changes what's measured — exactly the hidden-bias failure mode this project's
  "silent wrong answers are worse than loud crashes" principle exists to prevent, especially
  while testing a *new* hypothesis where a silently-altered sample could manufacture or hide
  the effect under test). Subsampling may exist only as an explicit, pre-registered, visibly
  logged escape hatch if disk-streaming still isn't enough for one pathological cell — never
  automatic. Treat the already-applied "bigger box" workaround (96GB swapfile) as a stopgap
  that does not survive further scale-up, not a substitute for D-04's structural fix. This is
  a hard prerequisite for D-01/D-02's actual backfill — todo 371 already OOM-killed `ic_engine`
  once at 182 symbols (23% of a Russell-3000-scale sample), and this is a systemic pattern
  (todo 290 flags the identical failure shape in `regime_volatility`'s obs-matrix), not an
  isolated bug.

### ETF gap-fill
- **D-05:** Bundle ETF gap-fill into Phase 174 rather than a separate phase — the same
  instrument-onboarding machinery (schema, backfill, ic_engine scaling) is being built/exercised
  anyway.
- **D-06:** Add momentum and quality factor-tilt ETFs (currently zero representation). Low-vol
  dropped from scope this phase. EM-FX and vol exposure (a VIX-linked ETF/ETN proxy, given no
  real futures curve infra exists — see todo 377) stay in scope per the exposure-gap analysis
  already done this session (zero `fx_em`-tagged symbols; no vol proxy at all). Exact tickers
  are a research/planning decision, not locked here — screen for liquidity, expense ratio, and
  inception date/history depth before finalizing.

### Instrument governance schema (todo 274)
- **D-07:** Build the **backfill-eligible / compute-eligible / live-tradeable** 3-way split
  (replacing the single `instruments.is_active` boolean) now, as part of this phase, applied to
  new instruments as they're added. Rationale: this gap already survived one expansion untouched
  (111→231); deferring it through a second, much larger expansion compounds the same
  postponement. `get_active_contracts()` is read by every consumer (backfill, feature_factory,
  ic_engine, regime models) — if the Russell 3000 pilot sample is marked `is_active=true` under
  the current single-flag model, that's correct for backfill/compute but silently also makes
  those names eligible for whatever future live-trading code path reads the same flag. IBKR's
  80-simultaneous-subscription cap only binds live streaming (`reqMktData`/
  `reqHistoricalData(keepUpToDate=True)`) — confirmed dormant right now (`indicagent-ibkr-provider`
  intentionally stopped) and NOT a blocker for backfill/corpus measurement at any scale — but a
  future restart against an unsplit "active universe" of hundreds-to-thousands of names would
  silently and nondeterministically fail to honor that cap. Cheaper to classify correctly now
  than to retroactively migrate thousands of already-`is_active=true` rows later.
- **D-08:** Also fold in todo 282's process fix while touching instrument onboarding anyway:
  the "add an instrument" workflow should write a stub `instrument_metadata` row (or explicitly
  and visibly skip it), so this doesn't silently recur a third time the way it did across the
  111→231 expansion (0% metadata coverage for those 151 symbols).

### Claude's Discretion
- Exact ETF tickers for the momentum/quality/EM-FX/vol gap-fill (D-06) — research/planning
  screens for liquidity, expense ratio, and history depth.
- Exact stratification scheme for the market-cap-stratified sample (D-02) — e.g. number of
  cap-deciles, sample size per decile — sized against whatever count D-01/D-04 land on.
- Schema shape for D-07 — separate boolean columns on `instruments` vs. `instrument_tags`
  entries per dimension; default semantics for existing rows (today's `is_active=true` mapping
  to which of the three dimensions).

### Down-cap sample: timeframe scope and pre-registered correlation gate (added mid-execution, 2026-09-15)

**Provenance:** decided live during Wave 2 execution, after an empirical cross-sectional
correlation-structure check on the existing 117 single-name equities (11 of the 128 dropped
for <95% daily coverage), run against `market_regimes` (`equity`/`1d`) for regime conditioning.
Not from `/gsd:discuss-phase` — recorded here so it is tracked and auditable rather than living
only in conversation history. Full numbers: `docs/research/` entry to be written by the plan
that implements D-10 (see below).

- **D-09:** The down-cap stratified sample (D-02) is backfilled **1d bars only**, not the full
  4-timeframe stack (5m/15m/1h/1d). This applies ONLY to the new down-cap cohort — the existing
  128-name single-name book and Plan 07/10's EM-FX/vol-proxy ETF gap-fill (D-05/D-06) are
  unaffected and keep full 4-TF treatment; those additions fill genuine exposure gaps and are
  permanent corpus members, not part of the breadth hypothesis test.
  Rationale: the empirical check found the existing 117-name book's average pairwise daily-return
  correlation is 0.316 unconditional and 0.479 in the `high_bear` regime (the same regime that
  OOM'd `ic_engine`, todo 371) — via the standard diversification-shrinkage formula
  `n_eff = N / (1 + (N-1)·avg_corr)`, this caps effective breadth at ~3.1 (~2.1 in `high_bear`)
  regardless of how many more similarly-correlated names are added, since `n_eff → 1/avg_corr`
  as N grows. Backfilling the full 4-TF stack for a large down-cap sample before knowing whether
  it actually decorrelates from this baseline risks paying the full IBKR-pacing/OOM-fix
  engineering cost for a population that may deliver near-zero incremental effective breadth —
  exactly the failure mode that already produced this project's 8.4-effective-breadth-vs-230-raw-
  feature-count gap. 1d-only lets the hypothesis be tested at near-full-population scale for a
  fraction of the backfill cost (1 IBKR request/symbol instead of 4; cross-sectional cell size
  shrinks by orders of magnitude since a 1d cell has ~250 timestamps/year vs. tens of thousands
  for 5m).
- **D-10:** Before the full-scale down-cap draw (Plan 12), a **pre-registered pilot gate** runs:
  draw a small pilot sample (~30-50 symbols) via Plan 08's sampler, onboard and backfill it 1d-
  only, then re-run the same correlation-structure diagnostic against the existing book's
  baseline. The full-scale draw proceeds **only if both thresholds clear, fixed here before any
  pilot data exists (pre-registration — not adjustable after seeing the result):**
  - Pilot's unconditional average pairwise daily-return correlation ≤ **0.10** (floors the
    n_eff ceiling at ~10 vs. today's ~3.1 — a ~3x improvement in achievable independent bets,
    economically meaningful against IC~0.03-0.06).
  - Pilot's `high_bear`-conditioned average pairwise correlation ≤ **0.30** (no worse than
    today's book's *blended-regime* unconditional average — some correlation increase under
    systemic stress is structurally unavoidable for any equity portfolio, but it should not be
    dramatically worse than today's baseline).
  If either threshold fails, Plan 11 leaves `alpha.universe.target_sample_size` unset (crash-loud,
  per D-01) and records an explicit pivot recommendation instead of silently proceeding to a
  full-scale draw that the data doesn't support — this is the same "silent wrong answers are
  worse than loud crashes" principle D-04 already applies to the OOM fix, applied here to the
  hypothesis test itself.
- **Schema mechanism (Claude's Discretion, resolved by planning):** `compute_eligible` (D-07,
  Plan 02, already merged) keeps meaning exactly what it means today — all 4 timeframes complete
  — for the existing book and any future full-stack additions. The down-cap 1d-only cohort gets
  a new, purely additive `compute_eligible_1d` column (or equivalent) and a new
  `get_active_contracts(dimension='compute_1d')` value, so a 1d-only symbol can never leak into
  the default `dimension='compute'` call sites that 5m/15m/1h cross-sectional cells rely on.
  This is a structural prevention, not a downstream filtering convention every call site must
  remember to apply correctly.

### Folded Todos
- **Todo 371** (ic_engine cross-sectional cell OOM at universe scale) — folded as D-04, a hard
  prerequisite for the phase's actual backfill.
- **Todo 274** (backfill/compute/live-tradeable schema split) — folded as D-07.
- **Todo 282** (instrument_metadata not backfilled for 111→231 expansion) — folded as D-08.
- **Todo 376** (survivorship bias, active-only universe) — folded as D-03 (research in parallel,
  doesn't gate the pilot).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Prior findings this session (not yet in any doc — read the discussion log or this file)
- Effective breadth ~8.4 vs. raw feature count ~230 (`docs/research/construction-verdict-ledger.md`)
  — the core rationale for why single-name breadth is the primary lever.
- `alpha_score_residual_single_security_15m` DEAD verdict (`docs/research/construction-verdict-ledger.md`)
  — 0/231, then 0/8 sector-bucketed, measured against an almost-entirely large/mega-cap
  population (only 1/128 tagged `eq_small_cap`). Do not cite this as evidence against a
  down-cap-inclusive expansion — it's evidence against resampling more of the same segment.
- ETF exposure-gap analysis (this session, via `instrument_tags`/`tag_vocabulary`): zero
  `fx_em`-tagged symbols, thin factor-equity coverage (`eq_value`=2, `eq_growth`=2,
  `eq_small_cap`=1, zero momentum/quality/low-vol), zero vol-ETF proxy.
- Futures/FX overlap check (this session): 14 of the original 22 empty futures/FX instruments
  are redundant with existing ETFs (SPY/QQQ/IWM/DIA, TLT/IEF/SHY, GLD/SLV, FXE/FXY) — informs
  why futures stay entirely out of scope here (todo 377).

### Todos (full detail, read before planning)
- `.planning/todos/pending/371-ic-engine-cross-sectional-cell-size-guard-post-materialization-ooms-at-universe-scale.md`
- `.planning/todos/pending/274-live-tradeable-vs-corpus-universe-flag.md`
- `.planning/todos/completed/282-instrument-metadata-not-backfilled-for-universe-expansion.md`
- `.planning/todos/pending/376-survivorship-bias-active-only-universe-no-owner.md`
- `.planning/todos/pending/377-futures-backfill-needs-continuous-contract-construction-not-just-gateway.md`
  (context only — futures stay out of scope)

### Infrastructure / data model
- `src/providers/CLAUDE.md` — confirms the 80-subscription cap is live-streaming-only, not a
  backfill/registration constraint. Read before assuming any subscription-count limit applies
  to this phase's backfill work.
- `docs/foundation/instrument-tag-registry.md` — ITR spec; governs how new instruments' tags
  (`single_name_equity`, sector, exposure category) should be seeded.
- `docs/foundation/adaptive-parameter-registry.md` — any new numeric thresholds from the OOM
  fix (D-04) or stratified-sampling logic must be APR-backed per this project's standing rule.
- `docs/foundation/performance-investigation-sop.md` — required process for diagnosing/fixing
  the todo-371 OOM (measure `pg_stat_activity.wait_event`, `iostat -x 1`, `EXPLAIN ANALYZE`
  before theorizing).
- `.planning/STATE.md` Strategic Plan section — full scoping-inputs record (TF-stack economics,
  cross-TF correlation, futures/FX overlap findings, single-name-lever reasoning) gathered
  2026-09-13/14, authoritative and live.

### Root CLAUDE.md sections
- "Design mindset" (council-of-senior-engineers / Renaissance framing) — applied throughout
  this discussion; downstream planning should continue applying the same 4-question test
  (survives 10x volume? hidden bias? DAG holds? manual step eliminated?) to remaining open
  decisions (D-*'s "Claude's Discretion" items).
- Adaptive Parameter Registry — any new thresholds (stratification bucket counts, OOM-fix
  chunk sizes, cell-size ceilings) must be APR-backed, not hardcoded.
- Instrument Tag Registry — new instruments need real tag rows, not placeholder/empty ones.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `get_active_contracts()` (`src/config/settings.py`) — sole source of the active universe for
  every consumer; D-07's schema split needs sibling functions or a dimension filter param here.
- `services/ic_engine.py`'s `_compute_one_cross_sectional_cell` (~line 4300+) and
  `_check_cell_size` — the exact code path D-04 fixes. `Float32ChunkAccumulator` already exists
  and was designed to bound memory via chunking; the finalize/concat step is what currently
  defeats that intent.
- `instrument_tags`/`tag_vocabulary` (migration-based ITR schema) — already has the exposure
  taxonomy (39 tags across 6 categories) needed to classify new ETF additions correctly.
- `contract_metadata` — has roll-chain bookkeeping fields but these are futures-only and
  irrelevant to this phase (no futures in scope).

### Established Patterns
- Migrate-as-you-go (CLAUDE.md APR section) — any new numeric constant from the OOM fix or
  sampling design must go through `config_schema`/`config_state`, not a hardcoded value.
- `BaseWriter`/`BaseBatch` DAG invariants apply to any new backfill/write path touched by D-04's
  fix or D-07's schema migration.

### Integration Points
- Instrument onboarding touches: `instruments` table (D-07's new columns), `instrument_tags`
  (new tag rows for sourced names), `backfill_status` (seed rows — see CLAUDE.md's "Corpus
  Pipeline Gotcha" section on `--compute-only` silently skipping unseeded symbols),
  `instrument_metadata` (D-08).

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this is a data-sourcing and infrastructure phase. The one recurring
methodological instruction from the user across this discussion: apply the CLAUDE.md
"council of senior engineers / Renaissance" reasoning explicitly to design decisions (the 4
standing questions), not just present option menus — this shaped D-02 and D-04 directly and
should continue shaping planning's remaining open calls (the "Claude's Discretion" items above).

</specifics>

<deferred>
## Deferred Ideas

- **Nautilus Trader** (OSS execution/backtest-parity engine) — flagged as a future
  execution-layer phase candidate once a construction actually proves out; not this phase.
  See `.planning/STATE.md` Strategic Plan section.
- **Qlib, Vectorbt** — evaluated and rejected as not fitting current needs (Qlib overlaps
  already-built correctness work; Vectorbt would duplicate existing bootstrap/FDR machinery).
  Not revisited unless a specific new gap emerges.
- **Full futures backfill (todo 377)** — explicitly out of scope for this phase. If pursued
  later, target only the 9 genuinely non-redundant instruments (CL, NG, HG, ZC, ZS, ZW, VX,
  GBPUSD, USDCHF), not all 22, and only after continuous-contract construction methodology is
  separately designed.

### Reviewed Todos (not folded)
- None beyond the futures-related ones already covered by "Deferred Ideas" above — the
  cross-reference search surfaced 105 keyword matches; only 371/274/282/376 were substantively
  relevant and all four were folded (see Folded Todos above).

</deferred>

---

*Phase: 174-Universe Expansion: Single-Name Breadth Scaling + Targeted ETF Gap-Fill*
*Context gathered: 2026-09-14*
