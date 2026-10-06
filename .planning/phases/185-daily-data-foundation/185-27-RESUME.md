# 185-27 resume note (paused 2026-10-06 at the owner's request)

## Done
- Task 1: 1ffc77f06 (RED tests), 56e8158e3 (migration 441 applied live and committed, `CANONICAL_1D_SOURCES`/`TRADIER_RULE_VERSION`, `write_1d_digests`, D2 digests after its scrub).
- Task 2: 3b7e8363b (RED tests), 32842eaac (loader: D1 elision, new/changed-only upsert, tradier-v1 lineage, tradier batch, scrub, digests).
- The live three-name run (SPY, AAPL, XOM) completed: batch 661780d4-27a0-4cd1-a977-1ab30ea001a7, 20,187 lineage rows, 966 digest rows, 0 D1 observations landed, acceptance query 0.
- The full unit suite passed (`-x`, exit 0). 185-27-SUMMARY.md is written and committed with this note.

## State
- Nothing half-applied. Migration 441 is live and committed. There are no uncommitted files of this plan.
- Other sessions' files in the tree that must not be touched: `docs/research/construction-verdict-ledger.md`, `docs/ideas/signal-credit-put-reverse-diagonal.md`, `evidence/`, and phase 189's `deferred-items.md`.

## Exact next step
1. Tick `- [ ] 185-27-PLAN.md` to `- [x]` in `.planning/ROADMAP.md` (line 243): copy it to scratch, edit, copy back, then commit with an explicit pathspec. Do not touch STATE.md.
2. Delete this RESUME file in the same commit (`git rm` on this path only).
3. Do not push.
