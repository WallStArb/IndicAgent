---
created: 2026-10-07
priority: P0
area: data-layer
---

# Amend 185-46, 185-47, 185-48 and 189-10 to the two-lane nightly design

Owner answers 2026-10-07: frozen Tradier history stays a valid source (not reference only); the nightly design is two generic, vendor-agnostic lanes. A shallow lane fetches 1d and 5m bars since the last fill, and its 1d pass checks that recent history is current, with no deep gap fill. A separate deeper, less frequent lane does gap filling. 185-46 to 185-48 and 189-10 currently assume one nightly fetcher cadence and Tradier as reference only. Amend them before executing 185-46. Planning docs only.

## Closed 2026-10-07

Done. 185-46, 185-47 and 185-48 carry the owner-answer amendment blocks (d5f4638ae, 99f2f1e1b) and 185-46 a review amendment (712eb7de3). The last item, the 189-10 block (both lanes as one queue with two span rules, the gap-fill cadence key, the overlap-verified update lane), landed with 185-46 Task 1 (2c9ddc53b).
