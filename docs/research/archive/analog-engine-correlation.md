# Correlation Intelligence Layer — Independence Measurement Across the Stack

**Archived 2026-07-02.** Superseded for its analog-predictor use case: redundancy control for
analog predictors is already handled by the ensemble's existing Ledoit-Wolf decorrelation
(`src/intelligence/ensemble/weights.py`) — not the same algorithm as this doc's eigenvalue
participation ratio, but sufficient for that purpose (see `docs/research/intel-13-analog-engine.md`
for the precise comparison). The entity-generic effective-N design (plugins, signals, agents,
features, instruments) is kept here as reference — no live consumer needs it built today, but
it is the correct design if one ever does; do not re-derive from scratch.

**Version:** 1.5
**Status:** under-review
**Priority:** high
**Last Updated:** 2026-05-31
**Tags:** pgvector, independence, effective-n, correlation, plugin-correlation, signal-independence, agent-decorrelation, feature-redundancy, shadow-registry, vil

---

## Foundation

This document is an application of the **Vector Intelligence Layer** (`analog-engine-substrate.md`). VIL is the shared substrate — embed and retrieve. This document defines the **Correlation Intelligence Layer**: the platform's **independence measurement layer**.

It is the counterpart to analog-engine-ic-factory. The two measure the orthogonal questions you ask of any signal source:

- **analog-engine-ic-factory** measures **prediction** — does this predict price? → IC
- **analog-engine-correlation** measures **independence** — is this redundant with that? → effective-N / correlation

The measurement is entity-agnostic: embed any set of entities' histories, take pairwise cosine similarity, derive effective-N (how many are truly independent) and the redundant pairs. **Plugin correlation is the flagship application — the first and most fully specified — but it is one application of a general capability, not the whole layer.** Independence is the scarce resource in this whole system: Renaissance's edge is *independent* bets, and this layer is where independence is measured, at every level it matters.

Do not read this as a standalone design. VIL owns the embedding infrastructure, the pgvector storage, and the cosine similarity primitive. This layer owns the redundancy question built on top of it — generically, with plugins as the worked example.

---

## The General Idea (told through plugins, the flagship case)

The shadow registry tracks 132 plugins individually — is this plugin's EV positive? What it cannot see is whether those 132 represent 132 independent observations of the market, or 20 observations counted 6 times each because many plugins measure the same phenomenon.

This is the redundancy question. It is a fundamentally different question from "is this plugin good?" A plugin can have strong positive EV and still be redundant — contributing no independent information beyond what another plugin already sees. The same question, unchanged, applies to live signals, swarm agents, features, and instruments (see "What This Layer Measures Independence Of" below) — plugins are simply where it was first noticed and first solved.

The solution is to embed each plugin's signal history as a vector and measure pairwise similarity using pgvector. Cosine distance over L2-normalized vectors gives `signed_r` — the [-1, 1] signed correlation metric needed to compute effective-N via eigenvalue decomposition. A pair of plugins that consistently fire in the same direction have high cosine similarity. A pair that consistently disagree have negative similarity — they are more independent than two uncorrelated plugins, not neutral.

From the full similarity matrix, eigenvalue decomposition produces a single number: **effective-N** — how many truly independent signal sources you actually have. That number is the primary output. Redundant pairs identified by the batch feed into shadow_registry suppression as a secondary output. The pipeline skip gate ensures suppressed plugins never reach `_compute()` — suppression reduces compute budget, not just signal count.

---

## What This Unlocks

| Consumer | What they gain |
|---|---|
| **Aggregator** | Confidence estimates calibrated to actual independent evidence count — not raw plugin count. If effective-N is 20, a 132-plugin confluence score is not 6.6× more confident than a 20-plugin score. |
| **Executor** | Suppressed redundant plugins never reach `_compute()`. Compute budget shrinks proportional to redundancy. |
| **LLM swarm** | 20 independent signal perspectives rather than 132 correlated ones. Diversified evidence, not duplicated evidence that the agent mistakes for consensus. |
| **shadow_registry** | Second governance dimension alongside EV-based suppression. A plugin can have positive EV and still be suppressed for correlation — they measure different fitness criteria. |
| **Grafana** | `effective_plugin_count` gauge — continuous, alertable visibility into signal independence. Drop below 6 → warning. |
| **Research** | Weekly effective-N trend reveals whether new plugins genuinely diversify the signal base or pile onto existing factors. |

