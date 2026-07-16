# `market_data_ohlcv` Active-Bars Boundary: Design

**Date:** 2026-07-16
**Status:** Design — approved by project owner, not yet implemented
**Scope:** Closes todo 035 (stale — its own file list predates Phase 144 and undercounted the
affected sites) and the live bug found while scoping it. Supersedes 035's own two proposed
options with a single decision.
**Author:** Sonnet, this session — synthesized from a live-DB audit of every `market_data_ohlcv`
call site, done in response to discovering `cross_sectional_regime_model.py` (the live Phase 144
cross-sectional regime writer) has zero active-bar filtering.

---

## Problem

`market_data_ohlcv` is a continuous calendar grid: `bar_normalizer.py` inserts flat-OHLC,
zero-volume, `source='synthetic_fill'` placeholder rows to fill weekend/holiday/gap slots so
every `(symbol, timeframe)` has a complete timestamp sequence. Real bars carry
`source='ibkr_named'`. Any compute/measurement consumer that reads raw bars without excluding
`source='synthetic_fill'` is silently mixing fabricated flat prices into its input series.

This has now been independently discovered and patched three times, in three different files,
over three weeks (2026-07-01, 2026-07-07, 2026-07-16 — this session) — each time by a different
person/session finding it fresh, each time as a per-call-site patch rather than a structural fix.
The recurrence is the actual finding here: leaving `market_data_ohlcv` as the default read target
guarantees a 4th, 5th, 6th instance, because nothing about the table's name, schema, or any call
site signals that raw reads are unsafe for compute.

### Full audit result (live DB + full-tree grep, this session)

**Zero filtering at all (broken):**
- `services/cross_sectional_regime_model.py` — live Phase 144 cross-sectional regime writer,
  feeds `market_regimes`, which `ic_engine` stratifies IC on. 82% intraday / 32% daily rows in
  the live corpus are `synthetic_fill`.
- `services/signal_probe_auditor.py` — forward PnL simulation from bars.
- `services/signal_replay_auditor.py` — bar-by-bar signal replay.
- `services/counterfactual_tracker.py` — **two sites**, `_ATR_SEED_SQL` and `_BAR_SCAN_SQL`,
  feeding `alpha_frames`' true-range/MFE/MAE/exit-determination (Phase 142B, capital-relevant).
  A synthetic bar here means `high=low=close=prev_close` → zero true range and a fabricated flat
  price feeding stop/target exit logic.

**Filtered, but with the wrong predicate (`volume > 0` instead of `source != 'synthetic_fill'`):**
- `services/regime_writer.py`
- `services/forward_return_writer.py`
- `services/backfill_feature_factory.py` — 3 query sites

`volume > 0` is the wrong proxy: it also excludes **2,146,462 genuine `ibkr_named` rows** with
real, legitimate zero volume (illiquid periods, no trades in that window) — silently dropping
real data that could contain signal, the opposite of what these sites intended. Confirmed via
live query:

| source | total rows | volume=0 | volume>0 |
|---|---|---|---|
| `synthetic_fill` | 175,403,754 | 175,403,754 | 0 |
| `ibkr_named` | 40,215,094 | 2,146,462 | 38,068,632 |

`source` is nullable in the schema but has 0 NULL rows live today — not guaranteed to stay that
way, so the corrected predicate must handle NULL defensively (see below).

**Correctly left alone (raw grid is the right read for these):**
- `services/equity_regime_model.py` — dead code, Phase 144 rollback path only, not live.
- `src/api/routes/market_data.py` — raw display/API surface, not a measurement input.
- `scripts/ops/pipeline/ops_pipeline_status.py` — monitoring wants the full grid (gaps are the
  signal here, not noise).

**Not yet classified — deferred to a follow-up todo, not this pass:**
`base_provider_agent.py`, `bar_replay_provider.py`, `bar_history_seeder.py`,
`ops_roll_batch.py`, `feature_snapshot_repository.py`, `crowding_proxy_regression.py`,
`debug_bic_k_selection.py`, `debug_lifecycle_replay.py`,
`infrastructure_context_features_writer.py`, `infrastructure_fetch_htf_bars.py`. Each needs a
genuine per-file read (some plausibly want the full grid intentionally — e.g. backfill
completeness checks counting against the calendar target). Rushing 10 judgment calls into this
session risks getting some wrong under the same time pressure that caused the original problem;
better to audit these properly as dedicated follow-up work once the boundary exists for them to
adopt.

## Decision 1 — Mechanism: a Postgres view, not a Python repository

```sql
CREATE VIEW market_data_ohlcv_active AS
SELECT * FROM market_data_ohlcv
WHERE source IS DISTINCT FROM 'synthetic_fill';
```

`IS DISTINCT FROM` rather than `!=`: `source` is nullable; `!=` against a future NULL evaluates
to NULL (false) under three-valued logic and would silently *exclude* a real bar. Cheap
insurance against a failure mode that costs nothing to prevent now.

