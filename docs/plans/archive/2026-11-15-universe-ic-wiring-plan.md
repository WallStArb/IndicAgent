# Universe IC wiring, todo 609 blocker I1 (archived)

Date: 2026-11-15. Archived 2026-11-22.
Outcome: built on main (todo 609 I1; status in `.planning/todos/pending/609-stage2-universe-from-massive-pit-liquidity-rule.md`). `services/ic_measure.py` and `src/intelligence/research/snapshot.py` declare `UNIVERSE_SOURCE` and read `membership_inputs`; targets are gated by the member mask; `corpus_rerun.check_ic_universe_aligned` is the per-timeframe tripwire. The rule itself is frozen in `docs/plans/2026-11-13-stage2-universe-preregistration.md`; the table and writer are in `docs/plans/2026-11-15-universe-membership-design.md`.

Ideas kept:
- Features compute on every name ever a member (so an entering name is warmed) and prices stay unmasked; only the IC cross-section is gated, by one boolean matrix `member[session, symbol]`, read once and applied at the boundary.
- A session is a member of the latest built as_of strictly before it, so a decision made on a month-end close never enters that month-end's own cross-section; no extrapolation beyond the ledger.
- Non-members are NaN (`no_fill`), not zero; every cross-sectional operation under `research/` and `statistics/` is audited so none counts a masked name.
- A new `PanelSpec.universe` value moves no existing spec hash; confirm with `repro_frozen`.

Full text: git history, `docs/plans/2026-11-15-universe-ic-wiring-plan.md` as of `cad278f2a`.
