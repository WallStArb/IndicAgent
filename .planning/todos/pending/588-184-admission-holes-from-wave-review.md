---
status: pending
objective: O1
priority: P0
filed: 2026-11-04
source: independent review of the phase-184 wiring wave (9f280d0aa..e1cca6456), lead rulings by indicagent-16
---

# Phase 184 admission holes: refuse first, then earn admission back with battery cells

## What

The wave review found that the runner admits runs no passing battery cell tested. Everything
else it checked (lookahead, no_fill, prefix rows, hashes, lineage) was clean. A counted test
admitted outside its certificate is a silent wrong answer, so these land before the first
counted test that uses an input member.

## Part A: code, one landing (research code: repro_frozen bit-identical, full gates)

1. **B1, the static gate comes from failed cells.** `null_battery_persistent.py:294-304`
   (`static_sizes.gate_from_cells`) takes the max over all gating cells, pass or fail. The only
   cells with static means failed. Build the gate per certificate from that certificate's passing
   cells only. Until part B adds static-stress cells, every passing certificate has a static gate
   of 0, so a real panel with measurable static means is refused (the honest state).
2. **B2, admission ignores the member function.** `runner.py:422-460`: an input member is
   admitted only when its signal is `families.features.centred`, the one function the battery
   certified. Any other signal is refused at spec load, naming the rule.
3. **M1, smoothing as a bypass of the persistence failure.** Drop the `feature, smoothing 5,
   1d->1d` certificate from `PASSING_CERTIFICATES` until part B tests it at tau 200.
4. **(e)** Drop the `rk_vwap_dev` certificates until S0 supplies `volume_basis` and the battery
   certifies on a mixed volume basis.
5. **m3** Refuse a book with more than one input member, or one that mixes input and
   residual-return members, until part B certifies multi-member books.
6. **m1** Resolve `source_configs` and `_check_member_memory` before `start_runs`, so a
   refusal never burns a spec hash as a failed run.
7. **m2** Refuse when `unmatched_rows > 0` inside the scored span (`snapshot.py:579-596`).
8. **Slot history (item 3, MINOR):** allow `slot_history_sessions = 0` for input members, which
   matches the certified condition.

The `test_passing_certificates_match_report` contract changes with 1, 3 and 4. The report's
table stays the evidence, and the dropped certificates are listed as withheld with the reason.

## Part B: battery extension (a counted battery run; never reclassify a failing cell)

For each certificate still passing after part A: a static-mean stress cell and a time-of-day
stress cell (sizes spanning the real-data range measured on the pilot names), a tau-200 cell,
and one two-member book cell. A certificate regains static admission only up to the largest
static size its own passing cells held. Smoothing 5 returns only if it passes at tau 200.

## Part C: real-data dry build

184-12's dry S0 build after 186-27 is the gate for real-mode `build_panel` (review item f):
row loss, the chunk grid and feature timestamp matching on live data.

## Done when

Part A has landed and its tests pin each refusal, part B's report is committed, and
`PASSING_CERTIFICATES` matches it. 184-12 has run clean before any counted test with an input
member.

## Part A landed (2026-11-04)

All eight items are in, each pinned by a refusal test. `PASSING_CERTIFICATES` is now
`feature 1h->1d`, `feature 15m->1d` and `rk_high_dist 126 1d->1d`; the smoothing-5 and both
`rk_vwap_dev` certificates are in `WITHHELD_CERTIFICATES` with reasons, and 184-05-BATTERY.md has a
"Withheld" section (the measured table is untouched). The static gate is per certificate from that
certificate's own cells (`null_battery_persistent.static_gate(certificates)`), so every passing
certificate gates at 0 until part B. Item 8 relaxes `slot_history_sessions` to 0 for input members
only. Part B and C remain.

## Part B landed (2026-11-04)

