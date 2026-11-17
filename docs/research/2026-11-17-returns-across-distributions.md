# Returns across a distribution no table holds

Status: proposal for the lead's ruling (indicagent-55, 2026-11-17). Written for todos 622, 628 and 629.

## The case

A spin-off or a distribution of another share class (ATRO 2026-06-15, a Class B share per five held; ABT 2013-01-02,
DELL 2021-11-02, HPQ 2015-11-02, POST 2022-03-11, XPO 2021-08-02) lowers the held line's price by the value
that leaves with the distributed shares. The held security is not split, so no split row exists and none
should; canonical keeps the as-traded series. A return computed across the break reads that drop as a loss,
although the holder also received the distributed shares. No table holds distributions (the dividend table
holds cash only), so total return across the break is unknown.

## Policy

1. Unknown is never zero (the dividend rule: outside `dividend_event_coverage` dividends are unknown). A
   distribution on the sweep's disposition list is a known break with an unknown total return: the return of
   the break session, and any multi-session target or feature window that contains it, is missing for that
   name (NaN under `no_fill`), not repaired by a price ratio. A ratio fitted to the price step would invent
   wealth continuity from the price alone, with no witness of the distributed value.
2. The disposition line is the registry: `config/corporate_actions/sweep_dispositions.csv` already names
   symbol, break date, reason and filing. The panel reads it as a masked-date list, so the mask has one
   source and the sweep gate and the research kernel cannot disagree.
3. The count is disclosed per run (names masked, sessions masked), like the survivorship and dividend
   coverage disclosures.
4. The proper fix is data: a `distribution_event` table (record date, ex date, ratio, distributed
   security) joined to the distributed security's first close for value, behind the stage 2 identity map
   (the distributed security is a second instrument). Until it exists the mask applies; once it does, the
   masked windows return to the sample with a total return, and the change is a methodology entry because it
   moves counted tests.

## Cost of the mask

Distributions are rare per name (a handful in 20 years on 1,529 active names), so the loss is a few return
windows. The alternative, leaving the drop in, adds a fabricated negative tail to every family that reads a
return across it, which is the failure the counted tests exist to avoid.

## Open

The kernel change (panel masked-date input from the disposition list) is not built; it is a
`src/intelligence/research/` edit and needs `repro_frozen` bit-identical. The ruling and the
reader belong in a todo once the lead accepts the policy.
