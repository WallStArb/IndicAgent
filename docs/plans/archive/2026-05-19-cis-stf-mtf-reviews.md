---
reviewers: [gemini]
reviewed_at: 2026-05-19
plan_reviewed: 2026-05-19-cis-stf-mtf-per-bar-design.md
---

# Cross-AI Plan Review — CIS STF/MTF Per-Bar Design

## Gemini Review

### Summary
The design is a well-considered improvement that addresses critical visibility and training gaps by decoupling intra-bar evidence (STF) from HTF-contextualized intelligence (MTF). The approach of leveraging the existing `CISScorer` interface by patching the feature dictionary is idiomatic and maintains test surface stability. The primary risks center on schema migration safety for large hypertables and potential "swallowing" of data if the `INSERT` conflict logic does not account for the expanded column set.

### Strengths
- **Minimalistic Integration:** Patching the input features to zero out CTF inputs rather than modifying `CISScorer` internals is an excellent use of existing abstractions.
- **Traceability:** Extending `SignalProcessorResult` ensures data flows consistently from the pipeline to storage, regardless of signal firing status.
- **Query-Time Flexibility:** Deriving the divergence signal at query time keeps the schema lean and allows for iterative refinement without further migrations.

### Concerns

| Severity | Concern |
|----------|---------|
| HIGH | **Schema/Migration:** `ALTER TABLE ... ADD COLUMN` on a large hypertable during high-frequency ingestion needs care — use `NULLABLE` columns (metadata-only op in PG11+, no table rewrite). |
| MEDIUM | **ON CONFLICT DO NOTHING:** Current INSERT uses `DO NOTHING` on conflict. If the row was already inserted without CIS columns (e.g., historical bars), a subsequent insert silently does nothing — CIS scores are lost for that bar. A `DO UPDATE SET col = EXCLUDED.col WHERE col IS NULL` strategy would backfill missing values. |
| MEDIUM | **Kalman State Init (STF key):** The `(symbol, tf, "stf")` Kalman key needs proper warm-up to avoid transient spikes in the first few bars of a session before the filter converges. |
| LOW | **Column width:** 4 new dedicated columns increases row size vs. stuffing into `i7` JSONB, but acceptable given query-performance benefits. |

### Suggestions
- **Migration Safety:** Add columns as `NULLABLE` first — this is a metadata-only operation in PG11+ and will not block the ingestion path.
- **Conflict Logic:** If any backfill path could insert a row before CIS is available, switch the feature INSERT to `ON CONFLICT DO UPDATE SET raw_cis_mtf_score = EXCLUDED.raw_cis_mtf_score, ...` with a `WHERE` guard so it only backfills NULLs.
- **Observability:** Emit a real-time metric for `MTF - STF` divergence magnitude during development to confirm Kalman filter stability and that the split is working as intended.
- **Divergence Materialization:** Start with query-time derivation (correct initial move). Promote to materialized view if it appears in every dashboard query.

### Risk Assessment: MEDIUM
Primarily due to schema migration on a production hypertable and the `ON CONFLICT DO NOTHING` gap for historical bars. The STF/MTF isolation logic itself is sound and unlikely to introduce scoring regressions.

---

## Consensus Summary

Single reviewer — no consensus synthesis needed.

### Key Actionable Items for Task #1
1. Use `NULLABLE` columns on both `ALTER TABLE` migrations (no table rewrite, no ingestion impact)
2. Audit the conflict strategy: `DO NOTHING` is safe for new bars (CIS added at same time as rest of row) but historical rows will remain NULL — decide whether backfill is needed
3. Initialize STF Kalman state with same warm-up logic as MTF key
4. Add a divergence magnitude metric/log for post-deploy validation
