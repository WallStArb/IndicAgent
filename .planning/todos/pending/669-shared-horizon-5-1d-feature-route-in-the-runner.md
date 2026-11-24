---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-3d family-order note (docs/plans/2026-11-24-family-order-after-1d-corpus.md), lead ruling 2026-11-24
---

# A horizon-5 1d stored-feature route in the research runner, with new persistent battery cells

## What

No corpus family can run as registered. The runner admits feature input members only at horizon 1, equal weight, in one family and never beside residual-return members (`runner._check_supported_subset`, `_check_input_mix`; todo 588 item m3). The certified routes are feature 1h to 1d, feature 15m to 1d and `rk_high_dist` 126 1d to 1d, all at horizon 1 (`null_battery_persistent._REPORT_PASSING`). No stored 1d to 1d feature route is certified, and every family since E23 is at horizon 5. Every corpus family (H-B low risk, `corpus_family`, market-residual reversion, regime variants) therefore waits on one shared build.

## Scope

One route: stored 1d feature members at horizon 5 through the runner, with new persistent battery cells (E17) bound by `bind_battery_pass.py`. No new family and no counted look. Gates: this edits `src/intelligence/research`, so `repro_frozen` must report bit-identical (or a recorded methodology-change entry), the existing battery pass records are rebound in the same commit if their code key moves, an independent review, and the suite by exit code.

## Sequence

Behind the four family 10 counted runs and the StepM read on 16 series. It lands after the corpus pilot and before the pin of any counted corpus test. It edits research code, so it never runs while a counted run is live (a live run imports it; `code_content_key`).
