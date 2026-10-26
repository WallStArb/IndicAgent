/** Timestamps from the API are ISO strings in UTC; the dashboard shows them in UTC. */

export function fmtUtc(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace("T", " ").slice(0, 16) + "Z";
}

export function fmtAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const ms = now - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "unknown";
  const future = ms < 0;
  const abs = Math.abs(ms);
  const minutes = Math.round(abs / 60_000);
  if (minutes < 1) return "now";
  let text: string;
  if (minutes < 60) text = `${minutes}m`;
  else if (minutes < 48 * 60) text = `${Math.round(minutes / 60)}h`;
  else text = `${Math.round(minutes / 1440)}d`;
  return future ? `in ${text}` : `${text} ago`;
}
