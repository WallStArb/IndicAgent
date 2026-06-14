---
phase: 124
phase_name: Signal Universe Integrity + Cold-Start Hardening
reviewers_invoked: [ollama-nemotron-3-nano:4b, ollama-qwen3.5:4b, codex, antigravity]
reviewers_succeeded: [ollama-nemotron-3-nano:4b (focused scope)]
reviewers_failed: [codex (usage limit until 2026-07-02), antigravity (GUI-only, stdout uncapturable), ollama-qwen3.5:4b (misunderstood task - produced completion summary not review)]
reviewed_at: 2026-06-14T00:00:00Z
plans_reviewed: [124-01, 124-02, 124-04]
plans_not_reviewed_due_to_context_constraints: [124-03, 124-05, 124-06, 124-07]
review_type: plan-markdown
review_caveat: |
  IMPORTANT: This is a SINGLE-REVIEWER result, not a multi-reviewer consensus. Three of four
  invoked reviewers failed (see frontmatter). The one successful review is from a local 4B
  parameter model on a REDUCED scope (3 of 7 plans) because the full 175KB prompt caused the
  small model to abandon the reviewer persona and role-play as the implementer. Treat findings
  as one data point, not independent validation. Recommend re-running this review with codex
  (after 2026-07-02) or claude (from outside the orchestrator) for independent coverage of
  plans 124-03/05/06/07 and full-scope re-review.
---

# Phase 124 Cross-AI Plan Review

## Reviewer Invocation Log

| Reviewer | Invocation | Result |
|----------|-----------|--------|
| antigravity (primary, planned) | `antigravity chat --mode ask -` | FAILED - `antigravity chat` launches a VS Code-fork GUI window and only echoes "Reading from stdin via: <path>" to stdout; the LLM response is not returned to stdout in this headless environment. Not capturable. |
| codex (primary, planned) | `codex exec --skip-git-repo-check -` | FAILED - echoed the prompt back then errored: "You've hit your usage limit ... try again at Jul 2nd, 2026". Hard-blocked until 2026-07-02. |
| ollama nemotron-3-nano:4b (secondary) | full 175KB prompt via `/v1/chat/completions` | PARTIAL - on the full 175KB prompt the 4B model abandoned the reviewer persona and produced an implementation checklist (Wave B executor output), not a review. 0 severity tags. Not usable as-is. |
| ollama nemotron-3-nano:4b (secondary, RETRY) | reduced 59KB focused prompt (plans 124-01/02/04 + CONTEXT) | SUCCESS - genuine, plan-grounded review with severity tags. See review below. |
| ollama qwen3.5:4b (secondary) | full 175KB prompt | FAILED - misunderstood the task; produced a fabricated "124-07 completion summary" with invented fire-rate results (2.1%, 1.8%, etc.) that were never measured. Not a review. |
| coderabbit | (not invoked) | SKIPPED - reviews git diffs, not plan markdown; task scope excluded it. |

**Note on ollama host:** The task specified port `11499`, but the live ollama container is bound to `127.0.0.1:11434`. Reviews were run against 11434. Port 11499 returned no models.

---

## Ollama nemotron-3-nano:4b Review (focused scope: 124-01, 124-02, 124-04)

> Reviewer: nemotron-3-nano:4b, temperature 0.2, system prompt forcing adversarial-staff-engineer persona on a 59KB reduced context (3 highest-risk plans + CONTEXT decisions). Generated 2026-06-14.

**Plan 124-01**
- Strengths: Migration promotes 4 nullable CTF columns, ON CONFLICT guard uses `IS NULL` only, warmup flag runs two passes.
- Concerns:
  - [HIGH] The migration `UPDATE ... WHERE ctf_score IS NULL` may skip compressed TimescaleDB chunks, causing incomplete backfill.
  - [MEDIUM] The migration strips CTF keys from JSONB, but other code may still read CTF from JSONB, creating a dual source of truth.

