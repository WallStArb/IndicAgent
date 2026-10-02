# S0/S6 data-quality hook hand-off (phase 185 plan 16 to the research lane owner)

Author: phase 185 plan 16 executor, 2026-10-02
Informed by: `.planning/phases/185-daily-data-foundation/185-16-PLAN.md` (task 2),
`.planning/phases/185-daily-data-foundation/185-08-PLAN.md` (labels.py),
`src/intelligence/bars/labels.py`, `src/intelligence/bars/label_inputs.py`,
`src/intelligence/research/snapshot.py`, `src/intelligence/research/runner.py`

Status: coordination pending. The STATE.md lanes table holds `src/intelligence/research/`
with the phase 183 session (the 2026-10-01 release covered only the one-line `HarnessConfig`
import switch in 186-29), so plan 16 wrote this document and touched nothing under
`src/intelligence/research/`. D-04 is met when this document is applied by the lane owner;
until then `ops_data_bar_check.py` (this phase, committed) remains the hard gate in front of
daily attempts 3, 3b and 4, and it currently FAILs on `late_name_dispositions`
(42 unresolved, plan 14's re-ask lane).

## What exists already (committed by 185-16, safe to import from anywhere)

- `src/intelligence/bars/label_inputs.py`:
  `LabelInputs` (frozen dataclass: `moved_symbols`, `move_dates`, `quarantine_keys`
  as `(symbol, ts_seconds)`, `exchange_of`, `d2_rule_version`, `dividend_coverage`) and
  `async def load_label_inputs(conn, *, symbols, tf, start, end) -> LabelInputs`.
  Read-only, asyncpg, every symbol list bound as an array parameter; registers the jsonb
  codecs so it works on both bare and pooled connections.
- `src/intelligence/bars/labels.py` (unchanged, plan 08):
  `build_labels(*, d2_rule_version, cell_symbols, moved_symbols, total_return, div_covered,
  cell_keys, flagged_keys, rule, small_cap_share, weights=None, exchange_of=None) ->
  DataQualityLabels` and `DataQualityLabels.to_manifest() -> dict`.
  `SurvivorshipRule.from_apr(apr_mapping)` builds the rule from the six
  `alpha.survivorship.*` keys (all six present in `config_state`, verified live).

## The exact change (two files, no schema, no migration)

### 1. `src/intelligence/research/snapshot.py`, inside `build_panel`

`build_panel(dsn, out_dir, *, symbols, tf, start, end_exclusive, manifest_extra=None,
dividends=False)` already owns the manifest (merged at the `manifest = {...}` site,
`manifest_extra` last). Add two manifest keys there, before the save:

- `d2_rule_version`: the `LabelInputs.d2_rule_version` from one
  `load_label_inputs(pool_conn, symbols=requested, tf=tf, start=lo, end=hi)` call
  (the pool is already open in the function). It is `None` until plan 17's first daily
  derivation run; record `None` as is, never a placeholder string. This is the D-07 hook:
  the snapshot hash then covers the derivation rule behind its bars.
- `bar_content_digests`: `{tf: {symbol: [range_start_iso, digest]}}` read from
  `bar_content_digest_current` for the panel's `requested` symbols, `tf`, and span
  (rows whose range intersects `[lo, hi)`), e.g.
  `SELECT symbol, range_start, digest FROM bar_content_digest_current
   WHERE symbol = ANY($1) AND timeframe = $2 AND range_start < $3 AND range_end >= $4`.
  Symbols without a digest row are simply absent from the inner dict (a digest gap is a
  disclosed fact, not an error; 185-12 covers 5m/15m/1h for derived symbols, 1d follows
  with plan 17).

The manifest is JSON-able already; ISO-format the range_start (`format_iso_ts` or
`.isoformat()` on the tz-aware value, matching the file's existing manifest scalars).

### 2. `src/intelligence/research/runner.py`, at evidence assembly

The runner loads the panel (via `_load_panel` / `_default_build`), so at run time, before
the first `finish(...)` / `finish_run(...)` call (the evidence paths at the
`evidence_record(...)` sites, family/member and book):

- call `load_label_inputs` once per run on a read-only pool connection with the run's
  symbols, tf, and span;
- build the cell inputs from the loaded panel (one entry per (symbol, session) cell:
  `cell_symbols`, per-cell `div_covered` booleans from `dividend_coverage`
  (session date inside `[covered_from, covered_to]`), `cell_keys` as
  `(symbol, ts_seconds)` from the cell timestamps, and the spec's `panel.total_return`
  flag; `small_cap_share` from whatever universe metadata the run already carries
  (leave 0.0 if the S0 universe does not carry a cap split; the bound then reports the
  haircut's floor, which is the honest number);
- `labels = labels.build_labels(..., rule=SurvivorshipRule.from_apr(apr), ...)`;
- put `labels.to_manifest()` under `evidence["data_quality"]` in the evidence dict handed
  to `finish`/`finish_run`. The S6 ledger stays the sole writer of `research_run`:
  `tests/unit/research/test_ledger_sole_writer.py` must stay green with no allow-list
  changes. Never write the block anywhere else (no direct table writes, no extra files).

### Tests to add

1. Manifest keys present: extend the `build_panel` coverage
   (`tests/unit/measure/test_targets.py`, `tests/unit/test_ic_measure.py` or a new
   `tests/unit/research/test_snapshot_manifest.py`) to assert `d2_rule_version` and
   `bar_content_digests` land in the saved manifest, `d2_rule_version=None` included.
2. Evidence carries `data_quality`: extend `tests/unit/research/test_runner_evidence.py`
   with a run whose evidence dict contains the `to_manifest()` block.
3. Old snapshots without the keys still load: a panel saved before this change (no
   `d2_rule_version`, no `bar_content_digests` in its manifest) must load and run
   unchanged through `_load_panel` (which compares only `start`/`end_exclusive`/
   `universe` today; keep it that way, missing keys are not a mismatch). One test with a
   pre-change fixture panel is enough.
4. `tests/unit/research/test_ledger_sole_writer.py` green, untouched.

## Why

D-04 (labels ride every attempt, as a bound reported beside the statistic, never a gate)
and D-07 (every recorded attempt names the derivation rule behind its bars). The inputs
are read-only and the label math is pure (plan 08), so the runner only wires reads to
labels to evidence.

## Constraints for the applying session

- `src/intelligence/research/` determinism: after these edits run
  `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch_dir>
  --logs /home/bg/dev/indicagent/logs` from a worktree; frozen verdicts must stay
  bit-identical (manifest keys change snapshot hashes only for NEW captures; old
  snapshots load unchanged, so frozen runs over existing snapshots are unaffected).
- No APR keys are added by this change; the six survivorship seeds already exist.
- `load_label_inputs` reads `bar_quality_flag`, `ohlcv_venue_head`, `ohlcv_request`,
  `bar_derivation_batch`, `dividend_event_coverage`; all reads are parameterized arrays.
  If the runner's connection role lacks SELECT on any of these, that is a role grant,
  not a code change.
