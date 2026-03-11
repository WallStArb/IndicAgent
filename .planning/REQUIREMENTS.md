# Requirements: IndicAgent v1.7 Data Integrity

**Defined:** 2026-03-10
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

## v1 Requirements

### CIS Backfill Fix

- [ ] **CIS-01**: `historical_backfill.py` passes `features=` kwarg to `aggregate()` so new backfill runs produce signals with populated CIS fields
- [ ] **CIS-02**: Pre-repair audit query reports NULL count, recoverable count (matched `intelligence_features`), and unrecoverable count (orphaned)
- [ ] **CIS-03**: Backfill repair UPDATE populates NULL CIS fields on all recoverable `signal_ledger` rows
- [ ] **CIS-04**: Post-repair verification reports before/after NULL counts; unrecoverable rows logged for investigation

### Signal Generator Warmup

- [ ] **WARM-01**: On startup, `signal_generator_service` seeds `bar_history` with `min_bars_for_tf(tf)` bars per active contract × timeframe from `intelligence_features`
- [ ] **WARM-02**: After seeding, signals fire on the first incoming live bar (no warmup wait)
- [ ] **WARM-03**: Seeding degrades gracefully if DB unavailable — logs loudly and falls back to live warmup without crashing
- [ ] **WARM-04**: Startup log reports seeding completion with bar counts per symbol/TF

## v2 Requirements

### Renaissance Follow-on

- **REN-01**: Once CIS fields are populated, re-run `validate_alpha.py --promote` for bootstrap-promoted plugins (DerivOsc, AC Osc) to validate with real data
- **REN-02**: Shadow signal gate tuning — analyze `regime_suppressed` signal outcomes vs fired signal outcomes once sufficient data accumulates

## Out of Scope

| Feature | Reason |
|---------|--------|
| Backfilling 4h/1d TF signals | Excluded as day-trading scope boundary (Phase 23 decision) |
| ML model training | Needs ~90 days labeled outcomes — not yet accumulated |
| CIS adaptive weight learning | Architecture ready; deferred until sufficient signal history |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CIS-01 | Phase 25 | Pending |
| CIS-02 | Phase 25 | Pending |
| CIS-03 | Phase 25 | Pending |
| CIS-04 | Phase 25 | Pending |
| WARM-01 | Phase 26 | Pending |
| WARM-02 | Phase 26 | Pending |
| WARM-03 | Phase 26 | Pending |
| WARM-04 | Phase 26 | Pending |

**Coverage:**
- v1 requirements: 8 total
- Mapped to phases: 8
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-10*
*Last updated: 2026-03-10 — traceability updated after roadmap creation (phases 25-26)*
