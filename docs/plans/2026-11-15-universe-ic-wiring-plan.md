# Universe IC wiring: todo 609 blocker I1, minimal plan

Status: plan, not started. Lands after step 7 D1 and the quiet list restart: it edits `src/intelligence/research/snapshot.py` and `services/ic_measure.py`, which the `ic-measure` timer and every research run import. Frozen rule: `2026-11-13-stage2-universe-preregistration.md`. Table and writer: `2026-11-15-universe-membership-design.md`.

## Goal

The IC measurement and the research runner measure the same securities the corpus computes, each date's cross-section restricted to that date's members, with the universe rule inside the snapshot pin. Today `ic_measure._symbols` and `runner._source_configs` read the `compute_eligible*` flags, so a membership corpus would be measured on another name set (`corpus_rerun.check_ic_universe_aligned` fails loudly until this lands).

## Design (one mask, read once, applied at the boundary)

Features compute on every name ever a member (so an entering name is warmed) and prices stay unmasked (returns and warmup need the full series). Only the IC cross-section is gated, by one boolean matrix `member[session, symbol]`.

1. Reader, in `snapshot.py`, no new table:
   - `membership_symbols(dsn)`: `SELECT DISTINCT symbol FROM universe_membership ORDER BY symbol`; raises when the ledger is empty (the same refusal as `services/corpus_universe.py`; both read one SQL constant so they cannot diverge).
   - `membership_mask(dsn, symbols, sessions)`: reads (as_of, symbol) rows and the ledger once. Session d is a member of the latest built as_of strictly before d (the decision at as_of t is effective for the following month; a strict inequality keeps a decision made on t's close out of t's own cross-section). Sessions on or before the first built as_of are all False. A session after the last built as_of plus one month-end raises: no extrapolation past the ledger. Vectorised with `searchsorted` over the sorted month-ends, one bool row per month-end gathered per session.
2. Spec: add `"universe_membership"` to the `PanelSpec.universe` Literal (`spec.py`). A new allowed value moves no existing spec hash (existing specs carry their old value), so `repro_frozen` stays bit-identical; confirm by running it. The core panel is `"universe_membership_core"`: the same mask restricted to symbols that are members at 90 percent or more of the vintage's built month-ends (computed from the same rows, no table). Core ships second, same code path.
3. Snapshot: `_default_build` takes symbols from `membership_symbols` and saves `member` through `panel.save(extra=...)`, so the mask is inside the snapshot hash, and writes `rule_id`, ledger month count and last as_of into `manifest_extra`. The universe rule is then part of the snapshot pin and, through the spec's `universe` value, the spec hash (unified design E18).
4. Consumption, at the one place panels become IC inputs: NaN the target and the feature cells of non-members (`no_fill`: missing is NaN). Do it in `measure/targets.py::build_target_panels` for ic_measure and at the panel load for the runner, with one helper (`apply_member_mask`) so S1 to S7 each see NaN, not a re-derived rule. First sub-step: list every cross-sectional operation under `research/` and `statistics/` (rank, demean, neutralise, quantile, size-bucket) and confirm each skips NaN; a name that is NaN is then out of the cross-section and out of N. A grep result goes into the PR description.
5. `ic_measure`: `_symbols("1d")` calls `membership_symbols`, its target build gets the mask, and the manifest records the rule id. `_symbols` for 5m is unchanged until the 5m tier exists (blocker I2 in todo 609: the tier is a preregistration amendment).
6. Both modules declare `UNIVERSE_SOURCE = corpus_universe` as the tripwire `check_ic_universe_aligned` reads. Make the check per timeframe once I2 splits the intraday universe.

## Tests

- Mask: session on a month-end uses the prior month's members; first session after as_of t uses t; a name entering and a name leaving across a boundary; session before the first as_of all False; a session beyond the ledger raises; empty ledger raises.
- Target and feature cells are NaN for a non-member and finite for a member; prices unchanged.
- A spec with `universe_membership` hashes differently from the same spec with `compute_eligible_1d`; every recorded spec hash is unchanged.
- `ic_measure` 1d on a synthetic two-name ledger measures only members and records the rule id.

## Gates

Unit suite exit code, ruff, black, glossary; `repro_frozen` bit-identical with no recorded entry needed (the old universes are untouched); a methodology-change ledger entry for the new universe value as a counted design choice, written before any real-data look; independent review. Real data: the member count by year goes to the owner first (preregistration gate 5), then the first membership IC run.

## Order and size

After D1 and the quiet-list restart. One session, about a day: reader and mask (2 h), spec and snapshot (2 h), cross-section audit and masking (3 h), ic_measure and tests (2 h), `repro_frozen` and review (1 h). Not before blocker I2's decision, because the 5m side of `ic_measure` and the data gate need the tier.
