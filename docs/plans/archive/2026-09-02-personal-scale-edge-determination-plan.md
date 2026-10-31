# Personal-scale edge determination program - archive stub

Program plan, 2026-09-02 (Claude/Sonnet 5, interactive session). CLOSED: the pre-registered decision gate's kill criterion (rule 3) fired 2026-09-12. Superseded by the unified research-to-production design (2026-09-26, E18) and at the program level by `docs/plans/2026-10-31-data-fill-and-corpus-rerun-plan.md` (2026-10-31).

Ideas worth keeping:

- The hurdle is a function, not a table: IC_min depends jointly on (IC, breadth, autocorrelation, horizon, cost), because slow signals trade turnover down at the same time breadth periods shrink - evaluate per candidate per horizon.
- Pre-registered cost constants, committed before any candidate placement; changing one after a placement invalidates every placement made with it (now module constants in `scripts/research/cost_hurdle.py`: sigma 0.16, 1.4 bp live spread anchor, Corwin-Schultz rejected at 15.7x off the [0.5, 3.0] validation band).
- Measured signal mass doubles from 1d to 5-10d horizons while turnover drops 5-10x - the cost hurdle is easiest where signal mass peaks; short-horizon falsification was testing the wrong corner of (signal x horizon) space.
- A pre-registered kill criterion ("this corpus, at breadth ~8 and this TF stack, cannot carry the endgame") as an anti-drift mechanism: at firing, 14 constructions had run to verdict, zero PASS, and every failure traced to construction/economic reality, never to the ruler.
- Verdict pattern that recurred: paper signal mass was real (218 FDR-passing cells clearing the personal hurdle) but nothing survived construction into a concentrated, market-neutral, cost-surviving form (beta tilt; uniformly dilute common effect at 0/231 per-symbol concentration; negative-gross OOS P&L).

Verdict record: `docs/research/construction-verdict-ledger.md` and the `legacy-*` cards in `docs/research/summary-cards/`; verdict rows in `concept_registry` (`domain='construction'`, migrations 328-335).

Full text in git history: `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` as of commit `1280dc0a4` (pre-condense) and `5d1bac867` (condensed summary).
