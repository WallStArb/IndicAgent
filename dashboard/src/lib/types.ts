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

export interface FeedRow {
  timeframe: string;
  provider: string;
  symbols: number;
  newest_bar: string | null;
  last_fetch: string | null;
  failing: number;
  /** Judged by the API with the Pipeline ingest card's function and APR bounds. */
  status: "ok" | "stale" | "failing";
}

export interface FailingRow {
  symbol: string;
  timeframe: string;
  provider: string;
  consecutive_failures: number;
  last_fetch_status: string | null;
  last_fetched_at: string | null;
}

export interface IntegrityRow {
  monitor_type: string;
  metric_name: string;
  failed: number;
  evaluated: number;
  evaluated_at: string;
}

export interface RestatementRow {
  symbol: string;
  timeframe: string;
  vendor: string;
  kind: string;
  n_stored: number;
  n_changed: number;
  share: number;
  flagged_at: string;
}

export interface ListingEndRow {
  symbol: string;
  last_session: string;
  reason: string;
  recorded_at: string;
}

export interface DividendRow {
  source: string;
  symbols: number;
  covered_from: string | null;
  covered_to: string | null;
  checked_at: string | null;
}

/** GET /api/data/summary: the six Data sections; a failed section is empty with meta.error. */
export interface DataSummary {
  feeds: Envelope<FeedRow, { error?: string; failing_rows?: number }>;
  failing: Envelope<FailingRow, { error?: string }>;
  integrity: Envelope<IntegrityRow, { error?: string }>;
  restatements: Envelope<RestatementRow, { error?: string }>;
  listing_ends: Envelope<ListingEndRow, { error?: string }>;
  dividends: Envelope<DividendRow, { error?: string }>;
}

/** The one state the universe map colours a name by, judged by the API (src/api/routes/universe.py). */
export type NameState = "current" | "stale" | "failing" | "ended" | "inactive" | "no_data";

export interface UniverseRow {
  symbol: string;
  name: string | null;
  is_active: boolean;
  compute_eligible: boolean;
  compute_eligible_1d: boolean;
  asset_class: string | null;
  sector: string | null;
  newest_bar: string | null;
  failing_feeds: number | null;
  feeds: number | null;
  listing_ended: string | null;
  state: NameState;
}

/** GET /api/universe/summary. */
export type UniverseSummary = Envelope<UniverseRow, { stale_hours: number }>;

export interface IdentityRow {
  symbol: string;
  name: string | null;
  exchange: string | null;
  is_active: boolean;
  compute_eligible: boolean;
  compute_eligible_1d: boolean;
  live_tradeable: boolean;
  level_1: string | null;
  level_2: string | null;
  level_3: string | null;
  level_4: string | null;
  listing_ended: string | null;
  listing_end_reason: string | null;
}

/** Bars per UTC session for one (timeframe, vendor) lane, as parallel arrays. */
export interface LaneRow {
  timeframe: string;
  vendor: string;
  sessions: string[];
  bars: number[];
}

export interface CloseSeries {
  t: string[];
  close: number[];
}

type Section<R> = Envelope<R, { error?: string }>;

/** GET /api/universe/{symbol}: one name's data passport; a failed section has meta.error. */
export interface Passport {
  identity: Section<IdentityRow>;
  coverage: Section<Record<string, unknown>>;
  lanes: Section<LaneRow>;
  closes: Envelope<CloseSeries, { error?: string; timeframe?: string }>;
  restatements: Section<Record<string, unknown>>;
  tags: Section<Record<string, unknown>>;
}
