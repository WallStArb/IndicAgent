# Requirements: IndicAgent

**Defined:** 2026-03-02
**Current Milestone:** v1.3 Signal Intelligence Expansion
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

---

## v1.3 Requirements

### I2 Acceleration

- [x] **ACCEL-01**: MomentumAcceleration computes `rsi_accel`, `macd_accel`, `roc_accel` (first differences of I1 indicators) each bar
- [x] **ACCEL-02**: MomentumAcceleration fires `inflection_flag=1` when any of the three deltas changes sign vs prior bar
- [x] **ACCEL-03**: Plugin is registered in TIER_I2 and validated by registry startup check

### I7 Gap Analysis

- [x] **GAP-01**: GapAnalysisSetup detects opening gaps by comparing prior close to current open price
- [x] **GAP-02**: Plugin classifies gap direction (bullish/bearish) and bias (fade vs continuation) based on gap size relative to ATR and volume context
- [x] **GAP-03**: Plugin produces a setup signal with confidence score, entry type (at_limit/at_pullback), stop, and target levels

### I7 Candlestick Setups

- [ ] **CNDL-01**: CandlestickPatternSetup reads existing I5 `candlestick_*` output fields (no re-detection of raw price patterns)
- [ ] **CNDL-02**: Plugin scores confluence of the active candlestick signal with trend direction, structure level proximity, and volume confirmation
- [ ] **CNDL-03**: Plugin produces a setup signal only when confluence threshold is met (consistent with other I7 gate logic)

### I7 Session Extremes

- [ ] **SESS-01**: SessionExtremesSetup reads I3 `SessionLevels` outputs (Asian session high/low) already computed in the pipeline
- [ ] **SESS-02**: Plugin detects price approaching or testing Asian session extremes during London or NY session windows
- [ ] **SESS-03**: Plugin produces a fade setup signal when price tests the extreme with at least one confirming context factor (trend, volume, or RSI extreme)

---

## Future Requirements

### Feature Store Completion (v1.4)

- **FEAT-01**: `intelligence_features` table gains `i7 JSONB` column (setup signals + scores)
- **FEAT-02**: `intelligence_features` table gains `i8 JSONB` column (narrative + metadata)
- **FEAT-03**: signal_generator_service writes i7 data back via enrichment stream
- **FEAT-04**: ai_narrative_service writes i8 data back via enrichment stream

### Dashboard (future)

- **DASH-01**: Timeframe matrix wired to live per-TF signal data
- **DASH-02**: Signal history view with outcome tracking

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution | Intelligence platform only |
| Re-detection of candlestick patterns in I7 | I5 already detects; I7 consumes I5 output |
| Session extremes for crypto | Asian session concept doesn't apply to 24/7 markets |
| Auth layer / external access | No external consumers yet |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ACCEL-01 | Phase 08 | Complete |
| ACCEL-02 | Phase 08 | Complete |
| ACCEL-03 | Phase 08 | Complete |
| GAP-01 | Phase 09 | Complete |
| GAP-02 | Phase 09 | Complete |
| GAP-03 | Phase 09 | Complete |
| CNDL-01 | Phase 10 | Pending |
| CNDL-02 | Phase 10 | Pending |
| CNDL-03 | Phase 10 | Pending |
| SESS-01 | Phase 11 | Pending |
| SESS-02 | Phase 11 | Pending |
| SESS-03 | Phase 11 | Pending |

**Coverage:**
- v1.3 requirements: 12 total
- Mapped to phases: 12
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-02*
*Last updated: 2026-03-02 after initial definition*
