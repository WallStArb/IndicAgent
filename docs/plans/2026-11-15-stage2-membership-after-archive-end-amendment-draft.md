# Stage 2 amendment draft: membership for months after the last Massive reference list

**Status:** DRAFT 2026-11-15, unapplied. It changes nothing until the owner adopts it, and it must be adopted before `universe_membership` is built for any month-end after the last captured Massive list. No return-based look at the universe has happened.
**Author:** Claude (indicagent-65), 2026-11-15, on the lead's brief (follow-up to `docs/plans/2026-11-15-massive-plan-lapse-deadlines.md`).
**Amends:** `docs/plans/2026-11-13-stage2-universe-preregistration.md` (adopted and frozen 2026-11-13; amendments are dated and counted as design choices under E18). Text in Part 1 is the amendment to append if adopted.

## The problem

The preregistered rule reads Massive's point-in-time ticker reference as captured: the active and inactive ticker lists at each NYSE month-end, from which a security gets its type (common stock, ADR or ETF) and its identity key (composite FIGI, else CIK plus share class plus type). The captures run to 2026-11-09 (6,132 files, 2026-11-13). The lapse checklist may add the 2026-11-30 list as raw evidence, but it does not move L (below). The plan lapses about 2026-12-10, so a month-end list for 2026-12-31 and later cannot be captured. The rule needs a stated source for those months, written before anyone builds them.

What the lapse does not touch: the bars. After the archive end (2026-11-16) canonical 1d and 5m come from Alpaca SIP, the same consolidated basis, so price, volume, dollar volume and session history are available without Massive.

## Why it matters less than it looks, and where it does

The discovery vintage ends before `alpha.validation.oos_start` (2025-12-24), and no member run or disclosure reads the forward span. Every month-end after the archive end lies in that span. So this amendment changes no counted test on the vintage. It matters for two readers only: a book's sealed forward shadow and its one forward confirmation, each of which must state the universe it trades as of each date.

## Fields known at t without Massive

| Element of the rule | Source after the last Massive list | Available without Massive |
|---|---|---|
| Price at or above $1 on t | Alpaca consolidated close, canonical 1d | yes |
| Trailing 60-session median of close times volume (floor $1M in, $0.5M out) | Alpaca consolidated volume; the volume basis gate of the family 10 draft (Massive over Alpaca median 0.99993 in 2026) shows the two agree | yes |
| At least 60 sessions of the security's own bars | canonical 1d | yes |
| Type: common stock, ADR or ETF | the Massive reference types as captured; fixed at the last list | not for a name absent from the last list |
| Identity key (FIGI, else CIK plus share class plus type) | the entity map built from the lists; fixed at the last list | not for a name absent from the last list |
| Entrants (a security new since the last list) | none | no: Alpaca's asset list carries no security type and no FIGI, and this repo captures no Alpaca asset list today |

## Part 1: amendment text (to append to the preregistration if adopted)

> Amendment 2026-11-15 (membership after the last captured Massive list; pre-look, no return-based look at the universe has happened).
>
> Let L be 2026-11-09, the last month-end ticker list in `pit_snapshots/20261113` and the anchor of the one-time pit install (lead ruling 2026-11-16: install after D4 at this anchor; the planner is not additive, so a later list cannot extend an installed map without rewriting installed spans). At a month-end t after L, membership is a closed list:
>
> 1. Candidates are exactly the securities placed on the list at L (type and identity key as captured; never changed after L). A security absent from that list is not a member at any later t, whatever its bars show. Names unplaced at L stay unplaced.
> 2. Every other condition of the preregistration holds unchanged and is evaluated on Alpaca SIP bars: close at or above $1 on t, at least 60 sessions of the security's own bars, the trailing 60-session median of close times volume at or above $1M to enter and held down to $0.5M to stay, hysteresis carried month to month. A name whose bars stop has an undefined or falling median and leaves by the same rule that governed it before L; no separate delisting rule is added.
> 3. The membership rows are written with rule id `stage2-closed-list`, never the rule id of the Massive-listed months, so a book's snapshot hash records which rule applied to each date.
> 4. Disclosure at every book freeze and every forward confirmation: the member count at each month-end after L, and the count of securities in the Alpaca active asset list on that date that are absent from the list at L (the excluded newcomers), so the decay of breadth is a number and not an assumption.
> 5. Entrants enter only through a later dated amendment that names a point-in-time source for type and identity, with its measured placement rate recorded first. Until then the universe after L only shrinks.
>
> Plan renewal: if the Massive plan is renewed, an additive planner and a new amendment are needed before a later list can be used; until then this closed-list rule applies after L whether or not the plan is renewed.

## Why a closed list and not Alpaca-based entrants

- Type is the missing element. The rule excludes preferreds, warrants, units, rights, ETNs and closed-end funds. Alpaca's asset record has no such type, and inferring it from the name string would be a new unreviewed screen on names (the nearest standing rule is never to screen names on history or returns) that could let non-equity securities in silently.
- Identity is the other. A ticker reused after L would attach to the old key and splice two companies into one series, the failure the identity element exists to prevent. With no new identity source, the safe behavior is to admit no name the list at L did not place. The closed list still carries that risk for a name whose ticker is reused after L (the old key stays a candidate while the series changes company). Mitigation (build item B-A below) is a witness, not an admission path.
- It is cheap and reversible: a later amendment that adopts a source for entrants only adds names; nothing the closed list decided is revisited.

Alternative considered and not recommended: carry the last list forward as an open universe with Alpaca assets as entrants and a type taken from the Alpaca `class` field. Rejected for the type gap above.

## Build requirements

- B-L: the universe membership writer of the held L3 landing (a file not yet on main, so no path here) refuses any `as_of` after L unless the rule id is `stage2-closed-list`, and refuses that rule id at or before L. A test pins both. This edits a module the corpus rerun key reads, so it lands in the post-D1 landing runbook order (`docs/plans/2026-11-15-post-d1-landing-runbook.md`), not before D1.
- B-A (optional, a witness only): capture Alpaca's asset list nightly into raw with its capture time, so a symbol change or a ticker reuse after L shows as a changed asset id or name. It is never an admission source. It needs a short measurement that the Alpaca asset id is stable across ticker changes before it is relied on (unverified here).
- B-C: the disclosure of item 4 added to the freeze and confirmation reports.

## Open points

- L is 2026-11-09. A 2026-11-30 list, if captured (dry run lists two units and exits 0; `--pit-dates` takes any date), is raw evidence only. Letting a later list extend the installed map (extend only, never rewriting installed spans) needs an additive planner and its own amendment; it is not built.
- Ticker reuse after L is not detectable without B-A; the amendment accepts that for the forward span and the disclosure of item 4 does not cover it.
- Owner adoption line: adopt the closed-list rule for months after L (this draft). Lead recommendation: adopt. It adds no look and no series.