---

## What Simons Would See First

The shadow governance system tracks each I7 plugin's individual expected value. What it cannot see is **redundancy**: the effective number of truly independent signal sources across 132 plugins, their features, and the signals they generate.

If effective-N is 20 when you have 132 plugins, every downstream confidence estimate is inflated by a factor of 6.6. The aggregator counts 132 votes where only 20 independent observations exist. The LLM swarm receives duplicated evidence it mistakes for diversified evidence. The inflation is invisible without continuous measurement.

Simons would demand three things:

**Correlation operates at every level.** Feature-level: RSI and MACD may encode identical momentum information. Plugin-level: two momentum plugins may produce correlated signal histories. Signal-level: a 1m signal and a 5m signal on the same setup may be the same trade counted twice. The question is identical at every level — are you counting one observation as two?

**Effective-N is the instrument, not a list of pairs.** Pairwise correlation is a means, not the end. The eigenvalue decomposition of the full correlation matrix produces a single number — effective-N — that answers the real question: how many truly independent sources do you have? Anything that doesn't move effective-N upward is redundant by definition.

**Anti-correlation is independence.** Two plugins that consistently fire in opposite directions are more independent than two that are uncorrelated. `signed_r = (agree - disagree) / co_fire` captures this; raw agreement rate does not. Effective-N computed from agreement rates is wrong — it must be computed from signed correlation via eigenvalue decomposition.

This is the Correlation Intelligence Layer. It runs continuously, governs nothing directly, and produces one primary output: effective-N at each entity level, with redundant pairs identified and surfaced for the governance consumer (shadow_registry) to act on.

---

## Why the Substrate, Not a Hand-Rolled Matrix

This question was originally planned (as Phase 112, since archived) with a hand-rolled direction-agreement matrix — custom Python re-implementing what pgvector does natively. That approach collapsed three concerns that must stay separate:

| Concern | What it is | Where it belongs |
|---------|-----------|------------------|
| **Signal representation** | What does a plugin's output history look like as a mathematical object? | Stored — VIL `embeddings` |
| **Similarity computation** | How do you measure distance between two histories? | Delegated — pgvector `<=>` |
| **Domain threshold** | What constitutes "redundant" in trading terms? | Application code — this doc |

Separation of concerns demands these be independent. The representation is **stored** in VIL's embedding registry; the similarity is **computed by the database**; only the domain threshold — what "redundant" means in trading terms — lives in correlation application code. pgvector v0.8.2 is already compiled into the database image (see `analog-engine-substrate`); the only prerequisite is `CREATE EXTENSION vector;`.

**Self-expiry is intrinsic.** Once a plugin is suppressed, its `co_event_count` stops accumulating. After ~13 weeks the pair drops below the minimum co-fire gate and the batch auto-clears the flag. Data starvation is the expiry mechanism — no manual re-activation needed.

---

## Effective-N: What It Means and Why It Matters

The effective number of independent plugins is computed via the **participation ratio** on the eigenvalue spectrum of the correlation matrix:

```
effective_n = 1 / Σ(λᵢ / Σλ)²
```

Where λᵢ are the eigenvalues of the pairwise correlation matrix. This is a standard measure from portfolio theory (Menchero, Stefek & Wang; also used in PCA dimensionality estimation). It answers: if the plugins were perfectly independent, effective_n = 132. If all 132 are measuring exactly the same thing, effective_n = 1.

The eigenvalue computation requires a proper **signed** correlation metric — not agreement rate `directional_r = agree / co_fire` which ranges [0, 1]. For effective-N you need `signed_r = (agree - disagree) / co_fire` which ranges [-1, 1] and captures anti-correlation (two plugins that consistently fire in opposite directions are *more* independent, not neutral). This is one of the Codex review's HIGH findings that was already incorporated into the revised plans.

