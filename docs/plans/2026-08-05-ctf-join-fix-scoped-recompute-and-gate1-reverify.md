# Scoped `ctf_momentum` recompute + authoritative Gate 1 re-verification

Status: proposed, not executed — recompute step needs explicit user go-ahead (real corpus
mutation). Written 2026-08-05 so the next session can execute immediately instead of
re-deriving scope.

## What this answers

Todo 243's hard blocker: `feature_vectors.ctf_momentum` (and `ctf_vwap_align`,
`ctf_regime_align`) were never recomputed with the join fix (`_rekey_ctf_series_to_actual_close`,
shipped 2026-08-03). Every prior re-verification attempt either used stale (leaked) values or
ran diagnostic-tier only. This plan recomputes real corpus rows and re-runs Gate 1 through the
actual production path (`cross_sectional_spread_tracker.py`), not a parallel diagnostic script.

**This produces the audit-of-record answer, not the strategic decision.** Two independent
diagnostic-tier measurements (SPY single-symbol pilot; the full cross-sectional
`phase167_gate1_ctf_join_fix_reverify_15m.py` reverify) already agree the corrected join fails
Gate 1 — CI crossing zero on both scales, shuffled-null clearing failing outright (0.675/1.0
against a 0.05 threshold, not a boundary case). STATE.md's "Phase 167 UNVERIFIED, Phase 168
blocked" call is correct now and does not wait on this recompute to remain correct. This plan
exists to produce the formal `gate_evaluations` record, not to unblock anything that diagnostic
evidence hasn't already settled at this p-value.

## Scope (not a full corpus rebuild)

| Axis | Scope | Why |
|---|---|---|
| Timeframe | `15m` only | Phase 167's `cross_sectional_relative_value` construction and both diagnostic re-verifications (SPY pilot, full cross-sectional reverify script) used 15m. Matches the already-measured baseline. |
| Symbols | All 80 active equity ETFs (`instruments.contract_details->>'asset_class'='equity'`) | Same universe Gate 1 already ran against; `--symbols` isn't needed since it's the full default equity set. |
| Columns | **Only `ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align`** — surgical UPDATE, not `--refresh` | `backfill_feature_factory.py --refresh` has no column-level scoping — it recomputes the entire ~250-column feature row via `ON CONFLICT DO UPDATE` at whatever the current git HEAD computes for every feature, not just CTF. **Do not use `--refresh` for this.** Confirmed 2026-08-05: `pipeline_version` is uniformly `"3.0.0"` across all 36.85M corpus rows despite weeks of intervening commits — it is not functioning as a vintage marker. A full-row refresh of 8.8M rows would silently conflate the join fix with every other feature-compute change since these rows were last written, with no marker to ever detect the mix later. This is a controlled-experiment requirement, not a cost optimization: isolating the causal variable is the only way to attribute any downstream IC delta to the join fix specifically. |
| Rows affected | 8,824,030 (`feature_vectors` current 15m row count, confirmed 2026-08-05) — ~24% of the full 36.85M-row corpus (5m: 25.4M, 15m: 8.8M, 1h: 2.25M, 1d: 0.33M) | |

## Preconditions (confirmed 2026-08-05)

- Join fix already shipped: `services/backfill_feature_factory.py`'s `_rekey_ctf_series_to_actual_close()`, applied 2026-08-03, tested (4 regression tests in `test_ctf_momentum_live_batch_parity.py::TestCtfBatchJoinLookaheadFix`), peer-reviewed.
- `forward_returns` OOS region genuinely populated (todo 253) — 302,039 rows, corroboration logic real, zero failures. Downstream IC/gate measurement will read real data, not frozen/stale rows.
- D-04 gate governance live (todo 253) — `gate_evaluations` run-once guard. `_GATE1_ID = "gate1_cross_sectional_relative_value"` (from `_GATE1_ID = f"gate1_{_CONSTRUCTION_NAME}"`, `cross_sectional_spread_tracker.py:124`) **already has a recorded PASS row** from the 2026-08-04 run against the still-leaked join. Re-running Gate 1 through the same code path will hit `_write_gate_result`'s guard and refuse to write a second row for that gate_id.

## Steps

### 1. Decide the gate_id collision up front (this IS a decision, make it explicit, not a side effect)

