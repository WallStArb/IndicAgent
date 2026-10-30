# Promotion protocol

**Status:** current (rewritten 2026-10-30; the swarm Path B to kernel Path A protocol, its correlation
gate and `alpha_multiplier_shadow` are gone with the v2.x path, see git history before this commit)

Capital follows proof, in this order. The binding text is `docs/plans/2026-09-26-unified-research-to-production-design.md` section 7.3 and the evidence ledger in `docs/plans/methodology-change-ledger.md` (E15 to E18).

1. Every test goes through the research runner and is counted on its vintage; no bar per attempt.
2. Selection: Romano-Wolf StepM over every attempt on the vintage at family-wise 0.05, attested by a complete StepM null-battery record (`scripts/research/select_books.py` refuses an unattested set).
3. Promotion: within the selection set, only a book with positive net expectation at a conservative cost quantile; the costed construction must itself be an attempt in the set.
4. Confirmation: one pre-declared test of the promoted book on its own unsearched forward span (after `alpha.validation.oos_start`, never earlier than the book's freeze date); a power-dated test more than 3 years out refuses promotion.
5. Then shadow (sealed forward runner), then capital sized on measured net.
