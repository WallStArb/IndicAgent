---
phase: 172
reviewers: [codex, antigravity]
reviewed_at: 2026-08-09T09:38:08Z
plans_reviewed:
  - 172-01-PLAN.md
  - 172-02-PLAN.md
  - 172-03-PLAN.md
  - 172-04-PLAN.md
  - 172-05-PLAN.md
  - 172-06-PLAN.md
  - 172-07-PLAN.md
---

# Cross-AI Plan Review — Phase 172

First pass used Codex only (`review.default_reviewers` was `["codex"]` at the time). A
follow-up pass added Antigravity via explicit `--agy`/`--antigravity` flag; `review.default_reviewers`
has since been updated to `["codex", "antigravity"]` so future no-flag runs cover both. Claude
was skipped for independence (this session runs inside Claude Code CLI).

## Codex Review

**Summary**
The plan set is strong on sequencing, evidence capture, and rollback-free safety checks. It correctly treats the volatility cutover as a gated, measured migration rather than a simple rename, and it separates schema, pure functions, runtime wiring, corpus relabeling, and downstream consumers into distinct waves. The main risk is not design intent but coordination density: many steps depend on subtle invariants like label ordering, scope semantics, and evidence queries staying aligned across files. That makes the phase workable, but operationally high risk.

**Strengths**
- The wave ordering is sensible: measure first, seed schema next, build pure functions, wire runtime, relabel corpus, then update downstream consumers and docs.
- 172-01 correctly uses a null-arm gate before any corpus mutation, which is the right place to force a GO/NO-GO decision.
- 172-02 and 172-04 explicitly protect the legacy `regime` path while adding `regime_volatility`, which reduces the chance of a mixed-method corpus.
- The plans are very explicit about provenance, idempotency, and evidence artifacts, which makes later review and rollback analysis feasible.
- 172-03 and 172-04 include tests aimed at the most failure-prone part of the refactor, the mapping between state order, vocabulary, and emitted row tuples.
- 172-05 treats corpus relabeling as staged, measurable work with per-cell accounting, which is the right posture for an expensive irreversible operation.
- 172-06 and 172-07 do not assume downstream consumers are unaffected, they audit and pin behavior with real query output and regression tests.
- The glossary rewrite is not cosmetic, it is tied to the actual shipped vocabulary and includes safeguards against stale terminology reappearing.

**Concerns**
- **HIGH** 172-01 does not fully specify a deterministic sampling algorithm for the 25-30 symbol set, only the sampling constraints. Without an exact tie-break rule, two executions can produce different samples even if they satisfy the same proportions.
- **HIGH** 172-05, 172-06, and 172-07 all rely on `regime_scope = symbol_hmm` continuing to mean "per-symbol HMM", while vintage separation is inferred from the label string. That is valid, but it is also easy to query incorrectly later. The plans should be more explicit about how evidence and downstream checks prevent vintage mixing.
- **HIGH** 172-05 is a full corpus relabel after a launcher gate change in 172-06. If the relabel is interrupted or only partially complete, the system can become operationally blocked until the corpus is finished. The plan needs a clearer operational stop condition or rollback posture between the relabel and the gate cutover.
- **MEDIUM** 172-03 and 172-04 depend on very subtle ordering contracts, especially the mapping from low/mid/high state groups into probability columns and row tuples. The unit tests are good, but there is still a real risk of a silent inversion that synthetic tests might miss.
- **MEDIUM** 172-04 changes the CLI contract and the worker tuple shape, which is a broad surface area change. The plan covers known call sites, but it assumes there are no other internal callers or ad hoc wrappers outside the listed tests.
- **MEDIUM** 172-07 only runs a scoped `ic_engine --refresh` on three symbols at one timeframe. That is a useful smoke test, but it is not a strong end-to-end proof for the whole relabeled corpus.
- **MEDIUM** 172-02 explicitly leaves the legacy probability-columns-in-training-matrix issue unresolved. It is documented and ticketed, but it is still a known leak in the feature pipeline while this phase is changing adjacent machinery.
- **LOW** Several tasks rely on grep-based verification of strings in comments or SQL. That is useful for auditability, but it is weaker than a structural test and can miss behavior changes that preserve the searched text.

