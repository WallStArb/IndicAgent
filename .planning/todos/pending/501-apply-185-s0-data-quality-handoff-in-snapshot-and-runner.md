---
status: pending
priority: P0
filed: 2026-10-07
source: 185-29 (VERIFICATION gap 3, D-04 and D-07)
owner: phase 183 research lane
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