**Plan 124-02**
- Strengths: trend_following demotes trend_regime to context filter, trigger fires on structural entry, instance consumed, unit tests.
- Concerns:
  - [HIGH] The pullback detection may fire on bars where SMA is still being computed, causing look-ahead bias.
  - [MEDIUM] The consolidation breakout detection may skip compressed TimescaleDB chunks, leading to incomplete backfill.

**Plan 124-04**
- Strengths: pattern_completion demotes confidence to context filter, structural completion trigger, instance consumed, unit tests.
- Concerns:
  - [HIGH] Instance ID collision due to rounding of structural anchor (4 decimal places) causing false deduplication between distinct patterns.
  - [MEDIUM] The trigger uses structural completion (neckline break) but if neckline is rounded, two patterns with the same anchor may be considered the same instance, leading to premature consumption.

---

## Consensus Summary

### Agreed Strengths
(none - only one reviewer; no multi-reviewer agreement is possible)

### Agreed Concerns (highest priority, single-reviewer basis only)
Given only one reviewer succeeded, there is no independent agreement. The following are the single reviewer's HIGH-severity findings, listed for triage but NOT independently corroborated:

1. **[HIGH] TimescaleDB compressed-chunk interaction (124-01 + 124-02)** - The migration UPDATE/backfill and any replay-driven backfill may skip or mishandle compressed chunks, yielding an incomplete or silently-wrong backfill. This is a known TimescaleDB operational risk and should be verified: confirm the migration either decompresses affected chunks first, or operates correctly across compressed row batches.
2. **[HIGH] Look-ahead bias in pullback detection (124-02)** - The trend-following pullback trigger may read a value still being computed on the firing bar (SMA warm-up), which would be a look-ahead / silent-wrong-answer defect. Verify the trigger guards against insufficient SMA history and never uses the current bar's close as an input to a decision to fire on that same bar.
3. **[HIGH] Structural-anchor rounding collision (124-04)** - Pattern instance IDs derived from a 4-decimal-place rounded anchor (neckline) risk false deduplication: two distinct patterns sharing a rounded anchor would be treated as one, dropping the second signal (survivorship-style loss of valid firings). Verify the dedup key is unique per `(symbol, tf, pattern_name, anchor)` AND that anchor precision is sufficient, or add a disambiguating component (e.g. time window).

### Divergent Views
N/A - single reviewer.

### Cross-Plan Concerns (single-reviewer)
- **Dual source of truth after JSONB strip [MEDIUM, 124-01]:** the migration strips CTF keys from the JSONB blob while promoting them to columns, but if any reader still reads CTF from JSONB, the two sources can diverge after the strip. The plan should grep all `ctf_score`/`ctf_confirmed`/`ctf_*` JSONB access paths and confirm every reader is migrated to the columns before the strip.
- **Wave A -> Wave B dependency:** the reviewer did not get scope on 124-01 vs Wave B ordering beyond the 124-01/02 plans. Unverified: whether Wave B plugin rewrites depend on 124-01's column promotion being live, and whether tests can run before 124-01's migration is applied.

### Overall Risk Verdict
**UNDETERMINED (insufficient reviewer coverage).** With 3 of 4 reviewers failed and the lone reviewer covering only 3 of 7 plans via a reduced context, there is no converged verdict. The reviewer's own per-plan risk ratings were not explicitly stated (it omitted the LOW/MEDIUM/HIGH + justification line for each plan despite the instruction). Based on the HIGH findings surfaced, the highest-credibility risks to resolve before execution are the TimescaleDB compressed-chunk backfill correctness (124-01), look-ahead bias in plugin triggers (124-02 and by extension 124-03/05/06), and dedup-key collision risk (124-04). Recommend a follow-up review with codex (post 2026-07-02) or an independent claude run covering the full plan set before marking plans ready to execute.

### Recommended Re-Review Scope
- Plans NOT covered: 124-03 (OFIContinuation), 124-05 (LiquiditySweepReclaim), 124-06 (AnchoredVWAPReversion), 124-07 (D6 fire-rate SQL).
- Re-run with at least one strong independent reviewer (codex after reset, or claude from outside the orchestrator) on the full 7-plan set before execution.
