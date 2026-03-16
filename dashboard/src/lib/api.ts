/**
 * Returns the API base URL, auto-detected from the current hostname.
 * - Direct LAN access (192.168.x.x, 10.x.x.x, localhost) → local API on :8000
 * - Any other host (CloudFlare tunnel, etc.) → https://api.indicagent.com
 *
 * NEXT_PUBLIC_API_BASE_URL overrides detection if set.
 * Result is cached — hostname is immutable during a session.
 */
let _cachedBase: string | null = null;

export function getApiBase(): string {
  if (_cachedBase) return _cachedBase;
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    _cachedBase = process.env.NEXT_PUBLIC_API_BASE_URL;
    return _cachedBase;
  }
  if (typeof window === "undefined") return "http://localhost:8000";
  const hostname = window.location.hostname;
  _cachedBase =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname.startsWith("192.168.") ||
    hostname.startsWith("10.")
      ? `http://${hostname}:8000`
      : "https://api.indicagent.com";
  return _cachedBase;
}

export async function fetchJson<T = unknown>(url: string, options?: RequestInit): Promise<T> {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(`HTTP ${r.status} ${url}`);
  return r.json();
}
