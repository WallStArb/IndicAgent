# Controlled Vocabulary Registry (CVR)

**Canonical name:** Controlled Vocabulary Registry (CVR)
**Informal alias:** "vocab system" (colloquial — acceptable in casual conversation, not in architecture docs or code comments)
**Status:** current — Phase 161 shipped complete 2026-07-18
**Last Updated:** 2026-08-15
**Phase introduced:** 161

---

## What It Is

The **Controlled Vocabulary Registry (CVR)** is the system-wide home for symbolic taxonomies — the set of valid codes a namespace can take, plus their human-readable labels and optional groupings. It is "the APR for symbolic codes": rather than a hardcoded label dict scattered across every consumer that needs to know `regime_hmm` has exactly `{trending_up, trending_down, ranging, high_vol, low_vol}` or that `timeframe` means `{1m, 5m, 15m, 1h, 1d}`, one migration-governed registry holds the authoritative set, and consumers read from it instead of re-declaring it.

CVR rows are **definitional, not falsifiable**. A code either exists in a namespace or it does not — no confidence, weight, or evidence attached. This is the key structural distinction from the [Instrument Tag Registry](instrument-tag-registry.md): a tag is a hypothesis about an instrument that can be measured, contradicted, and expired; a controlled-vocabulary code is a fixed symbolic definition, changed only by migration. `regime_hmm/trending_up` existing as a valid code is not something TagCalibrator-style measurement re-checks each week — it's the fixed name of a state a different system (HMM) assigns.

The registry closes a specific failure mode: silent taxonomy drift. A live source column can start emitting a code the registry never heard of — a renamed regime label, a new timeframe, a third `regime_group` value nobody registered — and every downstream consumer with a hardcoded label list just silently mishandles it. CVR makes that loud via `VocabularyDriftAuditor`.

### Relationship to APR and ITR

Three siblings under [Concept Governance Registries](../research/concept-governance-registries.md), each governing a different kind of knowledge:

- **APR** — tunable *numbers* (thresholds, weights, periods).
- **ITR** — falsifiable *classification claims* about instruments (this symbol has this exposure/sensitivity).
- **CVR** — fixed *symbolic definitions* (this code is valid in this namespace, and means this).

CVR is deliberately kept a **permanently separate system** from ITR (D-02, migration 231) even though both look like "vocabulary" at a glance — forcing a definitional row (`timeframe/5m`) and a confidence-weighted hypothesis row (`TLT`/`rate_sensitive`, `loading=0.71`, `p=0.02`) through one shared table would make the schema lie about what kind of row it is. No shared table, no FK, no bridging ENUM.

---

## Infrastructure

Three tables (Phase 161), one read-side service, one drift auditor. No dashboard yet (read-only API instead).
<!-- src: production/migrations/231_controlled_vocabulary_schema.sql, 233_controlled_vocabulary_seed_namespaces.sql -->

### Table Schemas

**`controlled_vocabulary`** — flat `(namespace, code)` → label/description registry.

| Column | Type | Description |
|--------|------|--------------|
| `namespace` | TEXT NOT NULL | e.g. `regime_hmm`, `timeframe` |
| `code` | TEXT NOT NULL | e.g. `trending_up`, `5m` |
| PK | `(namespace, code)` | |
| `label` | TEXT NOT NULL | Human-readable display label |
| `description` | TEXT | |
| `sort_order` | INT NOT NULL DEFAULT 0 | Display ordering |
| `is_deprecated` | BOOLEAN NOT NULL DEFAULT FALSE | Retired code, kept for historical row compatibility |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

**`vocabulary_group`** — named groupings within a namespace (e.g. `regime_hmm/trending` grouping `trending_up` + `trending_down`).

| Column | Type | Description |
|--------|------|--------------|
| `namespace` | TEXT NOT NULL | |
| `group_name` | TEXT NOT NULL | |
| PK | `(namespace, group_name)` | |
| `label`, `description`, `sort_order` | | Same shape as above |

**`vocabulary_group_member`** — join table; a code may belong to more than one group in the same namespace (e.g. `regime_hmm/trending_up` belongs to both `trending` and `bullish_bias`), which is why this is a join table rather than a `parent_code` column.

