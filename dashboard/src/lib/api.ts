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

/** GET JSON from the API; a failed response throws with the API's `detail` when it sends one. */
export async function fetchJson<T = unknown>(path: string, options?: RequestInit): Promise<T> {
  const r = await fetch(`${getApiBase()}${path}`, options);
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    const detail = body?.detail;
    // FastAPI validation errors (422) send detail as a list of objects, not a string.
    throw new Error(
      detail == null ? `HTTP ${r.status} ${path}` : typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return r.json();
}