**Why a view over a Python repository module:** ~22 files touch `market_data_ohlcv` directly,
many outside clean Ring-architecture Python services — ops shell scripts, debug scripts,
potential future Grafana/BI queries. A Python repository class (`fetch_bars()`) only protects
Python callers that choose to use it; a DB view protects every SQL client uniformly, with zero
extra runtime cost (Postgres inlines the view; the existing `idx_ohlcv_symbol_tf_time`
`(symbol, timeframe, timestamp)` index is used identically either way, since neither the old nor
new predicate is separately indexed — both are residual filters over the same index scan). A
repository module on top of the view is not ruled out for future ergonomic DRY reasons, but is
not part of this fix — building one now, before any Python call site has actually found the raw
`WHERE` clause painful, would be speculative infrastructure for a problem the view already
solves.

## Decision 2 — Predicate correction is in scope, not deferred

The already-"fixed" sites (`regime_writer.py`, `forward_return_writer.py`,
`backfill_feature_factory.py`) get their predicate corrected in the same pass, not left on
`volume > 0`. Reasoning: leaving a known-wrong predicate in place while fixing only the
zero-filter sites means shipping a "fix" that everyone will reasonably assume is now correct
everywhere it's applied — a worse outcome than the current honestly-broken state, since it
removes the visible signal (the file being on the audit's "broken" list) that would prompt a
future re-check. Fix it once, correctly, now that the audit has already found and quantified it.

This is a genuine methodology change to historical measurement inputs (2.1M bars re-admitted at
sites that already fed live IC/regime computation) and requires a
`docs/plans/methodology-change-ledger.md` entry, written at implementation time once the exact
before/after row counts per affected `(symbol, tf, regime)` cell are known.

## Decision 3 — Scope for this pass: Tier 1 only

Fix, with tests, in this pass:
`cross_sectional_regime_model.py`, `signal_probe_auditor.py`, `signal_replay_auditor.py`,
`counterfactual_tracker.py` (2 sites), `regime_writer.py`, `forward_return_writer.py`,
`backfill_feature_factory.py` (3 sites) — 7 files, 10 query sites total.

File a new todo for the Tier-2 audit list (10 files, not classified) as a fast-follow — the view
already exists for them once each is reviewed.

## Decision 4 — Prevention: make the wrong path structurally harder, not just documented

A view alone doesn't stop call site #8 — `SELECT * FROM market_data_ohlcv` is still shorter to
type and still compiles. Three layers, cheapest first, no new infrastructure beyond what
already exists in this codebase's own conventions:

1. **CI-enforced allow-list test** — `tests/unit/test_market_data_ohlcv_boundary.py`: grep the
   full tree for raw `FROM market_data_ohlcv\b` (excluding `_active`), assert the hit set exactly
   matches a checked-in allow-list (the "correctly left alone" files above, each with a one-line
   reason). Any new raw-table reference fails CI immediately unless the allow-list is also
   edited — forcing the "why does this need raw access" justification into the diff itself,
   at review time, rather than relying on someone remembering. Same shape of guard as todo 119's
   migration-schema-drift CI check — this project already has the pattern, just apply it here.
2. **One CLAUDE.md line**, same style as the existing `instruments.contract_details->>'asset_class'`
   gotcha: "`market_data_ohlcv` reads for compute/measurement must use `market_data_ohlcv_active`;
   raw access needs a `test_market_data_ohlcv_boundary.py` allow-list entry with a reason."
   Discoverable before the CI check ever has to catch it.
3. **Not doing (deliberately, avoid over-engineering):** no ORM layer, no repository-class
   enforcement, no runtime schema validator. A view + a grep-test + a doc line is the complete
   fix for what is fundamentally a one-predicate problem.

**Considered and deferred, not rejected:** renaming so `market_data_ohlcv` itself becomes the
filtered view and the raw grid gets the marked name (e.g. `market_data_ohlcv_raw`) — this would
make the safe path the *unmarked default*, needing zero vigilance at all, which is the stronger
structural fix. Not done now: renaming a 250-chunk hypertable with ~22 live call sites (writers
included) is a materially bigger, separate migration with its own blast radius and risk profile.
Worth reconsidering once `market_data_ohlcv_active` has been live and proven for a while.

## Implementation notes

- Migration number: 236 (next after 235).
- Corpus-run safety: the in-flight 143.1-07 rebuild has already executed steps 1-4 (including
  `cross_sectional_regime_model.py`) for this cycle — this fix cannot retroactively clean that
  run's regime labels, and doesn't need to; it lands cleanly for the next corpus rebuild. Editing
  these files now does not touch the currently-running `ic_engine` process (step 5) or its DB
  connections.
- TDD per CLAUDE.md's Done-Coding SOP: test each corrected query against a fixture with both
  `source` values before changing the query, confirm it fails on the bug, then fix.
- After implementation: `/simplify` → `/review` → `tests/unit/` green → commit on a feature
  branch → ff-merge to `main`, per CLAUDE.md's SOP.

## References

- `.planning/todos/pending/035-market-ohlcv-active-bars-view.md` — original todo, superseded by
  this design's decisions (close it, don't re-scope it further)
- `docs/reference/gotchas.md`, `src/core/bar_normalizer.py:23,223,239` — `synthetic_fill`
  convention
- `.planning/todos/pending/119-migration-schema-drift-ci-check.md` — same CI-guard pattern
  precedent
- `docs/plans/methodology-change-ledger.md` — entry required at implementation time
