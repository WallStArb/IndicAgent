# 324 - Gradient Scale Vocabulary (naming-system.md §7) has zero CI/pre-commit enforcement

**Filed:** 2026-08-15
**Source:** User Q&A session tracing whether the fast/mid/slow gradient-naming convention used
across Feature Factory primitives (`rsi_fast/mid/slow`, `momentum_z_fast/mid/slow`,
`bars_since_high_fast/slow`, etc.) is tracked in any of the project's governed registries
(APR/ITR/CVR/UCR).

## What's confirmed

- The gradient vocabulary table lives only as prose in `docs/foundation/naming-system.md §7`
  (two tables: generic scales `fast/mid/slow`, `low/mid/high`, `primary/secondary`; domain-specific
  scales `steep/flat/inverted`, `contango/neutral/backwardation`, `tight/wide`, `strong/weak`,
  `risk_on/risk_off`, `calm/elevated/turbulent`).
- It is genuinely widely used in `src/intelligence/schemas.py` — not a paper convention, real
  adoption across momentum/RSI/CCI/aroon/breakout-distance/variance-ratio/bb_pct_b/etc. primitives.
- `docs/foundation/naming-system.md §9` documents 5 "CI Enforcement" checks as bash/grep snippets,
  including Check 2 (Banned Code Abbreviations) and Check 5 (Segment Count) — but the doc's own
  text admits these are "advisory pre-checks" only, and explicitly says durable enforcement would
  need "an AST-based Python linter... Extract the taxonomy YAML block in Section 3 into a
  standalone `taxonomy.yaml`." That extraction/linter was never built.
- Checked `.github/workflows/ci.yml` directly: only **Check 3 (Ring 0 boundary)** plus plugin
  class/file naming guards are actually wired into CI. Checks 1, 2, 4, 5 from the doc — and
  nothing at all for §7's gradient-term whitelist — exist nowhere in CI, pre-commit, or
  `tests/unit/`.