With pgvector, `signed_r` is not a derived field — it falls out naturally from cosine similarity over L2-normalized signal history vectors.

---

## What This Layer Measures Independence Of

This is the layer's true scope, and plugins are one row of it. The eigenvalue/participation-ratio computation cares nothing about *what* it counts — it answers "how many independent things are in this set?" and "which pairs are redundant?" for any set of embedded entities. The math is fixed; only the `entity_type` and the consumer change. The question gets more valuable the higher up the stack you ask it:

| Entity | Question it answers | Redundancy means | Consumer |
|---|---|---|---|
| **Plugin** (flagship) | how many independent signal *sources*? | two plugins read the same phenomenon | aggregator confidence; suppression governance |
| **Signal** | how many independent *reads* firing now? | two live signals are the same bet | analog-engine-05's conviction bound |
| **Agent** | how many independent *opinions* vs echoes? | an agent just restates another | eAI decorrelation fitness |
| **Feature** | RSI vs MACD — same momentum twice? | two features encode the same information | feature selection / dimensionality reduction |
| **Instrument** | which assets move together? | two instruments share a common factor | cross-asset structure, risk concentration |
| **Position** (future) | how many independent *bets* actually on? | two exposures are one underlying bet | risk / sizing, if ever built |

Each is the same `entity_type`-generic computation over VIL's `similarity_pairs`, scoped to a different entity. Nothing new is built — a new level is a new `entity_type` filter and an eigenvalue call. Two applications are immediately useful: **signal-level** effective-N is the number analog-engine-05's conviction bound depends on, and **feature-level** redundancy is what tells the embedding spec (analog-engine-substrate) and the IC Factory (analog-engine-ic-factory) which features are duplicates rather than independent evidence.

Every application inherits the same data-starvation caveat: gate on co-occurrence before trusting a pair (signals, agents, and positions co-occur far less than plugin outputs do — sparse sets give noisy correlations). And the measurement is always just measurement — *what to do* with a redundant pair (suppress a plugin, bound the combiner, drop a feature, flag an agent) is the application's policy, decided by its consumer, never by this layer.

This is the compounding payoff of putting the independence question on the shared substrate: solve it once for plugins, and signals, agents, features, instruments, and positions are the same query.

---

## Plugin Correlation on the VIL Substrate

Infrastructure prerequisites (pgvector installation, L2-normalization law, operator reference, HNSW index guidance) are defined in `analog-engine-substrate` and not repeated here. This section covers what is specific to plugin correlation.

### Plugin Correlation via pgvector

Instead of computing a direction matrix in Python and storing scalar correlation coefficients:

1. **Represent** each plugin's recent signal history as a fixed-dimension float vector (last 90 days of `direction × confidence` per bar; zero for non-firing bars — length 90 or 252), serialized per the VIL embedding spec
2. **Store** one vector per plugin per weekly batch in VIL's `embeddings` table: `entity_type='plugin'`, `entity_id=plugin_name`, `scope`, `computed_at`, `embedding vector(N)`
3. **Query** redundant pairs using `<=>` cosine distance — the similarity score between two L2-normalized vectors is equivalent to `signed_r`; no Python matrix math required
4. **Write** qualifying pairs to VIL's `similarity_pairs` (`entity_type='plugin'`): `cosine_sim` carries `signed_r`, `co_event_count` carries `co_fire_count`
5. **Apply** domain thresholds (APR: `analog.correlation.min_co_event_suppression` >= 100, cosine similarity `>=` APR: `analog.correlation.redundancy_threshold` default 0.80) in the WHERE clause
6. **Derive** effective-N from the cosine similarity matrix via eigenvalue decomposition — same math, but the raw similarity values come from the database rather than custom formulas

No correlation-specific embedding or pairs table is needed — both are VIL substrate tables. Correlation owns only the suppression governance (`shadow_registry.correlation_suppressed`) and the effective-N history (`plugin_correlation_summary`).

