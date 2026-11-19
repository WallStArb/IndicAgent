---
status: pending
priority: P0
filed: 2026-11-19
source: Alpaca nightly 2026-11-19 exited 1 (PARTIAL, one basis-change restatement flag, VIXM 5m)
owner: lead
---

# VIXM 1-for-2 reverse split (ex-date 2026-11-19) leaves a 2x break in canonical

## What

Alpaca's corporate-actions feed lists a VIXM reverse split, old_rate 2, new_rate 1, ex, record and process date 2026-11-19. Alpaca now serves 2026-11-16 to 2026-11-18 on the new scale (1d closes 27.46, 28.82, 28.30; Yahoo, not yet restated, reads 13.73, 14.41, 14.15). Stored bars through 2026-11-13 (Massive and Alpaca) are on the old scale, so canonical VIXM steps 13.39 to 27.46 at 2026-11-16. The nightly flagged 136 restated 5m bars (price ratio 2.0, volume ratio 0.4999), load 09ea55d0-7737-4a04-9f28-0700613fecc0; that one flag is the only unreviewed basis-change flag left (the 290 stale ones were marked reviewed 2026-11-19).

The A3 sweep (`ops_split_calendar_audit --sweep --witness yahoo --symbols VIXM`) reads it as `reported`: no measured level against Yahoo at the junction, because Yahoo has not restated yet.

## Done when

After Yahoo restates (expected by 2026-11-20), rerun the sweep for VIXM, take the row verdict into a row file (CLBK precedent `config/corporate_actions/split_rescale_rows_2026_11_17_clbk.csv`, factor 0.5 on the old-scale series, last old-scale session 2026-11-13), apply it with `--apply-rows`, reselect VIXM, confirm `split_horizon_fresh` and the 5m seam read clean, mark the flag reviewed. Review the row independently before apply.

## Not blocking

No corpus compute runs before the data gate; the 609 chain does not touch VIXM's recent bars.
