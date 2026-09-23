---
phase: 176
reviewers: [codex]
reviewed_at: 2026-09-23T00:09:38Z
plans_reviewed: [176-01, 176-02, 176-03, 176-04, 176-05, 176-06, 176-07, 176-08]
---

# Cross-AI Plan Review — Phase 176

**Reviewer selection:** project default is `["codex", "antigravity"]` (`.planning/config.json`).
Claude was skipped for independence (this review was run from inside Claude Code).
**Antigravity failed**: `RESOURCE_EXHAUSTED (429): Individual quota reached... Resets in
26h43m58s`, not a prompt/invocation problem (the known `agy -p -` stdin bug was already worked
around via a file-path-pointer prompt + `--dangerously-skip-permissions`, per project memory —
that workaround itself functioned correctly; the account is just out of quota). Re-run
`/gsd-review 176 --antigravity` after 2026-09-24T~03:00 UTC to get the second opinion. This
review proceeds on Codex alone rather than blocking on a 26+ hour external wait.

## Codex Review

## Summary

Overall, these plans are unusually strong: they turn a deceptively small calendar primitive into a full data-governed pipeline change, with schema, APR, concept registry, compute, persistence, IC measurement, consumer isolation, corpus recompute, and final empirical gate all covered. The strongest qualities are the corrected evidence discipline, explicit handling of `ic_engine.py` OOM history, and the insistence that the phase ends on real `feature_ic_scores` rows rather than unit tests. The main risks are operational: plan 176-07/176-08 can run for many hours or days against a live compressed hypertable, and some plans require commits/live DB applies in an "autonomous" workflow that may not fit all execution environments. There are also a few correctness risks around SQL safety, scope naming, feature-count assumptions, and whether the new measurement-only `regime_scope='earnings_season'` stays isolated everywhere.

## Strengths

- The phase goal is actually completed, not merely coded: plan 176-08 requires a real `feature_ic_scores` FDR/walk-forward verdict for both primitives and a conditioning verdict.
- Corrected D-04 evidence is threaded prominently: 1.90x, Welch p=5.05e-05, 67% / 155 of 233, and the old 4.3x / p=1.2e-17 / 81% figures are repeatedly called out as superseded.
- Naming correction to `earnings_season_flag` is well justified and consistently applied.
- The plans respect separation of concerns: feature factory computes, writer persists, IC engine reads persisted values.
- Migration plan catches an important additional issue: `broadcast=true` metadata is mandatory for symbol-invariant features.
- The full site inventory is realistic: dataclass, persistence slice, construction sites, batch/live paths, tests, migrations.
- `ic_engine.py` integration reuses existing pass mechanics rather than inventing a new regime-group concept.
- Cross-sectional path avoids extra DB fetches, which is the right instinct given documented OOM history.
- Consumer isolation is explicitly handled through ensemble eligibility and scope audits.
- Recompute plan includes contention checks, batching, collateral-damage checks, and a covered-scope manifest.

## Concerns

- **HIGH — Plan 176-07 full-corpus `--refresh` is operationally dangerous.** Even with batching, this is a multi-hour or multi-day write workload against `feature_vectors`. The plan has good safeguards, but it still risks lock contention, partial completion, compression side effects, and backfill-status drift.
- **HIGH — Plan 176-08 may be too expensive to treat as a single autonomous task.** Historical `ic_engine` runtimes range from 11h to 76h, with failures. The plan supports resume, but operationally this is closer to a supervised production run than a normal coding task.
- **HIGH — Cross-sectional season subcells may still materially increase memory/runtime.** Skipping `use_disk=True` cells helps, but in-memory cells can still be large. Boolean slicing `X_raw[mask]`, `returns_mat[mask]`, and `complete_mat[mask]` creates copies. The plan deletes them between iterations, but peak memory can still spike.
- **HIGH — `feature_ic_scores` uniqueness not including `regime_scope` is a deeper schema smell.** Parent-qualified labels avoid collision, but this encodes scope into `regime` strings. That works, but it is brittle. A future scope could repeat the same issue.
- **MEDIUM — Plan 176-01 SQL column interpolation needs very explicit implementation guardrails.** The threat model says validate `--feature` and `--return-column`, but the action text should require using `psycopg.sql.Identifier` or strict allow-list interpolation. Otherwise the script invites SQL injection through analysis-only CLI args.
- **MEDIUM — "Commit" requirements may be incompatible with the review/execution model.** Several plans require committing after tasks. Should be explicit whether the executor is allowed to commit, and what to do if the working tree is dirty with unrelated user changes.
- **MEDIUM — Plan 176-03 assumes exact field counts: 298→300 and `_ALL_COLUMN_NAMES` 307→309.** Fragile if another phase lands first. The executor should verify counts dynamically.
- **MEDIUM — `_cold_start_vector(config: FeatureFactoryConfig | None = None)` changes a utility signature.** The plan says there is one caller, but tests or hidden callers may exist — back with grep and a regression test.
- **MEDIUM — `alpha.ic.earnings_season_conditioned` defaulting true adds runtime cost immediately.** Aligns with D-01, but given OOM history, default true is a conscious operational risk.
- **MEDIUM — Plan 176-05 audit could under-patch offline scripts.** "Scope-agnostic because offline" is only acceptable if it cannot later feed a decision.
- **LOW — Plan 176-01 may duplicate production calendar logic** (script-level reference classifier vs. production implementation) — acceptable for re-verification, but can drift over time.
- **LOW — The `days_since_quarter_end` tier choice is debatable** — reasonable given 0.935 correlation with `quarter_position` and the parent-feature partial-IC control mitigation.

