# Security Classification Hierarchy

**Author:** Fable 5
**Version:** 1.0
**Status:** draft
**Priority:** medium (design-ahead; build is gated, see Staging)
**Milestone:** unscheduled - individual-equities era, no ROADMAP phase exists yet
**Created:** 2026-07-04
**Last Updated:** 2026-07-06 (Fable 5 review pass - items 6-8 resolved, Layer 1/2 refinements)
**Tags:** instruments, classification, taxonomy, gics, tags, equities, stratification, point-in-time
**Review resolved (2026-07-06, Fable 5):** the pending flag below is closed. Items 6-8 were
reviewed against intel-10 v3 (`intel-confluence-detection-persistence-layer.md`), the
calibrator doc, and live schema (psql, 2026-07-06). Verdicts: item 6's intent survives but its
routing is corrected in place - the missing build step is a per-symbol peer-feature family
measured by the standard IC machinery, with the confluence gate stack as the second stage, and
its discovery-first origin gatekeeping is dropped; items 7 and 8 stand with refinements
(epistemic-provenance rendering; definitional-staleness handling plus a wording fix -
`measurement_type` is calibrator-designed, not live). The two-layer split itself is confirmed
(see the new Design gate check section); a node-immutability invariant and two silent-failure
guards were added to Layer 1, and one look-ahead note to Layer 2. All changes carry dated
inline markers.
**Pending review (2026-07-04 - RESOLVED above, kept as historical record):** Consumers items
6-8 (thematic contagion as a confluence variant, definitional-vs-empirical exposure reporting,
human-lookup queries) were added by Sonnet in the same session, reasoning from this doc's
existing design plus `intel-10`'s gate stack and the calibrator's `measurement_type` field -
not yet Fable-reviewed like the rest of this doc. Flagged for a follow-up pass; nothing in the
additions changes Layers 1/2 as Fable specced them.

---

## Problem

The stated future direction is trading individual equities, classified hierarchically:
GICS-style at the top (Sector → Industry Group → Industry → Sub-Industry), with a finer
custom taxonomy below it (e.g. therapeutic area → indication → mechanism-of-action class
for healthcare names). Nothing in the platform models a multi-level classification today:

- `instruments.contract_details->>'sector'` is a flat ~10-value ETF-basket label
  (`commodity`, `international`, `fixed_income`, ...) - one level, not GICS, no hierarchy.
- `tag_vocabulary` / `instrument_tags` (live: 71 tags, 410 assignments, all `source='human'`,
  verified 2026-07-04) is flat, soft, weighted, multi-membership - by design.
- `controlled_vocabulary` (`docs/research/concept-controlled-vocabulary.md`, unbuilt) is flat,
  platform-wide symbolic-code metadata with deliberately zero relationship to instruments.

A prior pass proposed adding `parent_code` to `controlled_vocabulary`. This doc replaces
that proposal after working the problem from first principles. The conclusion is a split
architecture: a small purpose-built system for the authoritative layer, and a one-column
extension of the live tag system for the custom layer. The reasoning is the point of this
doc; the schema is small.

---

## Two separations drive the whole design

**1. Taxonomy vs. membership are different concerns.** "What are the valid nodes and how
do they nest" (the tree) is independent of "which node does this security belong to" (the
assignment). Every consumer that matters - IC stratification, peer baskets, exposure
aggregation, analog conditioning - queries *through membership*. A hierarchy design that
solves only the tree half (which is all a `parent_code` column on any vocabulary table
does) leaves the load-bearing half undesigned.

**2. Authoritative and hypothesized membership are different epistemic objects.**
GICS assignment is external reference data: S&P/MSCI say AMGN is `35201010 Biotechnology`,
single-valued, no confidence interval, not falsifiable by us - only revisable by them.
A mechanism-of-action assignment is our own claim: uncertain, legitimately multi-valued
(a company can be 40% oncology / 20% cardiovascular by pipeline), and testable against
market data. The first is a fact to sync; the second is a hypothesis to calibrate - which
is exactly the epistemic model `instrument_tags` + the TagAuditor
(`docs/research/stratification-instrument-tag-calibrator.md`) were built around: "tags are hypotheses; the
system tests hypotheses, not stores beliefs."