**Suggestions**
- Add an explicit, deterministic sampling procedure for 172-01, including the sort key used to select the final 30 symbols when more qualify.
- Split the 172-05 evidence JSON into separate sections for `symbol_hmm` and `cross_sectional` rows, so vintage separation is proven mechanically instead of inferred from mixed-query output.
- Add one small end-to-end synthetic test that exercises the full volatility path from label map to row tuple, not just the individual helpers. That would catch state-order inversions between 172-03 and 172-04.
- Make the 172-05 and 172-06 transition gate explicit in operational terms, for example a written "do not start 172-06 until relabel coverage JSON and post-relabel verification both pass" rule.
- Broaden the 172-07 scoped refresh slightly, or clearly label it as a smoke test in the plan and keep a follow-on full-scope verification item separate.
- Add one regression test or lint rule that rejects stale glossary references to `feature_vectors.regime` as a current-state source in docs, not just in code.
- For 172-04, consider adding a dedicated test for the CLI dispatch table itself, so any future family addition or argument threading bug is caught early.
- For 172-02 and 172-06, keep the known legacy leak and vintage-separation assumptions in a short operational note, so the next phase does not re-derive them from planning prose.

**Risk Assessment**
High.

The plans are well designed, but the phase combines schema migration, model-path refactoring, corpus relabeling, downstream consumer cutover, and canonical documentation updates. Those are all individually risky, and here they are intentionally chained. The guardrails are strong, especially the null-arm gate and the staged relabel, but the number of moving parts and the potential for silent label/vintage confusion make this a high-risk execution plan even if the logic is sound.

---

## Antigravity Review

### 1. Summary
The Phase 172 implementation plan is a highly disciplined, scientifically-gated, and well-structured design to migrate the per-symbol HMM regime labeling from a 5-column composite model to a standalone 2-column volatility-only model (`regime_volatility`). The plans are logically partitioned across 5 waves of execution, starting with a crucial wider-scope empirical validation (null-arm scrambled-data block-reliability check) before any database mutations are executed. By maintaining the legacy `regime` column and trend vocabulary side-by-side with the new `regime_volatility` column, the design ensures a phased, backward-compatible cutover that minimizes risk to in-flight real-time pipelines. Downstream integrations (the IC Engine and the Ensemble Trainer) are handled carefully, ensuring that the new column family is properly excluded from the ensemble training matrix and validated step-by-step.

### 2. Strengths
- **Empirical Scientific Gating:** Gating the entire phase's database mutation and corpus relabel (Plan 172-05) on a wider-scope null-arm block-reliability control (Plan 172-01) at 5m/15m timeframes ensures that the model is only shipped if it demonstrates real predictive structure over noise.
- **Corpus-Scale Data Integrity Guards:** Preventing silent corruption by immediately updating `feature_vector_persistence.py` (preventing `--refresh` from NULLing out new columns) and `ensemble_trainer.py` (excluding new volatility columns from the training feature matrix via `_META_COLS`) in the same wave as the DDL migration prevents windows of vulnerability.
- **Non-Destructive Phased Cutover:** Allowing the legacy `regime` column and its associated trend vocabulary to coexist alongside the new `regime_volatility` column protects backward compatibility and prevents disruption to the live execution pipelines.
- **Operational Churn & Error Handling:** The walk-forward compute paths explicitly map and log skipped or degenerate segments with volatility-specific names (e.g., `regime_writer.volatility_walk_forward_insufficient_warmup`), making it easy to monitor failure rates.
- **Staged Incremental Relabeling:** The corpus relabeling (Plan 172-05) is divided into 3 controlled stages (single cell SPY 1d → validated symbol sample → full corpus) rather than a single massive query, bounding the lock time and operational blast radius on the TimescaleDB hypertable.

### 3. Concerns
- **LOW — Zero-padding warmup artifact in `vol_of_vol`.** In `_build_obs_matrix_volatility` (Plan 172-03), the warmup start index is `valid_start = max(vol_window, vol_of_vol_window) - 1`. But `vol_of_vol` is a rolling std of `realized_vol`, which is itself zero-padded for its first `vol_window - 1` bars. So the first `vol_window - 1` bars of the emitted `vol_of_vol` column still have zero-padded values inside their own rolling window, i.e. lookback distortion baked into "valid" output. The mathematically clean start index for a nested rolling operation is `vol_window + vol_of_vol_window - 2`, not `max(vol_window, vol_of_vol_window) - 1`. This exact pattern already exists in the legacy `_build_obs_matrix` and 172-03 explicitly mirrors it, so it is not a new bug introduced by this phase, but the plan doesn't call it out anywhere and it is worth a one-line code comment or an actual fix.
- **LOW — Fragility of positional tuple unpacking.** Plan 172-04 appends `regime_column` as a 20th positional element to the `_run_symbol_worker` args tuple. Long positional tuples to multiprocessing workers are fragile and prone to silent index mismatches under future edits.
- **LOW — Compute overhead on high-frequency data.** The null-arm validation sweep (172-01) fits HMMs across ~30 symbols × 4 timeframes × multiple windows × K values, including 5m/15m at ~20,000 bars/symbol. This could run for hours; worth sizing/timeboxing explicitly rather than discovering it live.