## Plan-by-Plan Notes

### 176-01 Evidence Re-Verification
Strong plan — prevents the A1 `up_vol_body_diff` claim from remaining folklore, adds a contention guard, treats blocked as a valid evidence state.
- MEDIUM: require strict SQL identifier handling, not just validation.
- LOW: verdict thresholds (1.7x) are somewhat arbitrary but fixed before measurement, which is the right discipline.
- Suggestions: `--limit-symbols`/`--sample-symbols` for safe dry runs; print exact SQL shape without values; require `return-column` from a fixed known set.

### 176-02 Migration
Very good — catches the `broadcast=true` issue, seeds APR, widens `regime_scope`, self-asserts.
- HIGH: applying DDL to `feature_vectors` needs careful scheduling, even for nullable `ADD COLUMN`.
- MEDIUM: the bogus `feature_ic_scores` insert for constraint testing may be cumbersome if required NOT NULL columns exist.
- Suggestions: `DO` block or temp-table smoke test for constraint rejection if direct insert is awkward; assert `feature.earnings_season.start_days <= end_days` at runtime.

### 176-03 Feature Factory and Persistence
Core implementation plan, mostly excellent — correctly treats the dataclass and persistence slice as one atomic change.
- MEDIUM: exact count assertions may drift; dataclass-field-append vs. persistence-slice-append ordering must be verified carefully.
- LOW: "no literal 14/42" grep may catch harmless docstrings/comments unless precise.
- Suggestions: test production functions against the script reference implementation over a full year of dates, not just boundary cases; add a field-order invariant test.

### 176-04 Per-Symbol IC Engine Conditioning
Good surgical design — deriving labels from the existing feature matrix avoids duplicate fetch, honors SoC.
- MEDIUM: `_FEATURE_NAMES.index("earnings_season_flag")` should fail loudly with a helpful message if migration/code are misaligned.
- MEDIUM: bare `in_season`/`off_season` per-symbol labels share the `regime` column with other scope labels.
- Suggestions: precompute the feature index at import with explanatory failure; test that NaN/None/non-0-1 values never become valid labels.

### 176-05 Consumer Isolation
Necessary and well placed — ensemble eligibility exclusion is a critical guardrail.
- HIGH: the audit must be production-critical, not documentation-only — any consumer that drives promotion/deployment must be patched, not merely recorded.
- MEDIUM: `regime_scope <> 'earnings_season'` vs `IS DISTINCT FROM` — NULL semantics may matter if older rows have NULL scope.
- Suggestions: include saved grep output in the audit file for future reviewer visibility.

### 176-06 Cross-Sectional Conditioning
Good architecture — no new DB fetch, no new regime group, parent-qualified labels, skips disk-backed cells.
- HIGH: memory spike from row slicing remains the largest code-level risk.
- HIGH: `regime_scope` not in the uniqueness key means correctness relies on string qualification — deserves a prominent test and a follow-up schema todo.
- MEDIUM: same RNG instance for primary and season subcells makes results order-sensitive (may be acceptable per existing convention).
- Suggestions: memory telemetry logging (parent rows, in/off rows, `X_raw.nbytes`); file a follow-up todo evaluating `regime_scope` in the uniqueness key.

