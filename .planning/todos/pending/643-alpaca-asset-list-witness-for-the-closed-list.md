---
status: pending
priority: P3
filed: 2026-11-19
source: preregistration Amendment 2026-11-18 (closed list), build item B-A of docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md
owner: lead
---

# Capture Alpaca's asset list nightly as a witness for the closed list

## What

After L = 2026-11-09 membership is a closed list (rule id `stage2-closed-list`): no entrant is admitted, so a ticker that is reused or changed after L attaches to the old identity key unseen. B-A is a witness only, never an admission source: capture Alpaca's asset list nightly into raw with its capture time, so a symbol change or a reuse after L shows as a changed asset id or name.

## Done when

The nightly writes the asset list to raw (one row per asset per capture, last-wins with the revision log, law 528); a short measurement shows whether the Alpaca asset id is stable across ticker changes (unverified today) and the result is recorded; a report lists the names whose asset id or name changed since L. The measurement decides whether the witness is relied on.

## Not blocking

The closed-list build itself does not need it; the amendment accepts undetected reuse for the forward span.

## Status 2026-11-24 (todo consolidation pass)

No Alpaca asset-list capture code exists; the amendment calls B-A optional.