### 4. Suggestions
- Refactor `_run_symbol_worker`'s positional argument tuple into a dataclass/dict so future parameter additions can't silently shift positions.
- Either compute the volatility warmup start as `vol_window + vol_of_vol_window - 2`, or add an explicit code comment in `_build_obs_matrix_volatility` documenting that the zero-padded-prefix artifact is a deliberately preserved legacy behavior, not an oversight.
- Monitor disk usage during Stage 2/3 of the 172-05 relabel: cell-by-cell UPDATEs against compressed TimescaleDB chunks force on-the-fly decompression, which can spike temp disk space before recompression policies run.

### 5. Risk Assessment
**LOW.** The transition is a parallel schema addition, not a destructive overwrite of the legacy `regime` column, so production systems can't break from this alone. The null-arm gate enforces mathematical validity before any database write, the relabel is staged to bound blast radius on the hypertable, and the downstream IC engine / ensemble trainer dependencies are audited and pinned with tests.

---

## Consensus Summary

### Agreed strengths
- Both reviewers rate the wave sequencing highly: null-arm gate before any mutation, schema +
  ownership-exclusion landing in the same wave as the DDL, staged (not single-shot) corpus
  relabel, and downstream consumers audited rather than assumed unaffected.
- Both call out the phased, non-destructive cutover (legacy `regime` untouched, new
  `regime_volatility` added alongside) as the design's strongest safety property.

### Divergent views
- **Overall risk rating disagrees sharply: Codex says HIGH, Antigravity says LOW.** Codex's HIGH
  comes from treating the *number of chained, individually-risky steps* (schema → refactor →
  corpus relabel → downstream cutover → doc rewrite) as the risk surface, regardless of how well
  each step is guarded. Antigravity's LOW comes from evaluating each step's *blast-radius
  containment* (parallel-add not destructive-overwrite, gated, staged, tested) and concluding the
  guardrails neutralize the chain risk. Read this as two different risk models rather than a
  factual disagreement — worth deciding explicitly which lens governs the actual go/no-go call
  before executing wave 3 (172-05, the corpus relabel).
- Codex's top concerns are almost entirely about *process/operational* risk (deterministic
  sampling, vintage-mixing query discipline, relabel/cutover stop conditions). Antigravity's
  concerns are almost entirely *numerical/implementation* risk (a real nested-rolling-window
  warmup artifact in `_build_obs_matrix_volatility`, positional-tuple fragility). The two reviews
  are complementary rather than overlapping — neither reviewer flagged what the other one caught.

### New finding worth acting on
Antigravity's `vol_of_vol` warmup-index finding is real and specific: `valid_start = max(vol_window,
vol_of_vol_window) - 1` (used identically in the legacy `_build_obs_matrix` and copied verbatim
into 172-03's `_build_obs_matrix_volatility`) leaves zero-padded `realized_vol` values inside the
first `vol_window - 1` bars of the emitted `vol_of_vol` column. This is a pre-existing artifact in
the legacy composite path, not something 172-03 introduces, but the plan gives it no acknowledgment.
Cheap to fix (`valid_start = vol_window + vol_of_vol_window - 2`) or cheap to document; worth a
decision before 172-03 executes rather than after.

### Notable findings (from Codex, unresolved single-reviewer items)
- 172-01's symbol-sampling procedure lacks a deterministic tie-break rule — two runs
  of the "stratified 25-30 symbol" query could pick different symbols.
- Vintage separation between the retired trend vocabulary and the new volatility vocabulary
  in `feature_ic_scores.regime_scope='symbol_hmm'` rests on the two label sets being disjoint
  strings rather than a first-class column — matches a decision 172-06/172-RESEARCH.md
  already made deliberately (no new `regime_scope` value), so this is a known and accepted
  tradeoff, not an oversight, but downstream queries need to get this right every time.
- No explicit operational stop/resume contract between 172-05 (corpus relabel) and 172-06
  (ic_engine cutover) beyond the coverage JSON succeeding — worth a one-line operational
  rule before executing wave 4.

To incorporate feedback into planning:
  /gsd-plan-phase 172 --reviews