Thirteen gating cells ran at battery module commit eb6651a9f (tag `battery/588-b`, 1,000 sims, 4,000
sessions, 60 names); the table and rule are in 184-05-BATTERY.md ("Part B extension"). Twelve hold
size at 0.05 and 0.01. `PASSING_CERTIFICATES` stays feature 1h to 1d, feature 15m to 1d and
rk_high_dist 126 1d to 1d, and each now gates at the largest stress its own passing cells held:
static 0.038 (twice the measured size) for all three, time-of-day 0.0192 for the two feature routes
and 0 for rk_high_dist (no applicable cell). The two-member book feature 1h with feature 15m
(equal weight) passed both book cells and is the one certified composition (`CERTIFIED_BOOKS`);
any other count or combination of input members stays refused, and a book of the two gates at 0
(its cells carry no stress). Smoothing 5 does not return: `f1d_s5_tau200` fails in the book arm
(70 at 0.05, 23 at 0.01), so it is a failing route (todo 586). The `rk_vwap_dev` certificates stay
withheld. The stress cells cannot move the statistic (dollar-neutral weights and the lagged cell
mean remove static means and a common mean), so the ceilings record sizes tested, not a sharper
claim. Part C remains.

## Lead note on Part B (2026-11-04)

The static-mean and time-of-day stress cells cannot fail by construction: dollar-neutral
weights and the lagged cell mean remove an injected static or common mean, and at a fixed seed
t was identical across stress sizes. So the earned ceilings (static 0.038, time of day 0.0192)
record the sizes tested, not a demonstrated robustness. Admission stays conservative and nothing
is admitted on a false claim. Open methodology question for the next E17 work (todo 586/547): if
the statistic is immune to static means in this form, the static gate certifies nothing and is a
deletion candidate; if real panels carry a static component the battery's injection does not
model (a per-name mean correlated with a persistent signal), the battery needs that cell instead.
Decide with a measured real-data example, not by argument.

## Status 2026-11-24 (todo consolidation pass)

Merged from 560 (2026-11-24): the NULL-volume path is deleted (17cfe233b) and canonical holds only Massive and Alpaca, both `VOLUME_BASIS_CONSOLIDATED` (`vendor_kind.py:249`), so there is no seam. The only open item of 560 is item (e): S0 supplying `volume_basis`.

## Item (e) spec: S0 supplies `volume_basis` (2026-11-24, indicagent-94; design only, no code edited)

Facts checked against live code (2026-11-24):
- `kernel_source.kernel_source` takes `volume_basis` and refuses a volume kernel without it ("the panel carries no vendor provenance (todo 555)", `kernel_source.py:187`). The runner's S0 path calls it through `snapshot._run_kernel` (`snapshot.py:795-807`), which passes no basis, so every volume kernel member (`rk_vwap_dev`) is refused at S0 today, on top of the withheld certificates (`null_battery_persistent.py:152-160`).
- The battery's own source array hard-codes one basis: `volume_basis=np.full(close.shape, VOLUME_BASIS_CONSOLIDATED)` (`null_battery_persistent.py:604`). The certificate cells therefore assume one consolidated basis; nothing proves a real panel has it.
- Canonical now holds only Massive and Alpaca, both `VOLUME_BASIS_CONSOLIDATED` (`vendor_kind.py:238-262`, `volume_basis()`; an unmapped pair raises, a basis never defaults). A mixed basis cannot occur in canonical after the IBKR removal, so a mixed-basis battery cell has nothing to certify; the missing piece is S0 proving the single basis instead of assuming it.
- Bars are read from `market_data_ohlcv_tradeable`, which carries `vendor` and `kind` per bar (`_VENDOR_SET_SQL`, `snapshot.py:83-86`, already queries the distinct pairs for intraday tfs).