- Checked whether §7 belongs in CVR instead (`controlled_vocabulary` table currently has 7
  namespaces: `asset_class`, `regime_cross_sectional_equity/rates`, `regime_hmm`,
  `regime_volatility`, `tier`, `timeframe`) — **revised conclusion, see below.** Initial pass
  concluded no (CVR governs codes emitted by live data columns, audited by
  `VocabularyDriftAuditor` against runtime values; gradient vocab governs identifier-naming
  grammar, a static source-code concern). User pushback correctly identified the fix: CVR's D-06
  admission test requires a *real consumer* reading the registry instead of a hardcoded/scattered
  copy — and wiring the CI enforcement check (and any future "what term for an N-level scale"
  lookup) to actually query CVR, rather than grep prose or a bespoke YAML, **is** that consumer.
  That satisfies D-06 non-speculatively. Confirmed: no conflict with CVR's "definitional, not
  falsifiable" contract (gradient terms are fixed vocabulary, same shape as every existing
  namespace) — the earlier "different kind of check" objection was about the *drift-audit*
  feature specifically (which genuinely doesn't apply here — no live data column to diff), not
  about CVR's core namespace/code/group storage, which fits cleanly.

## Fix — CVR `gradient_scale` namespace (final, revised again 2026-08-15 under D-07)

Went through three passes on this. Pass 1: CVR namespace. Pass 2 (design-rigor pass): reversed to
a minimal standalone Ring 0 module, reasoning that no external non-Python consumer existed
(D-06's 3-criterion test) and a CVR namespace would need a silent carve-out in
`VocabularyDriftAuditor`'s coverage check. Pass 3 (this one): reversed back to CVR after user
pushback ("CVR really should be a cheap single source of truth for lists — we have many scattered
throughout") prompted a grep for concrete evidence rather than reasoning about it in the
abstract. That grep found real, live, already-drifted scatter in namespaces CVR *already owns* —
`timeframe` has 9 independently-hardcoded tuples across the repo (two named identically with
different values — see todo 326), and `asset_class`'s API-layer `Literal` already includes a
`"crypto"` value the registry has never had. Two Python-only consumers drifting from each other,
zero live-data-column involved — a failure shape D-06 didn't account for.

This is now codified as **D-07** in `docs/foundation/controlled-vocabulary-registry.md`: a code
set hardcoded independently in ≥2 files qualifies for a CVR namespace on its own, without needing
D-06's external-consumer/metadata-enrichment tests, because the per-namespace marginal cost is
already near-zero (one migration row + `VocabularyService`'s existing cache, no new
infrastructure). Gradient vocabulary clears D-07 today, not speculatively: it's authored once in
naming-system.md §7 prose *and* will be read a second time by the CI check itself — that's
already 2 independent surfaces before a single new column is written, with the exact drift risk
(prose table silently diverging from what the CI check actually enforces) D-07 exists to close.

**The `VocabularyDriftAuditor` carve-out objection from Pass 2 is real but not disqualifying** —
fix it directly rather than avoiding CVR: add an explicit `has_live_source: bool` distinction (or
equivalent) to `assert_namespace_coverage()` so a D-07-admitted namespace with no live column is a
documented, checked category, not a silent gap next to the 7 D-06 namespaces. That's a small,
one-time addition to the auditor, not a reason to keep gradient vocab out of the registry it
belongs in.

**Fix (CVR route, restored):**

1. Migration adding `gradient_scale` namespace + groups per the design below.
2. `assert_namespace_coverage()` gets the `has_live_source` (or equivalent) distinction so
   D-07-admitted namespaces are an explicit, checked category rather than an implicit gap.
3. naming-system.md §7's prose tables render from / are cross-checked against
   `vocab.group_codes("gradient_scale", ...)` (doc-gen script or round-trip test), not
   hand-maintained duplicate text.
4. A CI/pre-commit check (same shape as the existing Ring 0 boundary guard in `ci.yml`) reads the
   namespace via `VocabularyService` and walks `FeatureVector` field names in
   `src/intelligence/schemas.py` plus APR key strings in `config_schema` migrations for a
   trailing `_<term>` scale-qualifier segment, failing the build if `<term>` isn't registered.
   (A cached, embedded `VocabularyService` read at CI-lint time has the same zero-hot-path-DB-call
   property as every other CVR consumer — Postgres availability at CI time is a real dependency
   either way once the check needs live migration state to catch newly-added terms; no worse than
   any other CI step that runs migrations first.)

Today nothing stops a column named `momentum_z_near` or `rsi_ultra_short` from merging clean.

---

### Design: CVR `gradient_scale` namespace (unchanged from original design pass)

Reusing `vocabulary_group`/`vocabulary_group_member` (already supports a code belonging to >1
group — needed since e.g. `mid` is shared across `speed_horizon_3` and `magnitude_intensity`):

- **Namespace:** `gradient_scale`. **Codes:** `fast`, `mid`, `slow`, `extended`, `low`, `high`,
  `primary`, `secondary`, `steep`, `flat`, `inverted`, `contango`, `neutral`, `backwardation`,
  `tight`, `wide`, `strong`, `weak`, `risk_on`, `risk_off`, `calm`, `elevated`, `turbulent`.
- **Groups** (one per scale family from naming-system.md §7): `speed_horizon_2` → `{fast, slow}`,
  `speed_horizon_3` → `{fast, mid, slow}`, `speed_horizon_4` → `{fast, mid, slow, extended}`,
  `magnitude_intensity` → `{low, mid, high}`, `rank_quality` → `{primary, secondary}`, plus one
  group per domain-specific scale (`curve_shape`, `term_structure_shape`, `credit_spread_state`,
  `currency_strength`, `risk_sentiment`, `volatility_state`).
- **Lookup workflow:** "what term set for a 3-level scale?" → `vocab.group_codes("gradient_scale",
  "speed_horizon_3")`, sorted by `sort_order`.