Forcing both through one membership table means either a `weight` column that is
meaningless for every authoritative row (the dead-column smell the APR-exempt reasoning
exists to catch), or authoritative facts pretending to be hypotheses inside a calibration
engine that must permanently exempt them. Either way the schema is lying about what one
class of rows is.

## The false premise: it is not one tree

The intuitive framing - Healthcare → Biotech → Oncology → Prostate Cancer → MOA class,
one continuous hierarchy - is factually wrong at the seam, and this kills the
"one hierarchical table" family of designs before any schema argument does.

Custom layers **cross GICS boundaries**. Oncology exposure is not a subdivision of
`Biotechnology`: Pfizer (`Pharmaceuticals`) and Amgen (`Biotechnology`) both carry
AR-antagonist prostate-cancer franchises. Nesting the MOA tree under a GICS leaf would
structurally misclassify roughly half of large-cap pharma. The custom layer is a
*separate, finer-grained dimension that correlates with* the GICS tree, not an extension
of it. So the design target is not "one deep tree" but:

- one strict tree per external scheme, exclusive membership;
- N independent soft trees (therapeutic area, MOA, and whatever comes later), weighted
  multi-membership, attached directly to the security - not to a GICS node.

This also disposes of the "tags scoped within a hierarchy node" variant (tags attached to
a taxonomy leaf rather than to the security): it re-imposes the single-tree premise one
level down.

---

## Chosen architecture

### Layer 1 - strict external classification (new, purpose-built, three tables)

```sql
CREATE TABLE classification_scheme (
    scheme      TEXT PRIMARY KEY,        -- 'gics'; 'icb' or 'sic' only if a consumer ever needs them
    name        TEXT NOT NULL,
    authority   TEXT NOT NULL,           -- 'S&P/MSCI'
    source_ref  TEXT,                    -- standard version / vendor identity
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE classification_node (
    scheme      TEXT     NOT NULL REFERENCES classification_scheme(scheme),
    code        TEXT     NOT NULL,       -- GICS: '35' / '3520' / '352010' / '35201010'
    parent_code TEXT,                    -- NULL = root level (GICS sector)
    level       SMALLINT NOT NULL,       -- 1..4 for GICS
    name        TEXT     NOT NULL,       -- 'Biotechnology'
    path        TEXT[]   NOT NULL,       -- materialized ancestor chain incl. self; derived
                                         -- projection of parent_code, rebuilt by the seeding
                                         -- migration - parent_code is the single source of truth
    valid_from  DATE     NOT NULL,
    valid_to    DATE,                    -- closed when a scheme revision retires the node
    PRIMARY KEY (scheme, code),
    FOREIGN KEY (scheme, parent_code) REFERENCES classification_node(scheme, code)
);

CREATE TABLE instrument_classification (
    symbol      TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    scheme      TEXT NOT NULL,
    code        TEXT NOT NULL,           -- deepest known node; normally the leaf (sub-industry)
    valid_from  DATE NOT NULL,
    valid_to    DATE,                    -- NULL = current assignment
    source_ref  TEXT NOT NULL,           -- 'spglobal_feed', 'ibkr_contract_details', ...
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, scheme, valid_from),
    FOREIGN KEY (scheme, code) REFERENCES classification_node(scheme, code)
);

-- Exactly one current assignment per (symbol, scheme):
CREATE UNIQUE INDEX uq_instrument_classification_current
    ON instrument_classification (symbol, scheme)
    WHERE valid_to IS NULL;
```

Deliberate design points:

- **No `weight`, no `confidence`, no `evidence`, no `source IN (human, empirical, ai)`.**
  Absence is the design. A security IS in a sub-industry or is not, per the scheme
  authority; a column that cannot mean anything for any row in the table does not get a
  column. Provenance collapses to `source_ref` (which feed said so) plus effective dates.
- **Membership stores the deepest node only; ancestors are derived** via `path` /
  `parent_code`. Never one row per level - parallel per-level rows can contradict each
  other, and a tree with one stored edge set cannot.
- **GICS codes are self-nesting numerically** (8-digit embeds 6 embeds 4 embeds 2), so
  GICS parent derivation is mechanical - but `parent_code` is stored explicitly anyway,
  because the tree walk must not depend on string arithmetic that other schemes (ICB, SIC)
  do not share.