The existing `gate1_cross_sectional_relative_value` row in `gate_evaluations` was computed
against leaked `ctf_momentum`. Once real corpus rows are recomputed, two options:

- **(a) Suffix a new gate_id** for the corrected-join run, e.g. `gate1_cross_sectional_relative_value_ctf_join_v2`, leaving the old row in place as a historical record of the pre-fix (invalid) result. Cleanest — preserves audit trail, no risk of silently overwriting evidence.
- **(b) Manually delete/supersede the old `gate_evaluations` row** before re-running with the original gate_id. Matches "this construction's real Gate 1 answer," but loses the paper trail of what the leaked-join number actually was without checking `git log`/backups.

Recommend (a). Low cost, keeps both numbers visible, and 2026-08-04's diagnostic-tier
re-verification already established what direction the answer moves — (a) lets that get
double-checked against the real one side by side.

### 2. Write a surgical CTF-only recompute script (new, small)

Do **not** use `backfill_feature_factory.py --refresh` (see Columns row above — it is not
causally isolated). Instead write a standalone script, e.g.
`scripts/ops/corpus/ops_ctf_columns_recompute_15m.py`, that:

- Iterates the 80 active equity symbols, tf=15m only.
- For each symbol, loads the same HTF bar history `_build_ctf_series` already consumes, calls
  `_build_ctf_series` + `_rekey_ctf_series_to_actual_close` **unmodified** (import from
  `backfill_feature_factory.py`, do not reimplement), and joins onto existing `feature_vectors`
  rows via the same `bisect_right` logic already in `feature_factory.py:6925` (also imported,
  not reimplemented).
- Writes via a targeted `UPDATE feature_vectors SET ctf_momentum = $1, ctf_vwap_align = $2, ctf_regime_align = $3 WHERE symbol = $4 AND tf = '15m' AND bar_ts = $5` — three columns only, every other column byte-identical to before.
- Single serial DB connection for writes (DAG invariant — no `ProcessPoolExecutor` workers writing directly).
- Runs read-only (dry-run / diff-only mode) first: report how many rows would change and the
  distribution of the delta, without writing, before committing to the real UPDATE pass.

### 3. Timed pilot before committing to the full 80-symbol run

No runtime baseline exists for this exact shape. Renaissance rigor: measure, don't assume. Run
the new script's dry-run mode against a single symbol (SPY) first, time it, multiply by 80 to
get a real estimate before running unattended against the full universe.

### 4. Full scoped recompute

Run the script from step 2 for real (write mode) against all 80 equity symbols, tf=15m. This is
a targeted 3-column UPDATE across up to 8,824,030 rows — no IBKR fetch, no `feature.factory.target_timeframes`
override needed (this script never touches the full-row compute path), no `pipeline_version`
ambiguity (every other column is provably untouched, so the existing "3.0.0" stamp stays
accurate for everything except these 3 columns — worth a one-line note in the script's own
docstring since this is the one legitimate exception to "pipeline_version = full row compute
vintage").

### 5. Spot-check before trusting it

Reuse the exact verification todo 243 already used: SPY 2026-01-05 15:00 UTC. Old leaked value
was `0.2321`; the corrected join (verified via the diagnostic script) computes `-0.1281` for the
same bar. After recompute, confirm `feature_vectors` now stores the corrected value, not the old
one — an UPDATE that silently no-ops (e.g. wrong WHERE clause, symbol/tf/bar_ts mismatch) would
look identical to success without this check.

```sql
SELECT ctf_momentum FROM feature_vectors
WHERE symbol='SPY' AND tf='15m' AND bar_ts='2026-01-05 15:00:00+00';
-- expect -0.1281 (or close, given any rounding), NOT 0.2321
```

### 5b. Also force `feature_ic_scores` to recompute — the watermark-based fingerprint will NOT catch this fix on its own

`ic_engine.py`'s staleness detection (`_watermark_forward_returns_feature_vectors`,
`ic_engine.py:980-994`) fingerprints `feature_vectors` by `MAX(bar_ts)` + `COUNT(*)` only — not
a content hash. Its own docstring assumes any real feature-value change is always accompanied by
either a `code_content_key` bump (a code change) or a `forward_returns` recompute (a bar
correction). Step 2's surgical UPDATE triggers neither: same bar count, same max `bar_ts`,
different values underneath. Left alone, `ic_engine` will classify every `ctf_momentum` cell as
still "valid" forever — not just until its next scheduled run, indefinitely — and
`feature_ic_scores` stays frozen on leaked values with nothing to ever flag it stale again. This
directly matters for [todo 256](../../.planning/todos/pending/256-ctf-columns-no-explicit-ensemble-exclusion-pending-join-fix-recompute.md):
its "currently excluded from ensemble eligibility" finding was checked against these same stale
rows and needs to be re-verified against real ones, not assumed to hold.

