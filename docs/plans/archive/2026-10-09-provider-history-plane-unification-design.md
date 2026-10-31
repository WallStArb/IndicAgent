# Provider history plane unification: one fetcher, N leaves, policy at the capture layer

Original: 2026-10-09 (approved; superseded in part 2026-10-27 by D-191-Q / D-191-P).
Archived 2026-10-31: landed design, kept for the architecture rule.

Rule worth keeping: adding a vendor is a new leaf module, policy rows and APR seeds; zero new
services, write paths or ledger machinery. Everything provider-specific stays in the leaf and
per-provider planner data, never in the loop (IBKR's single-connection semantics, Alpaca's
REST rate limits and no-data handling). The phase 189 design excluded a provider abstraction
as YAGNI; that exclusion's condition (no second OHLCV vendor) went false when Alpaca was
admitted, which is the general lesson about conditional YAGNI calls.

Live artifacts: the fetcher under scripts/infrastructure/backfill/; provider matrix in
docs/foundation/canonical-truth-registry.md.
Full text in git history at docs/plans/2026-10-09-provider-history-plane-unification-design.md as of 708f3fe09.
