# System-Wide Taxonomic Refactor: Renaissance Standardization

## Objective
Harmonize naming conventions across the entire intelligence pipeline to ensure data state and data domain alignment. Eliminate "drift" between filenames, topics, database tables, and code namespaces.

## Taxonomy Standard
- **`src/intelligence/`**: Logic and compute. 
  - `src/intelligence/features/<tier>_<name>/`: Raw and computed inputs.
  - `src/intelligence/signals/`: Final model outputs/decisions.
- **`src/persistence/`**: Storage.
  - `src/persistence/repository/`: Data access layers (Repository Pattern).
  - `src/persistence/writer/`: Kafka-consumer batch writers.
- **Data Domains**:
  - `feature.*` (Kafka topic prefix for all I1-I6 feature streams).
  - `intelligence.*` (Kafka topic prefix for all I7-I8 decision signals).

## Refactor Plan
1. **Directory Restructure**:
   - Move `src/intelligence/indicators` -> `src/intelligence/features/i1_indicators`.
   - Move `src/intelligence/structure` -> `src/intelligence/features/i3_structure`.
   - Move `src/intelligence/patterns` -> `src/intelligence/features/i5_patterns`.
   - Move `src/intelligence/smart_money` -> `src/intelligence/features/smc_context`.
2. **Topic Alignment**:
   - `dev.pipeline.data_quality` -> `dev.feature.quality`
   - `dev.intelligence.journal` -> `dev.intelligence.journal` (keep)
   - `dev.signals.aggregated` -> `dev.intelligence.signals`
3. **Database Alignment**:
   - Ensure table names match singular/plural conventions consistently (`feature_snapshots` instead of mixed `signal_features`).

## Verification
- Run all integration and unit tests.
- Verify Kafka producer/consumer topics match new convention.
- Check database migration scripts for name mapping.