End state. For a kernel member whose kernel declares `volume` without `volume_basis_safe` (the registry's own rule, `registry.py:735`), S0 reads the distinct (vendor, kind) pairs of the source tf's bars over the fetch span, maps each through `vendor_kind.volume_basis`, and:
- if every pair maps to one basis (NONE pairs carry none), passes `volume_basis = np.full(shape, that basis)` to the kernel and records `{basis, vendor_kinds}` in the member's evidence (`info`), so the claim is data in the snapshot, not a constant in a battery;
- if the pairs map to more than one basis, or a pair is unmapped, refuses the member loudly naming the pairs (`ValueError`, as `_run_kernel` does for `KernelSourceRefused`);
- on a derived 15m or 1h source, reads the pairs of the 5m constituents over the span (derived bars carry `DERIVED_PAIR`, whose basis comes from its constituents, `grid_volume_basis`), with the same rule.
No new spec field: the need is derived from the registry, so no spec hash moves and no `_OPTIONAL_*_FIELDS` entry is added. Members that do not read volume get exactly the arrays and manifest they get today.

Checkable scope list.
1. `src/intelligence/research/snapshot.py` only: a `_BASIS_VENDOR_SQL` beside `_VENDOR_SET_SQL`, a `_volume_basis_for(...)` helper (pure, takes the pairs, returns the basis or raises), the need test, the `volume_basis` argument of `_run_kernel` and the evidence key. Do not edit `Panel` or `panel.py` (it is in every recorded battery's code key), `kernel_source.py` (in the persistent battery's closure) or `vendor_kind.py`.
2. Tests (`tests/unit/research/test_snapshot_volume_basis.py`): one consolidated pair gives a full CONSOLIDATED array and the kernel runs; Alpaca plus an IBKR SMART pair refuses naming both; an unmapped pair raises; a kernel that does not read volume (and a `volume_basis_safe` one) gets no basis and an unchanged evidence dict; the derived-tf path reads 5m constituent pairs; the evidence records basis and pairs.
3. Optional second step, a lead ruling and a methodology-ledger line (not part of this landing): restore the two `rk_vwap_dev` certificates in `WITHHELD_CERTIFICATES` under the precondition "S0 verified one consolidated basis". That edits `null_battery_persistent.py` and the `test_passing_certificates_match_report` contract; it moves only the persistent battery's code key, and no bound pass record uses that battery (`research/battery_passes/` holds daily residual, seasonality and family 10 records, whose closures do not contain `null_battery_persistent`, checked by `import_closure` 2026-11-24). Recommendation: do step 3 with a ledger line once step 1 has landed and run on real bars; until then the certificates stay withheld.

Which hashes move. Spec hashes: none. Recorded battery keys: none, provided only `snapshot.py` outside `session_dates` is edited (`battery_code_key` hashes `snapshot.py` by the `session_dates` function only, `battery_pass.py:174-190`; `panel.py` is in the closure of the daily residual, volume shock and persistent batteries, which is why `Panel` stays untouched). Snapshot bytes of recorded runs: unchanged (verified by `repro_frozen`). `rebuild_code_key()`: unchanged; the writer's import closure is 61 modules and none is under `src/intelligence/research/` (`writer_code_modules()` 2026-11-24).

Gates. Unit suite exit code, ruff, black, glossary, `/simplify`, `/review`; `repro_frozen` bit-identical (`python -m scripts.research.determinism.repro_frozen <scratch> --logs /home/bg/dev/indicagent/logs`); `battery_code_key` of the three bound records recomputed equal (the `test_battery_pass` suite does this when the tree is clean); a real-data check on one name (read-only): the pairs and the basis printed for `rk_vwap_dev`'s 1d source.

Landing constraint. It edits research code: lands after the corpus pilot and the family 10 counted runs, before the pin of any counted corpus test, in a detached worktree off origin/main, never beside a live counted run (a live run imports `snapshot.py`; `code_content_key` hashes it). It does not touch `rebuild_code_key()`. It does not need the pilot's result.

Size: about 80 lines of code and about 120 of tests; one session.

## Item (e) step 1 build status and the step 3 ledger line draft (2026-11-24, indicagent-94)

Step 1 is built and unit-tested on the local branch `wip/588e-volume-basis` (commit aad05bea7 on origin/main 00b49fc9f), not pushed: `snapshot.py` (`volume_basis_of`, `_needs_volume_basis`, `_source_volume_basis`, `_run_kernel(..., volume_basis)`, evidence key `volume_basis` on the source block) and `tests/unit/research/test_snapshot_volume_basis.py` plus three end-to-end cases in `test_snapshot_features.py`. Measured: the three bound battery records' `battery_code_key` recompute equal with the change (daily residual 3632233bc610, family 10 volume shock 0c1c6a6059f7, seasonality ae9ff30d86e2) and `rebuild_code_key()` is unchanged (09708ae249f2); `tests/unit` at -n 4 exits 0. Held: `repro_frozen` and the one-name real-data check (heavy slot), and the push (research code; after the pilot and the family 10 counted runs).

Draft of the step 3 ledger line (to be appended with the step 3 landing, after step 1 has run on real bars; not before; `null_battery_persistent.py` is not edited until then):

`## <next free letter>: the two rk_vwap_dev certificates return under a proven single volume basis (lead record, owner veto reserved)`

Body: The 2026-11-24 withholding of `rk_vwap_dev` 1d to 1d and 1h to 1d (`WITHHELD_CERTIFICATES`, todo 588 item e) rested on the battery cells assuming one volume basis while S0 supplied none. S0 now proves the basis: for a volume kernel member it reads the source bars' (vendor, kind) pairs (the 5m constituents for a derived 15m or 1h), maps each through `vendor_kind.volume_basis` and refuses the member unless they give exactly one basis (`snapshot.volume_basis_of`), recording the basis and pairs in the source block's `volume_basis`. Canonical holds only Massive and Alpaca, both consolidated, so a mixed basis cannot occur and cannot be tested; the cells' single-basis assumption is now a checked precondition of every real panel. Change: the two certificates leave `WITHHELD_CERTIFICATES` and enter `PASSING_CERTIFICATES`, with the precondition named in their reason. No statistic, gate, window or threshold changes; the persistent battery's code key moves and no bound record uses that battery; `test_passing_certificates_match_report` is updated in the same commit. Evidence recorded before this line: FILL (the one-name read-only check: name, source tf, pairs, basis). Decided before any counted test reads an `rk_vwap_dev` member.


## Item (e) status (2026-11-25)

Recommendation: delete. Close item (e) as not needed; the two `rk_vwap_dev` certificates stay withheld; the lead deletes `wip/588e-volume-basis`. Reopen only when a prereg registers an `rk_vwap_dev` member, and rebuild from aad05bea7 then.

What the branch delivers. `wip/588e-volume-basis` (tip 7297116e5) is step 1 of the spec above: aad05bea7 (S0 reads the source bars' (vendor, kind) pairs, maps them through `vendor_kind.volume_basis`, refuses a mixed or unmapped set, records the basis in the source evidence) plus the review fixes in 7297116e5 (about 60 lines across `snapshot.py` and two test files).

What the revert removed and why. aad05bea7 reached main with the docs commit 81a2b9c63 (pushed 19:48), although that commit's own text says step 1 is "not pushed". 2ba4455d3 (19:59) reverted it. The revert message gives no reason; the timing and the hold in that section (research code, `repro_frozen` not run, a live counted run imports `snapshot.py`) point to restoring the hold. Main has the pre-item-(e) `snapshot.py`. Landing the branch now needs a revert of 2ba4455d3 plus 7297116e5.

Musk step 1: no counted test needs it.
- The only S0 path it guards is `snapshot._run_kernel` (`snapshot.py:795-807`) into `kernel_source`, which refuses a volume kernel without a basis (`kernel_source.py:187-189`, the registry guard at `features/contract/registry.py:735-740`). So an `rk_vwap_dev` member fails loudly at S0 today. Nothing slips through silently, and its certificates are withheld anyway (`null_battery_persistent.py:152-160`).
- No queued counted family reads a volume kernel. Family 9 registers only `high_52w_dist` and leaves out `vwap_dev_sigma` (`docs/plans/2026-11-15-family9-52week-high-prereg-draft.md:10`). Family 10 reads share volume as a `panel_source` member through `member_sources.compute_panel_members` (`member_sources.py:1-20`), not through the kernel path, so the branch would not cover it even if landed.
- Family 10's volume basis is guarded where it is read: prereg section 6 gate 2 (no ibkr 1d row and one basis over the span) and gate 4 (Massive over Alpaca volume ratio, median 0.99993 measured 2026-11-15) (`2026-11-15-family10-volume-shock-prereg-draft.md:47-49`). Canonical 1d and 5m hold only (massive, canonical) and (alpaca, sip_rth), both `VOLUME_BASIS_CONSOLIDATED` (`vendor_kind.py:249-260`; todo 663 measured 42,024,440 massive and 333,114 alpaca 1d rows, zero ibkr). A basis mismatch cannot reach a counted test.

What survives. Two things. (1) If a prereg ever registers an `rk_vwap_dev` member, the proof and the step 3 ledger line above come back, about one session plus a `repro_frozen` slot. (2) If a vendor with a different basis enters canonical, the right guard is a single-basis assertion in the selection gate (one check per timeframe at the data layer, covering every reader, family 10 included), not a check per S0 member. Neither has a trigger today, so neither is a todo.
