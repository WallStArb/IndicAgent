---
phase: 172
reviewers: [codex]
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

Note: `review.default_reviewers` is configured to `["codex"]`, so this run used Codex only.
Antigravity and Ollama were detected as available but not invoked (not in the configured
reviewer set); Claude was skipped for independence (this session runs inside Claude Code CLI).

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

## Consensus Summary

Only one reviewer (Codex) was invoked this run, so there is no cross-model agreement to
synthesize. Treat the findings below as single-source until a second reviewer is added.

### Notable findings (single-reviewer)
- 172-01's symbol-sampling procedure lacks a deterministic tie-break rule (HIGH) — two runs
  of the "stratified 25-30 symbol" query could pick different symbols.
- Vintage separation between the retired trend vocabulary and the new volatility vocabulary
  in `feature_ic_scores.regime_scope='symbol_hmm'` rests on the two label sets being disjoint
  strings rather than a first-class column (HIGH) — matches a decision 172-06/172-RESEARCH.md
  already made deliberately (no new `regime_scope` value), so this is a known and accepted
  tradeoff, not an oversight, but Codex is right that downstream queries need to get this right
  every time.
- No explicit operational stop/resume contract between 172-05 (corpus relabel) and 172-06
  (ic_engine cutover) beyond the coverage JSON succeeding (HIGH) — worth a one-line operational
  rule before executing wave 4.

### Divergent views
N/A — single reviewer.

To incorporate feedback into planning:
  /gsd-plan-phase 172 --reviews