### 176-07 Corpus Recompute
Thorough and appropriately cautious — collateral-damage checks are a standout strength.
- HIGH: the "every column except..." checksum query may be expensive/tricky on a wide table.
- HIGH: building the symbol list from `instruments.asset_class='equity'` may exclude non-equity ETFs/futures/crypto if `feature_vectors` has broader coverage relevant to this phase.
- MEDIUM: per-symbol batching assumes symbol is the right operational unit; uneven history lengths could imbalance batches.
- MEDIUM: "100% coverage" may be unrealistic if some rows are intentionally malformed/missing `bar_ts`.
- Suggestions: define eligible scope from `feature_vectors`/`backfill_status` directly, not only `instruments.asset_class='equity'`; use a fixed stable-column sample for the checksum if full-row hashing is too costly; record skipped symbols/tfs as an explicit limitation.

### 176-08 Gate Verdict and Closure
The right finish line — prevents "implementation done" from masquerading as "alpha measured."
- HIGH: "large majority compute" dry-run threshold is undefined.
- MEDIUM: the conditioning-verdict rule (pass FDR unconditioned + sharpen in two tfs) is defensible but strict — a real single-tf effect becomes NEUTRAL.
- MEDIUM: closure note must not imply success if the gate FAILs, even though the todo can still close as a measured result.
- Suggestions: define "large majority" numerically (e.g. >80%) before the run; separate "feature shipped" vs "alpha passed" statuses; prominently record `days_since_quarter_end`'s partial-IC result given its 0.935 correlation with `quarter_position`.

## Dependency and Ordering Review

Wave ordering is mostly sound (1: evidence + migration parallel; 2: compute depends on migration; 3: per-symbol IC + ensemble isolation; 4: cross-sectional IC depends on per-symbol helpers + consumer isolation; 5: recompute + final gate). One ordering issue: 176-07 is wave 3 depending only on 176-03, while 176-06 is wave 4 — acceptable since recompute only needs persisted columns, but operationally safer to run 176-07 after 176-04/05/06's unit tests are green, so the expensive recompute doesn't start before the measurement code is known to work.

## Suggestions (Phase-Level)

- Add a phase-level "go/no-go before expensive work" checkpoint after 176-06: migration applied, unit suite green, consumer audit clean, no dirty/uncommitted schema changes.
- Define exact numeric thresholds for ambiguous acceptance criteria ("large majority," "far outside," "runtime delta meaningful").
- Add a follow-up todo to revisit `feature_ic_scores`'s uniqueness key including `regime_scope`.
- Make SQL identifier safety explicit in analysis scripts (176-01).
- Consider whether `alpha.ic.earnings_season_conditioned` should default `false` until after the first controlled IC run, or keep `true` per D-01 with explicit rollback instructions.
- Ensure every place citing D-04 uses only corrected numbers (176-08 already guards STATE.md; verify the rest).

## Risk Assessment

**Overall Risk: HIGH.** Design quality is high, but the operational blast radius is also high — schema changes on a large TimescaleDB hypertable, a full-corpus `--refresh`, `ic_engine.py` changes in OOM-sensitive cross-sectional paths, a scope vocabulary widened for multiple services, and a potentially multi-day IC measurement. The plans mitigate these risks unusually well (pre-flight checks, batching, source-contract tests, consumer isolation, final empirical verdicts), but the combination of live corpus writes plus heavy measurement code makes this a high-risk phase that should be executed deliberately, with checkpoints before plans 176-07 and 176-08.

---

## Consensus Summary

Only one reviewer completed (Antigravity quota-exhausted) — no cross-reviewer consensus to synthesize. Codex's own findings stand on their own; treat "HIGH" items below as the priority list until a second opinion is available:

### Priority findings to act on before execution
1. **176-01 SQL injection guardrail** — cheap, mechanical fix (use `psycopg.sql.Identifier`/strict allow-list, not string interpolation).
2. **176-07/176-08 undefined numeric thresholds** ("large majority," checksum cost, symbol-scope source) — cheap, mechanical fixes (pin numbers, same pattern as the plan-checker's W6 fix).
3. **176-05 audit scope** — clarify "scope-agnostic offline script" only applies to genuinely non-decision-driving scripts.
4. **176-06/176-07 memory and cost risks** — real but harder to fix without live measurement; worth a runtime telemetry addition rather than a design change.
5. **`feature_ic_scores` uniqueness key gap** — real schema smell, correctly scoped as a follow-up todo rather than blocking this phase.

### Deferred (no second reviewer to cross-check)
Re-run `/gsd-review 176 --antigravity` after the quota resets (~2026-09-24T03:00 UTC) for a second opinion before committing to execution, especially given the HIGH-risk operational profile Codex flagged.
