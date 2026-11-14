# Data layer catalog and refinements, Massive era (archived)

Date: 2026-11-10 (draft, reviewed once). Archived 2026-11-14.
Outcome: its actions landed or moved. The REST reference capture (R1) is on disk under
`data/massive/reference/` (measured facts in `docs/reference/massive-plan-entitlements.md`); the
stage 2 universe question (R4) was ruled in `docs/plans/2026-11-13-stage2-universe-preregistration.md`;
identity, splits as witness and raw columns (R3, R5, R7) live in the admission design and todo 600;
the filings decision moved to todo 600's open list; per-field reference features (R8) follow the
data adjacency register (`docs/reference/data-adjacency-register.md`).

Ideas kept:
- Capture vendor responses to disk as served (manifest with endpoint, parameters with the key
  stripped, Date header, sha256); a typed table waits for a consumer.
- A reference row carries its domain date, `available_at` with `availability_basis`, and
  `served_at` (the glossary `availability time` entry, not a new convention).
- Point-in-time membership is a population ("listed on date d"), never "has bars in the files".
- Tick data (trades 4.1 TB, quotes 15 TB) is out of scope; a reduce-and-discard copy was rejected
  because a reduced copy can never be recomputed.
- The 5,829 Massive day files match the code calendar exactly, so they are a standing witness for
  historical sessions.

Full text: git history, `docs/plans/2026-11-10-data-layer-catalog-and-refinements.md` as of `59cf3b239`.
