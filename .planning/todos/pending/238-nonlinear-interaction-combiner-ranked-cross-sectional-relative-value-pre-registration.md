---
status: pending
priority: P1
filed: 2026-08-03
source: user-directed rigor review of Edge Source Thesis cross_sectional_relative_value/nonlinear_interaction_combiner next steps -- explicitly asked
  to apply Renaissance/Simons-council-level scrutiny before proceeding, which surfaced that
  "just swap cross_sectional_relative_value's ranking signal to nonlinear_interaction_combiner's tree score" was under-specified and needed a properly
  pre-registered falsification design first, same discipline as cross_sectional_relative_value's shuffled-null and nonlinear_interaction_combiner's
  todo-184 canary-leakage check (both pre-specified before running, not after seeing the number)
gate: nonlinear_interaction_combiner-at-5m replication (in progress, `scripts/analysis/nonlinear_interaction_combiner_replication_5m.py`)
  completing first -- may change which tf(s) are worth testing here
---

# Pre-registered design: does cross_sectional_relative_value's construction improve if ranked by nonlinear_interaction_combiner's tree score instead of `ctf_momentum`?

## Why this is the next real step, not a new invented hypothesis

cross_sectional_relative_value (cross-sectional dollar-neutral spread, `services/cross_sectional_spread_tracker.py`) is a
proven, productionized construction that currently ranks by `ctf_momentum`. nonlinear_interaction_combiner (LightGBM
non-linear combiner) independently proved a 3-5x stronger cross-sectional-neutral signal on the
*same* feature corpus, at 15m: tree `point_ic`=0.2506 vs `ctf_momentum`'s 0.0610. Nobody has
tested cross_sectional_relative_value's actual construction ranked by the stronger signal. Both halves are already proven;
this is the highest-expected-value untested combination on `docs/research/data-edge-source-thesis.md`.

## Why this is NOT a mechanical "just swap the column" change

A trained model's output used as a cross-sectional ranking signal needs the *same* falsification
discipline cross_sectional_relative_value already applied to `ctf_momentum` and its siblings -- arguably more, since a
200-tree GBM is structurally more capable of encoding a static factor tilt than one hand-specified
feature. cross_sectional_relative_value already killed two CTF siblings (`ctf_vwap_align`, `ctf_regime_align`) that cleared
CI but died on turnover or the CI test itself. Skipping any of the checks below to get to a
number faster is exactly the kind of shortcut this project's own gate stack exists to prevent.

## Pre-registered pass/fail design (write this down before running anything)

1. **Walk-forward OOS granularity check (prerequisite, not the test itself).** Confirm the
   tree's per-bar predictions used for ranking are genuinely OOS at the *cross-sectional ranking*
   grain cross_sectional_relative_value needs (every symbol, every bar, from a fold that never saw that bar in training) --
   not just an aggregate point_ic collapsed over the whole OOS window, which is what nonlinear_interaction_combiner's
   existing scripts report. If the existing walk-forward fold structure doesn't already produce
   a continuous per-bar OOS score usable for daily/intraday ranking, this needs building before
   anything else here is even measurable.

2. **Shuffled-ranking null** -- identical construction to cross_sectional_relative_value's original test (permute
   feature/tree-score-to-symbol assignment within each bar, rebuild the identical decile
   construction, 40 draws). Real result must clear every null draw, same bar as cross_sectional_relative_value's original
   pass.

3. **Cost-hurdle sweep** -- same tiers cross_sectional_relative_value's Gate 1 already uses. Report net spread at each tier,
   not just gross.

4. **Turnover measurement** -- leg-membership change rate, same statistic that killed
   `ctf_vwap_align` (72% turnover, net-negative despite clearing CI) and `ctf_regime_align`
   (87-90% turnover). A higher-IC ranking signal that also turns over faster could net out worse,
   not better -- must be measured, not assumed.

5. **Gate-2-equivalent factor-attribution check** -- is the tree-ranked spread's P&L explained by
   a static factor loading (low-vol/high-vol, sector, size) the tree could be implicitly encoding
   without anyone specifying it? cross_sectional_relative_value's own Gate 2 (attribution honesty) exists for exactly this
   failure mode and is *more* important here, not less, given the tree has far more capacity to
   encode a disguised static tilt than `ctf_momentum` does.

6. **Breadth-preservation check** -- does the tree score concentrate its cross-sectional
   differentiation (meaningfully distinct scores) on fewer symbols/days per bar than
   `ctf_momentum` does? The doc's own "Breadth Is the Binding Constraint" section says
   IR ≈ IC × √(effective breadth) is what actually matters -- a higher point IC that quietly
   narrows the number of independent bets per bar could net out to a *worse* IR despite a better
   headline number. Must be measured directly (e.g., effective N of non-degenerate scores per
   bar), not inferred from point_ic alone.

## Explicitly out of scope for this pre-registration

**Operationalizing a tree-ranked construction into a live daemon is a separate, larger decision,**
not bundled into this historical-validation test. `ensemble_trainer.py`'s architecture assumes a
scalar per-feature IC weight, refit in discrete batch runs (todo 089's stale-cadence concern
applies doubly to a heavier non-linear model) -- there is no model-versioning/storage story for a
serialized GBM today. If this pre-registered test passes, the retraining-cadence and
model-storage design is its own follow-on scoping question, filed separately, not assumed solved
by a good historical number.

## Sizing

Investigation/measurement, reusing existing infrastructure (`cross_sectional_spread_tracker.py`'s
construction logic, `_nonlinear_interaction_combiner_shared.py`'s trained-tree pipeline, cross_sectional_relative_value's existing
shuffled-null/cost-hurdle/turnover machinery) -- no new data, no new service. Real effort is in
item 1 (confirming per-bar OOS score availability) and item 5 (factor-attribution check design),
neither of which currently exists in exactly this shape.

## References

- `docs/research/data-edge-source-thesis.md` -- cross_sectional_relative_value and nonlinear_interaction_combiner sections, full result history
- `docs/research/trade-construction-layer.md` -- cross_sectional_relative_value's Gate 1/Gate 2 definitions and numeric
  verdicts
- `.planning/todos/completed/184-nonlinear-interaction-combiner-canary-leakage-check.md` -- the precedent
  for pre-registering a check before running it, same discipline applied here
