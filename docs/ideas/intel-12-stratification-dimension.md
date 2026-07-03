# StratificationDimension — A Unified Conditioning Layer

**Version:** 1.0
**Status:** draft — extracted from 2026-07-02 top-down architecture review for independent iteration
**Priority:** high (blocks AnalogEngine's retrieval correctness; names a real glossary gap)
**Milestone:** proposed v3.15 "Conditioning & Identity Foundation" — not scheduled, Phases TBD
**Last Updated:** 2026-07-02
**Tags:** regime, stratification, conditioning, governance, hmm, concept-registry, analog-engine
**Source:** `.planning/research/2026-07-02-v3-topdown-architecture.md` §1.3, §2.4, §3 (D5, D8), §7 (Q4) — Author: Fable 5
**Informed by:** Fable 5 - consolidation audit corrections, recommendations in § Open Questions, and design revisions marked *(Fable's revision)* inline (2026-07-02)

---

## The Core Idea

Today the codebase has two unrelated services that both do the same conceptual job — produce
a causal per-bar label that sharpens IC estimates by conditioning on regime:

| System | Service | Table | Grain |
|---|---|---|---|
| Per-symbol HMM | `regime_writer.py` | `feature_vectors.regime` | per (symbol, TF) |
| Cross-sectional | `equity_regime_model.py` / Phase 151 | `market_regimes` | market-wide per TF |

Plus an informal backlog of more candidate dimensions (`docs/plans/archive/2026-07-01-regime-stratification-alternatives.md`,
eight candidates: six percentile-rank/deterministic, plus HMM variants and a microstructure
regime) and an orphaned parallel idea doc proposing four more regime engines plus non-HMM
stamped vectors (`docs/ideas/archive/multi-engine-regime-architecture.md`, E1-E4). None of these share a
contract. Each is bespoke: its own writer, its own promotion story (or none), its own
correctness argument.

**The proposal:** name the concept — a *stratification dimension* — unify it behind one
provider contract, and make "which conditioning is true" an empirical, mechanical question
answered by the same measurement machinery that already governs features. This is not a new
capability; it is recognizing that `regime_writer.py`, `equity_regime_model.py`, the
alternatives backlog, and the multi-engine idea doc are four drafts of one interface that was
never written down.

## Why This Matters Now (not just architectural tidiness)

AnalogEngine's retrieval (`retrieve()`) **hard-filters** on regime labels — a bad label
silently pollutes every neighbor set it returns, with no downstream signal that anything went
wrong. The IC engine, by contrast, only *stratifies* by regime labels — a bad label there
dilutes an IC estimate but doesn't corrupt a whole retrieval. AnalogEngine is therefore more
sensitive to conditioning-layer bugs than anything that currently consumes these labels. Worse:
embeddings are versioned and expensive to rebuild (`embedding_version` bump = full re-embed).
Building AnalogEngine's substrate on top of known-suspect strata bakes the bias into stored
vectors before anyone notices. **This is the concrete reason the unification has to happen
before AnalogEngine, not sometime after** — it's the stated rationale for sequencing v3.15
between v3.1 and v3.2 (roadmap D5).

It does **not** block or change Phase 142B / 142B.1 — those only consume existing regime
labels as an opaque stratification key and don't care about the provider contract underneath.

## The Contract

```python
class StratificationDimension(Protocol):
    name: str                      # 'hmm_price_vol', 'cross_sectional_equity', 'volatility_pct', 'dispersion'
    grain: Literal['per_symbol', 'cross_sectional']
    labels: list[str]              # from Vocabulary
    causality_basis: Literal['deterministic', 'expanding_window', 'fitted']
    def compute(...) -> labels     # causal by construction; provider proves it
    def score(...) -> float | None # continuous underlying value, where one exists
```

*(Fable's revision)* Two fields beyond the original sketch, both forced by the doc's own
machinery:
- `causality_basis` declares *how* the provider avoids look-ahead: `deterministic` (wall-clock,
  e.g. session position), `expanding_window` (percentile ranks), or `fitted` (parameters
  learned from data). `fitted` providers must additionally declare their fit window: a causal
  decode on top of a full-history fit is exactly the parameter look-ahead ambiguity todo 026 is
  auditing in the incumbent HMM. The contract makes that risk visible per provider instead of
  rediscovered per audit.
- `score()` exists because the orthogonality gate below runs Pearson correlation on continuous
  values, which a labels-only contract cannot serve. Providers expose their underlying
  continuous score (percentile rank, HMM state posterior) where one exists.

Promotion state (shadow/live, per `regime_group`; see Governance) lives in `concept_registry`,
not on the provider.

**Canonical vocabulary (glossary additions needed):**
- *Conditioning Layer* — the layer as a whole
- *stratification dimension* — one axis (one provider, one set of labels)
- *stratum* — a cell within a dimension
- `regime` stays reserved for the HMM price/vol dimension specifically — it does not become a
  generic term for "any stratification label."

**Label identity invariant** *(Fable's revision, promoting the bottomup audit's §2.3 finding
to a contract rule)*: a label is only meaningful as a `(dimension, label)` pair. No consumer
or table stores a bare label without its dimension qualifier; the current
`feature_ic_scores.regime` column, which mixes 9 cross-sectional with 5 per-symbol labels
unqualified, is the standing counterexample this rule exists to kill.

### Many Producers, Many Consumers

The point of a shared contract instead of two bespoke services is that both sides multiply
independently — adding a new dimension should never require touching a consumer's code, and
adding a new consumer should never require special-casing a specific dimension.

**Producers (providers implementing the contract):**
- `hmm_price_vol` — today's per-symbol HMM (`regime_writer.py`)
- `cross_sectional_equity` — today's `equity_regime_model.py` / Phase 151 dispatcher
- `volatility_pct`, `dispersion` — percentile-rank candidates
- E1-E4 from the multi-engine HMM doc (volatility structure, volume character, factor style,
  flow/positioning)
- `ood_distance` — AnalogEngine's nearest-neighbor distance

**Consumers (processes reading dimension labels, unchanged in what they do with them):**
- **ic_engine** — stratifies IC by whichever dimension(s) win the substitution test; same job
  it does today with `regime`, just routed through one interface instead of hand-wired branches
  per dimension
- **EnsembleTrainer** — keys weights on whichever stratification produced the tightest CI per
  predictor (the "axis selection is learned" mechanism above)
- **AnalogEngine's `retrieve()`** — hard-filters neighbor search by dimension labels; the
  consumer most sensitive to a bad dimension (see "Why This Matters Now")
- **MeasurementEngine** (proposed L4 unification of ic_engine + EnsembleICEngine) — both a
  consumer and the judge: it runs the substitution test that promotes/demotes dimensions

Today, HMM and cross-sectional regime are each hand-wired into `ic_engine.py`'s routing logic
as one-off integrations (`_build_symbol_regime_class`, the `mr_dict` cross-sectional join,
etc.). Under this contract, every consumer reads through the same interface, and a new
dimension — say, factor style — starts competing for adoption via the substitution test without
any consumer's code changing.

**Hosting (unchanged storage split, just named):**
- Per-symbol dimensions → columns on `feature_vectors`, written by `regime_writer.py`
  (conceptually renamed to "the per-symbol dimension host" — the HMM becomes provider #1 among
  peers, not the only per-symbol axis forever).
- Cross-sectional dimensions → rows in `market_regimes`, written by Phase 151's `regime_group`
  dispatcher, which is *already* shaped like a pluggable provider — keep it as-is, just formalize
  it as a `StratificationDimension` implementation.

## Governance: Each Dimension Earns Its Cells

Every dimension is a `concept_registry` row (`domain='regime_model'`). Nothing enters as truth;
everything enters as a hypothesis that must clear three gates, in order — cheapest filter first:

**0. Structural redundancy pre-filter (free — no query needed).** If a candidate is already
substantially represented inside a dimension already in production, reject without running
anything. Precedent: Hurst/mean-reversion and autocorrelation-sign were rejected this way
against the existing HMM — both are direct proxies for `momentum`/`vol_of_vol`, two of its 5
observation dimensions already. Adding them as a *separate* stratification axis on top of a
label already conditioned on them double-counts the same dynamic under a new name. Not an
empirical question; don't spend a query on it.

**1. Orthogonality study.** Correlation (Pearson on the continuous percentile/z-score, or
normalized mutual information across discretized labels) between the candidate and every
dimension already in production, computed once against the existing corpus before anything is
built. Gate: below `alpha.regime_stratification.max_correlation`
(new APR key, no default asserted until the first study runs — needs empirical judgment, not a
guessed constant). A candidate that fails this is either dropped or merged into a composite
label with the dimension it duplicates (e.g. one combined liquidity-shock label instead of
separate vol + volume axes) rather than added as a second near-identical stratification cost.
`volatility_pct` and `dispersion` are exempt from this gate: already measurably distinct in
kind from the incumbents, not just presumed distinct.

**2. Substitution test (Partial IC).** Prove the candidate sharpens measurement, using this
concrete protocol (not just "measure a delta and eyeball it"):

```
IC_partial = Corr(X_bar, Y_forward | S_candidate)
```

- Train/compute the candidate on 3-5 symbols first — never commit to a full corpus run on an
  unvalidated candidate.
- Stamp the candidate's label onto existing `feature_vectors` for those symbols.
- Query IC stratified by `(existing_dimension_state, candidate_state)`; compare IC Sharpe with
  and without the candidate axis.
- **Pass criterion:** IC Sharpe increases by more than 10% in at least one joint cell, with
  N > 20,000 bars in that cell (below this, a cell is data-starved, not a genuine
  gate outcome).
- Only on pass: full corpus re-run with the candidate's column/row baked in.

A zero-schema-change first probe (recommended for `volatility_pct`): run ic_engine stratified
by the candidate instead of the incumbent label and compare IC separation directly, before
committing to any `feature_ic_scores` schema change.

**Promotion scope is per `regime_group`, not global** *(Fable's revision, generalizing the TLT
finding into a rule)*. A dimension passes or fails the gates per asset class. Todo 026's Step 1
is the existence proof: the same dimension (the incumbent HMM) carries real separation for
equities and none for rates. `concept_registry` records status per (dimension, regime_group);
a dimension live for `equity` and shadow for `rates` is a normal state, not an exception. This
is also what Open Question 1's fallback (b) reduces to once stated as a rule rather than a
remediation.

**Incumbents are re-measured, not grandfathered** *(Fable's revision)*. The substitution test
that admits a candidate re-runs for every live dimension at each measurement epoch (each full
ic_engine re-run); a live dimension whose separation decays below the admission bar is demoted
to shadow for that regime_group, still written and measured but no longer conditioned on. The
incumbent HMM sat unmeasured until todo 026 ran the query; this rule makes that class of
discovery routine instead of an audit finding.

**Axis selection is learned, not chosen by an engineer.** The Measurement Engine records which
dimension (or validated combination) produced the tightest CI for each predictor; the
EnsembleTrainer keys weights on whichever stratification won for that predictor. Guard: a
dimension combination that starves any cell below `alpha.ic.min_obs_per_regime` is inadmissible
regardless of how good its separation looks — N-budget beats elegance. Combinatorial cost is
multiplicative, not additive, and gets expensive fast:

| Dimensions active | Joint cells (naive) | After impossible-combo pruning |
|---|---|---|
| 1 (current HMM, K=5) | 5 | 5 |
| + 1 more K=5 dimension | 25 | ~18 |
| + 2 more K=5 dimensions | 125 | ~60 |
| + 3 more K=5 dimensions | ~625 | ~150 |
| + 4 more K=5 dimensions | ~3,125 | ~300 |

Sparsity is handled by the existing IC gate (sparse cells emit no score rather than a noisy
one), and Numba JIT (already shipped, Phase 141 P2) is a hard prerequisite for this to be
computationally tractable at all — each additional dimension was infeasible to even compute
before that landed.

**Storage:** settled as extending existing tables with nullable columns per dimension
(`feature_ic_scores`/`predictor_ic_scores` gains one column per active dimension, NULL where a
predictor wasn't stratified by it) rather than a separate table per dimension — single table,
extensible, avoids a join fan-out at measurement time.

The three gates replace both backlogs' informal orderings: the alternatives doc's manually
maintained implementation order falls out as an emergent property of the pipeline, and the
multi-engine doc's real contribution, its E0-E4 *domain taxonomy* (price/vol, volatility
structure, volume character, factor style, flow/positioning), becomes a candidate list that
flows through the same gate as everything else.

**Default mechanism: percentile-rank first.** The multi-engine doc's sequencing verdict
(deterministic percentile-rank first; a full HMM engine only once percentile-rank proves
insufficient) becomes every candidate's default mechanism, not just E1/E2's. Three reasons:

- This codebase's own stated principle: simple, robust features beat complex ones.
- The one HMM already in production is under active audit for exactly the failure modes HMMs
  are prone to (non-causal full-history fit, degenerate-state risk; see todo 026 below).
  Building more HMM engines before that audit resolves multiplies an unresolved risk instead
  of fixing it once.
- Percentile-rank's one real capability gap vs. an HMM, regime persistence/stickiness (a
  transition matrix encodes "once in state X, tend to stay there"), is patchable:
  `regime_writer.py` already applies `min_hold_bars` smoothing as a post-processing step
  separate from the HMM fit itself, and the same smoothing applies to a percentile-rank series.

## Candidate Dimensions (from existing backlogs, now unified under one gate)

**Live (incumbent providers):**

| Name | Mechanism | Grain |
|---|---|---|
| `hmm_price_vol` | Per-symbol HMM, provider #1 (`regime_writer.py`) | per_symbol |
| `cross_sectional_equity` | 9-label VIX-proxy × breadth model (`equity_regime_model.py`) | cross_sectional |

**Percentile-rank candidates (mechanism-first choice per the sequencing verdict below):**

| Name | What it measures | Why it might earn its cells | APR / notes |
|---|---|---|---|
| `volatility_pct` | Expanding percentile rank of realized vol | Vol directly controls sizing, spread costs, mean-reversion speed; factor relationships are documented to flip across vol regimes; causal by construction, no distributional assumptions | `alpha.volatility_regime.low_pct`/`high_pct`; per-symbol version of the existing cross-sectional VIX axis; exempt from the orthogonality gate (with `dispersion`) |
| `dispersion` | Cross-sectional return std across the 58-symbol universe | Invisible to per-symbol HMM by construction — a feature's IC in a low-dispersion (macro-driven) market differs fundamentally from a high-dispersion (stock-picker's) market | Exempt from the orthogonality pre-check — already measurably distinct in kind (per-symbol level vs. cross-sectional spread), not just presumed distinct |
| `factor_regime` | Which factor (momentum/value/quality/low-vol) is driving cross-sectional returns, via MTUM/QUAL/VTV/USMV rolling return spreads | Explicit economic mechanism rather than a learned latent state; a momentum feature's IC flips sign between momentum-rewarding and mean-reversion regimes in a way HMM state boundaries (learned from price dynamics, not factor rotation) don't capture | No new data pipeline — all 4 proxy ETFs already active; percentile-rank bucketing of the spread, not unsupervised |
| `volume_pct` | Expanding percentile rank of `rel_volume` | Plausibly captures participation/liquidity distinct from volatility's dispersion-of-outcomes | **Gated on orthogonality study** — volume and volatility spikes are well-documented to co-move; must clear the correlation check before admission, not approved alongside `volatility_pct` by default |
| `skew_tail` | Rolling return skewness percentile | High-vol-positive-skew (lottery-like) vs. high-vol-negative-skew (crash risk) are different prediction problems at the same vol percentile | **Gated on orthogonality study** — skew clusters with vol in the tails, exactly where this dimension would matter most |
| `session_position` | Deterministic wall-clock session bucket (open/midday/close), via existing `normalize_session_type()` | Zero look-ahead risk by construction, near-certainly orthogonal to price/volume-derived dimensions, zero incremental compute | Deprioritized 2026-07-01 — cheap and safe is not the same as valuable; no case made for session effects mattering at this system's swing (not HFT) cadence. Only intraday TFs benefit |

**HMM-engine candidates** (from the multi-engine doc's E0-E4 taxonomy — demoted from "parallel
architecture" to "candidates in the queue," each gated on its percentile-rank equivalent
proving insufficient first, per the sequencing verdict):

| Name | Domain | Percentile-rank equivalent |
|---|---|---|
| E1 — volatility structure | Vol geometry/acceleration (Garman-Klass, Yang-Zhang, vol velocity, intraday noise ratio) | `volatility_pct` |
| E2 — volume character | Participation intent (detrended vol z-score, volume-to-spread ratio, volume-price coupling) | `volume_pct` |
| E3 — factor style | Same territory as `factor_regime` above, originally specced as HMM-fit rather than percentile-rank | `factor_regime` |
| E4 — flow/positioning | Institutional structural intent via 13F/Form PF/COT | none — blocked on data acquisition (13F/Form PF/COT not yet ingested); the 45-60 day filing lag itself is a valid slow-moving prior, not the blocker |

**Incumbent-variant and deferred candidates** (from the alternatives doc's HMM Variants and
Microstructure sections; all gated, none in any build sequence):

| Name | Gate / dependency |
|---|---|
| IOHMM variant (exogenous-input transitions) | todo 026 deficiency proof; structural Phase 151 dependency: its exogenous inputs are direct reads of `regime_group` signal outputs (`breadth_vol`, `curve_credit`), so building it pre-151 re-derives inputs 151 obsoletes |
| Hamilton (1989) variant | todo 026 deficiency proof; no Phase 151 dependency (pure per-symbol simplification) |
| Factor-augmented HMM variant | todo 026 deficiency proof; structural Phase 151 dependency: reuses `_resolve_group_symbols()` peer resolution. Option (c) in Open Question 1 |
| Microstructure regime (5m/15m only) | Blocked on order flow / bid-ask infrastructure (V2 microstructure feature vector), not currently in place |

**Non-HMM stamped scalars** (additional candidates from the multi-engine doc, not yet in any
build sequence — a real category, not represented above):

| Name | What it measures | Notes |
|---|---|---|
| Corporate event vector | Insider Form 4 buy/sell clustering, active buyback windows, litigation/FDA NLP friction | Public via SEC EDGAR; insider-buy clustering combined with an accumulation-type state is one of the multi-engine doc's named high-conviction joint cells |
| Sentiment / GEX vector | Options gamma exposure (market-maker positioning), call/put ratio, retail NLP sentiment | Negative GEX amplifies vol, positive GEX suppresses it — directly modulates how a vol-structure dimension should be read; vendor data (CBOE) |
| Supply chain / macro vector | Cross-asset commodity spreads (copper/gold), Baltic Dry Index, satellite inventory proxies | Commodity spreads available now via existing IBKR futures feeds; satellite data is vendor-gated |

**Cross-cutting:** `ood_distance` - AnalogEngine's nearest-neighbor distance
("unprecedentedness"), bucketed low/mid/high. A candidate dimension rather than a hand-coded
conviction override; whether it conditions IC, caps conviction, or both is Open Question 3.
One DAG constraint *(Fable's revision)*: `ood_distance` is produced by AnalogEngine's retrieval
and may condition anything downstream, but must never feed back into `retrieve()`'s own filter
set; retrieval conditioning on its own output is a cycle.

**Explicitly rejected (gate 0 structural redundancy, no query run):** Hurst /
trend-vs-mean-reversion and autocorrelation-sign - both direct proxies of the incumbent HMM's
`momentum`/`vol_of_vol` observation dimensions. Either would double-count the primary
stratifying axis itself, a more insidious redundancy than the volume/skew case because it is
collinear with the incumbent, not a peer candidate.

## Current Empirical State — todo 026's Decision Gate

The build trigger for any HMM-related work under this contract is todo 026's regime-IC
separation decision gate (`.planning/todos/pending/026-hmm-regime-audit-optimization.md`). It
has **partially run**, and the result is exactly why "one unified per-symbol HMM" is the wrong
mental model to carry into this doc:

- **Step 1 (run 2026-07-02):** pooled SPY+TLT query showed a misleadingly small IC-separation
  gap (0.0084) — but that pooled number is an artifact. Broken out per symbol: **SPY**
  trending_up IC 0.0256 vs trending_down 0.0020 (gap +0.024, ambiguous zone) — **TLT**
  trending_up 0.0064 vs trending_down 0.0097 (gap **−0.003**, inverted sign — TLT's HMM labels
  carry no separation at all).
- **Finding:** HMM label quality is **asset-class-dependent**, not a single verdict. This is
  direct empirical evidence that the per-symbol HMM is a hypothesis to be tested per asset
  class under this contract's substitution test, not an architecture fixture that gets carried
  forward unconditionally.
- **Step 2 (partial):** for SPY only, cross-sectional labels showed 1.4x wider IC separation
  than per-symbol HMM on the same SPY/5m/1h slice. TLT's own clean comparison is blocked on
  Phase 151 shipping a valid `rates` cross-sectional group to compare against (comparing TLT to
  the *equity* cross-sectional label would repeat the same pooling error Step 1 just found).
- **Step 3/4 (rolling refit pilot, full rollout):** not started; gated on Steps 1-2 resolving
  and on P4a/P4b's own decision gate (4 conditions, all must hold — see todo 026).

This is real, in-progress evidence, not a hypothetical — the doc's contract exists partly
*because* this data already shows the incumbent isn't uniformly good.

## Sequencing

Proposed as part of a new milestone, **v3.15 "Conditioning & Identity Foundation,"** between
v3.1 and v3.2 (AnalogEngine), bundling:

- Phase 151 (regime_group dispatcher: commodity sub-group merge, exclude-unrouted-with-logging
  policy)
- todo 026 P1-P3 (JIT speedup, look-ahead bug fixes, restart/degeneracy/churn hardening —
  all ungated, no dependency on the decision gate above)
- todo 041 (tag category audit — exposure vs sensitivity)
- The `volatility_pct` substitution test
- All batched into **one** ic_engine re-run, per roadmap decision D5

Per decision D6, this absorbs Phase 148 (calibrator) and dissolves the standalone v3.3
milestone — "a milestone whose scope is TBD and whose contents all belong earlier is a
numbering artifact, not a plan."

**Explicit non-dependency:** this does not block or change Phase 142B.1's E1→E2→E3→E4 ensemble
weighting order — 142B.1 only consumes existing regime labels as an opaque key.

## What This Deletes / Replaces

- Two unrelated regime services with no shared contract → one contract, two hosts (the storage
  split stays; only the interface unifies).
- `docs/plans/archive/2026-07-01-regime-stratification-alternatives.md`'s informal implementation-order
  backlog → a mechanical gate (substitution test + orthogonality study) that produces the same
  ordering as an emergent property, not a manually maintained priority list. This doc's
  candidate list, concrete substitution-test protocol, orthogonality mechanics, and explicit
  rejections are now folded in above — the source doc is detail/provenance only from here.
- `docs/ideas/archive/multi-engine-regime-architecture.md` as a parallel architecture proposal → its
  E0-E4 taxonomy, the Additional Intelligence Vectors category, and the Partial IC validation
  protocol survive as candidates and procedure, folded in above; the "coordinated joint-engine
  system with a 5×5 product matrix" architecture does not — dimensions compete independently
  under one gate, and useful combinations are discovered empirically, not pre-wired.
- The regime-alternatives doc's flagged glossary gap ("stratification dimension" has no
  canonical name today) → closed by this doc's vocabulary section.

**Note on the two source docs:** both remain in `docs/plans/` and `docs/ideas/` as detail
layers (full vol/volume HMM formulas, per-engine data-source tables, phased build sequences)
that would over-bloat this doc if reproduced in full — but their decision-relevant content
(candidates, gates, procedure, rejections) now lives here and this doc is the one to iterate on.

## Open Questions (unresolved, need a decision before or during v3.15 planning)

Recommendations below are proposals for ratification, not decisions.

1. **Fallback if HMM separation is weak for a non-equity asset class** (the TLT finding above).
   Options on the table: (a) per-asset-class HMM observation vectors, (b) demote HMM to shadow
   for those classes and stratify them on cross-sectional + volatility_pct only, (c)
   factor-augmented HMM variant. The substitution-test machinery this doc proposes is exactly
   the mechanism to decide — but the *fallback default* (leaning toward (b)) should be
   pre-committed before the query runs again on more symbols, in SHADOW-REVIEW spirit — don't
   let the result pick its own remediation after the fact.

   **Recommendation: adopt (b) as the pre-committed fallback default, in writing, before the
   widened Step 1 query runs.** TLT's labels already failed the separation test (inverted sign,
   no signal); keeping them as a live conditioning axis for a weak class fails the
   earn-promotion-through-proof bar. Demotion to shadow keeps the labels written and measurable
   (never drop data that could contain signal) and leaves re-promotion open through the same
   substitution test as any candidate. (a) builds a fix before the root cause is isolated and
   multiplies HMM surface while the one production HMM is still under audit; the
   percentile-rank-first verdict rejects that shape of move for the same reason. (c) is the
   strongest challenger hypothesis (todo 026's root-cause note points at it for TLT
   specifically) but is gated on both Phase 151 and deficiency proof, so it belongs in the
   candidate queue as (b)'s eventual challenger, not as the default. Note that if the
   per-`regime_group` promotion rule in § Governance is ratified, (b) stops being a special
   fallback and becomes that rule's normal output for any weak class.

2. **TLT's own clean cross-sectional comparison is blocked on Phase 151.** Needs a valid
   `rates` cross-sectional group before this can be resolved even provisionally.

   **Recommendation: accept the block; pre-register the comparison now.** Do not run an interim
   comparison against the equity label - that repeats the exact contamination error Step 2
   already flagged. Write the query (same per-symbol shape as SPY's Step 2(c), TLT vs the
   `rates` group label) and todo 026's existing pass/fail thresholds into the todo now, so it
   runs mechanically the day Phase 151 ships. Committing criteria before the data exists costs
   nothing and is the whole point of the pre-commit discipline.

3. **Does OOD/unprecedentedness condition IC, cap conviction, or both?** Conditioning (make it
   a stratum, subject to the same substitution test as everything else) and conviction-capping
   (an emission-time multiplier that dampens size/confidence out-of-distribution) are different
   mechanisms with different failure modes. The AnalogEngine substrate docs propose the latter;
   this doc's framing (§ Candidate Dimensions) proposes the former. Needs a small design note
   before v3.2; plausibly both, gated separately.

   **Recommendation: both, staged, gated independently - stratum first as a shadow recording,
   conviction cap second as the only emission-side change.** Record `ood_distance` as a stamped
   dimension from day one and let it flow through the same substitution test as any candidate;
   high-OOD cells are data-starved by definition (unprecedented means few analogs), so the
   existing min-obs gate handles sparsity and the stratum costs nothing while N accumulates.
   The conviction cap touches live sizing, so it carries the higher burden: APR-governed
   multiplier, validated capped-vs-uncapped in shadow before it modifies anything. The two
   mechanisms answer different questions (does IC differ out-of-distribution vs. should point
   estimates be trusted there) and should pass or fail on their own evidence; neither is
   promoted by default.

4. **Generalizing todo 026's decision gate past SPY+TLT.** The doc's own methodology fix says:
   never pool across symbols with potentially different regime dynamics again; widen to at
   least one member of every `regime_group` before drawing a general verdict. That widening
   hasn't happened yet and is itself gated on Phase 151.

   **Recommendation: pre-commit the widened protocol now, before Phase 151 makes it runnable.**
   One representative symbol per `regime_group` (the most liquid member, maximizing N),
   per-symbol queries only, and the numeric bands todo 026 already uses (gap < 0.01 deficient;
   0.01 to 0.05 ambiguous). The output is a per-asset-class verdict table, never a global
   verdict - Step 1 already proved the global shape is wrong. Widen a group past its
   representative only if that representative lands in the ambiguous band; a clear pass or
   clear fail on the representative settles the group for now. Ratifying the symbol list and
   bands before the query runs is the same discipline Phase 142B's SHADOW-REVIEW used.

## References

- `.planning/research/2026-07-02-v3-topdown-architecture.md` — source proposal (§1.3, §2.4,
  §3 D5/D8, §7 Q4)
- `.planning/research/2026-07-02-v3-bottomup-audit.md` §2.3 — companion finding: today's
  `feature_ic_scores.regime` column mixes 9 cross-sectional and 5 per-symbol labels with no
  `regime_scope` qualifier; this doc's dimension-level identity (each dimension a named,
  registered concept) is the structural fix for that ambiguity.
- `.planning/todos/pending/026-hmm-regime-audit-optimization.md` — the live decision gate and
  empirical findings this doc's "current state" section is built on
- `docs/plans/archive/2026-07-01-regime-stratification-alternatives.md` — informal candidate backlog,
  superseded in spirit (not deleted) by this doc's governance model
- `docs/ideas/archive/multi-engine-regime-architecture.md` — E0-E4 domain taxonomy, demoted from
  parallel system to candidate list
- `docs/ideas/concept-governance-registries.md` — the three-registry taxonomy (`domain='regime_model'`
  is a Concept Registry domain, same governance shape as `feature` and `ensemble_strategy`)
- ROADMAP.md v3.15 entry; `.planning/STATE.md` line 114
