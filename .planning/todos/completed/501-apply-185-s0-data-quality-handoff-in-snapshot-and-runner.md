---
status: closed
priority: P0
filed: 2026-10-07
source: 185-29 (VERIFICATION gap 3, D-04 and D-07)
owner: phase 183 research lane
closed: 2026-10-26
---

# Apply the 185 S0 data-quality hand-off in snapshot.py and runner.py (D-04, D-07)

## What

The D0 labels (venue move, quarantine, dividend coverage; the survivorship label was retired by the owner 2026-10-09, todo 514, and is NOT part of the handoff) and the derivation rule record exist as code on the 185 side but no research attempt reads them: `src/intelligence/research/` belongs to the phase 183 lane, so 185 wrote the exact change instead of editing it. The recipe is `.planning/phases/185-daily-data-foundation/185-S0-HANDOFF.md`; the gap is VERIFICATION gap 3 in `185-VERIFICATION.md`. `load_label_inputs` (185-29) now returns `d2_rule_version` (every canonical rule behind the panel's 1d bars, comma-joined), `policy_as_of` and `verdict_as_of`.

## Gate

Before daily attempts 3, 3b and 4 run (the resumption of todo 442). D-04 stays unmet at phase 185 close and is overridden at re-verification, naming this todo.

## Done when

- The snapshot manifest carries `d2_rule_version`, `bar_content_digests`, the pinned symbol list, `policy_as_of`, `verdict_as_of` and the `bar_integrity` verdicts it read (the snapshot-pinning invariant, spec section 1).
- Run evidence carries the `data_quality` block (`labels.to_manifest()`) through the S6 ledger only.
- Old snapshots without the new keys still load unchanged.
- `scripts/research/determinism/repro_frozen` reports bit-identical.
- `tests/unit/research/test_ledger_sole_writer.py` is green and untouched.

## Resolution (2026-10-26)

Applied with two deliberate departures from the handoff.

- The labels are computed from the snapshot, not from a run-time database read. S0 calls
  `load_label_inputs` once and pins the raw inputs (`data_quality_inputs`: moved names,
  quarantined bar keys, dividend coverage) beside `symbols`, `d2_rule_version`, `policy_as_of`,
  `verdict_as_of`, the latest `bar_integrity` verdict per subject and metric, and
  `bar_content_digests`. The runner's `data_quality` block is then a pure function of the
  snapshot hash (the `determinism` invariant), and S0 stays the only research node reading
  Postgres for it.
- `bar_content_digests` holds one aggregate per symbol (`n_ranges` plus sha256 over the
  ordered `range_start:digest` lines of the `bar_content_digest_current` ranges the span
  touches), not every range: a full-universe 1d span is about 350k monthly ranges.

Labels are counted per column (`data_quality.panel_labels`), with a test pinning them equal to
`labels.build_labels` on a random panel. They are computed on database symbols after the
members-universe filter and before total_return segments the names. Evidence from a snapshot
captured before this change carries no `data_quality` key. Live smoke over 5 names at 1d and
15m: `d2-v3`, both as-of stamps, 13 ranges per name. The 1d quarantine keys align with the
grid but land on NaN cells, because the tradeable view already drops quarantined bars, so the
scrub share is 0 on what compute reads. Full unit suite green, `test_ledger_sole_writer.py`
untouched and green, `repro_frozen` bit-identical.