- **Assignment above the leaf is allowed** (a source that only knows the industry level
  writes the industry node). The partial unique index still holds; consumers asking for a
  level the assignment does not reach get NULL, loudly, rather than a fabricated leaf.
- **Reclassification never overwrites.** Close the old row (`valid_to`), insert the new
  one. `instrument_classification` is append-only in effect, like `config_history` and
  `concept_transition_log`.
- **Node immutability invariant** *(added 2026-07-06, Fable 5)*: `parent_code` and `level`
  are immutable per `(scheme, code)` - the seeding migration hard-fails if a new seed
  disagrees with an existing row's parent or level, never updates in place. The node table
  is effective-dated in its columns but not in its key (PK is `(scheme, code)`, one row per
  code), so a reparented code cannot be represented - and absorbing one as an UPDATE would
  silently rewrite history for every as-of join that walks `path`, which is the exact
  bias class this table exists to prevent. GICS is safe under this invariant because
  reparenting always mints a new code (the parent is embedded in the digits); renames that
  keep the code do happen (sector 50 kept its code through the 2018 Communication Services
  restructure) and are fine: `name` is display metadata and updates in place, because no
  consumer keys on historical node names - stratification keys on codes. A future scheme
  that reuses or reparents codes cannot be loaded into this shape, and the seed must crash
  saying so; widening the PK to `(scheme, code, valid_from)` is the known escape hatch,
  paid only if such a scheme ever earns a consumer.
- **`instrument_classification.symbol` is `ON DELETE RESTRICT`** *(corrected from CASCADE
  2026-07-06, Fable 5; schema above already reflects it)*: cascading an instrument delete silently destroys
  point-in-time classification history - quiet data loss in the one table whose whole
  justification is history that cannot be reconstructed. Instruments are deactivated
  (`is_active = false`), not deleted; if a delete is ever attempted, this FK should be
  what crashes it loudly.
- **NULL-at-requested-level handling** *(added 2026-07-06, Fable 5)*: "consumers get NULL,
  loudly" is only loud if consumers make it so - a NULL stratification key silently drops
  rows or forms an anonymous NULL stratum, both of which violate never-drop-data. Rule:
  stratification consumers map NULL-at-level to an explicit scheme-qualified
  `unclassified` label (e.g. `gics:unclassified`), so unclassified names form a visible,
  countable stratum instead of vanishing from denominators.

### Point-in-time correctness is the reason Layer 1 must be purpose-built

GICS is not static. September 2018 created Communication Services and moved Facebook and
Alphabet out of Information Technology; March 2023 moved payment processors from
Information Technology to Financials. A backtest that stratifies 2015-2018 IC by
*today's* sector membership leaks 2018 information into 2015 - the same class of
look-ahead bias Invariant 1 (executable returns) and todo 026 (HMM fit-window ambiguity)
exist to prevent, just entering through reference data instead of prices. Two rules
follow:

1. Every historical join is an as-of join:
   `valid_from <= bar_date AND (valid_to IS NULL OR valid_to > bar_date)`.
2. **Never backfill history from a current snapshot.** If point-in-time GICS history is
   unavailable (it is commercially expensive - see Open Questions), membership history
   starts at onboarding date and accumulates forward. A shallow-but-honest history beats
   a deep fabricated one; this is the "silent wrong answers are worse than loud crashes"
   principle applied to reference data.

Neither `controlled_vocabulary` (migration-seeded, no dating) nor `instrument_tags`
(only `assigned_at` live today) has this shape, and retrofitting effective dating onto
either would distort them for every existing use. This requirement alone is sufficient
justification for a dedicated membership table.

### Layer 2 - custom soft taxonomies: one column on the live tag system

```sql
ALTER TABLE tag_vocabulary
  ADD COLUMN parent_tag TEXT REFERENCES tag_vocabulary(tag);
```

That is the entire schema change. The custom layer (therapeutic area → indication → MOA,
and any future soft taxonomy) becomes a subtree of tags:

- `onc_prostate_ar_antagonist` with `parent_tag = 'onc_prostate'`,
  `parent_tag = 'exposure_oncology'` above that, root tags with `parent_tag IS NULL`.
  Existing 71 tags are untouched (all NULL).
