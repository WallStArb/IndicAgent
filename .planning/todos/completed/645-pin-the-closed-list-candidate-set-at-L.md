---
status: completed
priority: P2
filed: 2026-11-19
source: independent review of the closed-list build (todo 609, preregistration Amendment 2026-11-18)
owner: lead
---

# Pin the closed list's candidate set at L so a later pit install cannot add a name

## What

The closed-list rule reads each month-end after L = 2026-11-09 from the list at L: a symbol is a candidate when `_TYPES_SQL` finds a snapshot row at L whose ticker a live `ticker_event` span places on that day. Nothing in code enforces that the set stays what it was when the first closed-list month was built. The one-time pit install is non-additive today, so an install or a manual `ticker_event` write after L that adds or moves a span covering L would put a new symbol into the candidate set silently, and a new entrant would pass the "no entrant" rule. `ticker_event.recorded_at` cannot pin it, because the install itself is recorded after L.

## Proposed enforcement

1. A pre-registered constant beside `LAST_LIST_DATE`: `CLOSED_LIST_CANDIDATES_SHA256`, the sha256 of the sorted `symbol|type` lines the list at L yields (the writer's `types[L]` after eligibility), computed once from the first closed-list build and committed in a dated amendment line, not an APR key.
2. The writer, before it writes any month after L, recomputes that digest from `_TYPES_SQL` at L and refuses on a mismatch ("the candidate set at L moved since it was pinned").
3. A test that builds a synthetic list at L, pins its digest, then adds a symbol and expects the refusal; and a test that the pinned constant equals the digest of the live set (a read-only check in the s6 style report), so drift shows before a book freeze.
4. The membership report prints the digest next to the closed-list month count.

## Done when

The constant is pinned from the first closed-list build, the refusal and both tests exist, the report prints the digest, and the amendment line recording the pin is in the preregistration.

## Landed 2026-11-20

`CLOSED_LIST_CANDIDATES_SHA256` (`src/intelligence/universe_membership.py`, beside `LAST_LIST_DATE`) pins the digest of the 13,103 `symbol|type` lines the list at L places, read from the data on 2026-11-20 before any closed-list month was built (`e13546aa78be46026b204ea5de46cbd09a181c177f6a14cc206cbbeaf3b1b29c`; types ETF 5,555, CS 5,182, WARRANT 423, PFD 414, ADRC 378, FUND 330, UNIT 302, SP 154, others). The writer refuses, writing nothing, a month after L when the live set no longer hashes to it; the membership report prints both digests and the closed-list month count and exits 2 on a mismatch (read-only, run before a book freeze); tests cover the digest, the refusal with nothing written, and the report line. The amendment line is in the preregistration (Amendment 2026-11-20).