### Self-Expiry Still Works

The self-expiry mechanism (D-09 from the spec) is unaffected. Suppression still sets `correlation_suppressed = true`. `co_fire_count` still stops accumulating for suppressed pairs. The vector representation of a suppressed plugin still exists but its pair similarity drops below threshold as market regimes shift. The batch still auto-clears.

### The Three-Gate Suppression Logic Is Preserved

The pgvector approach changes how similarity is *computed*, not how suppression decisions are *made*. All three gates remain:
1. Cosine similarity >= APR `analog.correlation.redundancy_threshold` (default 0.80; replaces `directional_r >= 0.80` — equivalent for L2-normalized vectors)
2. `co_fire_count` >= APR `analog.correlation.min_co_event_suppression` (default 100) — still enforced in the batch
3. Inferior plugin has lower `last_eval_ci_lower` from `shadow_registry` — unchanged

When both `last_eval_ci_lower` values are the `-inf` sentinel (too few resolved signals), fall back to `last_eval_ev_r`. If neither gives a strict comparison, skip the pair — never guess.

Suppression clear is **scoped to `component_type = 'i7_plugin'`** — the batch never touches non-I7 components (swarm_agent, etc.).

### Schema Constraints

VIL's `similarity_pairs` already enforces canonical ordering (`CHECK (entity_a < entity_b)`) and latest-snapshot UPSERT semantics — both are substrate properties, not re-specified here. Correlation-specific constraints:

- `similarity_pairs.cosine_sim` carries `signed_r`; `co_event_count` carries `co_fire_count` — for `entity_type='plugin'` rows
- **Latest-snapshot for plugin pairs**: after each weekly UPSERT, DELETE `entity_type='plugin'` rows not in the current qualifying set. Stale pairs accumulate `co_event_count` forever otherwise.
- Pair qualification threshold: `co_event_count` >= APR `analog.correlation.min_co_event_write` (default 30) to write the row; >= APR `analog.correlation.min_co_event_suppression` (default 100) for the suppression gate (two separate thresholds)
- `plugin_correlation_summary` (correlation-owned) keeps **full history** — plain INSERT one row per weekly run (~52/year), not UPSERT. Holds effective-N and run metadata; no VIL equivalent exists.
- `shadow_registry_active` VIEW predicate is `WHERE NOT is_shadow AND NOT correlation_suppressed` — the base table has **no `promoted` column**; `promoted` is wrong and breaks the view

### Pipeline Skip Gate (approach-independent, always required)

The batch only *records* suppression — it does not stop suppressed plugins from running. So the executor needs an explicit skip gate, and the design intent is precise about *where* it fires: suppression must save compute, not just discard output. The suppressed set is loaded into the executor's existing shadow cache and the gate fires *before* a suppressed plugin does any work — earlier than the circuit breaker and lookback checks — so `_compute()` is never reached. (Skipping after compute would defeat the entire compute-budget rationale.)

One subtlety worth flagging now, because it inverts the usual rule: the cache loader reads the **base `shadow_registry` table**, not the `shadow_registry_active` view. The view hides suppressed rows by design, so it cannot answer "which enrolled plugins are suppressed" — this is the one documented exception to the all-consumers-use-the-view convention.

### What to Instrument

The standard VIL retrieval metrics and batch-job-completion contract are inherited from `analog-engine-substrate`. Correlation adds three point gauges that make signal independence continuously visible: **effective-N** (the headline number), the count of **redundant pairs**, and the count of **currently suppressed** plugins. effective-N is the one that earns a Grafana alert — a floor below APR `analog.correlation.effective_n_floor` (default 6) means the 132 plugins have collapsed to dangerously few independent sources.

### Cadence

A weekly batch, scheduled to avoid contention with the other weekly ML batches, and resilient to a missed run (it picks up on next boot). It does not need to run more often — redundancy structure shifts slowly.

---

## Shape of the Work