| Column | Type | Description |
|--------|------|--------------|
| `namespace`, `group_name`, `code` | TEXT NOT NULL | Composite PK |
| FK | `(namespace, code)` → `controlled_vocabulary`, `(namespace, group_name)` → `vocabulary_group` | Referential integrity — a membership row can never reference a code or group that doesn't exist |

### Live namespaces (7, per D-01/D-03/D-04/D-04b)

| Namespace | Live codes | Source column it governs |
|-----------|-----------|----------------------------|
| `regime_hmm` | 5 | `feature_vectors.regime` |
| `regime_volatility` | 3 | `feature_vectors.regime_volatility` (`calm`/`elevated`/`turbulent`, K=3, migration 307, Phase 172) |
| `regime_cross_sectional_equity` | 9 | `market_regimes.regime_label` (`regime_group='equity'`) |
| `regime_cross_sectional_rates` | 6 | `market_regimes.regime_label` (`regime_group='rates'`) |
| `timeframe` | 5 | `market_data_ohlcv_tradeable.timeframe` |
| `asset_class` | 3 | `instruments.contract_details->>'asset_class'` |
| `tier` | — | `concept_registry.metadata->>'tier'` (`domain='feature'`) |

Archived-SLA namespaces (`signal_outcome`, `entry_type`, `signal_status`, `session_type`) were explicitly deferred at build time — not seeded, since the tables they'd govern are themselves archived (v2.x, no live consumer).

---

## `VocabularyService` — read side

`src/config/vocabulary_service.py`. Mirrors `ConfigService` exactly: fully cached at `initialize()` (one prewarm `SELECT` per table, ~100 rows total across all namespaces), zero DB calls on the hot path, embedded as a library by any consumer — not a network service, not a new DAG node.

```python
vocab = VocabularyService(db_dsn, pool=pool)
await vocab.initialize()          # one-time prewarm

vocab.codes("timeframe")          # ['1m', '5m', '15m', '1h', '1d']
vocab.active_codes("timeframe")   # same, minus is_deprecated=true rows
vocab.label("regime_hmm", "trending_up")   # falls back to the code itself if unknown
vocab.group_codes("regime_hmm", "trending")  # frozenset() if unknown group
vocab.known_namespaces()          # frozenset of every namespace with >=1 cached code
```

No lazy miss-then-fetch fallback — the corpus is small (~100 rows total) and the design mandates zero hot-path DB calls, so a cache miss is answered from memory (fallback to the raw code/group name), never a DB round-trip.

The three vocabulary tables are **written only at migration time** — `VocabularyService` is a pure read-side projection, never a writer.

---

## `VocabularyDriftAuditor` — write-adjacent monitoring

`src/config/vocabulary_drift.py` — a `BaseBatch` oneshot, **not on a systemd timer**; chained as a non-blocking step into `scripts/ops/corpus/ops_corpus_pipeline_run.sh` after `alpha_publisher` (line ~389).

For each namespace, it queries the live source column for distinct observed codes over a recent window (`infra.vocabulary_drift.window_days`, APR-sourced, default 30) and diffs against `VocabularyService`'s registered set. Any observed code the registry doesn't know about is a **data-superset drift** — logged as an error, counted via the `vocabulary_drift_unregistered_total` OTel counter, and recorded as an `integrity_monitor` fact (`monitor_type='vocabulary_drift'`).

```
observed codes (live column, recent window)  −  registered codes (VocabularyService)
                                    │
                          non-empty difference?
                                    │
                    yes → loud error + integrity_monitor fact + OTel counter
                    no  → clean, integrity_monitor fact still recorded (passed=true)
```

**Guards against two specific false-positive shapes:**
- **Source-idle ≠ mass deprecation.** An empty observed set (no rows in the window) is skipped entirely, never misread as "every registered code just got deprecated."
- **Namespace-query drift.** `assert_namespace_coverage()` fails loud at startup if this module's own hardcoded per-namespace query dict falls out of sync with what `VocabularyService` actually has cached — catches a namespace silently dropped from checking, or one whose registered codes went stale.

