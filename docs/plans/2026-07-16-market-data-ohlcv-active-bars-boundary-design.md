# `market_data_ohlcv` Tradeable-Bars Boundary: Design

**Date:** 2026-07-16
**Status:** Design — approved by project owner, not yet implemented (revised after empirical
recheck of the first draft's predicate assumption — see "What changed" below)
**Scope:** Closes todo 035 (stale — its own file list predates Phase 144 and undercounted the
affected sites) and the live bug found while scoping it.
**Author:** Sonnet, this session — synthesized from a live-DB audit of every `market_data_ohlcv`
call site, done in response to discovering `cross_sectional_regime_model.py` (the live Phase 144
cross-sectional regime writer) has zero tradeable-bar filtering.

---

## What changed from the first draft

The first draft proposed correcting the existing `volume > 0` filter to `source != 'synthetic_fill'`,
reasoning that `volume > 0` was silently dropping 2.1M genuine bars. That reasoning was **not
checked against the actual data** before being written down — an unverified assumption dressed
as a fix. Sampling those 2.1M rows found **2,146,416 of 2,146,462 (99.998%) have
`open = high = low = close`** — flat carry-forward bars IBKR itself returns when no trade occurs
in a window, informationally identical to `synthetic_fill` placeholders despite the different
`source` label. Only 46 rows (0.002%) show any sub-cent intrabar movement. `volume > 0` was
already the correct, sufficient filter; the "predicate correction" is dropped entirely, and the
fix is simpler for it — no `source` column, no nullable-column edge case, one plain `NOT NULL`
integer comparison. Recheck detail in "Problem" below.

## Problem

`market_data_ohlcv` is a continuous calendar grid: `bar_normalizer.py` inserts flat-OHLC,
zero-volume, `source='synthetic_fill'` placeholder rows to fill weekend/holiday/gap slots so
every `(symbol, timeframe)` has a complete timestamp sequence. Any compute/measurement consumer
that reads raw bars without excluding these is silently mixing fabricated flat prices into its
input series.

This has now been independently discovered and patched multiple times, in different files, over
three weeks (2026-07-01, 2026-07-07, 2026-07-16 — this session) — each time by a different
session finding it fresh, each time as a per-call-site patch rather than a structural fix. The
recurrence is the actual finding here: leaving `market_data_ohlcv` as the default read target
guarantees a next instance, because nothing about the table's name, schema, or any call site
signals that raw reads are unsafe for compute.

### Full audit result (live DB + full-tree grep, this session)

**Zero filtering at all — the real bug, fixed in this pass:**
- `services/cross_sectional_regime_model.py` — live Phase 144 cross-sectional regime writer,
  feeds `market_regimes`, which `ic_engine` stratifies IC on. 82% intraday / 32% daily rows in
  the live corpus are `volume=0` (synthetic-fill or flat carry-forward).
- `services/counterfactual_tracker.py` — **two sites**, `_ATR_SEED_SQL` and `_BAR_SCAN_SQL`,
  feeding `alpha_frames`' true-range/MFE/MAE/exit-determination (Phase 142B, capital-relevant).
  A flat bar here means zero true range and a fabricated flat price feeding stop/target exit
  logic.

**Zero filtering, but dead code — not fixed, out of scope:**
- `services/signal_probe_auditor.py`, `services/signal_replay_auditor.py` — both read
  `market_data_ohlcv` unfiltered, but both are v2.x Signal Ledger Architecture code
  (`signal_events`/`trade_frames`/`signal_ledger`), which CLAUDE.md already documents as
  archived with no live consumer since 2026-07-02. Verified, not assumed: neither has a running
  systemd unit (`systemctl list-units --all` returns nothing for either, despite unit files
  existing in `production/systemd/`), and their actual data source — `signal_events` and
  `trade_frames` — has **zero rows** in the live DB. Fixing their queries would be effort spent
  on code with zero live execution path. Not deleted either — that's todo 056's separate,
  already-open v2.x-retirement decision, not this fix's call to make.

**Already correctly filtered — confirmed correct, not touched:**
- `services/regime_writer.py`, `services/forward_return_writer.py`,
  `services/backfill_feature_factory.py` (3 query sites) — all already use `volume > 0`.
  Verified empirically (see below) that this is the right predicate; no change needed, no
  historical-measurement impact, no methodology-change-ledger entry required for these.

**Empirical check behind the predicate decision:**

| source | total rows | volume=0 | volume>0 |
|---|---|---|---|
| `synthetic_fill` | 175,403,754 | 175,403,754 | 0 |
| `ibkr_named` | 40,215,094 | 2,146,462 | 38,068,632 |

Of the 2,146,462 `ibkr_named`/`volume=0` rows, a random sample and then a full aggregate check
found 2,146,416 (99.998%) are perfectly flat OHLC (`open=high=low=close`) — the remaining 46 show
only sub-cent intrabar noise. `volume` is `NOT NULL` in the schema. Conclusion: `volume > 0`
alone is a complete, simple, and empirically correct filter — it excludes both `synthetic_fill`
rows (100% of which are `volume=0` by `bar_normalizer.py`'s own contract) and IBKR's own
flat-carry-forward rows, with no dependency on the `source` column and no nullable-column
handling needed.

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
CREATE VIEW market_data_ohlcv_tradeable AS
SELECT * FROM market_data_ohlcv
WHERE volume > 0;
```

Named `_tradeable`, not `_active`: `active` is already a heavily-loaded lifecycle-status term in
this codebase's own glossary (`feature_registry`/`concept_registry`/`trade_frames`: `candidate →
active → shadow_only/expired → deprecated`). Reusing it here for "excludes placeholder bars"
would be exactly the kind of naming collision CLAUDE.md's glossary discipline exists to prevent.
`tradeable` is unused elsewhere and is the term todo 035 itself already reached for ("readers get
one canonical 'tradeable bars' surface").

**Why a view over a Python repository module:** ~22 files touch `market_data_ohlcv` directly,
many outside clean Ring-architecture Python services — ops shell scripts, debug scripts,
potential future Grafana/BI queries. A Python repository class (`fetch_bars()`) only protects
Python callers that choose to use it; a DB view protects every SQL client uniformly. Verified,
not assumed: `EXPLAIN (COSTS OFF)` on the view vs. the equivalent inline-filtered query against
live SPY 5m data produced **identical plans** — same compressed-chunk index scan
(`compress_hyper_*_chunk_symbol_timeframe__ts_meta_min_idx`), same vectorized columnar filter.
Postgres inlines the view; there is no runtime cost difference. A repository module on top of the
view is not ruled out for future ergonomic DRY reasons, but is not part of this fix — building one
now, before any Python call site has found the raw `WHERE volume > 0` clause actually painful,
would be speculative infrastructure for a problem the view already solves.

## Decision 2 — Scope for this pass

Fix, with tests, in this pass: `cross_sectional_regime_model.py`, `counterfactual_tracker.py`
(2 sites) — **2 files, 3 query sites**, all currently zero-filtered and confirmed live. Each
switches `FROM market_data_ohlcv` to `FROM market_data_ohlcv_tradeable` with no added `WHERE`
clause needed.

`regime_writer.py`, `forward_return_writer.py`, `backfill_feature_factory.py` are **not touched**
— their existing `volume > 0` is confirmed correct; migrating them to select from the view
instead of inlining the same predicate is a pure style nicety, not a correctness fix, and is
folded into the Tier-2 follow-up todo rather than done urgently here.

**Scope correction, found during Task 4's CI-guard implementation:** the guard test's first draft
matched only `FROM market_data_ohlcv`, missing `JOIN market_data_ohlcv` — a completely normal SQL
idiom. Widening the pattern to catch both surfaced a 3rd live, zero-filtered site of the exact
same bug class: `scripts/ops/corpus/ops_oos_holdout_eval.py`'s `_read_oos_rows` (a live diagnostic
reading `m.open` unfiltered for OOS feature-IC scoring, referenced from `OOS-EVAL-PROTOCOL.md`,
`methodology-change-ledger.md`, and `ic_engine.py`) — fixed the same way. Two more JOIN-based hits
were also found and correctly allow-listed rather than fixed: `services/bar_auditor.py` (a
legitimate gap-detection auditor that deliberately needs the full raw grid) and
`scripts/debug/analysis/debug_batch_agent_memory.py` (dead v2.x code, joins the zero-row
`signal_ledger`). **Total scope is now 3 files, 4 query sites.**

This is a straightforward bug fix (no filter → correct filter) for the 3 files touched, not a
retroactive change to an existing predicate's definition — no methodology-change-ledger entry is
needed for what didn't change (`regime_writer.py` et al.); the ledger only needs to note that
`cross_sectional_regime_model.py`/`counterfactual_tracker.py`/`ops_oos_holdout_eval.py` go from
"unfiltered" to "filtered" as of this fix, for anyone diffing pre/post corpus-rebuild or
OOS-eval numbers.

File a new todo for the Tier-2 audit list (11 files, not classified, plus the 3
already-correct-but-not-yet-view-based files above) as a fast-follow — the view already exists
for them once each is reviewed.

## Decision 3 — Prevention: make the wrong path structurally harder, not just documented

A view alone doesn't stop call site #6 — `SELECT * FROM market_data_ohlcv` is still shorter to
type and still compiles. Three layers, cheapest first, no new infrastructure beyond what already
exists in this codebase's own conventions:

1. **CI-enforced allow-list test** — `tests/unit/test_market_data_ohlcv_boundary.py`: grep the
   full tree for raw `FROM market_data_ohlcv\b` (excluding `_tradeable`), assert the hit set
   exactly matches a checked-in allow-list (the "correctly left alone" files above, plus the 3
   already-correct-but-raw-table sites, each with a one-line reason). Any new raw-table reference
   fails CI immediately unless the allow-list is also edited — forcing the "why does this need
   raw access" justification into the diff itself, at review time, rather than relying on someone
   remembering. Same shape of guard as todo 119's migration-schema-drift CI check — this project
   already has the pattern, just apply it here.
2. **One CLAUDE.md line**, same style as the existing `instruments.contract_details->>'asset_class'`
   gotcha: "`market_data_ohlcv` reads for compute/measurement must use
   `market_data_ohlcv_tradeable`; raw access needs a `test_market_data_ohlcv_boundary.py`
   allow-list entry with a reason." Discoverable before the CI check ever has to catch it.
3. **Not doing (deliberately, avoid over-engineering):** no ORM layer, no repository-class
   enforcement, no runtime schema validator. A view + a grep-test + a doc line is the complete
   fix for what is fundamentally a one-predicate problem.

**Considered and deferred, not rejected:** renaming so `market_data_ohlcv` itself becomes the
filtered view and the raw grid gets the marked name (e.g. `market_data_ohlcv_raw`) — this would
make the safe path the *unmarked default*, needing zero vigilance at all, which is the stronger
structural fix. Not done now: renaming a 250-chunk hypertable with ~22 live call sites (writers
included) is a materially bigger, separate migration with its own blast radius and risk profile.
Worth reconsidering once `market_data_ohlcv_tradeable` has been live and proven for a while.

## Implementation notes

- Migration number: 236 (next after 235).
- Corpus-run safety: the in-flight 143.1-07 rebuild has already executed steps 1-4 (including
  `cross_sectional_regime_model.py`) for this cycle — this fix cannot retroactively clean that
  run's regime labels, and doesn't need to; it lands cleanly for the next corpus rebuild. Editing
  these files now does not touch the currently-running `ic_engine` process (step 5) or its DB
  connections.
- TDD per CLAUDE.md's Done-Coding SOP: for each of the 4 files, write a test with a fixture
  containing both a `volume>0` bar and a `volume=0` bar, confirm the test fails against current
  code (proves the bug), then fix the query and confirm it passes.
- After implementation: `/simplify` → `/review` → `tests/unit/` green → commit on a feature
  branch → ff-merge to `main`, per CLAUDE.md's SOP.

## References

- `.planning/todos/pending/035-market-ohlcv-active-bars-view.md` — original todo, superseded by
  this design's decisions (close it, don't re-scope it further)
- `docs/reference/gotchas.md`, `src/core/bar_normalizer.py:23,223,239` — `synthetic_fill`
  convention
- `.planning/todos/pending/119-migration-schema-drift-ci-check.md` — same CI-guard pattern
  precedent
- `docs/plans/methodology-change-ledger.md` — entry required at implementation time, scoped to
  the 4 files whose filtering behavior actually changes
