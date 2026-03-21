---
created: 2026-03-21T18:49:54.000Z
title: Populate days_to_expiry in FeaturePipelineService
area: intelligence
files:
  - services/feature_pipeline_service.py
  - src/intelligence/schemas.py (BarIntelligenceRecord.days_to_expiry)
  - services/feature_writer_service.py (_load_expiry_map pattern to copy)
---

## Problem

`days_to_expiry` will be `None` through phases 44.1, 44.2, and 44.3. The field is defined as `days_to_expiry: int | None = None` on `BarIntelligenceRecord` (Phase 44.2 deliverable) and the `intelligence_features.days_to_expiry` DB column is nullable, so no execution failures occur — but the column is permanently unpopulated.

Root cause: the spec assigned expiry map computation to FeaturePipelineService startup step 2, but no 44.1 plan task implements it. FeatureWriterService's old `_load_expiry_map()` pattern (loads contract expiry dates from `instruments` table at startup) was silently lost in the simplification.

Phase 46 ML scoring uses `days_to_expiry` as a feature column (roll proximity affects signal reliability for futures). If null, the ML matrix will have a gap column.

## Solution

Add to FeaturePipelineService startup sequence (after DB connect, before bar consumption):

```python
async def _load_expiry_map(self) -> dict[str, date]:
    """Load active contract expiry dates — same pattern as old feature_writer_service.py."""
    rows = await self._db.fetch(
        "SELECT symbol, expiry_date FROM instruments WHERE is_active = TRUE AND expiry_date IS NOT NULL"
    )
    return {row["symbol"]: row["expiry_date"] for row in rows}
```

Then compute `days_to_expiry` per bar and embed it in `IntelligenceEvent` (preferred — single source) OR set it on `BarIntelligenceRecord` at publish time in `SignalGeneratorService`. Either way, `FeatureWriterService._record_to_insert_params()` currently receives `expiry_map=None` and the column stays null.

Simplest fix: add `days_to_expiry: int | None` to `IntelligenceEvent` (Phase 44.1 adds it), compute in `FeaturePipelineService._process_symbol()`, flow through to `BarIntelligenceRecord` in Phase 44.2.

Must complete before Phase 46 ML scoring feature matrix is built.