There is also a standalone **`regime_group` guard** (not a `controlled_vocabulary` namespace itself): it checks `market_regimes.regime_group` values against the hardcoded `{'equity', 'rates'}` set, to catch a future third cross-sectional regime group appearing before either `regime_cross_sectional_*` namespace was extended to cover it.

**Observability-only, never a hard gate** — a detected drift never fails the pipeline run; only a genuine runtime error (DB unreachable, etc.) propagates as a real failure.

---

## API surface

`src/api/routes/vocabulary.py` — read-only HTTP endpoint, `GET /{namespace}` (mounted under the vocabulary router), returning codes/labels/groups for a namespace. Lets any external consumer (dashboard, external tool) enumerate a namespace without importing Python or hardcoding labels. Unknown namespace → 404 (not an empty 200 or raw SQL error); genuine backend failure → 503. Not a dashboard/UI in itself — a data endpoint a UI would consume.

---

## When to Add a New Namespace (D-06 / D-07)

A namespace earns its place in CVR when **either** path holds.

**D-06 — external consumer path.** All three:

1. **Membership is mutable** — the code set can change without a code deployment.
2. **External consumers need enumeration without importing Python** — e.g. a dashboard dropdown, an API caller.
3. **Metadata enrichment has real, concrete consumers** — labels/descriptions/groups are actually read somewhere, not speculative.

**D-07 — scattered-duplicate path (added 2026-08-15, todo 324/326).** A fixed code set independently hardcoded in **2 or more files** qualifies on its own, even with zero external (non-Python) consumers and even with zero metadata enrichment need. Per-namespace marginal cost is already near-zero (one migration row + `VocabularyService`'s existing cache — no new infrastructure), so "duplicated in ≥2 files" is cheap enough to be a sufficient condition by itself, not just a nice-to-have alongside D-06. This closes a real gap D-06 alone missed: self-drift *among Python-only consumers*, not just live-column vs. registry drift. Confirmed non-speculative on namespaces CVR already owns:
   - `timeframe` (5 live codes, `VocabularyService` + API route already built) has **9 independently-hardcoded tuples** across the repo, two of them named identically (`_STANDARD_TFS` in `src/core/bar_history.py`, 4 values, vs. `src/intelligence/pipeline/feature_pipeline_executor.py`, 6 values — same name, different truth, in two live modules) — nobody reads the registry.
   - `asset_class` (3 live codes: `equity`/`futures`/`fx`) is hardcoded as `Literal["equity", "futures", "fx", "crypto"]` in `src/api/routes/instruments.py` (two call sites, served by the live `indicagent-api.service`) — a fourth value that exists nowhere in the registry or `get_active_contracts()`. The API type has already drifted from the source of truth it's supposed to mirror.

**Still not worth it** for a fixed set that appears in exactly one file and no consumer enumerates externally — a private internal `Literal["a", "b"]` used once doesn't need a CVR namespace just because it's a set of strings. The bar is duplication or external enumeration, not "it's a list."

---

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|-----------------|-----|
| Confidence-weighted, falsifiable instrument classification | [ITR](instrument-tag-registry.md) (`instrument_tags`) | A different epistemic kind of row — hypothesis with evidence, not a fixed definition |
| Tunable numeric values | APR (`config_state`) | CVR governs symbolic codes, not numbers |
| Archived-SLA vocabulary (`signal_outcome`, `entry_type`, `signal_status`, `session_type`) | Not seeded anywhere live | The tables these would govern are v2.x, archived, no live consumer |
| Evidence-gated research artifact lifecycle (features, ensemble strategies, HMM variants) | Concept Registry (`concept_registry`) | A different registry type entirely — see [Concept Governance Registries](../research/concept-governance-registries.md) |

---

## Related Docs

- `docs/foundation/adaptive-parameter-registry.md` — sibling registry (Type 1, tunable numbers) this doc's structure mirrors.
- `docs/foundation/instrument-tag-registry.md` — sibling registry (falsifiable instrument classification); read the D-02 note above for why the two are deliberately not merged.
- `docs/research/concept-controlled-vocabulary.md` — original Phase 161 design doc (staging order, enforcement-design review history). Design history now — this doc is canonical for current-state architecture.
- `docs/research/concept-governance-registries.md` — umbrella index across all registry types (stale as of this writing on Type 2/3 status — see that doc's own drift).
