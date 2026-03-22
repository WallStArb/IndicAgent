-- Phase 47 INTEL-04: Add roll premium/discount to intelligence features
-- roll_premium_pct: (front_price - back_price) / front_price as percentage
-- Nullable — only populated during roll windows when roll gap is known at detection time
-- Currently always 0.0 at detection (price comparison unavailable); Phase 49 ML training
-- will treat NULL as "no roll context" and 0.0 as "roll detected, gap unknown".

ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS roll_premium_pct DOUBLE PRECISION;

COMMENT ON COLUMN intelligence_features.roll_premium_pct IS
  'Roll premium/discount pct: (front - back) / front. NULL outside roll windows. '
  'Populated on roll detection via system_events -> feature_writer pipeline. '
  'Phase 47 INTEL-04.';