Run, after step 4's UPDATE completes:

```
.venv/bin/python services/ic_engine.py --refresh --tf 15m --symbols <80 equity symbols> \
  --training-window-end <same value used elsewhere in this recompute>
```

`--refresh` bypasses the fingerprint check entirely for the scoped cells (`ic_engine.py:4744-4751`),
forcing a real recompute regardless of watermark state. This reprocesses every feature's IC for
the scoped (symbol, 15m) cells, not just the 3 CTF columns — unlike step 2's concern with
`backfill_feature_factory.py --refresh`, this is not a causal-isolation problem: every other
feature's underlying `feature_vectors` values are genuinely unchanged, so their recomputed IC
values will be numerically identical (just a fresh `computed_at`/fingerprint stamp), and only
`ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align`'s IC actually moves.

After this run, re-check todo 256's meta-FDR table (`ensemble_trainer.py`'s `_meta_eligible`
logic) against the fresh `feature_ic_scores` rows — the corrected join could plausibly change
whether any of the three CTF columns clear ensemble eligibility, in either direction.

### 6. Re-run Gate 1 through the real production path

Before running: bump `alpha.construction.null_shuffles` from its default 40 to at least 1000 for
this run. `gate1_passes` gates on `null_p < 0.05` per scale (`null_p_threshold`,
`cross_sectional_spread_tracker.py:1403`) — with only 40 permutation draws the achievable
resolution is 1/40 = 0.025 per step, and the exact-binomial CI around any p̂ landing near the
0.05 boundary spans roughly [0.001, 0.13]. That was immaterial for the diagnostic run (null_p
0.675/1.0, nowhere near the boundary) but this run is D-04 run-once — no do-overs if the
corrected-join result lands closer to the boundary than the diagnostic did. The extra draws cost
seconds (pure in-memory resampling of an already-fetched panel, no added DB I/O) — cheap
insurance for a decision this project's own "p<0.05, sufficient N" mandate is supposed to gate
on. Restore `null_shuffles` to 40 afterward unless there's a reason to keep it elevated project-wide.

`cross_sectional_spread_tracker.py --backfill` (rebuilds `construction_spreads` from now-corrected
`feature_vectors.ctf_momentum`) then `--evaluate-gate` using the gate_id decided in step 1. This
is the authoritative answer — supersedes both the diagnostic-tier script
(`scripts/analysis/phase167_gate1_ctf_join_fix_reverify_15m.py`) and the SPY single-symbol pilot.

### 7. Update records regardless of outcome

- `docs/research/data-edge-source-thesis.md` — remove or confirm the `ctf_momentum` caveat depending on verdict.
- Phase 167's verdict record / STATE.md — resolve the "UNVERIFIED, do not start Phase 168" flag one way or the other.
- Close todo 243 with the real (non-diagnostic) numbers, referencing the new `gate_evaluations` row.
- Re-check todo 256's meta-FDR eligibility table against the fresh `feature_ic_scores` rows from step 5b (its finding was based on now-stale, still-leaked rows) and close or update it accordingly.
- If Gate 1 fails under the corrected join (both prior diagnostic measurements point this way — SPY pilot and the full cross-sectional diagnostic reverify both flip to FAIL): Phase 167 loses its only clean PASS, Phase 168 stays blocked, and discovery goes back to candidate hunting per the strategic plan's stated fork.

## Explicitly not in scope here

- 5m, 1h, 1d recompute — no measurement currently needs them; revisit only if 15m's answer is ambiguous or if a construction using those tfs needs the same fix.
- Any change to `_rekey_ctf_series_to_actual_close` itself — already shipped and tested, not touched by this plan.
- Live-path (`feature_vector_pipeline.py`) — already correct per todo 241, not affected.
