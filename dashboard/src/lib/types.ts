/**
 * Response shapes of the read-only API (src/api/routes/). Every route returns one envelope
 * (src/api/envelope.py): `source` is the table or system it read, `as_of` the newest timestamp in
 * it, and route-specific extras sit in `meta`
 * (docs/plans/2026-10-26-dashboard-v35-cockpit-design.md decision 4).
 */

export interface Envelope<Row, Meta = Record<string, unknown>> {
  source: string | null;
  as_of: string | null;
  rows: Row[];
  meta: Meta;
}

export type StageName = "ingest" | "feature" | "regime" | "measure" | "research" | "book";
export type StageStatus = "ok" | "stale" | "failing" | "error" | "empty" | "not_built";

export interface Stage extends Envelope<Record<string, unknown>, { failing_rows?: number; detail?: string; ic_rows?: number; error?: string }> {
  stage: StageName;
  status: StageStatus;
}

export interface PipelineSummary {
  generated_at: string;
  refresh_seconds: number;
  stale_hours: number;
  stages: Stage[];
}

export interface UiConfig {
  refresh_seconds: number;
  stale_hours: number;
}

export interface UnitRow {
  unit: string;
  active: string;
  sub: string;
  description: string;
  timer: string | null;
  last_run: string | null;
  next_run: string | null;
}

export interface DlqRow {
  dlq_topic: string;
  error_type: string;
  events: number;
  newest: string;
  quarantined: number;
}

export type UnitsResponse = Envelope<UnitRow>;
export type DlqResponse = Envelope<DlqRow, { window_days: number }>;