- **Membership is `instrument_tags`, unchanged.** `weight`, `source (human|empirical|ai)`,
  `evidence` JSONB are exactly the right membership model for hypothesized, multi-valued,
  uncertain classification - that table already is the soft-membership system; building a
  second one would fork provenance and calibration machinery for zero new capability.
- `category` keeps its current role (thematic axis, not taxonomy level). Classification
  subtrees fit the existing `exposure` category - `eq_sector` ("Single GICS sector equity
  basket") already lives there, so this is not even a new interpretation of the category.
  No CHECK change needed.
- Cycle prevention: seeding migrations construct subtrees top-down; a periodic audit
  query (recursive CTE depth check) guards against operator error. A DB-level trigger is
  not warranted at this volume - revisit only if AI-proposed tags ever get write access
  to `parent_tag`.

**Rollup semantics** (defined now so the first consumer does not improvise): a symbol's
effective weight at an ancestor tag = `MAX` over its weights on descendant tags.
Monotone, conservative, and interpretable ("its strongest claim to being an oncology
name"). Noisy-OR (`1 - prod(1 - w_i)`) was considered and rejected for now: it rewards
enumerating many weak sub-tags, which is a taxonomy-gaming artifact, not evidence.
Revisit when weights are empirical rather than human priors.

**Calibration convergence - why this placement pays for itself.** The TagAuditor's
measurement contract (`factor_series` + `beta_regression`) extends naturally to
hierarchical tags: the factor series for `onc_prostate` is the equal-weight daily-return
basket of its current high-weight members (or, better, that basket residualized against
the symbol's GICS industry basket, so the tag must prove *incremental* co-movement beyond
what the sub-industry already explains). A custom classification tag thereby becomes a
falsifiable hypothesis with an expiry path, like every other tag - which is precisely
what an authoritative GICS row could never be, and why the two layers must not share a
table. Forward-referenced in `docs/research/stratification-instrument-tag-calibrator.md`.

**Look-ahead asymmetry, stated once** *(added 2026-07-06, Fable 5)*: Layer 1 buys
point-in-time correctness with effective dating; Layer 2's live membership table has only
`assigned_at`. The calibrator doc already plans `valid_from`/`valid_to` on `instrument_tags`
(its temporal-validity section), which gives Layer 2 as-of membership when it ships. Until
then, any retrospective study that groups historical bars by *current* tag weights is a
look-ahead - the same leak the Layer 1 rules above exist to block, entering through the soft
layer instead. Discipline: tag-grouping studies either restrict to post-assignment data (the
calibrator's own forward-testing shape) or are labeled hypothesis-generation, never
measurement.

### How the layers relate

Structurally: they do not. No FK between `tag_vocabulary` and `classification_node` in
either direction - the crossing-boundaries argument above means a custom subtree must not
be anchored under a GICS node, and dual-registering custom nodes in both tables (a variant
considered and rejected, see Alternatives) creates two sources of truth for node
existence. The relationship is analytical, not structural: the calibrator uses GICS peer
baskets as residualization controls, and research queries join both through `symbol`.

---

## Alternatives considered, and why they lose

**A. Extend `controlled_vocabulary` with `parent_code`** (the prior proposal, removed
from that doc in this same change).
- Solves only the taxonomy half; membership - where every consumer lives - still needs a
  new table, at which point CV contributes only "a list of codes with parents."
- Scope mismatch: CV is platform-wide symbolic-code *metadata* (labels, groupings,
  display order), migration-seeded, read-only at runtime, with explicitly no instrument
  relationship. Classification is instrument *reference data* with vendor sync and
  effective dating. Same word ("vocabulary-ish"), different object.
- Couples equity classification to an unbuilt, indefinitely-deferred system - the exact
  mistake [Concept Registry](concept-unified-registry.md) already retracted once (the `concept_domain`
  namespace coupling: two deferred systems gating each other's build).
- CV has no effective dating, and adding it would distort the contract for every flat
  namespace (`signal_outcome` does not need `valid_from`).

**B. Everything in the tag system** (GICS levels as tags under `parent_tag`).
- `weight`/`source`/`evidence` are meaningless for authoritative rows - the dead-column
  smell, now for thousands of rows.
- `(symbol, tag)` PK cannot express "exactly one current sub-industry per symbol"; the
  exclusivity constraint would live in application convention, i.e. nowhere.
- No point-in-time model (`assigned_at` only, live).
- Philosophy inversion: the calibrator doc defines tags as falsifiable hypotheses. GICS
  membership is not falsifiable by regression - the calibrator would need a permanent
  structural exemption class, which is the system saying these rows do not belong.

**C. One new membership table serving both models** (nullable/constrained `weight` per
scheme; or custom trees in `classification_node` with `tag_vocabulary` rows bridging to
them).
- The nullable-weight variant relocates the dead-column smell into new code.
- The bridge variant dual-registers every custom node in two tables - two sources of
  truth for node existence, guaranteed drift.
- Both fork the weighted-membership machinery (`instrument_tags` + calibrator roadmap)
  that already exists and already has a designed empirical-validation path. Musk step 2:
  the best weighted-membership table is the one not built twice.

**D. Grand unification** - a new registry absorbing Tag Vocabulary and Controlled
Vocabulary under one table family / service base class.
- Rebuilds a live, working system (71 tags, 410 assignments, a designed calibration
  engine) for symmetry, not for any consumer.
- The three systems share only "codes with labels"; they diverge on every axis that
  matters: scope (instrument vs platform), membership (exclusive vs weighted vs none),
  mutation (vendor-synced vs calibrated vs migration-only), dating (required vs planned
  vs absent). A shared abstraction over that is a name, not a design.

---

## Relationship to the registry family (the unification verdict)

**Verdict: no umbrella - conceptually yes, structurally no.** This system slots into
[Concept Governance Registries](concept-governance-registries.md) as a third **Type 3** (static taxonomy)
sibling next to Tag Vocabulary and Controlled Vocabulary; that framework's taxonomy IS the
umbrella, and it costs nothing because it is documentation. A shared implementation
(common table family, `BaseRegistryService`) is rejected: two of the three systems do not
exist yet, and designing shared infrastructure to serve two unbuilt systems is precisely
the circular-justification pattern that doc's own refinement history (items 8 and 12:
`concept_gate_template` justified by unbuilt Interaction Factory) warns against. All
three can independently follow the same trivial *idiom* - load at startup, cached reads,
hard-crash on integrity divergence - without sharing a line of code. If, after all three
are live, a real consumer needs to query across them, extract the commonality then, from
evidence.

**Concept Registry: no interaction, checked rather than asserted.** Classification codes
have no evidence-gated lifecycle - GICS nodes change by external revision, not by
statistical proof, and custom tags already have their own empirical promote/expire path
via the TagAuditor. The one genuine lifecycle question in this area is whether a
classification *dimension as a whole* earns stratification status (does conditioning IC
on `gics_industry` beat conditioning on `gics_sector`?) - and that is intel-12's
substitution test governing a `StratificationDimension` provider, possibly as a
`concept_registry` row in the stratification domain. It governs the dimension, never the
codes.

**Controlled Vocabulary: fully decoupled.** CV keeps its flat-namespace contract; its
"Future Extension" hierarchy section is replaced by a pointer here. Neither system gates
the other's build.

---

## Consumers (what this is actually for)

1. **Stratification** - `gics_sector` / `gics_industry` become `StratificationDimension`
   providers (intel-12, now `docs/research/stratification-dimension-unification.md`): `grain='per_symbol'`,
   `causality_basis='deterministic'` (as-of joins on effective-dated membership), labels
   scheme-qualified per intel-12's label-identity invariant (`gics:35`, never bare `35`).
   Whether industry-level stratification earns its cells is decided by that doc's
   substitution test, not assumed here.
2. **Cross-sectional neutralization** - individual-equity IC work requires demeaning or
   residualizing returns within industry peers; peer sets come from tree-walk queries.
3. **Peer baskets** - the calibrator's residualization controls (above), and
   AnalogEngine (intel-13, now `docs/research/intel-analog-engine.md`) conditioning neighbor retrieval
   on classification.
4. **Exposure aggregation** - portfolio-level sector/industry exposure for the trade
   construction layer (`docs/research/trade-construction-layer.md`, v4.0 concern).
5. **The custom layer's own research question** - does finer-than-sub-industry grouping
   (indication, MOA) carry co-movement or IC *incremental to* GICS? If it does not, Layer
   2 taxonomies expire via the calibrator like any failed tag. That falsifiability is a
   feature of this placement, not an accident.
6. **Thematic contagion - routed through the feature pipeline first, confluence second**
   *(original added 2026-07-04 by Sonnet; reviewed and revised in place 2026-07-06, Fable 5)* -
   the motivating question: if exposure-weighted members of a theme (e.g. `quantum_computing`)
   fire together, can that be used to infer effect on other members, scaled by their weight?
   The original item's two instincts survive review intact: no propagation heuristic gets
   built outside the promotion gates, and two co-firing names are an anecdote, not evidence.
   Two corrections to how it gets there:
   (a) **The missing build step is a per-symbol feature, not a gate-stack routing.** intel-10
   v3 (`intel-confluence-detection-persistence-layer.md`) defines a confluence as a joint
   condition *over primitive features* - but a cross-symbol event ("two theme peers fired")
   is not a primitive anything currently computes, so "run it through the confluence gate
   stack" has nothing to condition on until the cross-sectional quantity is materialized per
   symbol. The concrete shape is a small **peer-feature family** in the Feature Factory: for
   symbol `s` and tag `t`, e.g. `peer_return_z(s, t)` = exposure-weighted same-bar return of
   the *other* high-weight members of `t`, residualized against `s`'s GICS industry basket
   (Layer 1 supplying the control - exactly the calibration-convergence pattern above);
   optionally a peer co-fire count at the alpha-event grain. These are ordinary features:
   ic_engine measures them, FDR and sample-size gates apply, the ensemble weights them - and
   the standard machinery already encodes every objection the original item raised (a
   3-member theme yields a noisy feature that simply fails the gates; no special-casing, no
   breadth heuristic). Only if the *joint* claim - "co-firing predicts more than the additive
   combination of these peer features" - remains interesting after that does this become an
   intel-10 condition, where gate 1's marginal-lift-over-the-additive-null test is precisely
   the right arbiter, along with the rest of that stack (batch-level BH-FDR across every
   theme considered, walk-forward stability, calibration, cost hurdle, OOS confirmation,
   `shadow` before `active`). Cheapest sufficient machinery first; the confluence layer is
   the second stage, not the front door.
   (b) **Origin gatekeeping is dropped.** The original item required the cluster itself to be
   discovered statistically before use ("derive tags from residual co-movement... not the
   reverse"). That is over-strict, and inconsistent with the calibrator's own philosophy,
   which admits human-asserted tags as seed hypotheses and lets the falsification engine
   decide. A hand-named theme is a legitimate hypothesis; a TagAuditor-discovered cluster is
   the same hypothesis with a better prior. The gate stack protects promotion; nothing needs
   to protect hypothesis origin. (The Simons-version discovery path stays valuable - as the
   stronger *generator* of candidate themes, not as an admission requirement.)
7. **Human-facing relationship lookup, decoupled from any trading claim** - "given company
   A, what else shares its classification or taxonomy membership, and how strongly" is a
   plain read query (tree-walk on `classification_node` / weighted lookup on
   `instrument_tags`, including subtree rollup via `parent_tag`), not a promotion-gated
   claim. Showing a relationship and trading on a relationship are different acts with
   different burdens of proof; this consumer only needs the former.
   *(Reviewed 2026-07-06, Fable 5 - kept as written, one addition:)* the lookup surface must
   render epistemic provenance per row - scheme-authoritative (Layer 1, with effective
   dates), `definitional` (asserted, with its as-of date, see item 8), or `empirical` (with
   weight and age) - so the human-facing view never flattens the two-model split this doc
   exists to maintain. A UI that shows "AMGN: Biotechnology, oncology 0.8" as two peer facts
   has silently re-merged the layers.
8. **Portfolio/watchlist exposure reporting across themes, whether or not they feed
   trading logic** - "how exposed am I to AI, quantum, semis, lithography, etc." is the
   same query as (7), aggregated across a book. This is where `tag_vocabulary`'s existing
   `measurement_type='definitional'` matters beyond its current use (`benchmark`,
   `spread_leg`, `sentiment`): a fact sourced from a filing (e.g. "22% of this company's
   semiconductor revenue is PC-oriented, not AI-accelerator") is `definitional` - asserted,
   never tested, never expired by the calibrator, purely descriptive - distinct from an
   `empirical` tag the calibrator tests and can expire. Both tiers live in the same
   `instrument_tags` table; only `empirical` tags (and only ones that clear the confluence
   gate stack in (6)) are eligible to become trading signals. A single security should
   carry sibling leaf tags at this grain rather than one coarse label - `semiconductors_pc`
   weight 0.7 and `semiconductors_ai_accelerator` weight 0.1 under a shared
   `semiconductors` parent - so an exposure report doesn't conflate "high semis exposure"
   with "high AI exposure" the way one flat sub-industry bucket would.
   *(Reviewed 2026-07-06, Fable 5 - placement confirmed, two refinements.)* First, a wording
   fix: `measurement_type` is not "existing" - it is a calibrator-designed column
   (`stratification-instrument-tag-calibrator.md`, schema section), unbuilt live (verified via psql
   2026-07-06: `tag_vocabulary` carries `tag`/`category`/`description` only). Item 8
   therefore depends on the calibrator's Phase 1 migration shipping first, worth stating.
   Second, the real strain this item puts on the two-model split, named and resolved: a
   filing-sourced revenue split is epistemically closer to Layer 1 than Layer 2 - externally
   asserted, dated, revisable by the issuer, not falsifiable by regression - yet it lands in
   `instrument_tags`. The placement is still right, for three reasons Layer 1 cannot absorb:
   the values are multi-valued weights (Layer 1's exclusive-membership index forbids that by
   design); mapping reported segments onto our taxonomy ("Client Computing Group" →
   `semiconductors_pc`) is itself a judgment, so the stored weight is an interpretation of a
   fact, not the fact; and a third membership table for "weighted facts" is exactly
   Alternative C. But `definitional` means the calibrator never expires these rows, and
   unlike Layer 1 they have no vendor sync - so a 2026 revenue mix silently drives a 2029
   exposure report. The proportionate fix, no schema change: definitional tags encoding
   dated facts carry provenance in the existing `evidence` JSONB
   (`{"source": "10-K FY2025", "as_of": "2026-02-15"}`), and exposure reports render
   staleness (flag weights whose `as_of` exceeds a threshold - an APR key, not a constant).
   If definitional exposure ever graduates from reporting to trade-construction inputs
   (consumer 4), it graduates to effective dating at the same moment - reporting can
   tolerate flagged staleness; position limits cannot.

---

## Design gate check (2026-07-06, Fable 5)

The CLAUDE.md four-question gate, applied to the whole design:

1. **Survives 10x volume?** Yes, trivially. This is reference data: ~800 symbols at 10x, a
   few thousand classification nodes, membership rows accruing only on reclassification
   events. Every consumer query is an indexed as-of join or a subtree walk over tables that
   fit in cache. Not a scaling design at all, and doesn't need to be.
2. **What fails silently?** Five vectors, each now addressed in place: snapshot backfill
   (accumulate-forward rule, original); seed migrations silently rewriting node parents
   (node-immutability invariant, added); NULL-at-level rows vanishing from strata
   (`unclassified` label rule, added); definitional fact staleness (as-of provenance plus
   report flagging, item 8); current-weight retrospective studies on Layer 2 (look-ahead
   note, added). The residual risk is the as-of join discipline itself - it lives in
   application code, which is why the `ClassificationService` read layer with its as-of
   helper should be the only sanctioned access path, same posture as `stream_keys.py` for
   topics.
3. **Does the DAG still hold?** Yes. Both layers are read-only reference data at runtime;
   seeds and vendor sync are the only writers, and the one-writer rule applies: whatever job
   syncs vendor classifications is the sole post-seed writer to `instrument_classification`,
   and the TagAuditor remains the sole empirical writer to `instrument_tags`. No compute
   daemon persists classification state, no cycles, and the two layers deliberately share no
   FK.
4. **What manual step does this eliminate?** Honestly: none that exists today. It prevents a
   class of future manual work (ad-hoc per-study classification lists, hand-maintained peer
   baskets) and a class of unfixable bias (single-snapshot history in the training corpus)
   rather than deleting a current step. That is consistent with its own staging rule below:
   build nothing until the equities trigger fires.

**Verdict on the two-layer split: confirmed.** The strongest argument is not the dead-column
smell (weight=1.0 authoritative rows would be ugly but survivable) - it is that the
calibrator is a falsification engine, and an authoritative row inside one must be either
falsified (wrong) or permanently exempted (the schema lying about what the row is), while the
exclusivity and point-in-time constraints Layer 1 needs are inexpressible in
`instrument_tags`' key. The steelman for unification - one membership table, fewer moving
parts - buys one fewer table at the cost of a permanent exemption class in the calibrator, an
exclusivity constraint enforced only by convention, and effective dating retrofitted onto 410
live rows that don't want it. A council signs off on the split.

---

## Staging and build trigger

**Unscheduled. No ROADMAP phase. Nothing here should be built now** - the current
universe is ETFs, funds have no GICS, and the flat `contract_details->>'sector'` label is
adequate for basket-level work. Building ahead of real candidates would violate both this
project's promotion discipline and CV's own "no namespace without a concrete consumer"
rule.

- **Layer 1 trigger:** the first phase that onboards individual equities into
  `instruments`. Hard requirement: that same phase ships the three tables and seeds
  membership, because point-in-time correctness cannot be retrofitted - months of
  single-snapshot classification data is the silent-bias failure mode, already in the
  training corpus by the time it is noticed. Layer 1 is small (three tables, one seed
  migration, an as-of query helper; `ClassificationService` read layer per the naming
  system) and must not lag the universe expansion.
- **Layer 2 trigger:** the first concrete custom-classification research question with a
  defined measurement (e.g. an oncology/MOA basket study specifying its residualization
  control). Seeding a therapeutic-area taxonomy before a consumer exists is exactly the
  belief-storage anti-pattern the calibrator doc exists to kill. `parent_tag` itself is a
  one-line migration; it ships with the first subtree, not before.
- **Calibration extension (basket factor series in TagAuditor):** with or after the
  calibrator's own Phase 1, whichever comes second. It is an extension of that engine,
  not part of this build.

---

## Open questions

1. **GICS data sourcing and licensing.** GICS is licensed (S&P/MSCI). Candidate paths:
   vendor feed, IBKR contract metadata (coverage/level unverified), or free proxies (SEC
   SIC codes - a *different* scheme, which the `scheme` key models honestly rather than
   pretending it is GICS). Point-in-time historical membership is the expensive part;
   the accumulate-forward rule above is the fallback. Decide at Layer 1 build time.
2. **Issuer vs symbol identity.** Classification is company-level; `instruments` is
   symbol-keyed (GOOGL/GOOG would each carry a row). Duplicate rows per share class are
   acceptable initially; a proper issuer entity table is a larger identity question that
   individual-equities work will raise everywhere (corporate actions, fundamentals), not
   just here. Do not solve it inside this system.
3. **Rollup operator** - `MAX` chosen for interpretability while weights are human
   priors; revisit vs noisy-OR once weights are empirical.
4. **Second scheme** - ICB/SIC only if a consumer needs one; note that two schemes
   disagreeing about a security is itself a potential data-quality or ambiguity signal
   (conglomerates), which the multi-scheme shape makes queryable for free.
   **Scheme choice note (2026-07-04):** by original launch date, SIC (1937, U.S.
   government; largely superseded domestically by NAICS in 1997 but still floating around
   in older financial feeds - the "free but crude" fallback in Open Question 1 above) is
   the oldest, GICS (1999, jointly developed by MSCI and S&P) is next, and ICB (2005,
   FTSE Russell/Dow Jones; restructured in 2019 into a GICS-like 4-level hierarchy) is the
   newest. Recency is not the deciding factor for the default `scheme` here, though -
   GICS's dominance in the equities/index space this platform actually trades (it
   underlies most S&P/MSCI index construction and the bulk of institutional equity
   research) is what makes it the right default, not that it happens to predate ICB. If a
   second scheme is ever added, choose it on coverage/licensing grounds, not recency.
5. **Depth/cycle enforcement for `parent_tag`** - migration discipline + audit query now;
   DB trigger only if AI-proposed tags ever gain `parent_tag` write access.