Correlation is a VIL application — it depends on the VIL substrate (extension enabled, `embeddings` + `similarity_pairs` tables) existing first. The broader compounding story (episodic memory, setup similarity, regime fingerprinting) belongs to `analog-engine-substrate` and is not re-listed here. Three pieces, in dependency order:

1. **Correlation-specific schema** — the substrate's embedding/similarity tables already exist; correlation adds only what is its own: the `correlation_suppressed` flag (and the active-set view that excludes it), an effective-N history table, and the supporting scan index. Everything else is borrowed from the substrate.
2. **The weekly batch** — embed each plugin's history (per the VIL embedding spec), let pgvector compute the pairwise similarities, apply the three-gate suppression logic, refresh the latest-snapshot pairs, and record effective-N. This is where the redundancy question is actually answered.
3. **The pipeline skip gate** — the batch only *records* suppression; something has to *act* on it. The executor skips suppressed plugins before compute (see below). This piece is independent of how similarity was computed.

---

## Open Questions

- **Vector dimension**: 90 trading days × 1 float = 90-dim. Or include confidence → 180-dim. Start at 90 (APR: `analog.embedding.plugin_dim`, default 90); measure whether adding confidence improves pair detection.
- **Backfill**: batch operates on `signal_ledger` history from execution date forward. At first run, ~90 days of data should already exist.
- **Plugin embedding serialization**: the general embedding-serialization law (rolling standardization, versioning) is owned by `analog-engine-substrate`. Open for plugins specifically: is `direction × confidence` per bar sufficient, or should the per-bar value be standardized against the plugin's own recent output range?

---

## Relationship to Existing Work

- **VIL substrate (`analog-engine-substrate`):** Owns the `embeddings` and `similarity_pairs` tables, the embedding serialization spec, and the k-NN/cosine primitive. Correlation is a consumer — it writes `entity_type='plugin'` rows and reads them back for effective-N.
- **Phase 112 plans:** Archived (`.planning/phases/archive/112-plugin-correlation/`). They used a hand-rolled direction matrix; this doc supersedes them with a VIL-substrate design. The concrete operational detail (exact systemd timing, cache wiring, OTel call patterns, regression assertions) lives in those archived plans and is intentionally left there — this doc keeps the design intent, not the implementation commands.
- **analog-engine-ic-factory (Predictive Feature Intelligence):** Sibling VIL application. Shares the weekly batch cadence and the same substrate; different question (forward prediction vs independence).
- **`shadow_registry`:** Unchanged. Suppression flags live there. Similarity computation is a separate concern.
- **`shadow_registry_active` VIEW:** `WHERE NOT is_shadow AND NOT correlation_suppressed` — single interface for active-set consumers. Cache loaders read the base table (documented exception above).

---

## Alternatives Considered

**Self-contained correlation schema (rejected).** An earlier plan gave correlation its own `plugin_embeddings` and `plugin_correlation_pairs` tables, isolated from the rest of the vector stack. Rejected: two embedding stores violate reuse and separation of concerns — the same vectors would exist in two places with two write paths. Chosen instead: correlation writes `entity_type='plugin'` rows into VIL's shared `embeddings`/`similarity_pairs` and owns only what is genuinely correlation-specific (suppression governance, effective-N history). If isolation is ever re-proposed, the cost is a duplicated substrate — not worth it at this scale.

---

## Principles Alignment

| Principle | How this satisfies it |
|-----------|----------------------|
| **Modularity** | Similarity is a substrate, not a feature. Any analysis needing "find similar X" uses the same primitive. |
| **Reuse** | One extension serves plugin correlation, episodic memory, and every future retrieval use case. |
| **Separation of concerns** | Representation (stored vector), computation (pgvector), threshold (application code) are independent layers. |
| **No redundant abstraction** | The direction matrix re-implements similarity that the database already provides. |
| **Instrument everything** | Vector queries are SQL — they appear in query logs, EXPLAIN ANALYZE, and pgstats automatically. |
| **Compounding** | Build the vector layer once; every future similarity problem is already solved. |
